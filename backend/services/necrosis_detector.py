"""
Necrosis detection: find dead code still attached to a living codebase.

The mirror image of git_forensics.py. Where git_forensics scans git *history* for
features that were KILLED (revival candidates), this scans the *live codebase* for
code that was DEPRECATED/DISABLED but never actually removed — "necrotic tissue"
that can now be safely excised.

Detection is built on the GitLab MCP `search_blobs` tool (scope=blobs), which
searches current file content rather than commit history. Three strategies:

  A. Annotation scan      — @deprecated, TODO: remove, FIXME: remove, etc.
  B. Flag tombstone scan  — machine-readable Deprecated:true / ToBeRemovedWith
  C. (Phase 6) reverted-deletion cross-reference

All data retrieval goes through the shared GitLab MCP client. Existing modules
(git_forensics, viability_scorer, etc.) are NOT modified — this is purely additive.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)


# ── Deprecation annotation patterns, grouped by intent ────────────────────────
# Each entry is (search_query, detection_method, language_hint). The search_query
# is what we send to GitLab blobs search; GitLab's Elasticsearch matches these as
# content substrings. We keep the list curated to avoid noise.
_ANNOTATION_QUERIES: list[tuple[str, str, str]] = [
    # Machine-readable Go feature-flag tombstones (highest confidence)
    ("Deprecated: true", "flag_tombstone", "go"),
    ("ToBeRemovedWith", "flag_tombstone", "go"),
    # Explicit deprecation annotations
    ("@deprecated", "annotation_scan", "any"),
    ("// Deprecated:", "annotation_scan", "go"),
    ("DeprecationWarning", "annotation_scan", "python"),
    # Intent-to-remove comments
    ("TODO: remove", "removal_marker", "any"),
    ("TODO remove after", "removal_marker", "any"),
    ("FIXME: remove", "removal_marker", "any"),
    ("will be removed in", "removal_marker", "any"),
    ("scheduled for removal", "removal_marker", "any"),
    ("no longer used", "removal_marker", "any"),
    ("REMOVEME", "removal_marker", "any"),
    # Intentionally-kept-deprecated suppressions (Go)
    ("nolint:staticcheck", "suppressed_deprecation", "go"),
]

# Files we must NEVER flag — generated, vendored, or doc/lock files.
# A deprecation comment in an auto-generated file is not actionable dead code.
_EXCLUDED_PATH_PATTERNS = re.compile(
    r"(^|/)(vendor|node_modules|third_party|3rdparty|\.bundle|dist|build|"
    r"generated|gen|_pb2|\.pb\.go|migrations?)/"
    r"|\.(lock|sum|min\.js|map|md|markdown|rst|txt|yml|yaml|json|csv|svg|png|jpg)$"
    r"|(^|/)CHANGELOG"
    r"|_test\.(go|py|rb|js)$"            # test files: deprecation refs are usually assertions
    r"|_spec\.(rb|js|ts)$"               # RSpec (.rb) + JS/TS spec suffix
    r"|\.(spec|test)\.(js|ts|py|rb)$"
    r"|(^|/)(spec|tests?)/"              # spec/ test/ tests/ as a path segment
    r"|auto.?generated|do not edit",
    re.IGNORECASE,
)

# Code-file extensions we DO consider (only real source files can be necrotic).
_CODE_EXTENSIONS = (
    ".go", ".rb", ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt",
    ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".php", ".scala", ".swift",
)

# Symbol extraction, in tiers (most meaningful first):
#  1) declarations — the thing being defined
#  2) member access — for call sites / nolint lines, the deprecated member used
#  3) fallbacks — local var / generic field
_DECL_PATTERNS = [
    re.compile(r"\bName:\s*([A-Za-z_]\w+)"),                        # Go flag Name: field (most meaningful)
    re.compile(r"\b(FF_[A-Z][A-Z0-9_]+)"),                          # GitLab feature-flag convention
    re.compile(r"\bfunc\s+(?:\([^)]*\)\s+)?([A-Za-z_]\w+)"),       # Go func
    re.compile(r"\b(?:def|class|module)\s+([A-Za-z_]\w+)"),         # Python/Ruby
    re.compile(r"\b(?:function)\s+([A-Za-z_]\w+)"),                 # JS
    re.compile(r"\balias_method\s+:([a-z_]\w+)"),                   # Ruby alias
    re.compile(r'"(FF_[A-Z][A-Z0-9_]+)"'),                          # FF name inside a quoted description
]
# Member-access patterns — capture ALL, we take the RIGHTMOST (the leaf member,
# which is the actually-deprecated method/field in a chain like a.b.Deprecated).
_MEMBER_CALL_RE = re.compile(r"\.([A-Za-z_]\w{2,})\s*\(")           # .method( call
_MEMBER_FIELD_RE = re.compile(r"\.([A-Za-z_]\w{2,})\b")            # .Field access
_FALLBACK_PATTERNS = [
    re.compile(r"\b(?:const|var|let)\s+([A-Za-z_]\w+)"),           # JS/Go local var
    re.compile(r"\b([A-Z][A-Za-z0-9]{3,})\s*[:=]"),                # Go struct field / const
]

# staticcheck codes that are NOT deprecation (SA1019 is the deprecation rule).
# A //nolint:staticcheck citing one of these is suppressing a different lint,
# not flagging dead/deprecated code — so it is not necrosis.
_NON_DEPRECATION_SA_RE = re.compile(
    r"\bSA(?!1019)\d{3,}\b|\bST\d{3,}\b|\bSA4\d{3}\b", re.IGNORECASE
)

# Field names / markers that are NOT meaningful symbols — skip them in extraction.
_NOISE_SYMBOLS = {
    "DefaultValue", "Deprecated", "Description", "ToBeRemovedWith",
    "true", "false", "nil", "null", "None", "self", "this",
    "TODO", "FIXME", "HACK", "XXX", "REMOVEME", "NOTE", "REMEMBER",
    "nolint", "staticcheck", "deprecated", "Deprecation",
    # Internet TLDs extracted from URLs in deprecation comments (e.g. "see example.com")
    "com", "org", "net", "io", "gov", "edu", "co", "uk", "dev", "app",
}

# staticcheck/golangci rule codes (SA1019, ST1003, etc.) are not symbols.
_RULE_CODE_RE = re.compile(r"^(SA|ST|S|U|QF|G)\d{3,}$")


@dataclass
class NecroticCode:
    """A piece of dead code still present in the live codebase (necrosis candidate)."""
    id: str                          # slug
    name: str                        # symbol / flag / description
    file_path: str                   # where it lives
    annotation: str                  # the deprecation comment / marker text
    detection_method: str            # annotation_scan | flag_tombstone | removal_marker | suppressed_deprecation
    language: str                    # go | ruby | python | js | unknown
    symbol_kind: str = "declaration" # declaration | usage | fallback — see _extract_symbol_kinded
    context_snippet: str = ""        # surrounding code
    ref: str = "HEAD"                # branch the blob was found on
    startline: int = 0

    # Age signals — populated by _age_annotation() for top candidates
    last_commit_sha: str = ""
    annotation_date: str = ""        # ISO date the file was last touched
    age_days: int = 0                # how long it's been undead (approx)

    # Extracted intent
    replacement: str = ""            # what supersedes it (if stated in the comment)
    removal_target: str = ""         # version/date promised for removal

    # Quality signals (mirror of DeadFeature)
    detection_confidence: int = 0
    detection_signals: list[str] = field(default_factory=list)

    # Populated by later pipeline stages (deletion_scorer, challenger)
    deletion_analysis: Optional[dict] = None
    deletion_safety: Optional[dict] = None


async def detect_necrosis(
    project_path: str,
    max_findings: int = 40,
    min_age_days: int = 90,
    progress_cb=None,
    mcp_calls: list | None = None,
    age_top_n: int = 12,
) -> list[NecroticCode]:
    """
    Scan the live codebase for necrotic (deprecated-but-present) code.

    Args:
      project_path: org/repo
      max_findings: cap on raw blob hits to process
      min_age_days: minimum age of the deprecation before it counts as necrosis
                    (fresh deprecations are intentional, not dead yet). Applied
                    only to candidates we successfully date (age_top_n of them).
      age_top_n:    how many top candidates to date via get_file+get_commit
                    (bounds MCP call volume).

    Returns a list of NecroticCode, quality-gated and deduplicated.
    """

    def log_mcp(tool: str, **kwargs):
        if mcp_calls is not None:
            mcp_calls.append({"tool": tool, "source": "gitlab_mcp", **kwargs})

    async def emit(msg: str):
        logger.info(msg)
        if progress_cb:
            await progress_cb(msg)

    await emit(f"[MCP] search_blobs — scanning live codebase of {project_path} for deprecation markers...")

    raw: list[NecroticCode] = []
    seen_keys: set[str] = set()

    for query, method, lang_hint in _ANNOTATION_QUERIES:
        if len(raw) >= max_findings:
            break
        await emit(f"[MCP] search_blobs query: {query!r}")
        hits = await mcp.search_blobs(project_path, query, per_page=20)
        log_mcp("search_blobs", repo=project_path, query=query, result_count=len(hits))
        if not hits:
            continue

        for hit in hits:
            if len(raw) >= max_findings:
                break
            file_path = hit.get("path") or hit.get("filename") or ""
            data = (hit.get("data") or "").strip()
            if not file_path or not data:
                continue
            # Only real source files
            if not file_path.lower().endswith(_CODE_EXTENSIONS):
                continue
            if _EXCLUDED_PATH_PATTERNS.search(file_path):
                continue

            # ── Precision filters ────────────────────────────────────────────
            # 1. Skip template/codegen files (e.g. doc generators with {{ }} syntax)
            if "{{" in data or "}}" in data:
                continue
            # 2. The matched marker must actually appear in the returned snippet —
            #    GitLab can return a file because the term is elsewhere; those
            #    snippets give wrong symbols/dates.
            if not _marker_in_snippet(query, data):
                continue
            # 3. flag_tombstone must be a REAL tombstone, not a field definition or ref
            if method == "flag_tombstone" and not _is_real_tombstone(query, data):
                continue
            # 3b. A //nolint:staticcheck citing a NON-deprecation rule (SA5011 nil
            #     pointer, SA4xxx, etc.) is suppressing a different lint — not dead
            #     code. Only SA1019 (or an explicit "deprecat") counts as necrosis.
            if method == "suppressed_deprecation" and _NON_DEPRECATION_SA_RE.search(data) \
                    and "deprecat" not in data.lower() and "SA1019" not in data:
                continue

            symbol, symbol_kind = _extract_symbol_kinded(data)
            # A //nolint:staticcheck suppression is, by construction, a USAGE site of an
            # externally-defined deprecated symbol — force the kind so it can never be
            # mistaken for a deletable in-repo definition downstream.
            if method == "suppressed_deprecation":
                symbol_kind = "usage"
            # 4. Require a real identifier — a bare comment with no extractable
            #    symbol is not actionable dead code regardless of detection method.
            #    annotation_scan previously fell through to a file:basename fallback,
            #    which produced noise findings like "file:epic" or "file:api".
            if not symbol:
                continue

            # Dedup by file + symbol + method
            key = f"{file_path}::{symbol}::{method}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            replacement, removal_target = _extract_intent(data)
            language = _detect_language(file_path, lang_hint)

            raw.append(NecroticCode(
                id=_slugify(f"{symbol}-{file_path.split('/')[-1]}"),
                name=symbol,
                file_path=file_path,
                annotation=_first_marker_line(data, query),
                detection_method=method,
                language=language,
                symbol_kind=symbol_kind,
                context_snippet=data[:300],
                ref=hit.get("ref", "HEAD") or "HEAD",
                startline=hit.get("startline", 0) or 0,
                replacement=replacement,
                removal_target=removal_target,
            ))

    await emit(f"search_blobs complete — {len(raw)} raw necrosis candidates across {len(_ANNOTATION_QUERIES)} markers")

    if not raw:
        await emit("No deprecation markers found — codebase appears free of lingering dead code in scanned patterns.")
        return []

    # ── Age the top candidates (bounded MCP calls) ───────────────────────────
    # Sort so the most promising (flag tombstones, explicit annotations) get dated first.
    _method_priority = {
        "flag_tombstone": 0, "annotation_scan": 1,
        "suppressed_deprecation": 2, "removal_marker": 3,
    }
    raw.sort(key=lambda c: _method_priority.get(c.detection_method, 9))

    now = datetime.now(timezone.utc)
    dated = 0
    for cand in raw[:age_top_n]:
        try:
            # Accurate per-line dating: blame the EXACT line the annotation sits on.
            # Far better than file-level last-commit for hot files (e.g. flags.go),
            # where a flag deprecated years ago lives in a file touched yesterday.
            line = cand.startline or 1
            await emit(f"[MCP] get_file_blame — dating annotation at {cand.file_path}:{line}...")
            blame = await mcp.get_file_blame(
                project_path, cand.file_path, ref=cand.ref,
                start_line=line, end_line=line,
            )
            log_mcp("get_file_blame", repo=project_path, file=cand.file_path, line=line, ranges=len(blame))
            commit = None
            if blame and isinstance(blame[0], dict):
                commit = blame[0].get("commit") or {}
            # Fallback: file-level last commit if blame unavailable (e.g. range unsupported)
            if not commit:
                file_info = await mcp.get_file(project_path, cand.file_path, ref=cand.ref)
                log_mcp("get_file", repo=project_path, file=cand.file_path, found=file_info is not None)
                last_sha = (file_info or {}).get("last_commit_id", "") if isinstance(file_info, dict) else ""
                if last_sha:
                    commit = await mcp.get_commit(project_path, last_sha) or {}
                    log_mcp("get_commit", repo=project_path, sha=last_sha[:8], found=bool(commit))
            if commit:
                cand.last_commit_sha = commit.get("id", "") or commit.get("short_id", "")
                created = commit.get("committed_date") or commit.get("created_at", "")
                if created:
                    cand.annotation_date = _parse_date(created)
                    dt = _try_parse_dt(created)
                    if dt:
                        cand.age_days = max(0, (now - dt).days)
                    dated += 1
        except Exception as exc:
            logger.debug("Age determination failed for %s: %s", cand.file_path, exc)

    await emit(f"Dated {dated} top candidates via blame (accurate per-line annotation age)")

    # ── Score confidence + quality gate ──────────────────────────────────────
    for cand in raw:
        _score_necrosis_confidence(cand, min_age_days)

    # Method-specific auto-pass: flag tombstones are machine-readable, auto-pass at >=1.
    # Annotation/marker candidates need >=2 signals.
    _AUTO_PASS = {"flag_tombstone", "annotation_scan", "suppressed_deprecation"}
    high_conf = [
        c for c in raw
        if (c.detection_method in _AUTO_PASS and c.detection_confidence >= 1)
        or c.detection_confidence >= 2
    ]
    low_conf = [c for c in raw if c not in high_conf]

    if low_conf:
        await emit(f"Quality gate: filtered {len(low_conf)} low-signal markers (generated/ambiguous)")

    # Adaptive fallback: never return empty if we found *something*
    if not high_conf and raw:
        high_conf = sorted(raw, key=lambda c: c.detection_confidence, reverse=True)[:5]
        await emit("Quality gate: no high-confidence necrosis — using best available signals")

    await emit(f"Necrosis detection complete — {len(high_conf)} dead-code candidates identified")
    return high_conf


# ── Confidence scoring ────────────────────────────────────────────────────────

def _score_necrosis_confidence(cand: NecroticCode, min_age_days: int) -> None:
    """Score 0-5 from corroborating signals. Mutates cand in place."""
    signals: list[str] = []
    score = 0

    if cand.detection_method == "flag_tombstone":
        score += 2
        signals.append("machine-readable deprecation flag")
    elif cand.detection_method == "annotation_scan":
        score += 2
        signals.append("explicit @deprecated annotation")
    elif cand.detection_method == "suppressed_deprecation":
        score += 1
        signals.append("deprecation suppression (nolint)")
    elif cand.detection_method == "removal_marker":
        score += 1
        signals.append("removal-intent comment")

    if cand.removal_target:
        score += 1
        signals.append(f"removal target stated: {cand.removal_target}")
    if cand.replacement:
        score += 1
        signals.append(f"replacement named: {cand.replacement}")

    # Age signal — old deprecations are stronger necrosis evidence
    if cand.age_days >= min_age_days:
        score += 1
        signals.append(f"aged {cand.age_days}d (>= {min_age_days}d threshold)")
    elif cand.age_days and cand.age_days < min_age_days:
        # Dated but too fresh — penalise; likely an intentional recent deprecation
        score -= 1
        signals.append(f"⚠ only {cand.age_days}d old — may be intentional")

    # A symbol we actually identified is more actionable than a bare comment
    if cand.name and not cand.name.startswith("file:"):
        score += 0  # neutral; name presence already implied

    cand.detection_confidence = max(0, score)
    cand.detection_signals = signals


# ── Extraction helpers ──────────────────────────────────────────────────────

def _marker_in_snippet(query: str, data: str) -> bool:
    """The matched marker should actually be present in the returned snippet.
    Normalises spacing/colons so 'Deprecated: true' matches 'Deprecated:   true'."""
    norm = lambda s: re.sub(r"\s+", " ", s.lower().replace(":", " ")).strip()
    return norm(query) in norm(data)


def _is_real_tombstone(query: str, data: str) -> bool:
    """A flag tombstone must be an actual deprecation, not a struct-field definition
    or a reference. 'Deprecated: true' must literally pair deprecated+true; and
    'ToBeRemovedWith' must carry a non-empty version value."""
    low = data.lower()
    if "deprecated" in query.lower():
        # require deprecated ... true together (Go: `Deprecated: true`)
        return bool(re.search(r"deprecated\s*:?\s*true", low))
    if "toberemovedwith" in query.lower():
        # require a non-empty target value: ToBeRemovedWith: "18.0"
        return bool(re.search(r'toberemovedwith\s*:?\s*"?\s*[\d]', low))
    return True


def _good_symbol(name: str) -> bool:
    return bool(
        name and len(name) > 1
        and name not in _NOISE_SYMBOLS
        and name.lower() not in ("true", "false", "nil", "null", "config", "self", "this")
        and not _RULE_CODE_RE.match(name)
    )


def _extract_symbol(code: str) -> str:
    """Back-compat wrapper — returns just the symbol name (see _extract_symbol_kinded)."""
    return _extract_symbol_kinded(code)[0]


def _extract_symbol_kinded(code: str) -> tuple[str, str]:
    """Pull the most meaningful symbol from the matched code snippet, plus its KIND.

    kind is one of:
      "declaration" — Tier 1: a func/class/flag the snippet DEFINES. This is the thing
                      that can be deleted if it has no callers (genuine dead code).
      "usage"       — Tier 2: member access on a call site / //nolint line — the deprecated
                      member being USED (e.g. `tlsConfig.BuildNameToCertificate()` or
                      `option.WithCredentialsFile(...)`). The symbol is defined ELSEWHERE
                      (often a third-party library), so "0 in-repo callers" does NOT mean it
                      is deletable — deleting the call removes functionality. This is a
                      deprecated-API MIGRATION target, never an "excise" candidate.
      "fallback"    — Tier 3: a local var / generic field guess.
    """
    # Tier 1 — declarations (the thing being defined)
    for pat in _DECL_PATTERNS:
        for m in pat.finditer(code):
            if _good_symbol(m.group(1).strip()):
                return m.group(1).strip()[:60], "declaration"

    # Tier 2 — member access (rightmost meaningful) — a USAGE of an (often external) symbol
    calls = [c for c in _MEMBER_CALL_RE.findall(code) if _good_symbol(c)]
    if calls:
        return calls[-1][:60], "usage"
    fields = [f for f in _MEMBER_FIELD_RE.findall(code) if _good_symbol(f)]
    if fields:
        return fields[-1][:60], "usage"

    # Tier 3 — fallbacks
    for pat in _FALLBACK_PATTERNS:
        for m in pat.finditer(code):
            if _good_symbol(m.group(1).strip()):
                return m.group(1).strip()[:60], "fallback"
    return "", ""


def _basename_symbol(file_path: str) -> str:
    """Fallback symbol name from the file basename."""
    base = file_path.split("/")[-1]
    base = re.sub(r"\.\w+$", "", base)
    return f"file:{base}"[:60]


def _extract_intent(code: str) -> tuple[str, str]:
    """Extract (replacement, removal_target) from a deprecation comment if stated."""
    replacement = ""
    removal_target = ""

    # "use X instead", "use full_path", "replaced by X", "see X"
    m = re.search(r"\buse\s+([A-Za-z_][\w\.]+)", code, re.IGNORECASE)
    if m:
        replacement = m.group(1)[:50]
    else:
        m = re.search(r"\b(?:replaced by|superseded by|in favou?r of)\s+([A-Za-z_][\w\.]+)", code, re.IGNORECASE)
        if m:
            replacement = m.group(1)[:50]

    # "removed in v3.0", "ToBeRemovedWith: 18.0", "removed after 16.x"
    m = re.search(r'ToBeRemovedWith:\s*"?([\d][\w\.]*)"?', code)
    if m:
        removal_target = m.group(1)[:20]
    else:
        m = re.search(r"\b(?:removed?|remove)\s+(?:in|after|with)\s+v?(\d[\w\.]*)", code, re.IGNORECASE)
        if m:
            removal_target = m.group(1)[:20]

    return replacement, removal_target


def _first_marker_line(code: str, query: str) -> str:
    """Return the line of the snippet that contains the matched marker."""
    q_low = query.lower().strip(":").strip()
    for line in code.split("\n"):
        if q_low in line.lower():
            return line.strip()[:200]
    return code.split("\n")[0].strip()[:200]


def _detect_language(file_path: str, hint: str) -> str:
    ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
    mapping = {
        "go": "go", "rb": "ruby", "py": "python", "js": "js", "ts": "ts",
        "jsx": "js", "tsx": "ts", "java": "java", "rs": "rust", "php": "php",
    }
    return mapping.get(ext, hint if hint != "any" else "unknown")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:50] or "necrosis"


def _parse_date(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return dt_str[:10]


def _try_parse_dt(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
