"""
Feature Vitality Time-Series — The Feature EKG.

Tracks the 'vitality curve' of every dead feature over time using MongoDB
time-series collections:

  - Pre-death signals:  demand was rising or falling? tests passing?
  - Post-death signals: demand recovering? competitors shipping it?
  - Revival window:     the optimal moment to act (decay resolved + demand rising)

The Feature EKG shows what nobody else shows:
  - Features don't just die — they get SICK before they die
  - After death, demand curves tell you exactly when to revive
  - The optimal revival window = decay_reason_resolved AND demand_rising AND competitor_gap_widening

MongoDB time-series collection: `feature_vitality`
  timeField: "ts"
  metaField: "feature_id"
  granularity: "hours"
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


async def ensure_vitality_collection() -> bool:
    """
    Create the MongoDB time-series collection for feature vitality snapshots.
    Called once on startup.
    """
    if not settings.MONGODB_URI:
        return False
    try:
        from backend.db.connection import get_db
        db = get_db()

        # Check if collection already exists
        collections = await db.list_collection_names()
        if "feature_vitality" in collections:
            return True

        # Create time-series collection
        await db.create_collection(
            "feature_vitality",
            timeseries={
                "timeField": "ts",
                "metaField": "feature_id",
                "granularity": "hours",
            },
        )
        logger.info("[Vitality] ✅ Time-series collection 'feature_vitality' created")
        return True

    except Exception as exc:
        # Time-series might not be supported on this Atlas tier — fall back to regular
        logger.warning("[Vitality] Time-series collection setup: %s — using regular collection", exc)
        return False


async def take_vitality_snapshot(
    feature: dict,
    project_path: str,
    open_issues: Optional[list] = None,
) -> dict:
    """
    Take a vitality snapshot of a feature's current demand state.
    Called by the autonomous monitor on every scan cycle.
    """
    from backend.routes.stream import _compute_revival_score, _match_open_requests

    # Compute current demand count
    if open_issues is None and settings.MONGODB_URI:
        try:
            from backend.services.gitlab_mcp import mcp
            open_issues = await mcp.list_open_issues(project_path, per_page=50)
        except Exception:
            open_issues = []

    demand_count = len(_match_open_requests(
        feature.get("name", ""), open_issues or [], project_path
    ))

    # Days since kill
    days_since_kill = _days_since_kill(feature.get("kill_date", ""))

    snapshot = {
        "feature_id": feature.get("feature_id", ""),
        "project_path": project_path,
        "ts": datetime.now(timezone.utc),
        "demand_count": demand_count,
        "revival_score": feature.get("revival_score", _compute_revival_score(feature)),
        "days_since_kill": days_since_kill,
        "recommendation": (feature.get("viability") or {}).get("recommendation", "unknown"),
    }

    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            await db["feature_vitality"].insert_one({**snapshot})
            snapshot.pop("_id", None)
        except Exception as exc:
            logger.debug("[Vitality] Snapshot storage failed: %s", exc)

    return snapshot


async def get_vitality_history(
    feature_id: str,
    project_path: str,
    limit: int = 12,
) -> list[dict]:
    """
    Fetch time-series vitality history for a feature.
    Returns list of {ts, demand_count, revival_score, days_since_kill} sorted oldest-first.
    Used by the frontend sparkline.
    """
    if not settings.MONGODB_URI:
        return []

    try:
        from backend.db.connection import get_db
        db = get_db()
        docs = await db["feature_vitality"].find(
            {"feature_id": feature_id, "project_path": project_path},
            {"_id": 0, "ts": 1, "demand_count": 1, "revival_score": 1, "days_since_kill": 1},
        ).sort("ts", 1).limit(limit).to_list(length=limit)

        # Serialize datetimes
        for doc in docs:
            if isinstance(doc.get("ts"), datetime):
                doc["ts"] = doc["ts"].isoformat()

        return docs
    except Exception as exc:
        logger.debug("[Vitality] get_history failed: %s", exc)
        return []


async def seed_vitality_snapshots() -> int:
    """
    Seed time-series vitality data for all demo features.
    Generates 12 monthly snapshots per feature showing realistic decay + recovery curves.
    Called once on startup after demo features are seeded.
    """
    if not settings.MONGODB_URI:
        return 0

    try:
        from backend.db.connection import get_db
        db = get_db()

        # Skip if already seeded
        existing = await db["feature_vitality"].count_documents({})
        if existing > 0:
            logger.debug("[Vitality] Already seeded (%d snapshots)", existing)
            return existing

        docs_to_insert = []
        now = datetime.now(timezone.utc)

        # Vitality curves: (feature_id, project_path, demand_points[12], revival_score_points[12])
        # Points: months -11 to 0 (relative to now), 12 monthly snapshots
        # demand_points: open issue count over time
        # 0 = "moment of kill" roughly at month -6 for most features
        CURVES = [
            # gitlab-foss: revive_now — rising demand after kill (users keep asking)
            ("pages-domain-verification-wildcard", "gitlab-org/gitlab-foss",
             [45, 38, 42, 51, 48, 55,  60, 78, 95, 112, 140, 168], [0, 0, 0, 0, 0, 0,  82, 84, 85, 86, 87, 87]),
            ("built-in-container-registry-cache", "gitlab-org/gitlab-foss",
             [30, 35, 28, 40, 45, 52,  58, 72, 88, 102, 122, 138], [0, 0, 0, 0, 0, 0,  88, 89, 90, 91, 91, 91]),
            # gitlab-foss: investigate — moderate demand
            ("elasticsearch-free-tier", "gitlab-org/gitlab-foss",
             [20, 22, 18, 25, 28, 30,  33, 37, 40, 42, 40, 38], [0, 0, 0, 0, 0, 0,  50, 51, 52, 53, 53, 53]),
            ("mattermost-integration", "gitlab-org/gitlab-foss",
             [15, 12, 10, 8, 7, 6,  5, 4, 4, 3, 3, 2], [0, 0, 0, 0, 0, 0,  38, 37, 37, 36, 36, 36]),
            # gitlab-foss: keep_buried — flat/dead demand
            ("omnibus-geo-replication-free", "gitlab-org/gitlab-foss",
             [10, 8, 6, 5, 4, 3,  2, 2, 1, 1, 0, 0], [0, 0, 0, 0, 0, 0,  20, 20, 20, 20, 20, 20]),

            # inkscape: revive_now
            ("live-path-effects-preview", "inkscape/inkscape",
             [15, 18, 22, 28, 35, 42,  50, 60, 72, 84, 92, 102], [0, 0, 0, 0, 0, 0,  76, 78, 79, 80, 80, 80]),
            # inkscape: investigate
            ("pdf-ghostscript-import", "inkscape/inkscape",
             [8, 10, 12, 9, 11, 12,  14, 16, 18, 17, 16, 15], [0, 0, 0, 0, 0, 0,  58, 59, 60, 60, 60, 60]),
            # inkscape: keep_buried
            ("gtk2-backend", "inkscape/inkscape",
             [5, 3, 2, 1, 1, 0,  0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0,  19, 19, 19, 19, 19, 19]),
            ("windows-xp-support", "inkscape/inkscape",
             [3, 2, 1, 1, 0, 0,  0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0,  19, 19, 19, 19, 19, 19]),
        ]

        for feature_id, project_path, demand_pts, score_pts in CURVES:
            for month_offset, (demand, score) in enumerate(zip(demand_pts, score_pts)):
                ts = now - timedelta(days=(11 - month_offset) * 30)
                days_since_kill = max(0, (month_offset - 5) * 30)  # kill at month index 5
                docs_to_insert.append({
                    "feature_id": feature_id,
                    "project_path": project_path,
                    "ts": ts,
                    "demand_count": demand,
                    "revival_score": score,
                    "days_since_kill": days_since_kill,
                    "recommendation": (
                        "revive_now" if score >= 70
                        else "investigate_further" if score >= 30
                        else "keep_buried"
                    ),
                })

        if docs_to_insert:
            await db["feature_vitality"].insert_many(docs_to_insert)
            logger.info("[Vitality] ✅ Seeded %d vitality snapshots", len(docs_to_insert))

        return len(docs_to_insert)

    except Exception as exc:
        logger.warning("[Vitality] Seeding failed: %s", exc)
        return 0


async def get_vitality_sparkline(feature_id: str, project_path: str) -> dict:
    """
    Get a compact sparkline data structure for the frontend.
    Returns {points: [int], trend: 'rising'|'falling'|'flat', peak: int, current: int}
    """
    history = await get_vitality_history(feature_id, project_path, limit=8)
    if not history:
        return {}

    points = [h.get("demand_count", 0) for h in history]
    current = points[-1] if points else 0
    peak = max(points) if points else 0

    # Trend: compare last 3 points vs first 3 points
    if len(points) >= 4:
        recent_avg = sum(points[-3:]) / 3
        early_avg = sum(points[:3]) / 3
        if recent_avg > early_avg * 1.15:
            trend = "rising"
        elif recent_avg < early_avg * 0.85:
            trend = "falling"
        else:
            trend = "flat"
    else:
        trend = "flat"

    return {
        "points": points,
        "trend": trend,
        "peak": peak,
        "current": current,
        "data_points": len(points),
    }


def _days_since_kill(kill_date_str: str) -> int:
    """Parse a kill_date string and return days elapsed since then."""
    if not kill_date_str:
        return 0
    try:
        from dateutil import parser as dtparser
        kill_dt = dtparser.parse(kill_date_str, fuzzy=True)
        if kill_dt.tzinfo is None:
            kill_dt = kill_dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - kill_dt).days)
    except Exception:
        return 0
