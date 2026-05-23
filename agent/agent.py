"""
Google ADK agent for NECRO — The Code Necromancer.

Model: gemini-3-flash-preview
MCP:   @zereight/mcp-gitlab via ADK MCPToolset (StdioConnectionParams)
       — gives the agent native GitLab MCP tools (list_commits, create_issue, etc.)
       — works on Linux/Cloud Run; gracefully degrades to REST on Windows localhost

Custom FunctionTools handle NECRO's analytical pipeline:
  scan_repository  → Git forensics + AI analysis via Gemini
  save_report      → Persist graveyard report to disk
  create_issue     → Create GitLab revival issue (via MCP or REST)
"""

import logging
import os
import sys
from pathlib import Path

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()

_runner: Runner | None = None
_agent: Agent | None = None


# ── Custom analytical FunctionTools ──────────────────────────────────────────

async def _scan_repository_tool(
    project_path: str,
    max_commits: int = 300,
    lookback_months: int = 24,
) -> dict:
    """
    Scan a GitLab repository for disabled/dead features using MCP tools.
    Returns a list of dead feature candidates with detection method and context.
    """
    from backend.services.git_forensics import detect_dead_features
    from backend.services.death_reason import extract_death_reason
    from backend.services.viability_scorer import score_revival_viability
    from backend.services.roi_estimator import estimate_revival_roi

    features = await detect_dead_features(project_path, max_commits, lookback_months)

    results = []
    for feat in features[:15]:
        feat.death_reason = await extract_death_reason(feat)
        feat.viability = await score_revival_viability(feat, feat.death_reason)
        feat.roi = await estimate_revival_roi(feat, project_path)
        results.append(_feature_to_dict(feat))

    return {"project_path": project_path, "features": results, "total_found": len(features)}


async def _save_report_tool(report_data: dict) -> dict:
    """
    Save the graveyard report to disk as Markdown and JSON.
    Returns the file paths that were written.
    """
    from backend.services.output_writer import write_graveyard_report
    paths = await write_graveyard_report(report_data)
    return {"status": "saved", "files": paths}


async def _create_revival_issue_tool(
    project_path: str,
    feature_name: str,
    kill_commit_message: str,
    what_changed: str,
    effort_estimate: str,
    revival_plan: str,
) -> dict:
    """
    Create a GitLab issue for a revival candidate via GitLab REST API.
    The ADK agent also has native GitLab MCP tools (create_issue, etc.)
    available via MCPToolset — use whichever is most appropriate.
    Returns the created issue URL.
    """
    from backend.services.gitlab_mcp import mcp

    title = f"Revival candidate: {feature_name}"
    description = f"""## Feature Revival Candidate — identified by NECRO

**Original kill reason:** {kill_commit_message}

**Why it's revivable now:** {what_changed}

**Estimated effort:** {effort_estimate}

## Revival Plan

{revival_plan}

---
*This issue was created by NECRO — The Code Necromancer agent.*
*Labels: revival-candidate, necro-identified*
"""
    result = await mcp.create_issue(
        project_path,
        title=title,
        description=description,
        labels=["revival-candidate", "necro-identified"],
    )

    if result:
        return {
            "status": "created",
            "issue_url": result.get("web_url", ""),
            "issue_iid": result.get("iid", ""),
            "title": title,
        }
    return {"status": "failed", "error": "GitLab create_issue returned no result"}


def _feature_to_dict(feat) -> dict:
    return {
        "id": feat.id,
        "name": feat.name,
        "kill_commit_sha": feat.kill_commit_sha,
        "kill_commit_message": feat.kill_commit_message,
        "kill_date": feat.kill_date,
        "detection_method": feat.detection_method,
        "linked_mr_iid": feat.linked_mr_iid,
        "linked_issue_iids": feat.linked_issue_iids,
        "context_snippets": feat.context_snippets,
        "death_reason": feat.death_reason or {},
        "viability": feat.viability or {},
        "roi": feat.roi or {},
    }


# ── MCP Toolset builder ───────────────────────────────────────────────────────

def _build_gitlab_mcp_toolset():
    """
    Build ADK MCPToolset for @zereight/mcp-gitlab.

    Uses StdioConnectionParams (stdio transport) with PAT auth — no OAuth
    browser flow required, works server-side.

    On Linux/Cloud Run: spawns `npx --yes @zereight/mcp-gitlab` directly.
    On Windows localhost: same command via system Node (may fall back gracefully).

    The official GitLab MCP server at /api/v4/mcp uses OAuth 2.0 and is
    designed for interactive tools (Claude, Cursor, etc.) that can open a
    browser. For server-side programmatic access, @zereight/mcp-gitlab with
    PAT auth is the correct approach — same MCP protocol over stdio transport.
    """
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from mcp import StdioServerParameters

    token = os.environ.get("GITLAB_TOKEN", "")
    gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")

    if not token:
        logger.warning("[MCP] GITLAB_TOKEN not set — skipping MCPToolset")
        return None

    # Build env for the MCP subprocess
    mcp_env = {
        **os.environ,
        "GITLAB_PERSONAL_ACCESS_TOKEN": token,
        "GITLAB_TOKEN": token,
        "GITLAB_API_URL": gitlab_url.rstrip("/") + "/api/v4",
    }

    try:
        return MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=["--yes", "@zereight/mcp-gitlab"],
                    env=mcp_env,
                )
            ),
            # Expose the most useful GitLab tools to the agent
            tool_filter=[
                "create_issue",
                "list_issues",
                "get_issue",
                "list_commits",
                "get_commit",
                "list_merge_requests",
                "get_merge_request",
                "get_project",
                "list_branches",
                "search_code",
            ],
        )
    except Exception as exc:
        logger.warning("[MCP] Failed to build MCPToolset: %s — agent will use REST tools only", exc)
        return None


# ── Agent builder ─────────────────────────────────────────────────────────────

def _build_agent() -> Agent:
    tools = [
        FunctionTool(_scan_repository_tool),
        FunctionTool(_save_report_tool),
        FunctionTool(_create_revival_issue_tool),
    ]

    mcp_toolset = _build_gitlab_mcp_toolset()
    if mcp_toolset:
        tools.append(mcp_toolset)
        logger.info("[OK] GitLab MCPToolset added to agent (StdioConnectionParams)")
    else:
        logger.warning("[WARN] Agent running without MCPToolset — REST fallback active")

    return Agent(
        name="necro_code_necromancer",
        model="gemini-3-flash-preview",
        instruction=_SYSTEM_PROMPT,
        tools=tools,
    )


def get_runner() -> Runner:
    global _runner, _agent
    if _runner is None:
        _agent = _build_agent()
        _runner = Runner(
            agent=_agent,
            app_name="necro",
            session_service=InMemorySessionService(),
        )
        logger.info("[OK] NECRO ADK agent initialized (model: gemini-3-flash-preview)")
    return _runner
