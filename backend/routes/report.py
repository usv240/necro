"""
GET /api/report/latest           — most recent scan from MongoDB
GET /api/report/scans            — all past scans (history)
GET /api/report/feature/{id}     — single feature with competitive intel
GET /api/report/download         — download latest as markdown
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

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
