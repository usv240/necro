"""
MongoDB Atlas connection via Motor (async).
Mirrors the pattern used in ORACLE — Motor client is the async driver,
MongoDB MCP is the agent-facing interface for queries.
"""

import logging

import motor.motor_asyncio
from pymongo import IndexModel, ASCENDING, DESCENDING

from backend.config import settings

logger = logging.getLogger(__name__)

_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None


def get_client() -> motor.motor_asyncio.AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URI)
    return _client


def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[settings.MONGODB_DB_NAME]
    return _db


async def ping() -> None:
    db = get_db()
    await db.command("ping")
    logger.info("[OK] MongoDB connected — db=%s", settings.MONGODB_DB_NAME)


async def close() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


async def ensure_indexes() -> None:
    """Create indexes idempotently on startup."""
    db = get_db()
    try:
        await db["scans"].create_index([("project_path", ASCENDING), ("scan_date", DESCENDING)])
        await db["features"].create_index([("project_path", ASCENDING), ("scan_id", ASCENDING)])
        await db["features"].create_index([("recommendation", ASCENDING)])
        await db["features"].create_index([("revival_score", DESCENDING)])
        await db["watch_list"].create_index("project_path", unique=True)
        await db["revival_log"].create_index([("project_path", ASCENDING), ("created_at", DESCENDING)])
        # Revival contracts — Feature Will Generator (indexed by project + MR + status)
        await db["revival_contracts"].create_index([("project_path", ASCENDING), ("status", ASCENDING)])
        await db["revival_contracts"].create_index([("mr_iid", ASCENDING), ("project_path", ASCENDING)])
        await db["revival_contracts"].create_index([("contract_id", ASCENDING)], unique=True, sparse=True)
        # Feature vitality time-series — Feature EKG (indexed by feature_id + ts)
        await db["feature_vitality"].create_index([("feature_id", ASCENDING), ("ts", DESCENDING)])
        await db["feature_vitality"].create_index([("project_path", ASCENDING), ("ts", DESCENDING)])
        logger.info("[OK] MongoDB indexes ready")
    except Exception as e:
        logger.warning("Index creation warning (may already exist): %s", e)
