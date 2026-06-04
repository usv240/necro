"""
Feature detection: five strategies for finding deliberately disabled features.

All data retrieval goes through the GitLab MCP client (or its REST fallback),
so the call log that appears in the UI shows real MCP tool usage.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)

# Keywords in commit messages that suggest deliberate feature disablement
_DISABLE_KEYWORDS = re.compile(
    r"\b(disabl|remov|revert|kill|bury|shelv|deprecat|comment.?out|roll.?back|turn.?off|flag.?off)\w*\b"
    r"|featureflag:\s*remov"  # gitaly-style: "featureflag: remove X"
    r"|REGISTRY_FF_\w+",       # container-registry: "REGISTRY_FF_ENFORCE_LOCKFILES"
    re.IGNORECASE,
)

_FEATURE_FLAG_PATTERNS = [
    # Python / Ruby / JS style
    re.compile(r"FEATURE[_\-][A-Z_]+\s*=\s*[Ff]alse"),
    re.compile(r"ENABLE[_\-][A-Z_]+\s*=\s*[Ff]alse"),
    re.compile(r"enabled\s*[=:]\s*false", re.IGNORECASE),
    re.compile(r"feature_flag\s*[=:]\s*false", re.IGNORECASE),
    re.compile(r"@feature\.(?:disable|off)\(", re.IGNORECASE),
    re.compile(r"\.feature\([\'\"][^\'\"]+[\'\"],\s*false\)"),
    re.compile(r"if\s+settings\.FEATURE_\w+\s*==\s*[Ff]alse"),
    # Go style (gitaly, container-registry, gitlab-runner)
    re.compile(r"OnByDefault:\s*false", re.IGNORECASE),
    re.compile(r"ops\.FeatureFlag\s*\{"),
    re.compile(r"featureflag\.[A-Z][A-Za-z0-9]+"),  # featureflag.TrackMaxRssAnon
    re.compile(r"REGISTRY_FF_[A-Z_]+"),               # REGISTRY_FF_ENFORCE_LOCKFILES
    re.compile(r"const\s+[A-Z_]*_?FF_?[A-Z_]+\s*="), # Go FF constants
]


@dataclass
class DeadFeature:
    id: str                          # slug, e.g. "recurring-billing"
    name: str                        # human readable
    kill_commit_sha: str
    kill_commit_message: str
    kill_date: str                   # ISO date string
    detection_method: str            # how we found it
    linked_mr_iid: Optional[int] = None
    linked_issue_iids: list[int] = field(default_factory=list)
    context_snippets: list[str] = field(default_factory=list)
    diff_excerpt: str = ""

    # Quality signals — each confirmed evidence source adds to confidence.
    # Features with detection_confidence < 2 are filtered before Gemini analysis.
    # detection_signals lists what we found (for transparency in the UI).
    detection_confidence: int = 0
    detection_signals: list[str] = field(default_factory=list)

    # Populated in later pipeline stages
    death_reason: Optional[dict] = None
    viability: Optional[dict] = None
    roi: Optional[dict] = None


async def _fetch_commits_stratified(
    project_path: str,
    since_date: datetime,
    until_date: datetime,
    max_commits: int,
    log_mcp,
    emit,
) -> list[dict]:
    """
    Sample commits from evenly-spaced yearly buckets across the full date range.

    GitLab's list_commits API returns newest-first. For large repos (e.g. gitlab-foss
    at ~2,000 commits/year), a single paginated call capped at 500 only covers the
    most recent few months of a multi-year window — missing all historical feature
    kills. Stratified sampling fixes this: one API call per year-bucket ensures every
    era of the codebase is represented, not just the most recent one.
    """
    total_days = max(1, (until_date - since_date).days)
    bucket_count = max(1, min(8, total_days // 365))
    bucket_days = total_days / bucket_count
    per_bucket = min(100, max(50, max_commits // bucket_count))

    all_commits: list[dict] = []
    seen_shas: set[str] = set()

    for i in range(bucket_count):
        b_since = since_date + timedelta(days=i * bucket_days)
        b_until = since_date + timedelta(days=(i + 1) * bucket_days)
        b_until = min(b_until, until_date)

        batch = await mcp.list_commits(
            project_path,
            per_page=per_bucket,
            page=1,
            since=b_since.isoformat(),
            until=b_until.isoformat(),
        )
        if log_mcp:
            log_mcp(
                "list_commits",
                repo=project_path,
                bucket=f"{b_since.strftime('%Y-%m')}→{b_until.strftime('%Y-%m')}",
                result_count=len(batch),
            )
        await emit(
            f"[MCP] list_commits bucket {i + 1}/{bucket_count} "
            f"({b_since.strftime('%Y-%m')} → {b_until.strftime('%Y-%m')}): {len(batch)} commits"
        )

        for c in batch:
            sha = c.get("id", "")
            if sha not in seen_shas:
                seen_shas.add(sha)
                all_commits.append(c)

        if len(all_commits) >= max_commits:
            break

    return all_commits


async def detect_dead_features(
    project_path: str,
    max_commits: int = 500,
    lookback_months: int = 36,
    progress_cb=None,
    mcp_calls: list | None = None,
) -> list[DeadFeature]:
    """
    Run all five detection strategies against a GitLab repo.
    progress_cb(message: str) is called for each step to stream to the client.
    mcp_calls is an optional list that will be populated with every MCP tool call made,
    providing a verifiable audit log of GitLab MCP usage (similar to 'source: mcp').
    """

    def log_mcp(tool: str, **kwargs):
        if mcp_calls is not None:
            entry = {"tool": tool, "source": "gitlab_mcp", **kwargs}
            mcp_calls.append(entry)

    async def emit(msg: str):
        logger.info(msg)
        if progress_cb:
            await progress_cb(msg)

    now = datetime.now(timezone.utc)
    # Skip the last 60 days — features killed that recently haven't had enough time
    # for their blocking constraint to resolve, so they all land as "investigate_further".
    since_date = now - timedelta(days=lookback_months * 30)
    until_date = now - timedelta(days=60)

    total_days = max(1, (until_date - since_date).days)
    bucket_count = max(1, min(8, total_days // 365))
    await emit(
        f"[MCP] list_commits — stratified {since_date.strftime('%Y-%m')} → "
        f"{until_date.strftime('%Y-%m')} ({lookback_months}mo, {bucket_count} yearly buckets, "
        f"up to {max_commits} commits)..."
    )

    all_commits = await _fetch_commits_stratified(
        project_path, since_date, until_date, max_commits, log_mcp, emit
    )
    log_mcp("list_commits_total", repo=project_path, result_count=len(all_commits))

    # Adaptive fallback: if stratified sampling still returns < 20 commits total,
    # the repo is either very low-activity or the API doesn't honour since/until.
    if len(all_commits) < 20:
        await emit(
            f"Stratified sampling returned only {len(all_commits)} commits — "
            f"widening to most recent {max_commits} commits (no date filter)..."
        )
        all_commits = []
        page = 1
        while len(all_commits) < max_commits:
            batch = await mcp.list_commits(project_path, per_page=100, page=page)
            if not batch:
                break
            all_commits.extend(batch)
            page += 1
            if len(batch) < 100:
                break
        all_commits = all_commits[:max_commits]
        until_date = now - timedelta(days=30)
        log_mcp("list_commits_fallback", repo=project_path, result_count=len(all_commits))
        await emit(f"[MCP] Fallback: fetched {len(all_commits)} commits")
    await emit(f"[MCP] list_commits returned {len(all_commits)} commits across {bucket_count} time buckets")

    if not all_commits:
        await emit("No commits found — check repository path and token permissions")
        return []

    # Run detection strategies in sequence
    candidates: list[DeadFeature] = []

    await emit("Scanning for revert commits...")
    candidates.extend(_detect_reverts(all_commits))

    await emit("Scanning for feature flag disablements...")
    candidates.extend(await _detect_feature_flags(all_commits, project_path, emit, log_mcp))

    await emit("Scanning commit messages for disable keywords...")
    candidates.extend(_detect_by_message(all_commits))

    await emit(f"[MCP] list_issues — scanning closed issues for shelved features...")
    issues = await mcp.list_issues(project_path, state="closed", per_page=100)
    log_mcp("list_issues", repo=project_path, state="closed", result_count=len(issues))
    await emit(f"[MCP] list_issues returned {len(issues)} closed issues")
    candidates.extend(_detect_from_issues(issues))

    await emit(f"[MCP] list_merge_requests — scanning merged MRs...")
    mrs = await mcp.list_merge_requests(project_path, state="merged", per_page=100)
    log_mcp("list_merge_requests", repo=project_path, state="merged", result_count=len(mrs))
    await emit(f"[MCP] list_merge_requests returned {len(mrs)} merged MRs")
    candidates.extend(_detect_from_mrs(mrs, all_commits))

    await emit("[MCP] feature_flags — querying GitLab native Feature Flags API...")
    candidates.extend(await _detect_from_feature_flags_api(project_path, emit, log_mcp))

    # Deduplicate by kill commit SHA
    seen: set[str] = set()
    unique: list[DeadFeature] = []
    for f in candidates:
        key = f.kill_commit_sha or f.id
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # Drop features killed in the last 60 days — too fresh for viability scoring
    # (Gemini correctly says "constraint may not have resolved yet" → all become
    # "investigate_further" and no "revive_now" results appear in the UI).
    fresh_count = 0
    aged: list[DeadFeature] = []
    for f in unique:
        kill_dt = _try_parse_kill_date(f.kill_date or "")
        if kill_dt and kill_dt > until_date:
            fresh_count += 1
        else:
            aged.append(f)
    if fresh_count:
        await emit(f"Filtered {fresh_count} features killed in last 60 days (too recent for viability)")
    unique = aged

    # Garbage-name filter: drop candidates whose extracted name is clearly not a feature
    # (usernames, linter pragmas, dangling prepositions from bad slice extraction, etc.).
    # These produce embarrassing false positives in the UI and waste Gemini calls.
    garbage_count = 0
    cleanup_count = 0
    clean: list[DeadFeature] = []
    for f in unique:
        if _is_garbage_feature_name(f.name):
            garbage_count += 1
        elif _is_cleanup_removal(f.name, f.kill_commit_message):
            # Removing something described as redundant/unused/dead/duplicate is correct
            # housekeeping, NOT a feature that was killed for an external constraint.
            # Reviving it would re-introduce the very thing that was deliberately cleaned up.
            cleanup_count += 1
        else:
            clean.append(f)
    if garbage_count:
        await emit(f"Filtered {garbage_count} garbage-name candidates (usernames/pragmas/dangling prepositions)")
    if cleanup_count:
        await emit(f"Filtered {cleanup_count} cleanup-removal candidates (redundant/unused/dead code — not revivable)")
    unique = clean

    await emit(f"Found {len(unique)} raw candidates — enriching with MR/issue context and scoring signal quality...")

    # Enrich each candidate with linked MR notes and issue context
    for feat in unique:
        await _enrich_feature(feat, project_path, emit, log_mcp)

    # ── Quality gate: score each feature, drop low-confidence noise ──────────
    # A feature must have ≥2 independent signals before being sent to Gemini.
    # This prevents keyword noise (maintenance "remove X" commits) from wasting
    # API calls and polluting results with low-quality false positives.
    for feat in unique:
        _score_feature_confidence(feat)

    # Method-specific thresholds:
    #   feature_flag_removal / gitlab_feature_flags_api — explicit by definition, auto-pass (≥1)
    #   revert_commit — intentional by definition, auto-pass (≥1)
    #   shelved_issue / commit_message_keyword — needs corroboration (≥2)
    _AUTO_PASS = {"feature_flag_removal", "gitlab_feature_flags_api", "revert_commit"}
    high_conf = [
        f for f in unique
        if f.detection_method in _AUTO_PASS and f.detection_confidence >= 1
        or f.detection_confidence >= 2
    ]
    low_conf = [f for f in unique if f not in high_conf]

    if low_conf:
        await emit(
            f"Quality gate: filtered {len(low_conf)} low-signal candidates "
            f"(keyword-only, no diff/MR/issue corroboration)"
        )

    # No dishonest resurrection. If nothing clears the quality gate, the honest
    # answer is "no strong-signal revival candidates" — NOT to relabel filtered
    # keyword-noise (routine "Remove X" cleanup) as "high-confidence". Returning []
    # lets the caller show the accurate "clean codebase" message instead of feeding
    # weak, contextless candidates to Gemini (which then confabulates kill reasons).
    if not high_conf:
        await emit(
            "Detection complete — 0 strong-signal revival candidates "
            "(only routine cleanup / keyword-noise removals found in this window)"
        )
        return []

    await emit(f"Detection complete — {len(high_conf)} strong-signal dead feature(s)")
    return high_conf


# ── Quality gate: confidence scoring ─────────────────────────────────

# Patterns that signal a feature was INTENTIONALLY disabled (not maintenance)
_INTENTIONAL_DISABLE_PATTERNS = re.compile(
    r"\b(feature.flag|featureflag|REGISTRY_FF_|OnByDefault|temporary|temp\b|"
    r"revisit|blocked.by|tracked.in|follow.?up|TODO|FIXME|re-enable|reenable|"
    r"roll.?back|revert.*for|disabled.until|disabled.pending|disabled.due)\w*\b",
    re.IGNORECASE,
)

# Patterns that suggest this is maintenance/cleanup, NOT a dead feature
_MAINTENANCE_PATTERNS = re.compile(
    r"\b(test|spec|translation|i18n|l10n|lint|format|style|typo|docs?|"
    r"readme|whitespace|blank.line|unused.import|dead.code|cleanup|"
    r"refactor|rename|reorgan|restructur)\w*\b",
    re.IGNORECASE,
)


def _score_feature_confidence(feat: DeadFeature) -> None:
    """
    Score detection confidence (0–5) based on independent corroborating signals.
    Mutates feat.detection_confidence and feat.detection_signals in place.

    Scoring:
      +2 : Explicit feature flag pattern in method or commit prefix
      +2 : Commit diff shows real code removal (not just a one-liner)
      +1 : Linked MR or issue provides context
      +1 : Commit message contains intentional-disable language
      +1 : Shelved issue with disable/wont-fix label
      -1 : Commit message looks like maintenance/cleanup (test, translation, etc.)
      -2 : No diff evidence and single-word commit message (near-certain false positive)
    """
    signals: list[str] = []
    score = 0

    msg = (feat.kill_commit_message or "").lower()
    diff = feat.diff_excerpt or ""
    snippets = " ".join(feat.context_snippets or [])

    # ── Strong positive signals ───────────────────────────────────────
    # Explicit feature flag detection is the gold standard
    if feat.detection_method == "feature_flag_removal":
        score += 2
        signals.append("explicit feature flag")
    elif feat.detection_method == "gitlab_feature_flags_api":
        score += 2
        signals.append("GitLab feature flags API")
    elif feat.detection_method == "revert_commit":
        # Reverts are intentional by definition — someone deliberately undid a change
        score += 1
        signals.append("intentional revert commit")
    elif feat.detection_method == "shelved_issue":
        score += 1
        signals.append("shelved/disabled issue")

    # Diff shows actual code was removed (at least 3 removed lines = real code change)
    removed_lines = [ln for ln in diff.split("\n") if ln.startswith("-") and ln.strip() not in ("-", "")]
    if len(removed_lines) >= 3:
        score += 2
        signals.append(f"diff: {len(removed_lines)} lines removed")
    elif len(removed_lines) >= 1:
        score += 1
        signals.append(f"diff: {len(removed_lines)} line(s) removed")

    # Linked MR or issue (independent context source)
    if feat.linked_mr_iid:
        score += 1
        signals.append(f"linked MR !{feat.linked_mr_iid}")
    if feat.linked_issue_iids:
        score += 1
        signals.append(f"linked issue(s) #{feat.linked_issue_iids[0]}")

    # ── Contextual positive signals ───────────────────────────────────
    # Intentional-disable language in commit message or snippets
    if _INTENTIONAL_DISABLE_PATTERNS.search(feat.kill_commit_message or ""):
        score += 1
        signals.append("intentional-disable language in commit")
    elif _INTENTIONAL_DISABLE_PATTERNS.search(snippets):
        score += 1
        signals.append("intentional-disable language in context")

    # ── Negative signals (maintenance noise) ─────────────────────────
    if _MAINTENANCE_PATTERNS.search(feat.kill_commit_message or ""):
        score -= 1
        signals.append("⚠ maintenance pattern in message")

    # Very short commit message + no diff = almost certainly noise
    # BUT: explicit detection methods are inherently meaningful — don't penalize them
    is_explicit = feat.detection_method in ("feature_flag_removal", "gitlab_feature_flags_api", "revert_commit")
    words = msg.split()
    if len(words) <= 3 and not diff and not is_explicit:
        score -= 2
        signals.append("⚠ very short message, no diff")

    feat.detection_confidence = max(0, score)
    feat.detection_signals = signals


# ── Detection strategy 1: Revert commits ──────────────────────────────


_MERGE_BRANCH_RE = re.compile(r"^Merge branch\b", re.IGNORECASE)

def _detect_reverts(commits: list[dict]) -> list[DeadFeature]:
    features = []
    for c in commits:
        title = c.get("title", "") or c.get("message", "")
        if not title.lower().startswith("revert"):
            continue
        # Skip bare "Revert 'Merge branch ...'" — meta merge commits, not features
        inner = re.sub(r'^revert\s+["\']?', '', title, flags=re.IGNORECASE).strip('"\'').strip()
        if _MERGE_BRANCH_RE.match(inner):
            continue
        # Use inner (already stripped of "Revert" prefix and outer quotes) as name basis.
        # Strip conventional commit type prefix: "feat(scope): ", "chore: ", etc.
        inner_clean = re.sub(
            r"^(?:feat|fix|chore|refactor|test|ci|docs?)(?:\([^)]*\))?\s*[:\-]\s*",
            "",
            inner,
            flags=re.IGNORECASE,
        ).strip()
        # Strip leading action verbs that describe what was done to the feature,
        # NOT verbs that describe the feature itself (upgrade/add/update give useful context).
        # e.g. "Remove GPG signing color" → "GPG signing color"
        #      "Disable S3 checksum" → "S3 checksum"
        #      "upgrade google-cloud-storage from 0.36 to 0.38" → unchanged (useful info)
        inner_clean = re.sub(
            r"^(remove|disable|bury|kill|shelve|deprecate|revert)\s+",
            "",
            inner_clean,
            flags=re.IGNORECASE,
        ).strip()
        name = inner_clean[:70] if inner_clean else f"reverted-{c.get('id', '')[:8]}"
        features.append(DeadFeature(
            id=_slugify(name),
            name=name,
            kill_commit_sha=c.get("id", ""),
            kill_commit_message=title,
            kill_date=_parse_date(c.get("created_at", "")),
            detection_method="revert_commit",
            context_snippets=[f"Revert commit: {title}"],
        ))
    return features


# ── Detection strategy 2: Feature flag disablements ───────────────────


async def _detect_feature_flags(
    commits: list[dict],
    project_path: str,
    emit,
    log_mcp=None,
) -> list[DeadFeature]:
    features = []
    candidates = [
        c for c in commits
        if _DISABLE_KEYWORDS.search(c.get("title", "") or c.get("message", ""))
    ]

    for c in candidates[:30]:  # limit MCP calls
        sha = c.get("id", "")
        if not sha:
            continue
        await emit(f"[MCP] get_commit {sha[:8]} — checking diff for feature flag changes...")
        detail = await mcp.get_commit(project_path, sha)
        if log_mcp:
            log_mcp("get_commit", repo=project_path, sha=sha[:8], found=detail is not None)
        if not detail:
            continue

        diff = detail.get("diff", "") or ""
        if not diff:
            diffs = detail.get("diffs", [])
            diff = "\n".join(d.get("diff", "") for d in diffs if isinstance(d, dict))

        for pattern in _FEATURE_FLAG_PATTERNS:
            removed_lines = [
                ln.lstrip("-")
                for ln in diff.split("\n")
                if ln.startswith("-") and pattern.search(ln)
            ]
            if removed_lines:
                flag_name = _extract_flag_name(removed_lines[0]) or _extract_feature_name_from_message(c.get("title", ""))
                name = flag_name or f"feature-{sha[:8]}"
                features.append(DeadFeature(
                    id=_slugify(name),
                    name=name,
                    kill_commit_sha=sha,
                    kill_commit_message=c.get("title", ""),
                    kill_date=_parse_date(c.get("created_at", "")),
                    detection_method="feature_flag_removal",
                    diff_excerpt="\n".join(removed_lines[:5]),
                    context_snippets=[f"Feature flag removed: {removed_lines[0]}"],
                ))
                break  # one detection per commit

    return features


# ── Detection strategy 3: Disable keywords in commit messages ─────────


_FF_PREFIX = re.compile(
    r"^(featureflag:\s*remove|feat\(.*\):\s*remove\s+[A-Z_]*_?FF_|ff-remove-)",
    re.IGNORECASE,
)

def _detect_by_message(commits: list[dict]) -> list[DeadFeature]:
    features = []
    for c in commits:
        title = c.get("title", "") or c.get("message", "")
        if not _DISABLE_KEYWORDS.search(title):
            continue
        # Skip if already caught by revert strategy
        if title.lower().startswith("revert"):
            continue
        # Skip "Merge branch '...'" meta-commits — they're plumbing, not features
        if _MERGE_BRANCH_RE.match(title):
            continue
        name = _extract_feature_name_from_message(title) or f"disabled-{c.get('id','')[:8]}"
        # Use precise detection_method for feature flag commits (gitaly / container-registry style)
        method = "feature_flag_removal" if _FF_PREFIX.search(title) else "commit_message_keyword"
        features.append(DeadFeature(
            id=_slugify(name),
            name=name,
            kill_commit_sha=c.get("id", ""),
            kill_commit_message=title,
            kill_date=_parse_date(c.get("created_at", "")),
            detection_method=method,
            context_snippets=[f"Commit message: {title}"],
        ))
    return features


# ── Detection strategy 4: Closed issues with shelved/disabled labels ──


_SHELVED_LABELS = {"disabled", "wont-fix", "wontfix", "shelved", "deferred", "postponed", "rejected"}

_SHELVED_TITLE_PATTERNS = re.compile(
    r"\b(disable|remove|deprecate|shelve|sunset|kill|bury)\b",
    re.IGNORECASE,
)


def _detect_from_issues(issues: list[dict]) -> list[DeadFeature]:
    features = []
    for issue in issues:
        labels = {str(lbl).lower() for lbl in (issue.get("labels") or [])}
        title = issue.get("title", "")
        if not (labels & _SHELVED_LABELS or _SHELVED_TITLE_PATTERNS.search(title)):
            continue
        name = _extract_feature_name_from_message(title) or f"issue-{issue.get('iid', '')}"
        features.append(DeadFeature(
            id=_slugify(name),
            name=name,
            kill_commit_sha="",
            kill_commit_message=title,
            kill_date=_parse_date(issue.get("closed_at") or issue.get("updated_at", "")),
            detection_method="shelved_issue",
            linked_issue_iids=[issue.get("iid", 0)],
            context_snippets=[f"Issue #{issue.get('iid')}: {title}"],
        ))
    return features


# ── Detection strategy 6: GitLab native Feature Flags API ────────────


async def _detect_from_feature_flags_api(
    project_path: str,
    emit,
    log_mcp=None,
) -> list[DeadFeature]:
    """
    Strategy 6: Query GitLab's native Feature Flags API.

    Unlike commit-message scanning, this returns *confirmed* disabled features — flags
    where `active=False` in GitLab's own feature flag tracking system. These are the
    flags GitLab explicitly tracks, not flags we inferred from commit messages.

    Requires Deployments > Feature Flags to be enabled on the project.
    """
    flags = await mcp.list_feature_flags(project_path, per_page=100)

    if log_mcp:
        log_mcp("list_feature_flags", repo=project_path, result_count=len(flags))

    await emit(f"[MCP] feature_flags returned {len(flags)} flags")

    disabled_flags = [f for f in flags if not f.get("active", True)]
    await emit(f"GitLab Feature Flags API: {len(disabled_flags)} disabled flags confirmed")

    features = []
    for flag in disabled_flags:
        name = flag.get("name", "unknown-flag")
        created_at = flag.get("created_at", "")
        updated_at = flag.get("updated_at", "")
        strategies = flag.get("strategies", [])
        strategy_names = [s.get("name", "") for s in strategies if s.get("name")]

        context = [
            f"GitLab Feature Flag (native API): {name}",
            f"Status: disabled (active=False)",
            f"Strategies: {', '.join(strategy_names) or 'none'}",
        ]
        if created_at:
            context.append(f"Created: {created_at[:10]}")

        features.append(DeadFeature(
            id=_slugify(name),
            name=name.replace("_", " ").replace("-", " ").title(),
            kill_commit_sha="",
            kill_commit_message=f"Feature flag '{name}' disabled in GitLab Feature Flags",
            kill_date=_parse_date(updated_at or created_at),
            detection_method="gitlab_feature_flags_api",
            context_snippets=context,
        ))

    return features


def _detect_from_mrs(mrs: list[dict], commits: list[dict]) -> list[DeadFeature]:
    features = []
    commit_shas = {c.get("id", "") for c in commits}
    for mr in mrs:
        source = mr.get("source_branch", "")
        if not (source.startswith("feature/") or source.startswith("feat/")):
            continue
        # Only flag MRs that were later reverted (the merge commit is in our commit list
        # as a revert) — heuristic: title mentions disable/remove
        title = mr.get("title", "")
        if not _DISABLE_KEYWORDS.search(title):
            continue
        name = source.removeprefix("feature/").removeprefix("feat/").replace("-", " ").replace("_", " ").title()
        features.append(DeadFeature(
            id=_slugify(name),
            name=name,
            kill_commit_sha=mr.get("merge_commit_sha", ""),
            kill_commit_message=title,
            kill_date=_parse_date(mr.get("merged_at") or mr.get("updated_at", "")),
            detection_method="merged_feature_branch",
            linked_mr_iid=mr.get("iid"),
            context_snippets=[f"Feature branch MR #{mr.get('iid')}: {title}"],
        ))
    return features


# ── Enrichment: pull MR discussion + issue context via MCP ────────────


async def _enrich_feature(feat: DeadFeature, project_path: str, emit, log_mcp=None) -> None:
    if feat.linked_mr_iid:
        await emit(f"[MCP] list_merge_request_notes — MR #{feat.linked_mr_iid} for '{feat.name}'...")
        notes = await mcp.list_merge_request_notes(project_path, feat.linked_mr_iid)
        if log_mcp:
            log_mcp("list_merge_request_notes", repo=project_path, mr_iid=feat.linked_mr_iid, result_count=len(notes))
        for note in notes[:5]:
            body = note.get("body", "")
            if body and len(body) > 10:
                feat.context_snippets.append(f"MR #{feat.linked_mr_iid} discussion: {body[:300]}")

    for iid in feat.linked_issue_iids[:2]:
        await emit(f"[MCP] list_issue_notes — Issue #{iid} for '{feat.name}'...")
        notes = await mcp.list_issue_notes(project_path, iid)
        if log_mcp:
            log_mcp("list_issue_notes", repo=project_path, issue_iid=iid, result_count=len(notes))
        for note in notes[:3]:
            body = note.get("body", "")
            if body and len(body) > 10:
                feat.context_snippets.append(f"Issue #{iid} comment: {body[:300]}")

    # Enrich with actual commit diff — real code lines removed at kill time
    if feat.kill_commit_sha and not feat.diff_excerpt:
        await emit(f"[MCP] get_commit_diff {feat.kill_commit_sha[:8]} — extracting code evidence for '{feat.name}'...")
        diffs = await mcp.get_commit_diff(project_path, feat.kill_commit_sha)
        if log_mcp:
            log_mcp("get_commit_diff", repo=project_path, sha=feat.kill_commit_sha[:8], file_count=len(diffs))
        if diffs:
            snippets = _extract_diff_snippets(diffs)
            if snippets:
                feat.diff_excerpt = snippets[0]
                for s in snippets[:2]:
                    if s not in feat.context_snippets:
                        feat.context_snippets.append(s)

    # Limit context snippets
    feat.context_snippets = feat.context_snippets[:8]


# ── Helpers ───────────────────────────────────────────────────────────


# Tokens that signal an extracted "feature name" is actually noise.
# Triggered by real production false-positives we observed on gitlab-pages:
#   "@vshushlin as the pages maintainer"  → person stepping down, not a feature
#   "from gitlab-pages"                   → name-extraction sliced the wrong half
#   "gocyclo:ignore"                      → Go linter directive
#   "local serving type"                  → too generic to be a feature
_GARBAGE_LEADING_PREPOSITIONS = {
    "from", "to", "for", "as", "by", "of", "in", "on", "with", "at", "the", "a", "an",
}

_LINTER_PRAGMA_RE = re.compile(
    r"^(gocyclo|nolint|noqa|eslint(?:-disable)?|prettier-ignore|fmt[:\.]|"
    r"pragma|//\s*ts-(?:ignore|expect-error)|@ts-(?:ignore|expect-error)|"
    r"@?suppress(?:warnings)?)",
    re.IGNORECASE,
)

_PERSONAL_ROLE_RE = re.compile(
    r"\b(maintainer|owner|reviewer|approver|codeowner|admin)s?\b",
    re.IGNORECASE,
)


# Words that mean the thing was removed BECAUSE it was unwanted — i.e. correct
# housekeeping, not a feature killed by an external constraint. You don't "revive"
# something that was deliberately deleted for being redundant/unused/dead.
_CLEANUP_REMOVAL_RE = re.compile(
    r"\b(redundant|unused|duplicate|duplicated|obsolete|stray|leftover|"
    r"unnecessary|no.longer.(?:used|needed|relevant|necessary)|"
    r"dead.code|dead-code|dead\s+\w+\s+code|"               # "dead code", "dead frontend code"
    r"old\s+\w+\s+(?:directive|code|helper|util|class|module)|"  # "old gl_introduced directives"
    r"directives?|"                                          # removing directives = config/lint cleanup
    r"rubocop.?todo|rubocop_todo|\.rubocop|lint.todo|todo.file|"
    r"commented.out|commented-out|orphan(?:ed)?|"
    r"in.favou?r.of|migrat\w*.to|replaced?.with|"
    r"all\s+\w+\s+use\s+\w+|use\s+\w+\s+now|"               # "all trials use DAP now"
    r"mock|msw|stub|fixture|"                               # test-infrastructure removal
    r"spec.tests?|specs?.from|from\s+\w*\s*tests?|"
    r"flaky.test|skip(?:ped)?.test)\b",
    re.IGNORECASE,
)

# But keep it if the removal was clearly about a real feature behind a flag or an
# external constraint (these CAN be revivable even if the word "unused" appears).
_REVIVABLE_OVERRIDE_RE = re.compile(
    r"\b(feature.flag|featureflag|FF_[A-Z]|disabled.(?:due|because|pending|until)|"
    r"security|vulnerab|deprecated.api|api.limit|infrastructure|performance)\b",
    re.IGNORECASE,
)


def _is_cleanup_removal(name: str, message: str = "") -> bool:
    """True when the candidate is housekeeping (removing redundant/unused/dead stuff),
    not a feature killed for a revisitable reason. Such items must not be surfaced as
    revival candidates — reviving them re-introduces the junk that was cleaned up."""
    blob = f"{name or ''} {message or ''}"
    if not _CLEANUP_REMOVAL_RE.search(blob):
        return False
    # Don't filter genuine flag/constraint-driven removals that happen to mention these words.
    if _REVIVABLE_OVERRIDE_RE.search(blob):
        return False
    return True


def _is_garbage_feature_name(name: str) -> bool:
    """Reject names that are clearly not features — pre-Gemini filter to avoid
    false positives in the UI and wasted analysis calls.

    Hard rejects:
      * empty / too short / pure whitespace
      * starts with @ (a GitLab username, not a feature)
      * starts with a preposition (slice extraction picked the wrong half)
      * matches a linter/compiler pragma
      * is purely role-change wording (maintainer stepping down)
    """
    if not name or not name.strip():
        return True
    stripped = name.strip()
    if len(stripped) < 4:
        return True

    # Username — never a feature
    if stripped.startswith("@"):
        return True

    lower = stripped.lower()
    tokens = re.split(r"[\s_\-]+", lower)
    if tokens and tokens[0] in _GARBAGE_LEADING_PREPOSITIONS:
        return True

    if _LINTER_PRAGMA_RE.match(lower):
        return True

    # Pure role-change phrasing — "X as the pages maintainer", "Remove Y as owner"
    # If the name contains a personal-role token and no feature-ish noun, drop it.
    if _PERSONAL_ROLE_RE.search(lower) and not re.search(
        r"\b(feature|flag|api|page|toggle|setting|option|module|service|integration)\b",
        lower,
    ):
        return True

    return False


def _extract_feature_name_from_message(msg: str) -> str:
    """
    Extract a human-readable feature name from a git commit message.

    Handles formats:
      "featureflag: remove TrackMaxRssAnon"  → "TrackMaxRssAnon"
      "feat(registry): remove REGISTRY_FF_ENFORCE_LOCKFILES" → "REGISTRY_FF_ENFORCE_LOCKFILES"
      "backup: Disable S3 checksum calculations" → "S3 checksum calculations"
      "Revert 'Add dark mode support'" → "dark mode support"
      "Remove deprecated payment gateway" → "deprecated payment gateway"
    """
    # Conventional commit format: "type[(scope)]: action noun"
    # Extract the noun part after the action keyword (remove/disable/revert/etc.)
    action_match = re.search(
        r"\b(remov(?:e|ing|ed)|disabl(?:e|ing|ed)|revert(?:ing|ed)?|kill(?:ing|ed)?|"
        r"bury|shelv(?:e|ing|ed)|deprecat(?:e|ing|ed)|turn(?:ing)?\s+off|flag(?:ged)?\s+off)"
        r"\s+(.*)",
        msg,
        re.IGNORECASE,
    )
    if action_match:
        name = action_match.group(2).strip()
        # Strip quote wrappers ONLY when they actually wrap the whole string
        # (matching quote at both ends). A naive ^["']|["']$ strip mangles a quoted
        # token sitting at the start — e.g. 'Remove "-/" section ...' would lose its
        # leading quote and leave a dangling '"' ('-/" section ...'). Balanced-only
        # stripping keeps such names intact.
        while len(name) >= 2 and name[0] in "\"'" and name[-1] == name[0]:
            name = name[1:-1].strip()
        # Stop at sentence end (dot followed by space, or ! or ?)
        name = re.split(r"\.\s|[!?]", name)[0].strip()
        return name[:70] if name else ""

    # Fallback: strip common commit-type prefixes and take the first clause
    cleaned = re.sub(
        r"^(?:featureflag|feat|fix|chore|refactor|test|ci|docs?)\s*(?:\([^)]*\))?\s*[:\-]\s*",
        "",
        msg,
        flags=re.IGNORECASE,
    ).strip()
    # Strip leading action verbs
    cleaned = re.sub(
        r"^(revert|disable|remove|bury|kill|shelve|deprecate)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    parts = re.split(r"[:\-\(\[\{]", cleaned)
    name = parts[0].strip()
    return name[:60] if name else ""


def _extract_flag_name(line: str) -> str:
    match = re.search(r"FEATURE[_\-]([A-Z_]+)", line, re.IGNORECASE)
    if match:
        return match.group(1).lower().replace("_", "-")
    match = re.search(r"ENABLE[_\-]([A-Z_]+)", line, re.IGNORECASE)
    if match:
        return match.group(1).lower().replace("_", "-")
    return ""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:50] or "feature"


def _try_parse_kill_date(kill_date: str) -> datetime | None:
    """
    Parse kill_date back to a timezone-aware datetime for age comparisons.
    Handles both ISO strings and the "%B %d, %Y" display format that
    _parse_date() stores (e.g. "April 17, 2026").
    """
    if not kill_date:
        return None
    for fmt in ("%B %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(kill_date, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # fallback: try fromisoformat
    try:
        dt = datetime.fromisoformat(kill_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _parse_date(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return dt_str[:10]


def _extract_diff_snippets(diffs: list[dict]) -> list[str]:
    """
    Pull the most informative removed lines from a commit's file diffs.
    Returns short human-readable strings like "[auth.rb] removed: user.session_token = nil"
    that become context_snippets and diff_excerpt on the DeadFeature.
    """
    snippets = []
    for file_diff in diffs[:4]:
        old_path = file_diff.get("old_path") or file_diff.get("new_path", "unknown")
        diff_text = file_diff.get("diff", "")
        if not diff_text:
            continue
        removed = []
        for ln in diff_text.split("\n"):
            if ln.startswith("-") and not ln.startswith("---"):
                code = ln[1:].strip()
                # Skip blank lines, pure comment lines, and trivial whitespace
                if code and not code.startswith("#") and not code.startswith("//") and len(code) > 4:
                    removed.append(code)
            if len(removed) >= 4:
                break
        if removed:
            preview = " | ".join(removed[:3])
            snippets.append(f"[{old_path}] removed: {preview[:200]}")
    return snippets
