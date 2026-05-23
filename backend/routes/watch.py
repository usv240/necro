"""
Watch list — register repos for autonomous monitoring.
GET  /api/watch/list
POST /api/watch/add
DELETE /api/watch/{project_path:path}
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class WatchRequest(BaseModel):
    repo_url: str
    label: str = ""
    scan_interval_hours: int = 24


@router.get("/list")
async def list_watched():
    if not settings.MONGODB_URI:
        return {"repos": [], "message": "MongoDB not configured"}
    from backend.db.connection import get_db
    db = get_db()
    repos = await db["watch_list"].find({}, {"_id": 0}).sort("added_at", -1).to_list(length=50)
    return {"repos": [_clean(r) for r in repos]}


@router.post("/add")
async def add_watch(req: WatchRequest):
    if not settings.MONGODB_URI:
        raise HTTPException(status_code=503, detail="MongoDB not configured")
    from backend.db.connection import get_db
    from backend.db.schemas import WatchedRepo
    db = get_db()

    project_path = _url_to_path(req.repo_url)
    existing = await db["watch_list"].find_one({"project_path": project_path})
    if existing:
        raise HTTPException(status_code=400, detail=f"'{project_path}' is already in the watch list.")

    repo = WatchedRepo(
        project_path=project_path,
        repo_url=req.repo_url,
        label=req.label or project_path,
        scan_interval_hours=req.scan_interval_hours,
    )
    await db["watch_list"].insert_one(repo.model_dump())
    logger.info("[watch] Added %s to watch list", project_path)
    return {"status": "watching", "project_path": project_path}


@router.delete("/{project_path:path}")
async def remove_watch(project_path: str):
    if not settings.MONGODB_URI:
        raise HTTPException(status_code=503, detail="MongoDB not configured")
    from backend.db.connection import get_db
    db = get_db()
    result = await db["watch_list"].delete_one({"project_path": project_path})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"'{project_path}' not in watch list.")
    return {"status": "removed", "project_path": project_path}


def _url_to_path(url: str) -> str:
    url = url.rstrip("/")
    if "gitlab.com/" in url:
        return url.split("gitlab.com/", 1)[1]
    return url


def _clean(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc
