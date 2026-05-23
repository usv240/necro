"""
GET  /api/monitor/status   — monitoring loop state + last run info
POST /api/monitor/run      — trigger a monitor cycle immediately
"""

from fastapi import APIRouter

from backend.services.monitor import get_monitor_status, run_monitor_now

router = APIRouter()


@router.get("/status")
async def monitor_status():
    return get_monitor_status()


@router.post("/run")
async def trigger_monitor():
    result = await run_monitor_now()
    return result
