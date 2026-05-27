"""
NECRO as an MCP Server — bidirectional GitLab integration.

Exposes NECRO's core capabilities as MCP tools that any MCP-capable client
can consume — including GitLab Duo Agent Platform, Claude Desktop, or any
ADK agent that accepts SseServerParams.

Transport: Streamable HTTP (POST /mcp, mounted by FastAPI)
Protocol:  MCP 1.0 (JSON-RPC over HTTP)

Tools exposed:
  scan_repository     — full forensic scan, returns revival candidates
  get_candidates      — fetch stored candidates for a repo from MongoDB
  get_health          — NECRO system + MCP server health

GitLab Duo usage:
  Configure a Custom Agent in GitLab Settings → Duo → Agents and point
  a tool endpoint to POST {NECRO_URL}/mcp for tool execution.

  Or configure an ADK MCPToolset with SseServerParams pointing to this server
  so any ADK agent can call NECRO's analytical pipeline as an MCP tool.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_mcp_app():
    """
    Build and return the FastMCP ASGI application.
    Mounted at /mcp by the main FastAPI app.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.warning("[MCP Server] FastMCP not available — NECRO MCP server disabled")
        return None

    mcp = FastMCP(
        name="NECRO",
        version="1.0.0",
        instructions=(
            "NECRO is a code forensics system that finds disabled features in GitLab "
            "repositories and evaluates which ones are worth reviving. "
            "Use scan_repository to analyze a repo. "
            "Use get_candidates to retrieve stored analysis results."
        ),
    )

    # ── Tool: scan_repository ─────────────────────────────────────────────────

    @mcp.tool()
    async def scan_repository(
        repo_url: str,
        max_commits: int = 200,
        lookback_months: int = 24,
    ) -> dict[str, Any]:
        """
        Scan a GitLab repository for dormant features that are ready to revive.

        Runs the full NECRO pipeline:
          Phase 0 — ADK agent assesses repository depth
          Phase 1 — GitLab MCP collects commits, issues, MRs, feature flags
          Phase 2 — Gemini 3 Flash analyzes kill reasons and viability

        Returns a list of features with recommendation (revive_now | investigate_further | keep_buried),
        feasibility scores, demand signals, and Resurrection Chains.

        Args:
            repo_url: Full GitLab URL (e.g. https://gitlab.com/org/repo)
            max_commits: Number of commits to analyze (50-500)
            lookback_months: How many months back to look (3-60)
        """
        import asyncio
        from backend.routes.stream import _stream_live, _url_to_path
        import json as _json
        from datetime import datetime, date

        def _default(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            return str(obj)

        project_path = _url_to_path(repo_url)
        collected: dict = {}
        log: list[str] = []

        async def emit(msg: str):
            log.append(msg)
            if msg.startswith("__REPORT__:"):
                try:
                    collected.update(_json.loads(msg[len("__REPORT__:"):]))
                except Exception:
                    pass

        try:
            await _stream_live(emit, project_path, max_commits, lookback_months)
        except Exception as exc:
            logger.error("[MCP Server] scan_repository failed: %s", exc)
            return {"error": str(exc), "project_path": project_path, "features": []}

        features = collected.get("features", [])
        revive_now = [f for f in features if f.get("viability", {}).get("recommendation") == "revive_now"]
        investigate = [f for f in features if f.get("viability", {}).get("recommendation") == "investigate_further"]

        return {
            "project_path": project_path,
            "total_commits_scanned": collected.get("total_commits_scanned", max_commits),
            "features_analyzed": len(features),
            "revive_now_count": len(revive_now),
            "investigate_count": len(investigate),
            "top_revival_candidates": [
                {
                    "feature_id": f.get("feature_id"),
                    "name": f.get("name"),
                    "kill_date": f.get("kill_date"),
                    "feasibility": f.get("viability", {}).get("revival_feasibility"),
                    "what_changed": f.get("viability", {}).get("what_changed", "")[:200],
                    "effort": f.get("viability", {}).get("effort_estimate"),
                    "revival_score": f.get("revival_score", 0),
                }
                for f in sorted(revive_now, key=lambda x: x.get("revival_score", 0), reverse=True)[:5]
            ],
            "resurrection_chains": collected.get("resurrection_chains", []),
            "adk_synthesis": collected.get("adk_synthesis"),
            "mcp_tool_count": collected.get("mcp_tool_count", 0),
        }

    # ── Tool: get_candidates ──────────────────────────────────────────────────

    @mcp.tool()
    async def get_candidates(project_path: str) -> dict[str, Any]:
        """
        Retrieve previously analyzed revival candidates from MongoDB for a repo.

        Use this to get NECRO's stored analysis results without re-running a full scan.
        Returns the most recent scan data including recommendations and scores.

        Args:
            project_path: GitLab project path (e.g. gitlab-org/gitlab-foss)
        """
        from backend.config import settings

        if not settings.MONGODB_URI:
            return {"error": "MongoDB not configured", "project_path": project_path}

        try:
            from backend.db.connection import get_db
            db = get_db()

            features = await db["features"].find(
                {"project_path": project_path},
                {"_id": 0, "embedding": 0}
            ).sort("created_at", -1).limit(20).to_list(length=20)

            revive_now = [f for f in features if (f.get("viability") or {}).get("recommendation") == "revive_now"]
            investigate = [f for f in features if (f.get("viability") or {}).get("recommendation") == "investigate_further"]

            return {
                "project_path": project_path,
                "total_stored": len(features),
                "revive_now": len(revive_now),
                "investigate": len(investigate),
                "candidates": [
                    {
                        "feature_id": f.get("feature_id"),
                        "name": f.get("name"),
                        "recommendation": (f.get("viability") or {}).get("recommendation"),
                        "feasibility": (f.get("viability") or {}).get("revival_feasibility"),
                        "kill_date": f.get("kill_date"),
                        "revival_score": f.get("revival_score", 0),
                    }
                    for f in features
                ],
            }
        except Exception as exc:
            logger.error("[MCP Server] get_candidates failed: %s", exc)
            return {"error": str(exc), "project_path": project_path}

    # ── Tool: get_health ──────────────────────────────────────────────────────

    @mcp.tool()
    async def get_health() -> dict[str, Any]:
        """
        Check NECRO system health — MCP servers, MongoDB, ADK agent, Gemini API.
        Use this to verify the system is operational before running a scan.
        """
        from backend.config import settings
        from backend.services.gitlab_mcp import mcp as gl_mcp

        health: dict[str, Any] = {
            "status": "ok",
            "service": "necro-mcp-server",
            "gitlab_mcp": "active" if gl_mcp.available else "no GITLAB_TOKEN",
            "gemini": "configured" if settings.GEMINI_API_KEY else "not configured",
            "mongodb": "configured" if settings.MONGODB_URI else "not configured",
            "mcp_servers": {
                "official_sse": f"{settings.GITLAB_URL}/-/ide/mcp",
                "community_stdio": "@zereight/mcp-gitlab (npx)",
            },
        }

        if settings.MONGODB_URI:
            try:
                from backend.db.connection import get_db
                db = get_db()
                count = await db["features"].count_documents({})
                health["features_in_db"] = count
                health["mongodb"] = "connected"
            except Exception as exc:
                health["mongodb"] = f"error: {exc}"

        return health

    logger.info("[OK] NECRO MCP server initialized (FastMCP, 3 tools: scan_repository, get_candidates, get_health)")
    return mcp.get_asgi_app()
