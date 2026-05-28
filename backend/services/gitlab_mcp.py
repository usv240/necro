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

    async def list_commits(
        self,
        project_path: str,
        per_page: int = 100,
        page: int = 1,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        params: dict = {"per_page": per_page, "page": page}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return await self._get(
            f"/projects/{_encode(project_path)}/repository/commits",
            params=params,
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

    async def list_issue_notes(self, project_path: str, issue_iid: int) -> list[dict]:
        return await self._get(
            f"/projects/{_encode(project_path)}/issues/{issue_iid}/notes",
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
                           description: str = "", labels: list[str] | None = None,
                           assignee_ids: list[int] | None = None) -> Optional[dict]:
        """Create a GitLab issue via REST API. assignee_ids auto-assigns to engineers."""
        labels = labels or []
        assignee_ids = assignee_ids or []
        logger.info("[REST] create_issue → %s: %s", project_path, title)
        payload: dict = {"title": title, "description": description, "labels": ",".join(labels)}
        if assignee_ids:
            payload["assignee_ids"] = assignee_ids
        return await self._post(
            f"/projects/{_encode(project_path)}/issues",
            json=payload,
        )

    async def search_users(self, query: str, per_page: int = 5) -> list[dict]:
        """
        Search GitLab users by name, username, or email.
        Used to resolve a kill commit author to a GitLab user ID for auto-assignment.
        """
        logger.info("[MCP] search_users → %s", query)
        result = await self._get("/users", params={"search": query, "per_page": per_page})
        return result if isinstance(result, list) else []

    # Alias used in git_forensics.py
    async def list_mr_notes(self, project_path: str, mr_iid: int) -> list[dict]:
        return await self.list_merge_request_notes(project_path, mr_iid)

    async def get_project(self, project_path: str) -> Optional[dict]:
        """Fetch project metadata (incl. default_branch)."""
        result = await self._get(f"/projects/{_encode(project_path)}")
        return result if isinstance(result, dict) else None

    async def get_default_branch(self, project_path: str) -> str:
        """Return the project's default branch name."""
        proj = await self.get_project(project_path)
        if proj:
            return proj.get("default_branch") or "main"
        return "main"

    async def create_branch(self, project_path: str, branch_name: str,
                             ref: str = "main") -> Optional[dict]:
        """Create a new branch from ref."""
        logger.info("[REST] create_branch → %s: %s (from %s)", project_path, branch_name, ref)
        return await self._post(
            f"/projects/{_encode(project_path)}/repository/branches",
            json={"branch": branch_name, "ref": ref},
        )

    async def create_file(self, project_path: str, file_path: str, content: str,
                           branch: str, commit_message: str) -> Optional[dict]:
        """Create a file on a branch (base64-encoded)."""
        import base64
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        logger.info("[REST] create_file → %s: %s on %s", project_path, file_path, branch)
        return await self._post(
            f"/projects/{_encode(project_path)}/repository/files/{_encode(file_path)}",
            json={
                "branch": branch,
                "content": encoded,
                "encoding": "base64",
                "commit_message": commit_message,
            },
        )

    async def create_merge_request(self, project_path: str, title: str,
                                    description: str = "", source_branch: str = "",
                                    target_branch: str = "main", labels: list[str] | None = None,
                                    draft: bool = True) -> Optional[dict]:
        """Create a draft merge request."""
        labels = labels or []
        full_title = f"Draft: {title}" if draft else title
        logger.info("[REST] create_merge_request → %s: %s", project_path, full_title)
        return await self._post(
            f"/projects/{_encode(project_path)}/merge_requests",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": full_title,
                "description": description,
                "labels": ",".join(labels),
                "draft": draft,
            },
        )

    async def list_open_issues(self, project_path: str, per_page: int = 100) -> list[dict]:
        """Fetch open issues — used for demand signal matching against dead features."""
        return await self._get(
            f"/projects/{_encode(project_path)}/issues",
            params={"state": "opened", "per_page": per_page},
        )

    async def search_code(self, project_path: str, query: str, per_page: int = 20) -> list[dict]:
        """Search project issues for demand signals mentioning query (feature requests, bug reports)."""
        return await self._get(
            f"/projects/{_encode(project_path)}/search",
            params={"scope": "issues", "search": query, "per_page": per_page},
        )

    async def get_file(self, project_path: str, file_path: str, ref: str = "HEAD") -> Optional[dict]:
        """
        Fetch a single file from the repository at a given ref.
        Returns dict with 'content' (base64), 'size', 'encoding', 'last_commit_id'.
        Decodes content to plain text automatically.
        """
        logger.info("[MCP] get_file → %s:%s@%s", project_path, file_path, ref)
        result = await self._get(
            f"/projects/{_encode(project_path)}/repository/files/{_encode(file_path)}",
            params={"ref": ref},
        )
        if isinstance(result, dict) and result.get("encoding") == "base64" and result.get("content"):
            import base64
            try:
                result["decoded_content"] = base64.b64decode(result["content"]).decode("utf-8", errors="replace")
            except Exception:
                result["decoded_content"] = ""
        return result if isinstance(result, dict) else None

    async def get_commit_diff(self, project_path: str, sha: str) -> list[dict]:
        """
        Fetch the file diffs for a single commit.
        Returns list of diffs with 'old_path', 'new_path', 'diff' (unified diff text).
        """
        logger.info("[MCP] get_commit_diff → %s@%s", project_path, sha)
        result = await self._get(
            f"/projects/{_encode(project_path)}/repository/commits/{sha}/diff",
        )
        return result if isinstance(result, list) else []

    async def list_project_members(self, project_path: str, per_page: int = 50) -> list[dict]:
        """
        List project members with their access levels.
        Used to find the original author of a dead feature and auto-assign revival issues.
        """
        logger.info("[MCP] list_project_members → %s", project_path)
        return await self._get(
            f"/projects/{_encode(project_path)}/members/all",
            params={"per_page": per_page},
        )

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Look up a GitLab user by username — used to resolve commit author to member ID."""
        logger.info("[MCP] get_user → %s", username)
        result = await self._get("/users", params={"username": username})
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def list_pipelines(self, project_path: str, ref: str = "HEAD",
                              per_page: int = 5) -> list[dict]:
        """
        List recent CI pipelines for the project.
        Used to check whether the codebase is in a healthy state before recommending revival.
        Returns status: 'success' | 'failed' | 'running' | 'pending' | 'canceled'.
        Orders by updated_at descending (chronologically correct, not by arbitrary ID).
        """
        logger.info("[MCP] list_pipelines → %s (ref=%s)", project_path, ref)
        params: dict = {"per_page": per_page, "order_by": "updated_at", "sort": "desc"}
        if ref and ref != "HEAD":
            params["ref"] = ref
        result = await self._get(
            f"/projects/{_encode(project_path)}/pipelines",
            params=params,
        )
        # Filter out pipelines without a status — they can't be evaluated
        return [p for p in (result or []) if p.get("status") in
                ("success", "failed", "running", "pending", "canceled", "skipped")]

    async def list_projects_in_group(
        self, namespace: str, per_page: int = 50, page: int = 1
    ) -> list[dict]:
        """
        List all projects in a GitLab group/namespace.
        Used by Cross-Repository Group Scan to enumerate repos automatically.
        Returns list of {id, name, path_with_namespace, web_url, default_branch}.
        """
        encoded = urllib.parse.quote(namespace, safe="")
        logger.info("[MCP] list_projects_in_group → %s (page %d)", namespace, page)
        result = await self._get(
            f"/groups/{encoded}/projects",
            params={
                "per_page": per_page,
                "page": page,
                "include_subgroups": False,
                "archived": False,
                "order_by": "last_activity_at",
                "sort": "desc",
            },
        )
        return result if isinstance(result, list) else []

    async def get_mr_changes(self, project_path: str, mr_iid: int) -> list[dict]:
        """
        Get file-level changes (diffs) for a Merge Request.
        Used by the Feature Will Generator to understand what code is being removed.
        Returns list of {old_path, new_path, diff, new_file, deleted_file, renamed_file}.
        """
        logger.info("[MCP] get_mr_changes → %s !%d", project_path, mr_iid)
        result = await self._get(
            f"/projects/{_encode(project_path)}/merge_requests/{mr_iid}/changes",
        )
        if isinstance(result, dict):
            return result.get("changes", [])
        return []

    async def get_merge_request(self, project_path: str, mr_iid: int) -> Optional[dict]:
        """Fetch full MR details including description, labels, author, and state."""
        logger.info("[MCP] get_merge_request → %s !%d", project_path, mr_iid)
        result = await self._get(
            f"/projects/{_encode(project_path)}/merge_requests/{mr_iid}",
        )
        return result if isinstance(result, dict) else None

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
            logger.debug("GET %s skipped — no GITLAB_TOKEN", path)
            return []
        url = settings.GITLAB_URL.rstrip("/") + "/api/v4" + path
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url, headers=self._headers, params=params or {})
                if r.status_code == 200:
                    data = r.json()
                    # GitLab sometimes returns a single dict for detail endpoints
                    return data if data is not None else []
                if r.status_code == 401:
                    logger.warning("GET %s → 401 Unauthorized — check GITLAB_TOKEN", path)
                elif r.status_code == 403:
                    logger.warning("GET %s → 403 Forbidden — token lacks permission for this resource", path)
                elif r.status_code == 404:
                    logger.debug("GET %s → 404 Not Found (repo may not have this resource)", path)
                elif r.status_code == 429:
                    logger.warning("GET %s → 429 Rate Limited — slow down requests", path)
                else:
                    logger.debug("GET %s → %d", path, r.status_code)
        except httpx.TimeoutException:
            logger.warning("GET %s timed out after 30s", path)
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
                logger.warning("POST %s → %d: %s", path, r.status_code, r.text[:300])
                try:
                    body = r.json()
                except Exception:
                    body = {"message": r.text[:200]}
                body["_status_code"] = r.status_code
                return {"_error": True, **body}
        except Exception as exc:
            logger.warning("REST POST %s failed: %s", path, exc)
        return None


def _encode(path: str) -> str:
    return urllib.parse.quote(path, safe="")


# Singleton — started at FastAPI lifespan
mcp = GitLabClient()
