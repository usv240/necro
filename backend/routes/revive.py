"""
POST /api/revive/{feature_id} — create a GitLab revival issue + log to MongoDB.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings
from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)
router = APIRouter()


class ReviveRequest(BaseModel):
    project_path: str | None = None


@router.post("/{feature_id}")
async def create_revival_issue(feature_id: str, req: ReviveRequest):
    """
    Create a GitLab issue for a revival candidate via MCP create_issue.
    Logs the created issue to MongoDB revival_log collection.
    """
    # Fetch feature from MongoDB
    feat = await _get_feature(feature_id)
    if not feat:
        raise HTTPException(status_code=404, detail=f"Feature '{feature_id}' not found.")

    viability = feat.get("viability", {})
    if viability.get("recommendation") == "keep_buried":
        raise HTTPException(
            status_code=400,
            detail="This feature is marked 'Keep Buried'. Only 'Revive Now' and 'Investigate' candidates can have revival issues created.",
        )

    project_path = req.project_path or feat.get("project_path", "")
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path required.")

    death_reason = feat.get("death_reason", {})
    title = f"Revival candidate: {feat['name']}"
    description = _build_description(feat, death_reason, viability)

    logger.info("[MCP] create_issue — '%s' in %s", title, project_path)
    result = await mcp.create_issue(
        project_path,
        title=title,
        description=description,
        labels=["revival-candidate", "necro-identified"],
    )

    if not result:
        raise HTTPException(
            status_code=502,
            detail="GitLab MCP create_issue returned no result. Check GITLAB_TOKEN has 'api' scope.",
        )

    issue_url = result.get("web_url", "")
    issue_iid = result.get("iid")

    # Log to MongoDB
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            from backend.db.schemas import RevivalLogEntry
            db = get_db()
            entry = RevivalLogEntry(
                feature_id=feature_id,
                feature_name=feat["name"],
                project_path=project_path,
                issue_url=issue_url,
                issue_iid=issue_iid,
            )
            await db["revival_log"].insert_one(entry.model_dump())
        except Exception as e:
            logger.warning("Failed to log revival to MongoDB: %s", e)

    # Slack notification
    try:
        from backend.services.slack_client import send_issue_created_alert
        await send_issue_created_alert(project_path, feat["name"], issue_url)
    except Exception:
        pass

    logger.info("[MCP] Issue created: %s", issue_url)
    return {
        "status": "created",
        "issue_url": issue_url,
        "issue_iid": issue_iid,
        "title": title,
        "via": "gitlab_mcp_create_issue",
    }


# ── POST /api/revive/{feature_id}/ghost-mr ───────────────────────────────────

@router.post("/{feature_id}/ghost-mr")
async def create_ghost_mr(feature_id: str, req: ReviveRequest):
    """
    Ghost MR — NECRO creates a real draft GitLab Merge Request with a full revival plan.

    Unlike "Create Issue" (which creates a discussion item), Ghost MR creates an
    actionable code artifact in the repository:
      1. Creates branch  necro/revival/{feature-slug}
      2. Commits NECRO_REVIVAL.md to that branch — a step-by-step revival plan
      3. Opens a Draft MR from that branch → default branch
         with the full constraint analysis, challenger verdict, and checklist

    MCP tools used: create_branch, create_file (repository API), create_merge_request
    """
    feat = await _get_feature(feature_id)
    if not feat:
        raise HTTPException(status_code=404, detail=f"Feature '{feature_id}' not found.")

    viability = feat.get("viability", {})
    if viability.get("recommendation") == "keep_buried":
        raise HTTPException(
            status_code=400,
            detail="Ghost MR is only for 'Revive Now' and 'Investigate' candidates.",
        )

    project_path = req.project_path or feat.get("project_path", "")
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path required.")

    # Slugify feature name for branch name
    import re
    slug = re.sub(r"[^a-z0-9-]", "-", feat["name"].lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:40]
    branch_name = f"necro/revival/{slug}"

    # Get default branch
    default_branch = await mcp.get_default_branch(project_path)
    logger.info("[Ghost MR] default_branch=%s project=%s", default_branch, project_path)

    # 1. Create branch
    branch_result = await mcp.create_branch(project_path, branch_name, ref=default_branch)
    if not branch_result:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create branch '{branch_name}'. Check GITLAB_TOKEN has 'api' scope and Developer+ role.",
        )

    # 2. Create NECRO_REVIVAL.md on the branch
    plan_content = _build_ghost_mr_plan(feat, project_path)
    file_result = await mcp.create_file(
        project_path,
        file_path="NECRO_REVIVAL.md",
        content=plan_content,
        branch=branch_name,
        commit_message=f"necro: revival plan for {feat['name']}",
    )
    if not file_result:
        logger.warning("[Ghost MR] File creation failed — continuing with MR creation anyway")

    # 3. Create Draft MR
    dr = feat.get("death_reason", {})
    vi = feat.get("viability", {})
    roi = feat.get("roi", {})
    grounding = vi.get("grounding", {})

    mr_description = _build_description(feat, dr, vi)
    mr_description += "\n\n---\n\n"
    mr_description += "## Ghost MR — NECRO Revival Scaffold\n\n"
    mr_description += f"This Draft MR was auto-created by **NECRO** to scaffold the revival of `{feat['name']}`.\n\n"
    mr_description += f"The `NECRO_REVIVAL.md` file on this branch contains a step-by-step revival checklist.\n"
    mr_description += f"**To revive this feature:** review the plan, write the code, remove the `Draft:` prefix, and merge.\n\n"
    mr_description += "_MCP tools used: `create_branch`, `create_file`, `create_merge_request` — 3 write operations via GitLab REST API_"

    mr_title = f"Revival: {feat['name']}"
    mr_result = await mcp.create_merge_request(
        project_path,
        title=mr_title,
        description=mr_description,
        source_branch=branch_name,
        target_branch=default_branch,
        labels=["revival-candidate", "necro-ghost-mr", "draft"],
        draft=True,
    )

    if not mr_result:
        raise HTTPException(
            status_code=502,
            detail="GitLab MR creation failed. Check GITLAB_TOKEN has 'api' scope with Developer+ role.",
        )

    mr_url = mr_result.get("web_url", "")
    mr_iid = mr_result.get("iid")

    # Log to MongoDB
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            from backend.db.schemas import RevivalLogEntry
            db = get_db()
            entry = RevivalLogEntry(
                feature_id=feature_id,
                feature_name=feat["name"],
                project_path=project_path,
                issue_url=mr_url,
                issue_iid=mr_iid,
                via="ghost_mr",
            )
            await db["revival_log"].insert_one(entry.model_dump())
        except Exception as e:
            logger.warning("Failed to log Ghost MR to MongoDB: %s", e)

    logger.info("[Ghost MR] Created: %s", mr_url)
    return {
        "status": "created",
        "mr_url": mr_url,
        "mr_iid": mr_iid,
        "branch_name": branch_name,
        "title": f"Draft: {mr_title}",
        "plan_file": "NECRO_REVIVAL.md",
        "via": "gitlab_mcp_ghost_mr",
    }


def _build_ghost_mr_plan(feat: dict, project_path: str) -> str:
    """Build the NECRO_REVIVAL.md content for the Ghost MR branch."""
    dr = feat.get("death_reason", {})
    vi = feat.get("viability", {})
    roi = feat.get("roi", {})
    grounding = vi.get("grounding", {})
    challenger = feat.get("challenger", {})

    risks = vi.get("technical_risks", [])
    risks_block = "\n".join(f"- [ ] {r}" for r in risks) if risks else "- None identified"

    evidence_line = ""
    if grounding.get("evidence_url"):
        evidence_line = f"Evidence: [{grounding.get('technology')} {grounding.get('latest_version')}]({grounding['evidence_url']})"
    elif vi.get("what_changed"):
        evidence_line = vi["what_changed"]

    challenger_note = ""
    if challenger:
        verdict = challenger.get("challenger_verdict", "")
        score = challenger.get("challenger_score", "?")
        obj = challenger.get("strongest_objection", "")
        step = challenger.get("recommended_first_step", "")
        challenger_note = f"""
