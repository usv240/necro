"""
Evaluate whether a piece of necrotic (deprecated-but-present) code can be safely
DELETED today.

The mirror image of viability_scorer.py:
  viability_scorer asks:  "Is the kill reason still valid?"     -> should we REVIVE?
  deletion_scorer  asks:  "Is it safe to remove this now?"      -> should we EXCISE?

Reuses the existing constraint_grounder (to verify a stated removal-target version
shipped) and the Gemini JSON client. Adds ONE new live signal: caller-count via
GitLab blobs search — if nothing references the deprecated symbol anymore, it is a
strong "safe to delete" signal. Existing modules are NOT modified.

Verdicts:
  excise_now    — replacement shipped / 0 callers / aged past threshold / CI green
  needs_biopsy  — partial evidence; might still be referenced; human review
  leave_intact  — still load-bearing, replacement not shipped, or callers remain
"""

import logging
import re

from backend.services.constraint_grounder import ground_constraint
from backend.services.gemini import generate_json
from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)


async def score_deletion_safety(necrotic, project_path: str = "") -> dict:
    """
    Decide whether necrotic code is safe to excise.

    Steps:
      1. Count live callers of the symbol via GitLab blobs search (NEW signal).
      2. If a removal-target version was stated, verify it shipped (constraint_grounder).
      3. Check CI health (list_pipelines) — never recommend deleting into broken CI.
      4. Ask Gemini to weigh all evidence and return a structured verdict.
      5. Apply deterministic safety post-rules (callers found => never excise_now).

    Returns: is_safe_to_delete, callers_found, deletion_risk, effort_estimate,
             blast_radius, recommendation, reasoning, confidence, grounding.
    """
    symbol = (necrotic.name or "").strip()
    annotation = necrotic.annotation or ""
    replacement = necrotic.replacement or ""
    removal_target = necrotic.removal_target or ""
    age_days = getattr(necrotic, "age_days", 0) or 0
    language = getattr(necrotic, "language", "unknown")

    # Is this finding a USAGE of a deprecated (often third-party) symbol rather than a
    # deletable in-repo definition? e.g. `tlsConfig.BuildNameToCertificate()` or
    # `option.WithCredentialsFile(...)` with a //nolint:staticcheck. For these the symbol
    # is defined ELSEWHERE, so "0 in-repo callers" is meaningless and deleting the line
    # removes real functionality — they are deprecated-API MIGRATION targets, never
    # "excise" candidates. This is the guard that stops NECRO from recommending deletion
    # of load-bearing code (its core safety promise).
    is_usage = (
        getattr(necrotic, "symbol_kind", "declaration") == "usage"
        or necrotic.detection_method == "suppressed_deprecation"
    )

    # ── 1. Caller count via blobs search ─────────────────────────────────────
    # If the deprecated symbol is referenced nowhere else, it's a strong delete
    # signal. We search for the bare symbol and subtract self-references in the
    # declaring file.
    #
    # Accuracy notes:
    # * per_page=30 caps results — generic names (Error, Handler, Stage, String)
    #   will saturate the 30-result window; the count is an undercount for these.
    # * Same-file callers are excluded by design (we want external references).
    #   For struct-field accesses or file-local helpers this is correct behaviour:
    #   the deprecation IS in the file, and removing it won't break anything external.
    #   For exported functions called only within their own package, the count is
    #   also correct — 0 external callers means safe to remove (or via interface,
    #   but that risk is captured in the Gemini prompt).
    _GENERIC_IDENTIFIERS = frozenset({
        "error", "handler", "stage", "string", "len", "type", "value",
        "name", "data", "result", "response", "request", "client",
    })
    callers_found = -1  # -1 = unknown
    caller_files: list[str] = []
    caller_count_reliable = True
    searchable = symbol and not symbol.startswith("file:") and len(symbol) >= 4
    if searchable and project_path:
        try:
            hits = await mcp.search_blobs(project_path, symbol, per_page=30)
            # NOTE: each alternative is independently anchored. A single trailing
            # $ over the whole group (the previous bug) made the directory patterns
            # /spec/ /test/ only match when the PATH ENDED with them — which never
            # happens for a file — so spec/test files slipped through as "callers".
            _TEST_FILE_RE = re.compile(
                r"_test\.(go|py|rb|js)$"      # Go/Py/Ruby/JS unit test suffix
                r"|_spec\.(rb|js|ts)$"        # RSpec + JS/TS spec suffix
                r"|\.(spec|test)\.(js|ts|py|rb)$"  # foo.spec.js / foo.test.ts
                r"|(^|/)(spec|tests?)/",      # spec/ test/ tests/ as a path segment
                re.IGNORECASE,
            )
            distinct_files = {
                (h.get("path") or h.get("filename") or "")
                for h in hits
                if (h.get("path") or h.get("filename"))
                # Test files are expected to reference deprecated symbols in
                # assertions — they don't represent load-bearing production callers.
                and not _TEST_FILE_RE.search(h.get("path") or h.get("filename") or "")
            }
            # Exclude the declaring file itself — we want EXTERNAL callers
            distinct_files.discard(necrotic.file_path)
            caller_files = sorted(f for f in distinct_files if f)
            callers_found = len(caller_files)
            # If the result window is near-full (≥25 of 30) OR the symbol is short/
            # generic, the count is likely an undercount — flag it so the prompt is
            # honest. 25 rather than 30: "human_name" returned 29 hits in gitlab-org/
            # gitlab where the real count is hundreds.
            if len(hits) >= 25 or symbol.lower() in _GENERIC_IDENTIFIERS:
                caller_count_reliable = False
            logger.info(
                "[Necrosis] %s: %d external caller file(s) (reliable=%s)",
                symbol, callers_found, caller_count_reliable,
            )
        except Exception as exc:
            logger.debug("Caller count failed for %s: %s", symbol, exc)

    # ── 2. Ground the removal-target version (reuse constraint_grounder) ──────
    grounding = {
        "grounded": False, "technology": "", "latest_version": "",
        "evidence_date": "", "evidence_url": "", "description": "",
        "source": "unverified", "is_resolved": None,
    }
    if removal_target or replacement:
        try:
            constraint_text = (
                f"{replacement or symbol} {removal_target}".strip()
                or annotation
            )
            grounding = await ground_constraint(
                constraint_text=constraint_text,
                kill_date=getattr(necrotic, "annotation_date", "") or "unknown date",
            )
        except Exception as exc:
            logger.debug("Removal-target grounding failed for %s: %s", symbol, exc)

    # ── 3. CI health (same pattern as viability_scorer) ──────────────────────
    ci_block = ""
    ci_broken = False
    if project_path:
        try:
            pipelines = await mcp.list_pipelines(project_path, per_page=3)
            if pipelines:
                last_status = pipelines[0].get("status", "unknown")
                ci_broken = last_status == "failed"
                ci_block = (
                    f"\nGITLAB CI STATUS (live): most recent pipeline = {last_status.upper()}. "
                    + ("RISK: CI is broken — do NOT delete code into a red pipeline."
                       if ci_broken else "CI healthy — safe environment for removal.")
                )
        except Exception as exc:
            logger.debug("CI check skipped: %s", exc)

    # ── 4. Caller evidence block for the prompt ──────────────────────────────
    if callers_found == 0 and caller_count_reliable:
        caller_block = (
            f"CALLER ANALYSIS (live GitLab blobs search, reliable): 0 external files "
            f"reference '{symbol}'. Nothing outside its own file uses it — strong "
            f"signal that removal is safe."
        )
    elif callers_found == 0 and not caller_count_reliable:
        caller_block = (
            f"CALLER ANALYSIS (live GitLab blobs search, UNRELIABLE — symbol is "
            f"short/generic, 30-result window may be saturated): 0 external files found "
            f"in the sampled results, but true caller count may be higher. "
            f"Treat as 'unknown' and prefer needs_biopsy."
        )
    elif callers_found > 0 and caller_count_reliable:
        preview = ", ".join(caller_files[:5])
        caller_block = (
            f"CALLER ANALYSIS (live GitLab blobs search, reliable): {callers_found} "
            f"external file(s) still reference '{symbol}': {preview}. "
            f"Removal would require migrating these call sites first."
        )
    elif callers_found > 0 and not caller_count_reliable:
        preview = ", ".join(caller_files[:5])
        caller_block = (
            f"CALLER ANALYSIS (live GitLab blobs search, UNRELIABLE — 30-result window "
            f"saturated): at least {callers_found} external file(s) reference '{symbol}': "
            f"{preview}. True count is likely higher — do NOT excise_now."
        )
    else:
        caller_block = (
            f"CALLER ANALYSIS: could not reliably count callers of '{symbol}' "
            f"(symbol too generic or search unavailable). Treat blast radius as unknown."
        )

    usage_block = ""
    if is_usage:
        usage_block = (
            "\nSYMBOL KIND: USAGE (not a definition). This snippet USES a deprecated symbol "
            f"('{symbol}') that is defined elsewhere — typically a third-party/stdlib API "
            "with a //nolint:staticcheck suppression (e.g. tls.Config.BuildNameToCertificate, "
            "option.WithCredentialsFile). The caller count is therefore irrelevant: deleting "
            "this line REMOVES FUNCTIONALITY, it does not remove dead code. The correct action "
            "is to MIGRATE to the replacement API, not excise. Recommendation MUST be "
            "needs_biopsy at most — NEVER excise_now."
        )

    grounding_block = ""
    if grounding.get("grounded"):
        grounding_block = (
            f"\nREMOVAL-TARGET EVIDENCE (source: {grounding['source']}): "
            f"{grounding['technology']} latest {grounding['latest_version']} "
            f"({grounding.get('evidence_date','')}), {grounding['evidence_url']}. "
            f"Released after deprecation: {grounding.get('is_resolved')}."
        )

    prompt = f"""A piece of code in a live codebase is annotated as deprecated/dead but has NOT been removed.

Symbol: {symbol}
File: {necrotic.file_path}
Language: {language}
Deprecation annotation: "{annotation}"
Stated replacement: {replacement or "not stated"}
Stated removal target: {removal_target or "not stated"}
How long it has carried the deprecation annotation: {age_days} days
Detection method: {necrotic.detection_method}

{caller_block}
{usage_block}
{grounding_block}
{ci_block}

Decide whether this deprecated code can be SAFELY DELETED today (May 2026).

Return a JSON object with these exact fields:
{{
  "is_safe_to_delete": true or false,
  "deletion_risk": 0 to 10 (0 = trivially safe to delete, 10 = extremely risky),
  "blast_radius": "one sentence: what would break if this is removed",
  "effort_estimate": "rough estimate like '30 min', '2-3 hours', '1-2 days'",
  "technical_risks": ["specific", "risks", "of", "removing", "it"],
  "recommendation": "excise_now" or "needs_biopsy" or "leave_intact",
  "reasoning": "2-3 sentences citing the caller analysis and evidence above",
  "confidence": "high" if caller analysis + evidence are clear, "medium" if plausible, "low" if uncertain
}}

Recommendation guide:
- excise_now: ALL of the following:
    * Caller analysis is RELIABLE (not flagged as unreliable/generic)
    * 0 external callers confirmed
    * aged >= 180 days
    * No explicit removal blocker in the annotation ("cannot remove", "still used", etc.)
    * AND at least ONE of:
        - replacement shipped (verified in grounding evidence)
        - annotation explicitly says safe to remove / scheduled for removal
        - aged >= 365 days AND deletion_risk <= 2 (long-lived dead code with no external callers is safe to excise even without a stated replacement — if nothing calls it, risk is inherently low)
    NOTE: a symbol with 0 confirmed external callers CANNOT legitimately have deletion_risk > 3.
    If you think it has high risk despite 0 callers, explain why in reasoning and use needs_biopsy.
- needs_biopsy: any callers found; OR caller analysis is unreliable; OR annotation states a blocker; OR ambiguous evidence; OR aged < 180 days
- leave_intact: callers remain with no migration path; OR annotation says still load-bearing; OR removal target version has NOT shipped; OR CI is broken

IMPORTANT: if the CALLER ANALYSIS is marked UNRELIABLE, always use needs_biopsy at most, regardless of the count shown. A wrong deletion breaks production.
If ANY external callers were found (reliable or not), do NOT say excise_now."""

    result = await generate_json(prompt, thinking_budget=1024)

    if not (result and "recommendation" in result):
        return {
            "is_safe_to_delete": False,
            "deletion_risk": 5,
            "blast_radius": "Unknown — insufficient context",
            "effort_estimate": "unknown",
            "technical_risks": ["Insufficient context to assess deletion safety"],
            "recommendation": "needs_biopsy",
            "reasoning": "Could not gather enough evidence to recommend deletion confidently.",
            "confidence": "low",
            "callers_found": callers_found,
            "caller_files": caller_files,
            "grounding": grounding,
        }

    result["callers_found"] = callers_found
    result["caller_files"] = caller_files
    result["caller_count_reliable"] = caller_count_reliable
    result["grounding"] = grounding

    # ── 5. Deterministic safety post-rules ───────────────────────────────────
    rec = result.get("recommendation")

    # Hard rule (safety-critical): a USAGE of a deprecated symbol is never dead code to
    # excise — it's a migration target. Deleting `option.WithCredentialsFile(...)` would
    # break credential loading even though it has "0 in-repo callers". Cap at needs_biopsy
    # and reframe. This upholds the scanner's promise to never recommend deleting
    # load-bearing code.
    if is_usage:
        if result.get("recommendation") == "excise_now":
            result["recommendation"] = "needs_biopsy"
        result["deletion_risk"] = max(result.get("deletion_risk", 5), 5)
        result["reasoning"] = (
            result.get("reasoning", "") +
            f" This is a USAGE of a deprecated symbol ('{symbol}') defined elsewhere "
            "(suppressed third-party/stdlib deprecation), not deletable dead code — the "
            "'0 callers' count reflects that the definition lives in another package. "
            "Migrate to the replacement API rather than deleting the call site."
        )
        result.setdefault("technical_risks", []).insert(
            0, "Deprecated-API usage, not dead code — deleting the call removes functionality; migrate instead",
        )

    # Override Gemini's deletion_risk when we have reliable caller data.
    # Gemini consistently over-estimates risk (gives 8/10 to 0-caller functions)
    # because it reasons about internal codebase complexity rather than actual
    # external blast radius. The caller count IS the blast radius — derive it.
    if callers_found == 0 and caller_count_reliable and not is_usage:
        # (usage findings are excluded — 0 in-repo callers does NOT imply low risk for a
        # symbol that is DEFINED elsewhere; that's handled by the usage guard above.)
        if age_days >= 365:
            # 0 external callers + 1+ year old = risk ≤ 1 (possibly an interface,
            # but with 0 grep hits in a 30-result window, that's the only risk)
            result["deletion_risk"] = min(result.get("deletion_risk", 1), 1)
        else:
            result["deletion_risk"] = min(result.get("deletion_risk", 3), 3)
    elif callers_found > 0 and caller_count_reliable:
        # Always floor risk at 5 when there are real callers (migration needed)
        result["deletion_risk"] = max(result.get("deletion_risk", 5), 5)

    # Hard rule: ANY external callers => never excise_now (cap at needs_biopsy).
    if callers_found > 0 and rec == "excise_now":
        result["recommendation"] = "needs_biopsy"
        result["reasoning"] = (result.get("reasoning", "") +
            f" Downgraded from excise_now: {callers_found} external caller(s) still reference this symbol.")
        result.setdefault("technical_risks", []).insert(
            0, f"{callers_found} external file(s) still call this symbol — migrate first")

    # Hard rule: an explicit "cannot remove yet" / "still used" blocker in the
    # annotation forces leave_intact regardless of caller count.
    _BLOCKER_PHRASES = (
        "cannot remove", "can't remove", "still used", "still in use",
        "do not remove", "don't remove", "keep for", "needed for",
        "has an index", "backward compat", "backwards compat",
    )
    if any(p in annotation.lower() for p in _BLOCKER_PHRASES):
        if result["recommendation"] == "excise_now":
            result["recommendation"] = "needs_biopsy"
        result["reasoning"] = (result.get("reasoning", "") +
            " Annotation states an explicit removal blocker — flagged for human review.")

    # Freshness rule: too-recent deprecations are likely intentional, not dead.
    if 0 < age_days < 180 and result["recommendation"] == "excise_now":
        result["recommendation"] = "needs_biopsy"
        result["reasoning"] = (result.get("reasoning", "") +
            f" Deprecation is only {age_days} days old — may be an intentional recent decision.")

    # Promotion rule: if Gemini said needs_biopsy but all hard evidence is clear,
    # upgrade to excise_now. Gemini can be over-cautious when no replacement is
    # stated even though 0 callers + 0 risk + old age is unambiguous dead code.
    # Never promote if caller count is unreliable (generic symbol / saturated window).
    # Promotion rule: if Gemini said needs_biopsy or leave_intact but all hard evidence
    # is clear, upgrade to excise_now.  Gemini is over-cautious when no replacement is
    # stated even though 0 callers + old age is unambiguous dead code.
    # Use deletion_risk <= 2 (not == 0): a func with 0 external callers cannot realistically
    # be risk > 2 — risk 8 on a 0-caller symbol means Gemini is confused, not that it's risky.
    if (
        result.get("recommendation") in ("needs_biopsy", "leave_intact")
        and not is_usage  # never promote a deprecated-API usage to excise
        and callers_found == 0
        and caller_count_reliable
        and age_days >= 365
        and result.get("deletion_risk", 10) <= 2
        and not any(p in annotation.lower() for p in _BLOCKER_PHRASES)
        and not ci_broken
    ):
        result["recommendation"] = "excise_now"
        result["reasoning"] = (
            result.get("reasoning", "") +
            " Promoted to excise_now: 0 reliable external callers + low deletion risk "
            f"({result.get('deletion_risk')}/10) + {age_days}d old with no annotation "
            "blocker — textbook dead code."
        )

    # CI broken => never excise into a red pipeline.
    if ci_broken and result["recommendation"] == "excise_now":
        result["recommendation"] = "needs_biopsy"
        result.setdefault("technical_risks", []).insert(
            0, "CI pipeline is currently failing — stabilize before removing code")

    logger.info(
        "Deletion verdict: %s (risk=%s, callers=%s, rec=%s)",
        symbol, result.get("deletion_risk"), callers_found, result.get("recommendation"),
    )
    return result
