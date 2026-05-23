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