## Adversarial Review (Challenger Agent — Vertex AI Gemini 2.5)

> **Verdict:** {verdict.upper()} (Score: {score}/10)
> **Key objection:** {obj}
> **Suggested first step:** {step}
"""

    return f"""# NECRO Revival Plan: {feat["name"]}

> Auto-generated by **NECRO — The Code Necromancer**
> Google Cloud Agent Builder + Gemini 3 Flash + GitLab MCP

---

## Summary

| | |
|---|---|
| Feature | `{feat["name"]}` |
| Originally disabled | {feat.get("kill_date", "unknown")} |
| Kill commit | `{feat.get("kill_commit_sha", "unknown")[:8]}` |
| Recommendation | **{vi.get("recommendation", "unknown").replace("_", " ").title()}** |
| Feasibility | {vi.get("revival_feasibility", "?")} / 10 |
| Effort estimate | {vi.get("effort_estimate", "unknown")} |
| Demand signals | {roi.get("request_count", 0)} issue references |

---

## Why it was disabled

**Category:** {dr.get("category", "unknown")}

{dr.get("primary_reason", feat.get("kill_commit_message", ""))}

> *"{dr.get("cited_evidence", "")}"*

---

## Why it's revivable now

{vi.get("what_changed", "See viability assessment above.")}

