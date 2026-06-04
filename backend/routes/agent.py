"""
POST /api/agent/ask    — send a freeform prompt to the ADK agent (Google Cloud Agent Builder)
POST /api/agent/revive — create a revival issue via the ADK agent + MCPToolset
POST /api/webhook/gitlab — GitLab webhook: re-scan repo when new commits are pushed

These routes make the ADK agent (Google Cloud Agent Builder) the visible orchestrator
for NECRO's two key actions — analysis and GitLab issue creation.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ── /api/agent/ask ────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    prompt: str
    project_path: str = ""


@router.post("/ask")
async def agent_ask(req: AskRequest):
    """
    Send a freeform prompt to the ADK agent (Google Cloud Agent Builder).
    The agent has access to all GitLab MCP tools and NECRO's analytical tools.
    Streams the agent's response as SSE.
    """
    from backend.services.adk_runner import get_runner
    from google.genai import types as genai_types

    runner = get_runner()
    session_id = f"ask-{uuid.uuid4().hex[:8]}"
    user_id = "necro-user"

    context = f"\nRepository context: {req.project_path}" if req.project_path else ""
    full_prompt = req.prompt + context

    async def generate():
        try:
            await runner.session_service.create_session(
                app_name="necro", user_id=user_id, session_id=session_id
            )
            message = genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=full_prompt)],
            )
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    text = event.content.parts[0].text or ""
                    yield f"data: {json.dumps({'type': 'response', 'text': text})}\n\n"
                elif hasattr(event, "actions") and event.actions:
                    for action in event.actions:
                        if hasattr(action, "tool_use") and action.tool_use:
                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': action.tool_use.name})}\n\n"
        except Exception as exc:
            logger.exception("ADK agent ask failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── /api/agent/mission ────────────────────────────────────────────────────────

class MissionRequest(BaseModel):
    repo_url: str
    action_repo: str | None = None       # where ACT writes land (defaults to repo_url)
    max_commits: int = 120
    lookback_months: int = 36
    dry_run: bool = False                # plan + prepare, no writes (oversight checkpoint)


@router.post("/mission")
async def agent_mission(req: MissionRequest):
    """
    Autonomous code-lifecycle mission (SSE).

    One instruction -> the agent plans the objectives, red-teams them, acts
    (creates revival + deletion Ghost MRs), verifies the artifacts, and reports.
    This is NECRO operating as an autonomous agent that finishes the job, not a
    dashboard. Streams every phase. dry_run=true is the human-oversight checkpoint.
    """
    from backend.routes.stream import _url_to_path
    from backend.services.mission import run_mission

    repo = _url_to_path(req.repo_url)
    action_repo = _url_to_path(req.action_repo) if req.action_repo else None

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(msg: str):
            await queue.put(msg)

        async def run():
            try:
                report = await run_mission(
                    emit, repo, action_repo=action_repo,
                    max_commits=req.max_commits, lookback_months=req.lookback_months,
                    dry_run=req.dry_run,
                )
                # Persist the mission so it can be replayed instantly (demo fallback).
                if settings.MONGODB_URI:
                    try:
                        from backend.db.connection import get_db
                        db = get_db()
                        await db["missions"].insert_one(
                            {"_mission_id": report.get("mission_id"), **json.loads(json.dumps(report, default=str))}
                        )
                    except Exception as _exc:
                        logger.warning("Mission persist failed: %s", _exc)
                await queue.put("__REPORT__:" + json.dumps(report, default=str))
            except Exception as exc:
                logger.exception("Mission failed")
                await emit(f"ERROR: {exc}")
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            if item.startswith("__REPORT__:"):
                yield f"data: {json.dumps({'type': 'report', 'data': json.loads(item[len('__REPORT__:'):])})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'progress', 'message': item})}\n\n"
        await task

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/mission/latest")
async def agent_mission_latest():
    """Most recent autonomous mission report (instant replay for the demo)."""
    if not settings.MONGODB_URI:
        return {"available": False}
    try:
        from backend.db.connection import get_db
        db = get_db()
        m = await db["missions"].find_one({}, {"_id": 0}, sort=[("_id", -1)])
        return {"available": True, "mission": m} if m else {"available": True, "mission": None}
    except Exception as exc:
        logger.warning("mission_latest failed: %s", exc)
        return {"available": False}


# ── /api/agent/revive ─────────────────────────────────────────────────────────

class AgentReviveRequest(BaseModel):
    feature_id: str
    project_path: str


@router.post("/revive")
async def agent_revive(req: AgentReviveRequest):
    """
    Create a GitLab revival issue via the ADK agent (Google Cloud Agent Builder).

    The ADK agent orchestrates:
    1. Fetch feature details from MongoDB
    2. Use MCPToolset create_issue to create the GitLab issue
    3. Log the revival to MongoDB
    4. Return the created issue URL

    This is the primary demo of Google Cloud Agent Builder + GitLab MCP in action.
    """
    from backend.services.adk_runner import get_runner
    from google.genai import types as genai_types

    # Fetch feature details for the agent prompt
    feat = await _get_feature(req.feature_id)
    if not feat:
        raise HTTPException(status_code=404, detail=f"Feature '{req.feature_id}' not found.")

    viability = feat.get("viability", {})
    if viability.get("recommendation") == "keep_buried":
        raise HTTPException(
            status_code=400,
            detail="This feature is marked 'Keep Buried'. Only 'Revive Now' and 'Investigate' candidates can have revival issues created.",
        )

    death_reason = feat.get("death_reason", {})
    roi = feat.get("roi", {})
    risks = viability.get("technical_risks", [])
    risks_text = "\n".join(f"- {r}" for r in risks) if risks else "None identified"

    prompt = f"""Create a GitLab revival issue for the following dead feature in repository '{req.project_path}'.

