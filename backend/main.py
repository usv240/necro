import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import OUTPUT_PATH, settings
from backend.routes import report, revive, scan, stream, watch, monitor as monitor_route, agent as agent_route
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

        # Atlas Vector Search index (required for semantic demand matching)
        try:
            from backend.services.atlas_setup import ensure_vector_index
            await ensure_vector_index()
        except Exception as e:
            logger.warning("[WARN] Atlas Vector Search index setup: %s", e)

        # Feature Vitality Time-Series — Feature EKG (decay/recovery curves)
        try:
            from backend.services.vitality import ensure_vitality_collection, seed_vitality_snapshots
            await ensure_vitality_collection()
            await seed_vitality_snapshots()
        except Exception as e:
            logger.warning("[WARN] Vitality time-series setup: %s", e)
    else:
        logger.warning("[WARN] MONGODB_URI not set — running without persistence")

    # GitLab REST client
    await mcp.start()

    # ADK agent — initialize eagerly so health check shows "initialized"
    try:
        from backend.services.adk_runner import get_runner
        get_runner()
        logger.info("[OK] ADK agent runner initialized at startup")
    except Exception as e:
        logger.warning("[WARN] ADK agent startup: %s", e)

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
app.include_router(agent_route.router, prefix="/api/agent", tags=["agent"])
app.include_router(watch.router, prefix="/api/watch", tags=["watch"])
app.include_router(monitor_route.router, prefix="/api/monitor", tags=["monitor"])

# ── NECRO as MCP Server — bidirectional GitLab integration ───────────────────
# NECRO calls GitLab's MCP server (Phase 1) AND exposes its own MCP endpoint
# so GitLab Duo agents can call NECRO's analytical pipeline as MCP tools.
# Mounted at /mcp — configure as MCP endpoint in GitLab Duo Agent Platform.
try:
    from backend.routes.mcp_server import create_mcp_app
    _necro_mcp_asgi = create_mcp_app()
    if _necro_mcp_asgi:
        app.mount("/mcp", _necro_mcp_asgi)
        logger.info("[OK] NECRO MCP server mounted at /mcp (FastMCP, 3 tools)")
except Exception as _mcp_err:
    logger.warning("[WARN] NECRO MCP server not available: %s", _mcp_err)


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
        "gitlab_mcp": "active" if mcp.available else "unavailable (no GITLAB_TOKEN)",
        "mcp_servers": {
            "official": {
                "name": "GitLab Official MCP Server",
                "transport": "SSE (SseServerParams)",
                "endpoint": f"{settings.GITLAB_URL}/-/ide/mcp",
                "auth": "Bearer PAT",
                "status": "active" if mcp.available else "no GITLAB_TOKEN",
            },
            "community": {
                "name": "@zereight/mcp-gitlab",
                "transport": "stdio (StdioConnectionParams)",
                "command": "npx --yes @zereight/mcp-gitlab",
                "auth": "GITLAB_PERSONAL_ACCESS_TOKEN env",
                "status": "active" if mcp.available else "no GITLAB_TOKEN",
            },
        },
        "mcp_tools": [
            "list_commits", "get_commit", "get_commit_diff",
            "list_merge_requests", "list_merge_request_notes",
            "list_issues", "list_issue_notes",
            "create_issue", "get_project",
            "list_branches", "search_code",
            "list_pipelines", "search_users",
            "create_branch", "create_file", "create_merge_request",
            "get_default_branch", "list_open_issues",
        ],
        "mcp_tool_count": 19,
        "adk_agent": "initialized" if _runner is not None else "pending",
        "adk_endpoints": [
            "POST /api/agent/ask — freeform prompt to ADK agent",
            "POST /api/agent/revive — create GitLab revival issue via ADK + MCPToolset",
            "POST /api/agent/webhook/gitlab — GitLab push webhook → re-evaluate graveyard",
        ],
        "necro_mcp_server": {
            "endpoint": "POST /mcp",
            "transport": "Streamable HTTP (FastMCP)",
            "tools": ["scan_repository", "get_candidates", "get_health"],
            "usage": "Configure as MCP tool endpoint in GitLab Duo Agent Platform",
        },
        "slack": "configured" if settings.SLACK_BOT_TOKEN else "not configured",
        "monitor": get_monitor_status(),
        "gemini_primary": "gemini-3-flash-preview",
        "gemini_fallback": "gemini-2.5-flash (vertex-ai)",
    }


# Serve frontend — must be last
frontend_path = Path("frontend")
if frontend_path.exists():
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
