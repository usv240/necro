"""
Feature detection: five strategies for finding deliberately disabled features.

All data retrieval goes through the GitLab MCP client (or its REST fallback),
so the call log that appears in the UI shows real MCP tool usage.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)

# Keywords in commit messages that suggest deliberate feature disablement
_DISABLE_KEYWORDS = re.compile(
    r"\b(disabl|remov|revert|kill|bury|shelv|deprecat|comment.?out|roll.?back|turn.?off|flag.?off)\w*\b",
    re.IGNORECASE,
)

_FEATURE_FLAG_PATTERNS = [
    re.compile(r"FEATURE[_\-][A-Z_]+\s*=\s*[Ff]alse"),
    re.compile(r"ENABLE[_\-][A-Z_]+\s*=\s*[Ff]alse"),
    re.compile(r"enabled\s*[=:]\s*false", re.IGNORECASE),
    re.compile(r"feature_flag\s*[=:]\s*false", re.IGNORECASE),
    re.compile(r"@feature\.(?:disable|off)\(", re.IGNORECASE),
    re.compile(r"\.feature\([\'\"][^\'\"]+[\'\"],\s*false\)"),
    re.compile(r"if\s+settings\.FEATURE_\w+\s*==\s*[Ff]alse"),
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

    # Populated in later pipeline stages
    death_reason: Optional[dict] = None
    viability: Optional[dict] = None
    roi: Optional[dict] = None


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

    await emit(f"[MCP] list_commits — scanning last {lookback_months} months (up to {max_commits} commits)...")

    # Paginate commits
    all_commits: list[dict] = []
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
    log_mcp("list_commits", repo=project_path, result_count=len(all_commits))
    await emit(f"[MCP] list_commits returned {len(all_commits)} commits")

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

    await emit(f"Found {len(unique)} candidate dead features — enriching with MR and issue context...")

    # Enrich each candidate with linked MR notes and issue context
    for feat in unique:
        await _enrich_feature(feat, project_path, emit, log_mcp)

    await emit(f"Detection complete — {len(unique)} dead features found")
    return unique


# ── Detection strategy 1: Revert commits ──────────────────────────────


def _detect_reverts(commits: list[dict]) -> list[DeadFeature]:
    features = []
    for c in commits:
        title = c.get("title", "") or c.get("message", "")
        if title.lower().startswith("revert"):
            name = _extract_feature_name_from_message(title) or f"reverted-{c.get('id', '')[:8]}"
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


def _detect_by_message(commits: list[dict]) -> list[DeadFeature]:
    features = []
    for c in commits:
        title = c.get("title", "") or c.get("message", "")
        if not _DISABLE_KEYWORDS.search(title):
            continue
        # Skip if already caught by revert strategy
        if title.lower().startswith("revert"):
            continue
        name = _extract_feature_name_from_message(title) or f"disabled-{c.get('id','')[:8]}"
        features.append(DeadFeature(
            id=_slugify(name),
            name=name,
            kill_commit_sha=c.get("id", ""),
            kill_commit_message=title,
            kill_date=_parse_date(c.get("created_at", "")),
            detection_method="commit_message_keyword",
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


def _extract_feature_name_from_message(msg: str) -> str:
    # Strip common prefixes like "revert", "disable", "remove"
    cleaned = re.sub(
        r"^(revert|disable|remove|bury|kill|shelve|deprecate|feat|fix|chore|refactor)[:\-\s]+",
        "",
        msg,
        flags=re.IGNORECASE,
    ).strip()
    # Take first meaningful segment
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
