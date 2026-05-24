"""
GitLab REST client for NECRO backend routes.

The ADK agent uses ADK's MCPToolset (StdioConnectionParams → @zereight/mcp-gitlab)
for native GitLab MCP tool access. This module handles backend route calls
(revive endpoint, watch list scanning) via the GitLab REST API — the same
underlying API that the MCP server calls.

Transport summary:
  ADK agent tools  → MCPToolset → @zereight/mcp-gitlab (MCP stdio protocol + PAT)
  Backend routes   → This module → GitLab REST API v4 (PAT Bearer auth)
"""

import logging
import urllib.parse
from typing import Any, Optional

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class GitLabClient:
    """
    GitLab REST API v4 client for backend routes.
    All calls are authenticated with GITLAB_TOKEN (PAT).
    """

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.GITLAB_TOKEN}"}

    @property
    def available(self) -> bool:
        return bool(settings.GITLAB_TOKEN)

    # reported transport for health endpoint
    @property
    def _transport(self) -> str:
        return "rest"

    @property
    def tool_names(self) -> list[str]:
        return []

    async def list_commits(self, project_path: str, per_page: int = 100, page: int = 1) -> list[dict]:
        return await self._get(
            f"/projects/{_encode(project_path)}/repository/commits",
            params={"per_page": per_page, "page": page},
        )

    async def get_commit(self, project_path: str, sha: str) -> Optional[dict]:
        result = await self._get(f"/projects/{_encode(project_path)}/repository/commits/{sha}")
        return result if isinstance(result, dict) else None

    async def list_merge_requests(self, project_path: str, state: str = "merged",
                                   per_page: int = 50) -> list[dict]:
        return await self._get(
            f"/projects/{_encode(project_path)}/merge_requests",
            params={"state": state, "per_page": per_page},
        )

    async def list_merge_request_notes(self, project_path: str, mr_iid: int) -> list[dict]:
        return await self._get(
            f"/projects/{_encode(project_path)}/merge_requests/{mr_iid}/notes",
        )

    async def list_issues(self, project_path: str, state: str = "closed",
                          per_page: int = 50) -> list[dict]:
        return await self._get(
            f"/projects/{_encode(project_path)}/issues",
            params={"state": state, "per_page": per_page},
        )

    async def list_feature_flags(self, project_path: str, per_page: int = 100) -> list[dict]:
        """
        Fetch GitLab native Feature Flags (Deployments > Feature Flags).
        Returns flags that have active=False — confirmed disabled features,
        not guesses from commit messages.
        Requires Developer+ role for private repos; available on public repos.
        """
        return await self._get(
            f"/projects/{_encode(project_path)}/feature_flags",
            params={"per_page": per_page},
        )

    async def create_issue(self, project_path: str, title: str,
                           description: str = "", labels: list[str] | None = None) -> Optional[dict]:
        """Create a GitLab issue via REST API."""
        labels = labels or []
        logger.info("[REST] create_issue → %s: %s", project_path, title)
        return await self._post(
            f"/projects/{_encode(project_path)}/issues",
            json={"title": title, "description": description, "labels": ",".join(labels)},
        )

    # ── lifecycle stubs (no-ops — no subprocess to manage) ────────────────────

    async def start(self) -> None:
        if self.available:
            logger.info("[OK] GitLab REST client ready (token configured)")
        else:
            logger.warning("[WARN] GITLAB_TOKEN not set — GitLab integration disabled")

    async def stop(self) -> None:
        pass

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> Any:
        if not settings.GITLAB_TOKEN:
            return []
        url = settings.GITLAB_URL.rstrip("/") + "/api/v4" + path
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url, headers=self._headers, params=params or {})
                if r.status_code == 200:
                    return r.json()
                logger.debug("GET %s → %d", path, r.status_code)
        except Exception as exc:
            logger.debug("REST GET %s failed: %s", path, exc)
        return []

    async def _post(self, path: str, json: dict | None = None) -> Optional[dict]:
        if not settings.GITLAB_TOKEN:
            return None
        url = settings.GITLAB_URL.rstrip("/") + "/api/v4" + path
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, headers=self._headers, json=json or {})
                if r.status_code in (200, 201):
                    return r.json()
                logger.debug("POST %s → %d %s", path, r.status_code, r.text[:200])
        except Exception as exc:
            logger.debug("REST POST %s failed: %s", path, exc)
        return None


def _encode(path: str) -> str:
    return urllib.parse.quote(path, safe="")


# Singleton — started at FastAPI lifespan
mcp = GitLabClient()
