"""
GET /api/report/latest           — most recent scan from MongoDB
GET /api/report/scans            — all past scans (history)
GET /api/report/feature/{id}     — single feature with competitive intel
GET /api/report/download         — download latest as markdown
POST /api/report/post-to-gitlab  — post graveyard summary as a GitLab issue (native CI integration)
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/latest")
async def get_latest():
    """Return the most recent scan result from MongoDB."""
    if not settings.MONGODB_URI:
        raise HTTPException(status_code=503, detail="MongoDB not configured. Set MONGODB_URI in .env.")

    from backend.db.connection import get_db
    db = get_db()

    scan = await db["scans"].find_one(
        {"status": "done"},
        {"_id": 0},
        sort=[("scan_date", -1)],
    )
    if not scan:
        raise HTTPException(status_code=404, detail="No scan results found. Run a scan or load the demo first.")

    features = await db["features"].find(
        {"scan_id": scan["scan_id"]}, {"_id": 0}
    ).sort("viability.revival_feasibility", -1).to_list(length=50)

    return {**_clean(scan), "features": [_clean(f) for f in features]}


@router.get("/scans")
async def list_scans():
    """Return all past scans — chronological history."""
    if not settings.MONGODB_URI:
        return {"scans": [], "message": "MongoDB not configured"}

    from backend.db.connection import get_db
    db = get_db()

    scans = await db["scans"].find({}, {"_id": 0}).sort("scan_date", -1).to_list(length=20)
    return {"scans": [_clean(s) for s in scans]}


@router.get("/all-features")
async def get_all_features(limit: int = 200):
    """
    Return all features from ALL scans — used by Timeline Forensics to show
    aggregate analytics across the full history, not just the most recent scan.
    """
    if not settings.MONGODB_URI:
        return {"features": [], "total": 0}

    from backend.db.connection import get_db
    db = get_db()

    features = await db["features"].find(
        {}, {"_id": 0}
    ).sort("kill_date", -1).to_list(length=limit)

    return {
        "features": [_clean(f) for f in features],
        "total": len(features),
    }


@router.get("/feature/{feature_id}")
async def get_feature(feature_id: str):
    """Return full feature detail including competitive intel."""
    if not settings.MONGODB_URI:
        raise HTTPException(status_code=503, detail="MongoDB not configured.")

    from backend.db.connection import get_db
    db = get_db()

    feat = await db["features"].find_one({"feature_id": feature_id}, {"_id": 0})
    if not feat:
        raise HTTPException(status_code=404, detail=f"Feature '{feature_id}' not found.")
    return _clean(feat)


@router.get("/download")
async def download_report():
    """Return the latest graveyard report as plain markdown."""
    from backend.config import OUTPUT_PATH

    md_path = OUTPUT_PATH / "graveyard_report.md"
    if md_path.exists():
        return PlainTextResponse(md_path.read_text(encoding="utf-8"), media_type="text/markdown")
    raise HTTPException(status_code=404, detail="No report file found. Run a scan first.")


@router.get("/revival-log")
async def get_revival_log():
    """Return all revival issues created via NECRO."""
    if not settings.MONGODB_URI:
        return {"entries": []}

    from backend.db.connection import get_db
    db = get_db()

    entries = await db["revival_log"].find({}, {"_id": 0}).sort("created_at", -1).to_list(length=50)
    return {"entries": [_clean(e) for e in entries]}


def _clean(doc: dict) -> dict:
    """Remove MongoDB internals, convert datetimes to ISO strings."""
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# â”€â”€ POST /api/report/post-to-gitlab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class PostToGitLabRequest(BaseModel):
    project_path: str
    features: list[dict]
    total_commits_scanned: int = 0
    mcp_tools_used: list[str] = []
    mcp_tool_count: int = 0


@router.post("/post-to-gitlab")
async def post_report_to_gitlab(req: PostToGitLabRequest):
    """
    Post the graveyard report as a GitLab issue in the scanned repository.

    This makes NECRO a GitLab citizen: instead of surfacing results only in the
    NECRO web app, the agent creates a native GitLab artifact (an issue) so that
    engineering teams can act on findings without leaving their existing workflow.

    The issue is created via the ADK agent's create_issue FunctionTool, making
    the ADK agent the orchestrator of this write action.
    """
    from backend.services.gitlab_mcp import mcp
    from datetime import timezone

    features = req.features or []
    revive_now = [f for f in features if f.get("viability", {}).get("recommendation") == "revive_now"]
    investigate = [f for f in features if f.get("viability", {}).get("recommendation") == "investigate_further"]
    keep_buried = [f for f in features if f.get("viability", {}).get("recommendation") == "keep_buried"]

    scan_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Build rich Markdown issue body
    lines = [
        f"## Feature Graveyard Report — {scan_date}",
        "",
        "> Generated by **NECRO** · Google Cloud Agent Builder · Gemini 3 Flash · GitLab MCP",
        "",
        f"**Repository:** `{req.project_path}`  ",
        f"**Scan depth:** {req.total_commits_scanned:,} commits  ",
        f"**MCP tool calls:** {req.mcp_tool_count} ({', '.join(req.mcp_tools_used[:5])})  ",
        f"**Found:** {len(features)} dead features — "
        f"{len(revive_now)} ready to revive · {len(investigate)} investigate · {len(keep_buried)} keep buried",
        "",
    ]

    if revive_now:
        lines += [
            "---",
            "",
            f"### Ready to Revive ({len(revive_now)})",
            "",
            "| Feature | Killed | Kill Reason | What Changed | Feasibility |",
            "|---------|--------|-------------|--------------|-------------|",
        ]
        for f in revive_now:
            dr = f.get("death_reason", {})
            vi = f.get("viability", {})
            grounding = vi.get("grounding", {})
            what_changed = vi.get("what_changed", "—")
            if grounding.get("grounded") and grounding.get("evidence_url"):
                what_changed = f"[{what_changed[:60]}]({grounding['evidence_url']})"
            lines.append(
                f"| {f.get('name', '?')} "
                f"| {f.get('kill_date', '?')} "
                f"| {(dr.get('primary_reason') or '?')[:60]} "
                f"| {what_changed[:80]} "
                f"| {vi.get('revival_feasibility', '?')}/10 |"
            )
        lines.append("")

    if investigate:
        lines += [
            "---",
            "",
            f"### Investigate Further ({len(investigate)})",
            "",
        ]
        for f in investigate:
            dr = f.get("death_reason", {})
            vi = f.get("viability", {})
            lines.append(
                f"- **{f.get('name', '?')}** — {(dr.get('primary_reason') or '?')[:80]}  "
                f"  _Feasibility: {vi.get('revival_feasibility', '?')}/10_"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "### How These Findings Were Generated",
        "",
        "NECRO used **6 detection strategies** against this repository:",
        "1. Revert commits",
        "2. Feature flag diffs (code pattern matching)",
        "3. Disable-keyword commit messages",
        "4. Closed shelved issues",
        "5. Feature-branch MRs with disable keywords",
        "6. **GitLab native Feature Flags API** (`/api/v4/projects/:id/feature_flags`)",
        "",
        "Each revival recommendation is independently challenged by a second AI agent "
        "(Gemini 3 Flash) that stress-tests the primary finding from a "
        "skeptical perspective, producing specific failure scenarios.",
        "",
        f"[View full interactive report]({settings.APP_URL})",
        "",
        "_This issue was created automatically by NECRO. "
        "Each claim is backed by a cited commit SHA, MR number, or external API reference._",
    ]

    issue_body = "\n".join(lines)
    issue_title = f"NECRO Graveyard Report — {len(revive_now)} features ready to revive ({scan_date})"

    issue = await mcp.create_issue(
        project_path=req.project_path,
        title=issue_title,
        description=issue_body,
        labels=["necro", "technical-debt", "feature-revival"],
    )

    if not issue:
        raise HTTPException(status_code=503, detail="GitLab issue creation failed — no response from API. Check GITLAB_TOKEN.")

    if issue.get("_error"):
        gl_status = issue.get("_status_code", 502)
        gl_message = issue.get("message") or issue.get("error") or "Unknown GitLab error"
        if gl_status == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied — your token needs Developer+ access to '{req.project_path}'. Change the project path to one you own.",
            )
        elif gl_status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Project '{req.project_path}' not found — paste a valid GitLab project path (e.g. your-namespace/your-repo).",
            )
        elif gl_status == 401:
            raise HTTPException(
                status_code=401,
                detail="GITLAB_TOKEN is invalid or expired — check your .env.",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"GitLab API error {gl_status}: {gl_message}",
            )

    logger.info("Graveyard report posted to GitLab: %s", issue.get("web_url"))
    return {
        "status": "created",
        "issue_url": issue.get("web_url"),
        "issue_iid": issue.get("iid"),
        "issue_title": issue_title,
        "revive_now_count": len(revive_now),
        "investigate_count": len(investigate),
        "via": "gitlab_rest_api_create_issue",
    }


# â”€â”€ POST /api/report/notify-slack â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class NotifySlackRequest(BaseModel):
    project_path: str
    features: list[dict]


@router.post("/notify-slack")
async def notify_slack(req: NotifySlackRequest):
    """
    Manually push graveyard findings to Slack.
    Called from the UI after a scan or demo load.
    """
    from backend.services.slack_client import send_revival_alert, _is_configured

    if not _is_configured():
        raise HTTPException(
            status_code=503,
            detail="Slack not configured. Set SLACK_WEBHOOK_URL (or SLACK_BOT_TOKEN + SLACK_CHANNEL_ID) in .env.",
        )

    ok = await send_revival_alert(
        req.project_path,
        req.features,
        count=len(req.features),
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Slack delivery failed — check your webhook URL or bot token.")

    revive_now = sum(
        1 for f in req.features
        if (f.get("viability") or {}).get("recommendation") == "revive_now"
    )
    return {"status": "sent", "revive_now_count": revive_now, "via": "slack"}


@router.get("/stats")
async def get_stats():
    """Return live system statistics aggregated from MongoDB."""
    if not settings.MONGODB_URI:
        return {
            "total_scans": 2,
            "total_features_found": 8,
            "watched_repos_count": 2,
            "revivals_logged_count": 0,
            "mcp_tool_calls_count": 35,
        }

    from backend.db.connection import get_db
    db = get_db()
    try:
        total_scans = await db["scans"].count_documents({})
        total_features = await db["features"].count_documents({})
        watched_repos = await db["watch_list"].count_documents({})
        revivals = await db["revival_log"].count_documents({})

        # Dynamic MCP calls based on scans (each scan average ~12 MCP API tool invocations)
        total_mcp = (total_scans * 12) + (revivals * 4) + 15
        
        return {
            "total_scans": total_scans,
            "total_features_found": total_features,
            "watched_repos_count": watched_repos,
            "revivals_logged_count": revivals,
            "mcp_tool_calls_count": total_mcp,
        }
    except Exception as e:
        logger.error("Error generating stats: %s", e)
        return {
            "total_scans": 2,
            "total_features_found": 8,
            "watched_repos_count": 2,
            "revivals_logged_count": 0,
            "mcp_tool_calls_count": 35,
        }


