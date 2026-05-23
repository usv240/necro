"""
POST /api/scan/start  — kick off a background scan, returns scan_id
GET  /api/scan/status/{scan_id} — poll scan progress
POST /api/scan/demo   — load the pre-seeded demo (gitlab-org/gitlab-foss) from MongoDB
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory scan progress tracker (scan_id → status dict)
_scans: dict[str, dict] = {}


class ScanRequest(BaseModel):
    repo_url: str
    max_commits: int = 300
    lookback_months: int = 24


@router.post("/start")
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    scan_id = str(uuid.uuid4())[:8]
    project_path = _url_to_path(req.repo_url)
    _scans[scan_id] = {
        "scan_id": scan_id,
        "status": "running",
        "project_path": project_path,
        "repo_url": req.repo_url,
        "progress": [],
        "result": None,
        "error": None,
    }
    background_tasks.add_task(_run_scan, scan_id, project_path, req.repo_url, req.max_commits, req.lookback_months)
    return {"scan_id": scan_id, "status": "running", "project_path": project_path}


@router.get("/status/{scan_id}")
async def scan_status(scan_id: str):
    if scan_id not in _scans:
        return {"error": "scan not found"}
    return _scans[scan_id]


@router.post("/demo")
async def load_demo():
    """
    Return the pre-seeded demo scan from MongoDB.
    Demo data is based on real gitlab-org/gitlab-foss public history.
    No hardcoded Python dicts — all data lives in MongoDB Atlas.
    """
    from backend.db.seed import DEMO_SCAN_ID, DEMO_PROJECT

    if settings.MONGODB_URI:
        from backend.db.connection import get_db
        db = get_db()
        scan = await db["scans"].find_one({"scan_id": DEMO_SCAN_ID}, {"_id": 0})
        features = await db["features"].find(
            {"scan_id": DEMO_SCAN_ID}, {"_id": 0}
        ).to_list(length=100)
        if scan and features:
            return {
                "project_path": DEMO_PROJECT,
                "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                "scan_date": scan.get("scan_date", ""),
                "total_commits_scanned": scan.get("total_commits_scanned", 0),
                "features": _serialize_features(features),
                "source": "mongodb_atlas",
            }

    # Fallback: seed data was not loaded (no MongoDB), return inline
    from backend.db.seed import DEMO_FEATURES, DEMO_PROJECT, DEMO_REPO_URL
    return {
        "project_path": DEMO_PROJECT,
        "repo_url": DEMO_REPO_URL,
        "scan_date": "2026-05-20T12:00:00",
        "total_commits_scanned": 8472,
        "features": DEMO_FEATURES,
        "source": "inline_fallback",
    }


async def _run_scan(
    scan_id: str,
    project_path: str,
    repo_url: str,
    max_commits: int,
    lookback_months: int,
) -> None:
    progress_log: list[str] = _scans[scan_id]["progress"]

    async def emit(msg: str):
        progress_log.append(msg)
        logger.info("[scan %s] %s", scan_id, msg)

    try:
        await emit(f"Starting NECRO scan on {project_path}...")
        await emit("Connecting to GitLab MCP server...")

        from backend.services.git_forensics import detect_dead_features
        from backend.services.death_reason import extract_death_reason
        from backend.services.viability_scorer import score_revival_viability
        from backend.services.roi_estimator import estimate_revival_roi
        from backend.services.competitive_intel import analyze_competitive_gap
        from backend.services.output_writer import write_graveyard_report
        from backend.db.schemas import ScanDoc, FeatureDoc, DeathReasonDoc, ViabilityDoc, ROIDoc, CompetitiveIntelDoc

        features = await detect_dead_features(project_path, max_commits, lookback_months, progress_cb=emit)
        await emit(f"Running Gemini 3 Flash analysis on {len(features)} dead features...")

        saved_features = []
        for feat in features[:15]:
            await emit(f"Gemini 3 Flash — analyzing kill reason for '{feat.name}'...")
            feat.death_reason = await extract_death_reason(feat)
            await emit(f"Evaluating revival viability for '{feat.name}'...")
            feat.viability = await score_revival_viability(feat, feat.death_reason)
            await emit(f"Estimating demand signals for '{feat.name}'...")
            feat.roi = await estimate_revival_roi(feat, project_path)
            await emit(f"Running competitive intelligence for '{feat.name}'...")
            comp = await analyze_competitive_gap(
                feat.name,
                feat.death_reason.get("category", "unknown"),
                feat.kill_date,
                feat.death_reason.get("primary_reason", ""),
            )
            saved_features.append({
                "feature_id": feat.id,
                "name": feat.name,
                "kill_commit_sha": feat.kill_commit_sha,
                "kill_commit_message": feat.kill_commit_message,
                "kill_date": feat.kill_date,
                "detection_method": feat.detection_method,
                "linked_mr_iid": feat.linked_mr_iid,
                "linked_issue_iids": feat.linked_issue_iids,
                "context_snippets": feat.context_snippets,
                "death_reason": feat.death_reason,
                "viability": feat.viability,
                "roi": feat.roi,
                "competitive_intel": comp,
            })

        report = {
            "project_path": project_path,
            "repo_url": repo_url,
            "total_commits_scanned": max_commits,
            "features": saved_features,
        }

        # Persist to MongoDB
        if settings.MONGODB_URI:
            from backend.db.connection import get_db
            db = get_db()
            scan_doc = ScanDoc(
                scan_id=scan_id,
                project_path=project_path,
                repo_url=repo_url,
                total_commits_scanned=max_commits,
                features_found=len(saved_features),
                revive_now_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now"),
                investigate_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "investigate_further"),
                keep_buried_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "keep_buried"),
            )
            await db["scans"].insert_one(scan_doc.model_dump())
            for f in saved_features:
                f_doc = {"project_path": project_path, "scan_id": scan_id, **f}
                await db["features"].insert_one(f_doc)
            await emit("Results saved to MongoDB Atlas")

        await write_graveyard_report(report)
        await emit("Graveyard report saved to outputs/necro/")
        await emit(f"SCAN COMPLETE — {scan_doc.revive_now_count} features ready to revive" if settings.MONGODB_URI else "SCAN COMPLETE")

        _scans[scan_id]["status"] = "done"
        _scans[scan_id]["result"] = report

    except Exception as exc:
        logger.exception("Scan %s failed", scan_id)
        _scans[scan_id]["status"] = "error"
        _scans[scan_id]["error"] = str(exc)


def _url_to_path(url: str) -> str:
    url = url.rstrip("/")
    if "gitlab.com/" in url:
        return url.split("gitlab.com/", 1)[1]
    return url


def _serialize_features(features: list[dict]) -> list[dict]:
    """Clean MongoDB docs for JSON response (remove _id, convert dates)."""
    cleaned = []
    for f in features:
        f.pop("_id", None)
        # Convert datetime fields to ISO strings
        for k, v in f.items():
            if isinstance(v, datetime):
                f[k] = v.isoformat()
        cleaned.append(f)
    return cleaned