{evidence_line}
{challenger_note}

---

## Revival Checklist

- [ ] **Locate the code:** `git show {feat.get("kill_commit_sha", "COMMIT_SHA")}` to see what was removed
- [ ] **Verify constraint resolved:** {evidence_line or "Check the kill reason above"}
- [ ] **Create feature flag:** `{feat["name"].lower().replace(" ", "_")}_enabled: false` → enable for testing
- [ ] **Write tests** covering the original failure mode that caused the kill
- [ ] **Roll out:** 10% → monitor error rates → 50% → 100%
- [ ] **Remove `Draft:` prefix** from this MR title and assign for review

---

## Technical Risks

{risks_block}

---

## Related GitLab Items

{f"- Kill commit: [{feat.get('kill_commit_sha', '')[:8]}](https://gitlab.com/{project_path}/-/commit/{feat.get('kill_commit_sha', '')})" if feat.get("kill_commit_sha") else ""}
{f"- Linked MR: [!{feat.get('linked_mr_iid')}](https://gitlab.com/{project_path}/-/merge_requests/{feat.get('linked_mr_iid')})" if feat.get("linked_mr_iid") else ""}
{chr(10).join(f"- Issue: [#{iid}](https://gitlab.com/{project_path}/-/issues/{iid})" for iid in feat.get("linked_issue_iids", [])[:3])}

---

*This file was created by **NECRO** on behalf of the engineering team.*
*All claims are backed by cited commit history and external API evidence where available.*
"""


async def _get_feature(feature_id: str) -> dict | None:
    """Fetch feature from MongoDB, or from demo data as fallback."""
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            feat = await db["features"].find_one({"feature_id": feature_id}, {"_id": 0})
            return feat
        except Exception:
            pass

    # Fallback to demo data
    from backend.db.seed import DEMO_FEATURES
    return next((f for f in DEMO_FEATURES if f.get("feature_id") == feature_id), None)


def _build_description(feat: dict, dr: dict, vi: dict) -> str:
    sha = feat.get("kill_commit_sha", "")
    sha_ref = f" (commit `{sha[:8]}`)" if sha else ""
    mr_ref = f" · MR #{feat.get('linked_mr_iid')}" if feat.get("linked_mr_iid") else ""
    issue_refs = ", ".join(f"#{i}" for i in feat.get("linked_issue_iids", []))
    issue_ref = f" · Issues: {issue_refs}" if issue_refs else ""
    cited = dr.get("cited_evidence", "")
    cited_block = f'\n> *"{cited}"*\n' if cited else ""
    risks = vi.get("technical_risks", [])
    risks_block = "\n".join(f"- {r}" for r in risks) if risks else "- None identified"
    roi = feat.get("roi", {})

    return f"""## Feature Revival Candidate — identified by NECRO

**Feature:** {feat['name']}
**Originally disabled:** {feat.get('kill_date', 'unknown')}{sha_ref}{mr_ref}{issue_ref}

---

### Why it was disabled

**Category:** {dr.get('category', 'unknown')}
**Kill reason:** {dr.get('primary_reason', feat.get('kill_commit_message', ''))}
{cited_block}
---

### Why it's revivable now

{vi.get('what_changed', 'See viability assessment')}

---

### Revival assessment

| | |
|---|---|
| Feasibility | {vi.get('revival_feasibility', '?')}/10 |
| Estimated effort | {vi.get('effort_estimate', 'unknown')} |
| Recommendation | {vi.get('recommendation', 'unknown').replace('_', ' ').title()} |
| Demand signals | {roi.get('request_count', 0)} issue references |
| ROI estimate | {roi.get('roi_estimate_label', 'not estimated')} |

*{roi.get('caveats', 'Rough estimate based on available signals.')}*

**Reasoning:** {vi.get('reasoning', '')}

### Technical risks

{risks_block}

---

### Suggested revival steps

1. Locate the original feature code (git log for the kill commit: `{feat.get('kill_commit_sha', 'unknown')}`)
2. Verify the resolution of the original constraint (see "Why it's revivable now" above)
3. Re-enable behind a feature flag for safe rollout
4. Write tests for the previously-failing edge cases
5. Roll out to 10% → monitor → 100%

---

*This issue was created by **NECRO — The Code Necromancer** agent.*
*GitLab MCP tools used: list_commits, get_commit, list_issues, list_merge_requests, list_merge_request_notes, create_issue*
*All claims are cited from repository history. ROI estimates are rough signal-based projections, not revenue forecasts.*
"""
