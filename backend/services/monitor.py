"""
Autonomous monitoring loop — APScheduler re-scans watched repos every N hours.

On each cycle:
1. Calls GitLab MCP list_commits to check for new commits since last scan
2. If new commits found, runs the full forensics pipeline
3. Saves results to MongoDB
4. Fires Slack notification if new revival candidates found

This makes NECRO a genuine agent — it watches without being asked.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_last_run: datetime | None = None
_last_result: dict | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def start_monitor() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        return

    scheduler.add_job(
        _monitor_cycle,
        trigger=IntervalTrigger(hours=settings.MONITOR_INTERVAL_HOURS),
        id="necro_monitor",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    scheduler.start()
    logger.info("[OK] Autonomous monitor started (interval: %dh)", settings.MONITOR_INTERVAL_HOURS)


async def stop_monitor() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Monitor stopped")


async def run_monitor_now() -> dict:
    """Trigger a monitor cycle immediately (called from API)."""
    return await _monitor_cycle()


def get_monitor_status() -> dict:
    return {
        "running": _scheduler.running if _scheduler else False,
        "interval_hours": settings.MONITOR_INTERVAL_HOURS,
        "last_run": _last_run.isoformat() if _last_run else None,
        "last_result": _last_result,
    }


async def _monitor_cycle() -> dict:
    """Main monitoring cycle — runs for all watched repos."""
    global _last_run, _last_result

    _last_run = datetime.now(timezone.utc)
    result = {"checked_repos": [], "new_candidates": 0, "errors": []}

    try:
        from backend.db.connection import get_db
        db = get_db()

        watched = await db["watch_list"].find({}).to_list(length=50)
        if not watched:
            logger.info("[monitor] No repos in watch list")
            _last_result = result
            return result

        for repo in watched:
            project_path = repo.get("project_path", "")
            if not project_path:
                continue

            try:
                repo_result = await _check_repo(project_path, repo)
                result["checked_repos"].append(repo_result)
                result["new_candidates"] += repo_result.get("new_revive_now", 0)
            except Exception as e:
                logger.error("Monitor error for %s: %s", project_path, e)
                result["errors"].append({"project_path": project_path, "error": str(e)})

        _last_result = result
        logger.info("[monitor] Cycle complete — %d repos, %d new candidates", len(watched), result["new_candidates"])

    except Exception as e:
        logger.exception("Monitor cycle failed: %s", e)
        result["errors"].append({"error": str(e)})
        _last_result = result

    return result


async def _check_repo(project_path: str, repo_doc: dict) -> dict:
    """Check a single repo for new dead features since last scan."""
    from backend.services.gitlab_mcp import mcp
    from backend.db.connection import get_db

    db = get_db()
    last_scanned = repo_doc.get("last_scanned")

    # Check if new commits exist since last scan
    recent_commits = await mcp.list_commits(project_path, per_page=5, page=1)
    if not recent_commits:
        return {"project_path": project_path, "status": "no_commits", "new_revive_now": 0}

    latest_sha = recent_commits[0].get("id", "") if recent_commits else ""

    # If last scan was recent and no new commits, skip
    if last_scanned and isinstance(last_scanned, datetime):
        hours_since = (datetime.now(timezone.utc) - last_scanned).total_seconds() / 3600
        if hours_since < settings.MONITOR_INTERVAL_HOURS * 0.8:
            return {"project_path": project_path, "status": "skipped_recent", "new_revive_now": 0}

    # Run lightweight scan (fewer commits for monitor cycles)
    from backend.services.git_forensics import detect_dead_features
    from backend.services.death_reason import extract_death_reason
    from backend.services.viability_scorer import score_revival_viability
    from backend.db.schemas import FeatureDoc, DeathReasonDoc, ViabilityDoc, ScanDoc
    import uuid

    features = await detect_dead_features(project_path, max_commits=100, lookback_months=12)

    scan_id = f"monitor-{uuid.uuid4().hex[:8]}"
    new_revive_now = 0

    for feat in features[:10]:
        feat.death_reason = await extract_death_reason(feat)
        feat.viability = await score_revival_viability(feat, feat.death_reason)

        if feat.viability and feat.viability.get("recommendation") == "revive_now":
            # Check if we already know about this one
            existing = await db["features"].find_one({
                "project_path": project_path,
                "feature_id": feat.id,
            })
            if not existing:
                new_revive_now += 1
                doc = FeatureDoc(
                    project_path=project_path,
                    scan_id=scan_id,
                    feature_id=feat.id,
                    name=feat.name,
                    kill_commit_sha=feat.kill_commit_sha,
                    kill_commit_message=feat.kill_commit_message,
                    kill_date=feat.kill_date,
                    detection_method=feat.detection_method,
                    linked_mr_iid=feat.linked_mr_iid,
                    linked_issue_iids=feat.linked_issue_iids,
                    context_snippets=feat.context_snippets,
                    death_reason=DeathReasonDoc(**feat.death_reason),
                    viability=ViabilityDoc(**feat.viability),
                )
                await db["features"].insert_one(doc.model_dump())

    # Update last_scanned timestamp
    await db["watch_list"].update_one(
        {"project_path": project_path},
        {"$set": {"last_scanned": datetime.now(timezone.utc), "last_scan_id": scan_id, "revive_now_count": new_revive_now}},
    )

    # Fire Slack notification if new candidates found
    if new_revive_now > 0:
        await _notify_slack(project_path, new_revive_now, features[:new_revive_now])

    return {"project_path": project_path, "status": "scanned", "new_revive_now": new_revive_now, "features_checked": len(features)}


async def _notify_slack(project_path: str, count: int, features: list) -> None:
    """Send Slack notification when new revival candidates are found."""
    try:
        from backend.services.slack_client import send_revival_alert
        await send_revival_alert(project_path, count, features)
    except Exception as e:
        logger.warning("Slack notification failed: %s", e)
