import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import OUTPUT_PATH, settings
from backend.routes import report, revive, scan, stream, watch, monitor as monitor_route
from backend.services.gitlab_mcp import mcp
from backend.services.monitor import start_monitor, stop_monitor

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    # MongoDB
    if settings.MONGODB_URI:
        from backend.db.connection import ping, ensure_indexes
        from backend.db.seed import seed_demo_data
        try:
            await ping()
            await ensure_indexes()
            await seed_demo_data()
        except Exception as e:
            logger.warning("[WARN] MongoDB startup issue: %s", e)
    else:
        logger.warning("[WARN] MONGODB_URI not set — running without persistence")

    # GitLab REST client
    await mcp.start()

    # Autonomous monitoring loop
    start_monitor()

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    await stop_monitor()
    await mcp.stop()
    if settings.MONGODB_URI:
        from backend.db.connection import close
        await close()


app = FastAPI(
    title="NECRO — The Code Necromancer",
    description="AI agent that finds disabled features in GitLab repositories and evaluates revival viability",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


app.include_router(scan.router, prefix="/api/scan", tags=["scan"])
app.include_router(stream.router, prefix="/api/scan", tags=["scan"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(revive.router, prefix="/api/revive", tags=["revive"])
app.include_router(watch.router, prefix="/api/watch", tags=["watch"])
app.include_router(monitor_route.router, prefix="/api/monitor", tags=["monitor"])


@app.get("/api/health")
async def health():
    from backend.services.adk_runner import _runner
    from backend.services.monitor import get_monitor_status

    mongo_status = "connected"
    pattern_count = 0
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            pattern_count = await db["features"].count_documents({})
        except Exception:
            mongo_status = "error"
    else:
        mongo_status = "not configured"

    return {
        "status": "ok",
        "service": "necro-code-necromancer",
        "mongodb": mongo_status,
        "features_in_db": pattern_count,
        "gitlab_mcp": "rest (ADK MCPToolset handles MCP in agent)" if mcp.available else "unavailable (no token)",
        "mcp_transport": "rest+adk_mcptoolset",
        "mcp_tools": "via ADK MCPToolset (@zereight/mcp-gitlab)",
        "adk_agent": "initialized" if _runner is not None else "pending",
        "slack": "configured" if settings.SLACK_BOT_TOKEN else "not configured",
        "monitor": get_monitor_status(),
        "gemini_primary": "gemini-3-flash-preview",
        "gemini_fallback": "gemini-2.5-flash (vertex-ai)",
    }


# Serve frontend — must be last
frontend_path = Path("frontend")
if frontend_path.exists():
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