Feature name: {feat['name']}
Originally disabled: {feat.get('kill_date', 'unknown')} (commit: {feat.get('kill_commit_sha', 'unknown')})
Kill reason: {death_reason.get('primary_reason', feat.get('kill_commit_message', 'unknown'))}
Kill reason category: {death_reason.get('category', 'unknown')}
Why it's revivable now: {viability.get('what_changed', 'constraint may have been resolved')}
Revival feasibility score: {viability.get('revival_feasibility', '?')}/10
Estimated effort: {viability.get('effort_estimate', 'unknown')}
Demand signals: {roi.get('request_count', 0)} issue references
ROI estimate: {roi.get('roi_estimate_label', 'not estimated')}
Technical risks:
{risks_text}

Use the create_issue tool to create a well-structured GitLab issue with:
- Title: "Revival candidate: {feat['name']}"
- Labels: revival-candidate, necro-identified
- A detailed description covering: why it was disabled, why it's revivable now, effort estimate, technical risks, and step-by-step revival plan
- Note that this issue was created by the NECRO agent using GitLab MCP tools

Return the issue URL after creating it."""

    runner = get_runner()
    session_id = f"revive-{uuid.uuid4().hex[:8]}"
    user_id = "necro-user"

    issue_url = ""
    issue_iid = None
    agent_response = ""

    try:
        await runner.session_service.create_session(
            app_name="necro", user_id=user_id, session_id=session_id
        )
        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=prompt)],
        )
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                agent_response = event.content.parts[0].text or ""
                logger.info("[ADK] Revival agent response: %.200s", agent_response)

    except Exception as exc:
        logger.warning("[ADK] Revival agent error: %s — falling back to direct REST", exc)
        # Fallback to direct REST create_issue
        from backend.services.gitlab_mcp import mcp
        from backend.routes.revive import _build_description
        title = f"Revival candidate: {feat['name']}"
        description = _build_description(feat, death_reason, viability)
        result = await mcp.create_issue(req.project_path, title=title, description=description, labels=["revival-candidate", "necro-identified"])
        if result:
            issue_url = result.get("web_url", "")
            issue_iid = result.get("iid")

    # Extract issue URL from agent response if present
    if not issue_url and agent_response:
        import re
        match = re.search(r"https://gitlab\.com/[^\s\)\"']+", agent_response)
        if match:
            issue_url = match.group(0).rstrip(".,")

    # Extract issue iid from URL if not already set  (e.g. /-/issues/123)
    if issue_url and issue_iid is None:
        import re
        iid_match = re.search(r"/-/issues/(\d+)", issue_url)
        if iid_match:
            issue_iid = int(iid_match.group(1))

    # Log to MongoDB
    if settings.MONGODB_URI and issue_url:
        try:
            from backend.db.connection import get_db
            from backend.db.schemas import RevivalLogEntry
            db = get_db()
            entry = RevivalLogEntry(
                feature_id=req.feature_id,
                feature_name=feat["name"],
                project_path=req.project_path,
                issue_url=issue_url,
                issue_iid=issue_iid,
            )
            await db["revival_log"].insert_one(entry.model_dump())
        except Exception as e:
            logger.warning("MongoDB revival log failed: %s", e)

    return {
        "status": "created" if issue_url else "attempted",
        "issue_url": issue_url,
        "issue_iid": issue_iid,
        "agent_used": "google_cloud_agent_builder_adk",
        "mcp_tool": "create_issue (GitLab MCP via ADK MCPToolset)",
        "agent_response": agent_response[:500] if agent_response else "",
        "via": "adk_mcptoolset_gitlab",
    }


# ── /api/webhook/gitlab ───────────────────────────────────────────────────────

@router.post("/webhook/gitlab")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: str = Header(None),
):
    """
    GitLab webhook receiver — handles two event types:

    1. Push Hook (existing): re-evaluates the graveyard when new commits arrive.
       May trigger revival contract fulfillment if push resolves a known condition.

    2. Merge Request Hook (NEW — Feature Will Generator):
       When an MR is OPENED that kills a feature, NECRO intercepts in real-time:
       - ADK Gemini 3 Flash analyzes the kill reason and revival conditions
       - Creates a Revival Contract issue in GitLab (via MCP create_issue)
       - Auto-assigns the engineer who opened the MR (engineer attribution)
       - Stores the contract in MongoDB with vector embedding
       This preserves institutional knowledge at 100% fidelity — the exact
       moment it exists at maximum clarity, before any decay.

    Configure in GitLab: Settings → Webhooks → Push events + Merge requests events
    Optional: set X-Gitlab-Token header to NECRO_WEBHOOK_SECRET env var.
    """
    # Validate secret if configured
    expected = getattr(settings, "NECRO_WEBHOOK_SECRET", None)
    if expected and x_gitlab_token != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload = await request.json()
    event_type = request.headers.get("X-Gitlab-Event", "unknown")

    project = payload.get("project", {})
    project_path = project.get("path_with_namespace", "")

    logger.info("[WEBHOOK] %s — project: %s", event_type, project_path)

    # ── Merge Request Hook: Feature Will Generator ────────────────────────────
    if event_type in ("Merge Request Hook", "merge_request") and project_path:
        mr = payload.get("object_attributes", {})
        action = mr.get("action", "")
        mr_iid = mr.get("iid") or mr.get("id")
        mr_title = mr.get("title", "")
        mr_description = mr.get("description", "") or ""
        author = payload.get("user", {})
        author_name = author.get("name", "") or author.get("username", "")
        author_email = author.get("email", "")

        # Trigger will generation on MR open — intercept at the moment of death
        if action in ("open", "reopen") and mr_iid:
            background_tasks.add_task(
                _background_will_generation,
                project_path, int(mr_iid), mr_title, mr_description,
                author_name, author_email,
            )
            return {
                "status": "will_generation_queued",
                "event": event_type,
                "project": project_path,
                "mr_iid": mr_iid,
                "mr_title": mr_title,
                "action": "feature_will_generator_triggered",
                "note": "NECRO will analyze this MR for feature kills and create a Revival Contract if applicable",
            }

        # On merge: update contract status to 'in_flight' (feature is now officially dead)
        if action == "merge" and mr_iid and settings.MONGODB_URI:
            background_tasks.add_task(
                _background_contract_activate, project_path, int(mr_iid)
            )
            return {
                "status": "contract_activated",
                "event": event_type,
                "project": project_path,
                "mr_iid": mr_iid,
                "action": "revival_contract_monitoring_active",
            }

        return {"status": "ignored", "event": event_type, "action": action}

    # ── Push Hook: graveyard re-evaluation ───────────────────────────────────
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])
    branch = ref.replace("refs/heads/", "") if ref else "unknown"

    if event_type in ("Push Hook", "push") and branch in ("main", "master") and project_path:
        background_tasks.add_task(_background_re_evaluate, project_path, commits)
        return {
            "status": "queued",
            "project": project_path,
            "branch": branch,
            "commits": len(commits),
            "action": "graveyard_re_evaluation_queued",
        }

    return {"status": "ignored", "event": event_type, "reason": "unhandled event type"}


async def _background_will_generation(
    project_path: str,
    mr_iid: int,
    mr_title: str,
    mr_description: str,
    author_name: str,
    author_email: str,
) -> None:
    """
    Background: Feature Will Generator.
    Analyzes the MR for feature kills and creates Revival Contract if applicable.
    """
    logger.info("[WEBHOOK] Will generation starting for MR !%d in %s", mr_iid, project_path)
    try:
        from backend.services.will_writer import generate_revival_will
        contract = await generate_revival_will(
            project_path=project_path,
            mr_iid=mr_iid,
            mr_title=mr_title,
            mr_description=mr_description,
            author_name=author_name,
            author_email=author_email,
        )
        if contract:
            logger.info(
                "[WEBHOOK] ✅ Revival Contract created: '%s' → %s",
                contract.get("feature_name"), contract.get("issue_url", "no issue URL")
            )
        else:
            logger.info("[WEBHOOK] MR !%d — not a feature kill, no will generated", mr_iid)
    except Exception as exc:
        logger.error("[WEBHOOK] Will generation failed for MR !%d: %s", mr_iid, exc)


async def _background_contract_activate(project_path: str, mr_iid: int) -> None:
    """
    Background: when an MR merges, confirm the kill is live — the contract is now actively monitoring.
    """
    if not settings.MONGODB_URI:
        return
    try:
        from backend.db.connection import get_db
        from datetime import datetime, timezone
        db = get_db()
        result = await db["revival_contracts"].update_many(
            {"project_path": project_path, "mr_iid": mr_iid, "status": "active"},
            {"$set": {"merged": True, "merged_at": datetime.now(timezone.utc)}},
        )
        if result.modified_count:
            logger.info(
                "[WEBHOOK] Contract activated (MR merged): %s !%d — %d contracts now live",
                project_path, mr_iid, result.modified_count,
            )
    except Exception as exc:
        logger.debug("[WEBHOOK] Contract activation failed: %s", exc)


async def _background_re_evaluate(project_path: str, commits: list):
    """
    Background task: re-evaluate the graveyard when new commits arrive.
    Checks if any new commit resolves a previously identified kill reason.
    """
    logger.info("[WEBHOOK] Background re-evaluation started for %s", project_path)
    try:
        from backend.services.git_forensics import detect_dead_features
        from backend.services.viability_scorer import score_revival_viability
        from backend.services.death_reason import extract_death_reason

        # Check if any new commit message suggests a blocker was resolved
        resolved_patterns = [
            "fix", "resolve", "upgrade", "update", "migrate", "enable",
            "add support", "implement", "release", "stable", "available"
        ]
        relevant_commits = [
            c for c in commits
            if any(p in c.get("message", "").lower() for p in resolved_patterns)
        ]

        if relevant_commits:
            logger.info(
                "[WEBHOOK] %d potentially relevant commits found — scanning graveyard for %s",
                len(relevant_commits), project_path
            )

            # Re-evaluate existing buried features for this project
            if settings.MONGODB_URI:
                from backend.db.connection import get_db
                db = get_db()
                buried = await db["features"].find(
                    {
                        "project_path": project_path,
                        "viability.recommendation": {"$in": ["investigate_further", "keep_buried"]},
                    },
                    {"_id": 0}
                ).to_list(20)

                for feat in buried:
                    # Re-score viability with awareness of new commits
                    updated_viability = await score_revival_viability(feat, feat.get("death_reason", {}))
                    new_rec = updated_viability.get("recommendation")
                    old_rec = feat.get("viability", {}).get("recommendation")

                    if new_rec != old_rec:
                        logger.info(
                            "[WEBHOOK] Status change for '%s': %s → %s",
                            feat.get("name"), old_rec, new_rec
                        )
                        await db["features"].update_one(
                            {"feature_id": feat["feature_id"]},
                            {"$set": {"viability": updated_viability, "webhook_updated": True}},
                        )

        logger.info("[WEBHOOK] Re-evaluation complete for %s", project_path)
    except Exception as exc:
        logger.error("[WEBHOOK] Re-evaluation failed for %s: %s", project_path, exc)


async def _get_feature(feature_id: str) -> dict | None:
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            feat = await db["features"].find_one({"feature_id": feature_id}, {"_id": 0})
            if feat:
                return feat
        except Exception:
            pass
    from backend.db.seed import DEMO_FEATURES, DEMO2_FEATURES
    all_features = DEMO_FEATURES + DEMO2_FEATURES
    return next((f for f in all_features if f.get("feature_id") == feature_id), None)
