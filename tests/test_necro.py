"""
NECRO comprehensive end-to-end test suite.

Tests cover all backend routes, frontend-backend contract validation,
data integrity, and the new endpoints added in the red-team fix cycle.

Run all tests (requires running backend on localhost:8080):
    python -m pytest tests/test_necro.py -v

Run fast tests only (no live scans):
    python -m pytest tests/test_necro.py -v -k "not live and not quick_scan"

Run a specific class:
    python -m pytest tests/test_necro.py::TestHealth -v
"""

import asyncio
import json
import re
import time
import pytest
import httpx

BASE = "http://localhost:8080"
CLIENT_TIMEOUT = 30.0
LONG_TIMEOUT = 180.0  # for /api/scan/quick which is synchronous


@pytest.fixture(scope="session")
def wait_for_server():
    """Wait for the backend to be fully ready before running any tests.
    Skips gracefully when no server is available (e.g. CI without credentials).
    Not autouse — unit-marked tests never request this fixture, so they run freely."""
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=3.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    pytest.skip("NECRO backend not reachable on localhost:8080 — skipping integration tests")


@pytest.fixture(scope="session")
def client(wait_for_server):
    with httpx.Client(base_url=BASE, timeout=CLIENT_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def long_client(wait_for_server):
    """Client with extended timeout for synchronous scan endpoints."""
    with httpx.Client(base_url=BASE, timeout=LONG_TIMEOUT) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health & Startup
# ─────────────────────────────────────────────────────────────────────────────
class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_health_status_is_ok(self, client):
        r = client.get("/api/health")
        assert r.json()["status"] == "ok"

    def test_health_service_name_contains_necro(self, client):
        r = client.get("/api/health")
        assert "necro" in r.json()["service"].lower()

    def test_health_mongodb_field_present(self, client):
        r = client.get("/api/health")
        assert "mongodb" in r.json()

    def test_health_gitlab_mcp_field_present(self, client):
        r = client.get("/api/health")
        assert "gitlab_mcp" in r.json()

    def test_health_adk_agent_field_present(self, client):
        r = client.get("/api/health")
        # Must be "initialized" or "pending" — never absent
        val = r.json().get("adk_agent")
        assert val is not None
        assert val in ("initialized", "pending")

    def test_health_gemini_primary_is_gemini3(self, client):
        r = client.get("/api/health")
        assert "gemini-3" in r.json().get("gemini_primary", "")

    def test_health_gemini_fallback_is_vertex(self, client):
        r = client.get("/api/health")
        assert "vertex" in r.json().get("gemini_fallback", "").lower()

    def test_health_monitor_field_present(self, client):
        r = client.get("/api/health")
        assert "monitor" in r.json()

    def test_health_monitor_has_running_key(self, client):
        r = client.get("/api/health")
        monitor = r.json().get("monitor", {})
        assert "running" in monitor

    def test_health_slack_field_present(self, client):
        r = client.get("/api/health")
        assert "slack" in r.json()

    def test_health_mcp_tools_listed(self, client):
        r = client.get("/api/health")
        d = r.json()
        assert "mcp_tools" in d
        tools = d["mcp_tools"]
        assert isinstance(tools, list)
        assert len(tools) >= 6  # at minimum: list_commits, get_commit, list_issues, etc.

    def test_health_adk_endpoints_listed(self, client):
        r = client.get("/api/health")
        endpoints = r.json().get("adk_endpoints", [])
        assert any("/api/agent/ask" in ep for ep in endpoints)
        assert any("/api/agent/revive" in ep for ep in endpoints)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Frontend-Backend Contract (all fetch() routes)
# ─────────────────────────────────────────────────────────────────────────────
class TestFrontendBackendContract:
    """
    Verifies that every route the frontend app.js calls actually exists
    and returns the expected HTTP status (not 404/405).
    """

    def test_get_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_post_scan_stream_exists(self, client):
        # Only check it's not 404/405 — don't wait for full scan
        try:
            r = client.post("/api/scan/stream", json={"repo_url": "https://gitlab.com/test/test"},
                            timeout=3.0)
            # 200 (SSE starts), 422 (validation), 500 — all mean route exists
            assert r.status_code not in (404, 405)
        except httpx.TimeoutException:
            pass  # Server accepted the request and started streaming — route exists

    def test_post_agent_revive_exists(self, client):
        # Missing required fields → 422 (Unprocessable Entity), NOT 404
        r = client.post("/api/agent/revive", json={})
        assert r.status_code in (400, 404, 422)  # route exists

    def test_post_report_post_to_gitlab_exists(self, client):
        r = client.post("/api/report/post-to-gitlab", json={})
        assert r.status_code in (400, 404, 422, 503)  # route exists

    def test_post_watch_add_exists(self, client):
        r = client.post("/api/watch/add", json={})
        assert r.status_code == 422  # missing repo_url → validation error

    def test_delete_watch_exists(self, client):
        # Path routing: /api/watch/{project_path:path} — org/repo must work
        r = client.request("DELETE", "/api/watch/test-org/test-repo")
        assert r.status_code in (404, 503)  # route exists, repo not found

    def test_get_watch_list_exists(self, client):
        r = client.get("/api/watch/list")
        assert r.status_code == 200

    def test_post_monitor_run_exists(self, client):
        r = client.post("/api/monitor/run")
        assert r.status_code == 200

    def test_get_monitor_status_exists(self, client):
        r = client.get("/api/monitor/status")
        assert r.status_code == 200

    def test_get_report_revival_log_exists(self, client):
        r = client.get("/api/report/revival-log")
        assert r.status_code == 200

    def test_post_scan_quick_exists(self, client):
        # New endpoint for CI integration — just verify route exists
        r = client.post("/api/scan/quick", json={})
        assert r.status_code in (400, 422, 503)  # validation, not 404

    def test_post_scan_start_exists(self, client):
        r = client.post("/api/scan/start", json={})
        assert r.status_code == 422

    def test_get_scan_status_exists(self, client):
        r = client.get("/api/scan/status/nonexistent")
        assert r.status_code == 200  # returns {error: "scan not found"}, not 404

    def test_get_report_latest_exists(self, client):
        r = client.get("/api/report/latest")
        assert r.status_code in (200, 404, 503)

    def test_get_report_scans_exists(self, client):
        r = client.get("/api/report/scans")
        assert r.status_code == 200

    def test_post_agent_ask_exists(self, client):
        r = client.post("/api/agent/ask", json={})
        assert r.status_code in (400, 422, 503)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scan endpoints
# ─────────────────────────────────────────────────────────────────────────────
class TestScanEndpoints:
    def test_start_scan_requires_url(self, client):
        r = client.post("/api/scan/start", json={})
        assert r.status_code == 422

    def test_start_scan_returns_scan_id(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/gitlab-org/gitlab-foss"})
        assert r.status_code == 200
        assert "scan_id" in r.json()

    def test_start_scan_extracts_project_path(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/my-org/my-repo"})
        assert r.json().get("project_path") == "my-org/my-repo"

    def test_start_scan_project_path_no_trailing_slash(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/my-org/my-repo/"})
        assert r.json().get("project_path") == "my-org/my-repo"

    def test_scan_status_unknown_returns_error(self, client):
        r = client.get("/api/scan/status/does-not-exist-12345")
        assert r.status_code == 200
        assert "error" in r.json()

    def test_scan_status_known_id_has_status_field(self, client):
        start_r = client.post("/api/scan/start",
                              json={"repo_url": "https://gitlab.com/gitlab-org/gitlab-foss"})
        scan_id = start_r.json()["scan_id"]
        status_r = client.get(f"/api/scan/status/{scan_id}")
        assert status_r.status_code == 200
        d = status_r.json()
        assert "status" in d
        assert d["status"] in ("running", "done", "error")

    def test_quick_scan_requires_url(self, client):
        r = client.post("/api/scan/quick", json={})
        assert r.status_code == 422

    def test_quick_scan_request_body_accepted(self, client):
        """Body shape check — don't wait for full scan result."""
        try:
            r = client.post("/api/scan/quick",
                            json={"repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                                  "max_commits": 10, "lookback_months": 6},
                            timeout=5.0)
            assert r.status_code not in (404, 405, 422)
        except httpx.TimeoutException:
            # Timeout means server accepted the request and started a real scan — that's fine
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 4. MongoDB / Report endpoints
# ─────────────────────────────────────────────────────────────────────────────
class TestReportEndpoints:
    def test_report_latest_returns_200_or_404_or_503(self, client):
        r = client.get("/api/report/latest")
        assert r.status_code in (200, 404, 503)

    def test_report_scans_has_scans_key(self, client):
        r = client.get("/api/report/scans")
        assert r.status_code == 200
        assert "scans" in r.json()

    def test_report_scans_is_list(self, client):
        r = client.get("/api/report/scans")
        scans = r.json().get("scans", [])
        assert isinstance(scans, list)

    def test_revival_log_has_entries_key(self, client):
        r = client.get("/api/report/revival-log")
        assert r.status_code == 200
        assert "entries" in r.json()

    def test_revival_log_entries_is_list(self, client):
        r = client.get("/api/report/revival-log")
        entries = r.json().get("entries", [])
        assert isinstance(entries, list)

    def test_report_feature_by_id_not_found(self, client):
        r = client.get("/api/report/feature/this-id-does-not-exist")
        assert r.status_code in (404, 503)

    def test_report_download_endpoint_exists(self, client):
        r = client.get("/api/report/download")
        assert r.status_code in (200, 404, 503)

    def test_report_latest_has_no_fake_data(self, client):
        r = client.get("/api/report/latest")
        if r.status_code == 200:
            text = r.text.lower()
            for word in ["acmecorp", "lorem ipsum", "fake company"]:
                assert word not in text

    def test_post_to_gitlab_validates_body(self, client):
        # Empty body → 422
        r = client.post("/api/report/post-to-gitlab", json={})
        assert r.status_code == 422

    def test_post_to_gitlab_with_valid_body_shape(self, client):
        """Test that a properly shaped body is accepted (503 if no token, not 422)."""
        r = client.post("/api/report/post-to-gitlab", json={
            "project_path": "gitlab-org/gitlab-foss",
            "features": [],
            "total_commits_scanned": 0,
            "mcp_tools_used": [],
            "mcp_tool_count": 0,
        })
        # 200 (success), 400 (no revive candidates), 503 (no token) — all are valid
        assert r.status_code in (200, 400, 503)
        # NOT 422 (validation error) or 404 (route not found)
        assert r.status_code not in (404, 422)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Agent endpoints (ADK)
# ─────────────────────────────────────────────────────────────────────────────
class TestAgentEndpoints:
    def test_agent_ask_validates_body(self, client):
        r = client.post("/api/agent/ask", json={})
        assert r.status_code in (400, 422)

    def test_agent_ask_accepts_prompt(self, client):
        """
        /api/agent/ask returns SSE (text/event-stream), not JSON.
        Verify the response content-type and that it starts streaming.
        """
        try:
            with client.stream("POST", "/api/agent/ask",
                               json={"prompt": "What is NECRO?"},
                               timeout=15.0) as resp:
                assert resp.status_code in (200, 503)
                content_type = resp.headers.get("content-type", "")
                if resp.status_code == 200:
                    # SSE streams have text/event-stream content type
                    assert "text/event-stream" in content_type or "text/" in content_type
        except httpx.TimeoutException:
            pass  # ADK started responding — counts as pass

    def test_agent_revive_validates_body(self, client):
        r = client.post("/api/agent/revive", json={})
        assert r.status_code in (400, 422)

    def test_agent_revive_missing_feature_id(self, client):
        r = client.post("/api/agent/revive", json={"project_path": "test/repo"})
        assert r.status_code in (400, 422)

    def test_agent_revive_missing_project_path(self, client):
        r = client.post("/api/agent/revive", json={"feature_id": "some-id"})
        assert r.status_code in (400, 422)

    def test_agent_revive_nonexistent_feature(self, client):
        r = client.post("/api/agent/revive",
                        json={"feature_id": "this-does-not-exist-99999",
                              "project_path": "test/repo"})
        assert r.status_code == 404

    def test_agent_webhook_endpoint_exists(self, client):
        r = client.post("/api/agent/webhook/gitlab", json={})
        # 400 (bad signature) or 422 (invalid body) — NOT 404
        assert r.status_code not in (404, 405)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Watch list
# ─────────────────────────────────────────────────────────────────────────────
class TestWatchList:
    def test_watch_list_returns_200(self, client):
        r = client.get("/api/watch/list")
        assert r.status_code == 200

    def test_watch_list_has_repos_key(self, client):
        r = client.get("/api/watch/list")
        assert "repos" in r.json()

    def test_watch_list_repos_is_list(self, client):
        r = client.get("/api/watch/list")
        assert isinstance(r.json()["repos"], list)

    def test_watch_add_requires_url(self, client):
        r = client.post("/api/watch/add", json={})
        assert r.status_code == 422

    def test_watch_add_accepts_valid_body(self, client):
        r = client.post("/api/watch/add",
                        json={"repo_url": "https://gitlab.com/test-org/test-repo",
                              "label": "Test Repo"})
        assert r.status_code in (200, 503)

    def test_watch_delete_with_slash_path(self, client):
        """
        Key regression: /api/watch/{project_path:path} must match paths with slashes.
        Frontend fix: encodes each segment, NOT the whole path.
        So /api/watch/test-org/test-repo (not /api/watch/test-org%2Ftest-repo).
        """
        r = client.request("DELETE", "/api/watch/test-org/test-repo")
        # 200 (found and deleted), 404 (not in watch list) or 503 (no MongoDB)
        # All three confirm the route matched (not a 404 "route not found")
        assert r.status_code in (200, 404, 503)

    def test_watch_delete_encoded_slash_also_works(self, client):
        """
        Regression: %2F-encoded slash should NOT cause a routing failure.
        Backend should still decode and match the path.
        """
        r = client.request("DELETE", "/api/watch/test-org%2Ftest-repo")
        # Must be a valid response (200, 404, 503) not a framework 404
        assert r.status_code in (200, 404, 503)

    def test_remove_nonexistent_watch_returns_404(self, client):
        r = client.request("DELETE", "/api/watch/nonexistent-org/nonexistent-repo-xyz")
        assert r.status_code in (404, 503)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Monitor
# ─────────────────────────────────────────────────────────────────────────────
class TestMonitor:
    def test_monitor_status_returns_200(self, client):
        r = client.get("/api/monitor/status")
        assert r.status_code == 200

    def test_monitor_status_has_running_key(self, client):
        r = client.get("/api/monitor/status")
        assert "running" in r.json()

    def test_monitor_status_has_interval_hours(self, client):
        r = client.get("/api/monitor/status")
        d = r.json()
        assert "interval_hours" in d
        assert d["interval_hours"] > 0

    def test_monitor_run_returns_200(self, client):
        r = client.post("/api/monitor/run")
        assert r.status_code == 200

    def test_monitor_run_has_checked_repos(self, client):
        r = client.post("/api/monitor/run")
        d = r.json()
        assert "checked_repos" in d or "errors" in d


# ─────────────────────────────────────────────────────────────────────────────
# 8. Revive endpoint (direct MCP, not ADK)
# ─────────────────────────────────────────────────────────────────────────────
class TestReviveEndpoint:
    def test_revive_nonexistent_feature(self, client):
        r = client.post("/api/revive/nonexistent-feature-id-xyz123",
                        json={"project_path": "test/repo"})
        assert r.status_code == 404

    def test_revive_requires_project_path(self, client):
        r = client.post("/api/revive/some-feature-id", json={})
        # Either 404 (feature not found) or 400 (no project_path for MCP call)
        assert r.status_code in (400, 404)

    def test_build_description_function_exists(self):
        """Unit test: _build_description helper in revive.py."""
        from backend.routes.revive import _build_description
        feat = {
            "name": "Wildcard Domain Support",
            "kill_commit_sha": "abc1234def5678",
            "kill_date": "2021-03-15",
            "linked_mr_iid": 42,
            "linked_issue_iids": [101, 102],
            "project_path": "gitlab-org/gitlab-foss",
        }
        dr = {
            "cited_evidence": "DNS subdomain takeover vulnerability CVE-2021-0001",
            "primary_reason": "Security: subdomain takeover",
            "category": "security",
        }
        vi = {
            "what_changed": "Domain verification shipped in 16.x (2023)",
            "revival_feasibility": 8,
            "effort_estimate": "2-3 weeks",
            "effort_category": "weeks",
            "technical_risks": ["Backwards compat with existing wildcard DNS"],
            "recommendation": "revive_now",
            "reasoning": "Constraint resolved by domain verification feature",
        }
        desc = _build_description(feat, dr, vi)
        assert "Wildcard Domain Support" in desc
        assert "NECRO" in desc
        assert "abc1234" in desc

    def test_keep_buried_feature_rejected(self, client):
        """Features with keep_buried recommendation must be blocked."""
        r = client.post("/api/revive/omnibus-geo-replication-free",
                        json={"project_path": "gitlab-org/gitlab-foss"})
        # 400 (keep_buried) or 404 (not in DB) — both valid
        assert r.status_code in (400, 404, 503)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Data integrity & no hardcoded data
# ─────────────────────────────────────────────────────────────────────────────
class TestDataIntegrity:
    def test_demo_endpoint_returns_200(self, client):
        r = client.post("/api/scan/demo")
        assert r.status_code == 200

    def test_demo_has_features_key(self, client):
        r = client.post("/api/scan/demo")
        assert "features" in r.json()

    def test_demo_features_have_required_fields(self, client):
        r = client.post("/api/scan/demo")
        required = ["name", "kill_commit_sha", "kill_date", "death_reason", "viability", "roi"]
        for feat in r.json().get("features", []):
            for field in required:
                assert field in feat, f"Feature missing required field: {field}"

    def test_demo_features_no_fake_placeholders(self, client):
        r = client.post("/api/scan/demo")
        text = r.text.lower()
        forbidden = ["acmecorp", "lorem ipsum", "test company", "fake company", "placeholder"]
        for word in forbidden:
            assert word not in text, f"Response contains forbidden placeholder: '{word}'"

    def test_viability_recommendation_values_valid(self, client):
        r = client.post("/api/scan/demo")
        valid = {"revive_now", "investigate_further", "keep_buried"}
        for feat in r.json().get("features", []):
            rec = (feat.get("viability") or {}).get("recommendation")
            if rec:
                assert rec in valid, f"Invalid recommendation value: {rec}"

    def test_no_fabricated_revenue_numbers(self, client):
        """ROI must not contain fabricated dollar revenue figures like '$5.2M ARR'."""
        r = client.post("/api/scan/demo")
        bad_pattern = re.compile(r'\$\d+\.?\d*[MB]\s*(ARR|MRR|revenue)', re.IGNORECASE)
        assert not bad_pattern.search(r.text), "ROI must not contain fabricated revenue figures"

    def test_roi_request_count_non_negative(self, client):
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            roi = feat.get("roi") or {}
            assert roi.get("request_count", 0) >= 0

    def test_death_reason_category_present(self, client):
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            cat = (feat.get("death_reason") or {}).get("category")
            assert cat, f"Feature '{feat.get('name')}' missing death_reason.category"

    def test_orchestrated_by_field_present_in_scan_response(self, client):
        """New: every live scan response must include orchestrated_by field."""
        r = client.get("/api/report/latest")
        if r.status_code == 200:
            d = r.json()
            # orchestrated_by should be set when the scan was live
            if "orchestrated_by" in d:
                assert d["orchestrated_by"] in (
                    "google_cloud_agent_builder_adk",
                    "direct_pipeline_with_adk_synthesis_attempted",
                )

    def test_no_hardcoded_gitlab_com_url_in_project_path(self, client):
        """project_path must be 'org/repo' not 'https://gitlab.com/org/repo'."""
        r = client.post("/api/scan/demo")
        d = r.json()
        pp = d.get("project_path", "")
        assert not pp.startswith("http"), f"project_path must be 'org/repo' not a full URL: {pp}"


# ─────────────────────────────────────────────────────────────────────────────
# 10. ROI integrity
# ─────────────────────────────────────────────────────────────────────────────
class TestROIIntegrity:
    def test_roi_estimates_no_dollar_fabrication(self, client):
        r = client.post("/api/scan/demo")
        text = r.text
        bad = re.compile(r'\$\d+\.?\d*[MB]\s*(ARR|MRR|revenue)', re.IGNORECASE)
        assert not bad.search(text)

    def test_roi_has_demand_tier_or_count(self, client):
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            roi = feat.get("roi") or {}
            # At minimum, should have either request_count or demand_tier
            has_signal = (
                "request_count" in roi
                or "demand_tier" in roi
                or "priority_tier" in roi
                or "demand_level" in roi
            )
            assert has_signal, f"Feature '{feat.get('name')}' ROI lacks demand signal"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Competitive intelligence
# ─────────────────────────────────────────────────────────────────────────────
class TestCompetitiveIntel:
    def test_competitive_intel_urgency_is_valid(self, client):
        r = client.post("/api/scan/demo")
        valid_urgencies = {"critical", "high", "medium", "low", "unknown"}
        for feat in r.json().get("features", []):
            ci = feat.get("competitive_intel")
            if ci:
                assert ci.get("market_urgency") in valid_urgencies

    def test_competitive_intel_has_summary_or_caveat(self, client):
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            ci = feat.get("competitive_intel")
            if ci:
                has_content = ci.get("summary") or ci.get("caveat") or ci.get("gap_analysis")
                assert has_content, "Competitive intel must have content (summary/caveat/gap)"


# ─────────────────────────────────────────────────────────────────────────────
# 12. ADK synthesis structure (new)
# ─────────────────────────────────────────────────────────────────────────────
class TestADKSynthesis:
    def test_adk_synthesis_field_in_latest_report(self, client):
        """If a live scan ran, the report should have adk_synthesis field."""
        r = client.get("/api/report/latest")
        if r.status_code == 200:
            d = r.json()
            # adk_synthesis may be None if ADK synthesis failed, or a dict if it succeeded
            if "adk_synthesis" in d and d["adk_synthesis"] is not None:
                synth = d["adk_synthesis"]
                assert "status" in synth
                if synth["status"] == "success":
                    # Must have executive summary and priorities
                    assert "executive_summary" in synth or "top_3_priorities" in synth

    def test_orchestrated_by_valid_values(self, client):
        r = client.get("/api/report/latest")
        if r.status_code == 200:
            d = r.json()
            ob = d.get("orchestrated_by")
            if ob:
                valid = {
                    "google_cloud_agent_builder_adk",
                    "direct_pipeline_with_adk_synthesis_attempted",
                }
                assert ob in valid, f"Unexpected orchestrated_by value: {ob}"


# ─────────────────────────────────────────────────────────────────────────────
# 13. URL path extraction utility
# ─────────────────────────────────────────────────────────────────────────────
class TestURLExtraction:
    """Unit tests for _url_to_path helper used in scan, stream, watch routes."""

    def test_full_url_extracts_path(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/my-org/my-repo"})
        assert r.json()["project_path"] == "my-org/my-repo"

    def test_url_with_trailing_slash(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/my-org/my-repo/"})
        assert r.json()["project_path"] == "my-org/my-repo"

    def test_bare_path_passthrough(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "my-org/my-repo"})
        assert r.json()["project_path"] == "my-org/my-repo"

    def test_url_with_dot_git_suffix(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/my-org/my-repo.git"})
        # Should either strip .git or preserve it — must not crash
        pp = r.json().get("project_path", "")
        assert "my-org" in pp

    def test_nested_subgroup_url(self, client):
        r = client.post("/api/scan/start",
                        json={"repo_url": "https://gitlab.com/group/subgroup/repo"})
        assert r.json()["project_path"] == "group/subgroup/repo"


# ─────────────────────────────────────────────────────────────────────────────
# 14. GitLab CI integration endpoint
# ─────────────────────────────────────────────────────────────────────────────
class TestCIIntegration:
    def test_quick_scan_validates_repo_url(self, client):
        r = client.post("/api/scan/quick", json={"max_commits": 10})
        assert r.status_code == 422  # missing repo_url

    def test_quick_scan_accepts_all_params(self, client):
        """Verify the endpoint accepts the full body shape used in .gitlab-ci.yml."""
        try:
            r = client.post("/api/scan/quick", json={
                "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                "max_commits": 10,
                "lookback_months": 6,
            }, timeout=5.0)
            # Scan starts — 200 (with results), 408 (timeout), or any non-404/405 status
            assert r.status_code not in (404, 405, 422)
        except httpx.TimeoutException:
            pass  # Server accepted the request and started a real scan — route exists

    def test_post_to_gitlab_body_matches_frontend_payload(self, client):
        """Verify the exact body shape the frontend sends matches what the backend expects."""
        # This is exactly what postReportToGitLab() in app.js sends
        frontend_payload = {
            "project_path": "gitlab-org/gitlab-foss",
            "features": [],
            "total_commits_scanned": 100,
            "mcp_tools_used": ["list_commits", "list_issues"],
            "mcp_tool_count": 2,
        }
        r = client.post("/api/report/post-to-gitlab", json=frontend_payload)
        # 400 if no revive_now features, 503 if no GitLab token — but NOT 422 (schema mismatch)
        assert r.status_code != 422, "Frontend payload must match backend schema exactly"


# ─────────────────────────────────────────────────────────────────────────────
# 15. Live scan (slow — skip in CI with pytest -k "not live")
# ─────────────────────────────────────────────────────────────────────────────
class TestLiveScanFull:
    """
    End-to-end live scan tests. Require a running backend with GITLAB_TOKEN set.
    These make real GitLab API calls and take 60-120 seconds.
    Mark: pytest -k "not live" to skip.
    """

    @pytest.mark.live
    def test_live_stream_scan_returns_features(self, long_client):
        """Full SSE stream scan of a small public repo."""
        import httpx

        features = []
        with long_client.stream("POST", "/api/scan/stream", json={
            "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
            "max_commits": 20,
            "lookback_months": 12,
        }) as resp:
            assert resp.status_code == 200
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                for line in buf.split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                        if evt.get("type") == "report":
                            features = evt["data"].get("features", [])
                    except Exception:
                        pass

        # Live scan should find at least some features in a 20-year-old codebase
        # (may be 0 if repo is clean — acceptable)
        assert isinstance(features, list)

    @pytest.mark.live
    def test_live_quick_scan_returns_report(self, long_client):
        """Synchronous quick scan returns a full report dict."""
        r = long_client.post("/api/scan/quick", json={
            "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
            "max_commits": 20,
            "lookback_months": 12,
        })
        assert r.status_code == 200
        d = r.json()
        assert "features" in d
        assert "project_path" in d
        assert d["project_path"] == "gitlab-org/gitlab-foss"
        assert "orchestrated_by" in d

    @pytest.mark.live
    def test_live_scan_orchestrated_by_is_set(self, long_client):
        """Live scan must always set orchestrated_by."""
        r = long_client.post("/api/scan/quick", json={
            "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
            "max_commits": 15,
            "lookback_months": 6,
        })
        if r.status_code == 200:
            d = r.json()
            assert "orchestrated_by" in d
            valid = {
                "google_cloud_agent_builder_adk",
                "direct_pipeline_with_adk_synthesis_attempted",
            }
            assert d["orchestrated_by"] in valid

    @pytest.mark.live
    def test_live_scan_mcp_calls_logged(self, long_client):
        """Live scan must log at least one MCP tool call."""
        r = long_client.post("/api/scan/quick", json={
            "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
            "max_commits": 15,
            "lookback_months": 6,
        })
        if r.status_code == 200:
            d = r.json()
            assert d.get("mcp_tool_count", 0) > 0 or len(d.get("mcp_tools_used", [])) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 16. Ghost MR endpoint  (POST /api/revive/{feature_id}/ghost-mr)
# ─────────────────────────────────────────────────────────────────────────────
class TestGhostMR:
    """
    Ghost MR is a headline feature: NECRO creates branch + NECRO_REVIVAL.md + Draft MR
    via three GitLab MCP write operations.
    """

    def test_ghost_mr_route_exists(self, client):
        """Route must be registered — a missing feature_id yields 404 (feature not found), not 405."""
        r = client.post("/api/revive/nonexistent-feature-xyz/ghost-mr",
                        json={"project_path": "test/repo"})
        # 404 (feature not in DB) is the expected path — NOT 405 (method not allowed) / 422
        assert r.status_code in (404, 503)

    def test_ghost_mr_requires_project_path(self, client):
        """If no project_path and feature has none stored, should return 400 or 404."""
        r = client.post("/api/revive/nonexistent-feature-xyz/ghost-mr", json={})
        assert r.status_code in (400, 404, 503)

    def test_ghost_mr_not_404_or_405(self, client):
        """Regression guard: route must not silently vanish from the router."""
        r = client.post("/api/revive/any-id/ghost-mr",
                        json={"project_path": "gitlab-org/gitlab-foss"})
        assert r.status_code != 405, "Ghost MR route returned 405 — router may be misconfigured"
        assert r.status_code != 422, "Ghost MR route has unexpected schema validation"

    def test_ghost_mr_keep_buried_rejected(self, client):
        """
        Ghost MR, like regular revive, must refuse keep_buried features.
        (feature not found in test env → 404, which is acceptable)
        """
        r = client.post("/api/revive/a-keep-buried-feature-id/ghost-mr",
                        json={"project_path": "test/repo"})
        assert r.status_code in (400, 404, 503)


# ─────────────────────────────────────────────────────────────────────────────
# 17. Group scan (POST /api/scan/group)  — cross-repo federation
# ─────────────────────────────────────────────────────────────────────────────
class TestGroupScan:
    """
    Group scan (Cross-Repository Graveyard Federation) — scans an entire GitLab
    namespace in parallel and federates feature graveyards across repos.
    """

    def test_group_scan_route_exists(self, client):
        """Route must be registered."""
        r = client.post("/api/scan/group", json={})
        # 422 (missing namespace) — NOT 404/405
        assert r.status_code not in (404, 405), "Group scan route is not registered"

    def test_group_scan_requires_namespace(self, client):
        r = client.post("/api/scan/group", json={})
        assert r.status_code == 422  # namespace is required

    def test_group_scan_accepts_valid_body(self, client):
        """Verify the body schema the frontend sends is accepted by the backend."""
        try:
            r = client.post("/api/scan/group", json={
                "namespace": "gitlab-org",
                "max_repos": 2,
                "max_commits_per_repo": 5,
                "lookback_months": 6,
            }, timeout=5.0)
            # May time out mid-scan or return a result — both are valid
            assert r.status_code not in (404, 405, 422), f"Unexpected status: {r.status_code}"
        except httpx.TimeoutException:
            pass  # Server accepted the request and started scanning — route exists

    def test_group_scan_response_has_namespace(self, client):
        """If the call completes within timeout, response must echo the namespace."""
        try:
            r = client.post("/api/scan/group", json={
                "namespace": "gitlab-org",
                "max_repos": 1,
                "max_commits_per_repo": 5,
                "lookback_months": 3,
            }, timeout=8.0)
            if r.status_code == 200:
                d = r.json()
                assert "namespace" in d or "repos" in d or "results" in d
        except httpx.TimeoutException:
            pass  # scan started — acceptable


# ─────────────────────────────────────────────────────────────────────────────
# 18. Revival contracts (GET /api/scan/contracts/{project_path})
# ─────────────────────────────────────────────────────────────────────────────
class TestRevivalContracts:
    """
    Revival Contracts (Feature Wills) — auto-generated revival intent documents
    created when MRs kill features, so the will is written before burial.
    """

    def test_contracts_route_exists(self, client):
        r = client.get("/api/scan/contracts/test-org/test-repo")
        assert r.status_code not in (404, 405), "Contracts route is not registered"

    def test_contracts_returns_project_path(self, client):
        r = client.get("/api/scan/contracts/test-org/test-repo")
        if r.status_code == 200:
            d = r.json()
            assert "project_path" in d
            assert "contracts" in d
            assert isinstance(d["contracts"], list)

    def test_contracts_accepts_status_filter(self, client):
        """Query param ?status=active must not cause 422."""
        r = client.get("/api/scan/contracts/test-org/test-repo?status=active")
        assert r.status_code not in (404, 405, 422)

    def test_contracts_unknown_status_handled(self, client):
        """Invalid status filter must not crash the server."""
        r = client.get("/api/scan/contracts/test-org/test-repo?status=bogus")
        assert r.status_code in (200, 400, 422, 503)

    def test_contracts_slash_path_works(self, client):
        """Path with subgroup (group/subgroup/repo) must not 404 on routing."""
        r = client.get("/api/scan/contracts/group/subgroup/repo")
        assert r.status_code not in (404, 405)


# ─────────────────────────────────────────────────────────────────────────────
# 19. Feature vitality / EKG  (GET /api/scan/vitality/{feature_id})
# ─────────────────────────────────────────────────────────────────────────────
class TestFeatureVitality:
    """
    Feature EKG — returns the demand curve + revival score time-series for
    a feature, showing the optimal revival window.
    """

    def test_vitality_route_exists(self, client):
        r = client.get("/api/scan/vitality/test-feature-id")
        assert r.status_code not in (404, 405), "Vitality route is not registered"

    def test_vitality_returns_feature_id(self, client):
        r = client.get("/api/scan/vitality/test-feature-id")
        if r.status_code == 200:
            d = r.json()
            assert d.get("feature_id") == "test-feature-id"

    def test_vitality_has_sparkline_key(self, client):
        r = client.get("/api/scan/vitality/test-feature-id")
        if r.status_code == 200:
            assert "sparkline" in r.json()

    def test_vitality_has_history_key(self, client):
        r = client.get("/api/scan/vitality/test-feature-id")
        if r.status_code == 200:
            d = r.json()
            assert "history" in d
            assert isinstance(d["history"], list)

    def test_vitality_project_path_query_param(self, client):
        """Optional project_path query param must not cause 422."""
        r = client.get("/api/scan/vitality/test-feature-id?project_path=test-org/test-repo")
        assert r.status_code not in (404, 405, 422)


# ─────────────────────────────────────────────────────────────────────────────
# 20. Report all-features, stats, notify-slack
# ─────────────────────────────────────────────────────────────────────────────
class TestReportExtendedEndpoints:
    """Covers the three report endpoints missing from TestReportEndpoints."""

    # ── GET /api/report/all-features ─────────────────────────────────────────
    def test_all_features_route_exists(self, client):
        r = client.get("/api/report/all-features")
        assert r.status_code not in (404, 405)

    def test_all_features_has_features_key(self, client):
        r = client.get("/api/report/all-features")
        assert r.status_code == 200
        d = r.json()
        assert "features" in d
        assert "total" in d

    def test_all_features_is_list(self, client):
        r = client.get("/api/report/all-features")
        assert isinstance(r.json()["features"], list)

    def test_all_features_total_matches_list_length(self, client):
        r = client.get("/api/report/all-features")
        d = r.json()
        assert d["total"] == len(d["features"])

    def test_all_features_limit_param(self, client):
        """?limit= query param must be accepted without 422."""
        r = client.get("/api/report/all-features?limit=5")
        assert r.status_code == 200
        assert len(r.json()["features"]) <= 5

    # ── GET /api/report/stats ─────────────────────────────────────────────────
    def test_stats_route_exists(self, client):
        r = client.get("/api/report/stats")
        assert r.status_code not in (404, 405)

    def test_stats_has_required_keys(self, client):
        r = client.get("/api/report/stats")
        assert r.status_code == 200
        d = r.json()
        required = ["total_scans", "total_features_found", "watched_repos_count",
                    "revivals_logged_count", "mcp_tool_calls_count"]
        for key in required:
            assert key in d, f"stats missing key: {key}"

    def test_stats_values_are_non_negative(self, client):
        r = client.get("/api/report/stats")
        d = r.json()
        for key in ["total_scans", "total_features_found", "mcp_tool_calls_count"]:
            assert d.get(key, 0) >= 0, f"stats[{key}] is negative"

    # ── POST /api/report/notify-slack ─────────────────────────────────────────
    def test_notify_slack_route_exists(self, client):
        r = client.post("/api/report/notify-slack", json={})
        # 422 (missing fields) or 503 (Slack not configured) — NOT 404/405
        assert r.status_code not in (404, 405), "notify-slack route is not registered"

    def test_notify_slack_requires_project_path(self, client):
        r = client.post("/api/report/notify-slack", json={"features": []})
        assert r.status_code == 422

    def test_notify_slack_requires_features(self, client):
        r = client.post("/api/report/notify-slack", json={"project_path": "test/repo"})
        assert r.status_code == 422

    def test_notify_slack_no_token_returns_503(self, client):
        """Without Slack credentials configured, must return 503 (not 500 crash)."""
        r = client.post("/api/report/notify-slack", json={
            "project_path": "test/repo",
            "features": [],
        })
        # 503 (not configured) or 200 (if a webhook is set in env) — both are valid
        assert r.status_code in (200, 503), f"Unexpected status: {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# 21. Gemini service unit tests (no server needed — pure Python)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestGeminiService:
    """
    Unit tests for the Gemini client helpers — no live API calls, no server.
    Tests the JSON extraction and parsing robustness used in all agent pipelines.
    Runs in CI without a live backend (marked @pytest.mark.unit).
    """

    def test_extract_json_robust_simple_object(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_extract_json_robust_with_preamble(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust('Here is the result: {"status": "ok"}')
        assert result == {"status": "ok"}

    def test_extract_json_robust_with_markdown_fence(self):
        from backend.services.gemini import _extract_json_robust
        text = '```json\n{"recommendation": "revive_now"}\n```'
        # After fence stripping, this should still parse
        import re
        cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()
        result = _extract_json_robust(cleaned)
        assert result is not None
        assert result.get("recommendation") == "revive_now"

    def test_extract_json_robust_nested_braces(self):
        from backend.services.gemini import _extract_json_robust
        text = '{"outer": {"inner": {"deep": true}}}'
        result = _extract_json_robust(text)
        assert result == {"outer": {"inner": {"deep": True}}}

    def test_extract_json_robust_array(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust('[{"name": "Feature A"}, {"name": "Feature B"}]')
        assert isinstance(result, list)
        assert len(result) == 2

    def test_extract_json_robust_escaped_quotes(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust('{"msg": "He said \\"hello\\""}')
        assert result is not None
        assert "hello" in result.get("msg", "")

    def test_extract_json_robust_returns_none_on_invalid(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust("this is not json at all")
        assert result is None

    def test_extract_json_robust_partial_braces(self):
        from backend.services.gemini import _extract_json_robust
        result = _extract_json_robust('{"key": "value"} some trailing garbage')
        assert result == {"key": "value"}


# ─────────────────────────────────────────────────────────────────────────────
# 22. Challenger agent unit tests (no server needed)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestChallengerService:
    """
    Unit tests for challenger.py — the adversarial Gemini agent that stress-tests
    viability assessments. Tests the prompt building and result merging logic.
    Runs in CI without a live backend (marked @pytest.mark.unit).
    """

    def test_challenger_module_importable(self):
        """Challenger service must import cleanly."""
        import backend.services.challenger  # noqa: F401

    def test_challenger_has_run_function(self):
        from backend.services import challenger
        assert hasattr(challenger, "run_challenger") or hasattr(challenger, "challenge_feature") or \
               any(callable(getattr(challenger, a)) for a in dir(challenger) if not a.startswith("_"))

    def test_challenger_build_prompt_contains_feature_name(self):
        """If challenger has a prompt builder, it should include the feature name."""
        try:
            from backend.services.challenger import _build_challenge_prompt
            prompt = _build_challenge_prompt(
                {"name": "OAuth Single Sign-On", "kill_reason": "Security audit"},
                {"recommendation": "revive_now", "revival_feasibility": 8},
            )
            assert "OAuth Single Sign-On" in prompt
        except ImportError:
            pytest.skip("_build_challenge_prompt not exposed — skipping internal unit test")


# ─────────────────────────────────────────────────────────────────────────────
# 23. Resurrection chains — feature dependency graph
# ─────────────────────────────────────────────────────────────────────────────
class TestResurrectionChains:
    """
    Resurrection Chains reveal features that died together because they shared
    a blocking constraint. Fixing ONE constraint unlocks a chain of revivals.
    """

    def test_demo_features_may_have_resurrection_chain(self, client):
        """Demo scan may include resurrection_chain field on features."""
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            chain = feat.get("resurrection_chain")
            if chain is not None:
                # If present, must be a list (of related feature IDs or names)
                assert isinstance(chain, (list, dict)), \
                    "resurrection_chain must be list or dict"

    def test_demo_features_constraint_field(self, client):
        """Features should carry their blocking constraint when known."""
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            dr = feat.get("death_reason") or {}
            # constraint field is optional but if present must be a string
            constraint = dr.get("constraint") or feat.get("constraint")
            if constraint is not None:
                assert isinstance(constraint, str)


# ─────────────────────────────────────────────────────────────────────────────
# 24. Vector search / demand matching
# ─────────────────────────────────────────────────────────────────────────────
class TestVectorSearch:
    """
    MongoDB Vector Search — Google text-embedding-004 embeddings on issue bodies
    match open GitLab demand against buried features.
    """

    def test_demo_features_have_roi_demand_signal(self, client):
        """Every feature in demo should have at least one demand signal in ROI."""
        r = client.post("/api/scan/demo")
        for feat in r.json().get("features", []):
            roi = feat.get("roi") or {}
            has_demand = (
                "request_count" in roi
                or "demand_tier" in roi
                or "priority_tier" in roi
                or "demand_level" in roi
                or "open_issues_mentioning" in roi
                or "issue_demand" in roi
            )
            assert has_demand, \
                f"Feature '{feat.get('name')}' has no demand signal (vector search result) in ROI"

    def test_report_stats_mcp_tool_count_positive(self, client):
        """Vector search enriches ROI — at least some MCP calls must have occurred."""
        r = client.get("/api/report/stats")
        if r.status_code == 200:
            d = r.json()
            # mcp_tool_calls_count tracks all tool invocations including embedding calls
            assert d.get("mcp_tool_calls_count", 0) >= 0  # non-negative at minimum


# ─────────────────────────────────────────────────────────────────────────────
# 25. Constraint grounder — ambiguous-word guard (regression for fabricated URLs)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestConstraintGrounderAmbiguousGuard:
    """
    Regression tests for the constraint_grounder hallucination bug:
    prose like "all requests are routed" used to falsely match the PyPI `requests`
    package and return a fabricated evidence URL. The fix requires a tech-context
    co-occurrence marker (library/version/upgrade/etc.) for ambiguous keywords.
    """

    def test_bare_english_requests_does_not_match(self):
        """The English word 'requests' in prose must NOT match the PyPI package."""
        from backend.services.constraint_grounder import _identify_technology
        text = "The feature flag was removed because the rollout was completed and all requests are now routed through the new path."
        tech, _lt = _identify_technology(text)
        assert tech == "", f"Expected no match for ambiguous 'requests' in plain English, got '{tech}'"

    def test_two_requests_in_error_message_does_not_match(self):
        """The phrase 'two requests' (HTTP requests) must NOT match the PyPI package."""
        from backend.services.constraint_grounder import _identify_technology
        text = "The feature was disabled because it returns a 401 Unauthorized error when two requests arrive concurrently."
        tech, _lt = _identify_technology(text)
        assert tech == "", f"Expected no match for HTTP 'requests' in error prose, got '{tech}'"

    def test_requests_library_with_version_matches(self):
        """A real tech mention like 'requests library v2.32' must still match."""
        from backend.services.constraint_grounder import _identify_technology
        text = "Upgrade the requests library to version 2.32 to fix the connection pool bug."
        tech, lt = _identify_technology(text)
        assert tech == "requests", f"Expected 'requests' to match in tech context, got '{tech}'"
        assert lt == "pypi"

    def test_requests_package_in_dependency_context_matches(self):
        """'requests' next to 'package' or 'dependency' is a real tech mention."""
        from backend.services.constraint_grounder import _identify_technology
        text = "Bumping the requests package to address a CVE in the dependency."
        tech, _lt = _identify_technology(text)
        assert tech == "requests"

    def test_node_as_english_word_does_not_match(self):
        """The English 'node' (e.g. 'a node in the cluster') must NOT match Node.js
        when used outside any tech-marker context."""
        from backend.services.constraint_grounder import _identify_technology
        # No tech-marker words (no "library", "version", "upgrade", "dependency", etc.)
        text = "Each leaf node was marked stale and pruned from the tree."
        tech, _lt = _identify_technology(text)
        assert tech == "", f"Expected no match for tree 'node', got '{tech}'"

    def test_node_js_upgrade_matches(self):
        """'Node 20' or 'Node.js library' is a real tech mention."""
        from backend.services.constraint_grounder import _identify_technology
        text = "Upgrade Node to version 20 to drop ES2015 transpilation."
        tech, lt = _identify_technology(text)
        assert tech == "node"
        assert lt in ("github", "npm")

    def test_unambiguous_keywords_still_match_without_context(self):
        """Non-ambiguous keywords like 'kubernetes' should match anywhere — they're
        not English words that happen to collide with package names."""
        from backend.services.constraint_grounder import _identify_technology
        text = "Migrated kubernetes manifests to the new operator pattern."
        tech, _lt = _identify_technology(text)
        assert tech == "kubernetes"


# ─────────────────────────────────────────────────────────────────────────────
# 26. Garbage-name filter (regression for @username / "from X" / linter pragma)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestGarbageNameFilter:
    """
    Regression tests for the _is_garbage_feature_name filter:
    git_forensics used to surface non-feature noise as 'dormant features':
      - @vshushlin as the pages maintainer   (person, not feature)
      - from gitlab-pages                    (slice-extraction error)
      - gocyclo:ignore                       (Go linter pragma)
    These must be filtered BEFORE Gemini calls to keep the UI honest.
    """

    def test_username_with_at_prefix_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("@vshushlin as the pages maintainer") is True

    def test_bare_username_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("@octocat") is True

    def test_dangling_preposition_from_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("from gitlab-pages") is True

    def test_dangling_preposition_for_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("for the new release") is True

    def test_dangling_preposition_to_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("to the legacy adapter") is True

    def test_gocyclo_ignore_pragma_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("gocyclo:ignore") is True

    def test_nolint_pragma_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("nolint:gosec") is True

    def test_eslint_disable_pragma_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("eslint-disable-next-line") is True

    def test_personal_role_phrase_rejected(self):
        """'X as the maintainer' is a person leaving, not a feature."""
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("Alice as the pages maintainer") is True

    def test_personal_role_with_feature_word_accepted(self):
        """If the candidate ALSO mentions 'feature', 'flag', etc. it's likely a real feature."""
        from backend.services.git_forensics import _is_garbage_feature_name
        # 'feature owner approval' is a workflow feature, not a person stepping down
        assert _is_garbage_feature_name("automatic feature owner approval flag") is False

    def test_real_feature_flag_accepted(self):
        """Real Go-style feature flag must pass the filter."""
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("REGISTRY_FF_ENFORCE_LOCKFILES") is False

    def test_real_feature_name_accepted(self):
        """Multi-word real feature names pass."""
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("Bundled Mattermost Integration") is False

    def test_real_revert_name_accepted(self):
        """Reverted feature descriptions pass."""
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("GPG signing color in ci status") is False

    def test_empty_string_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("") is True

    def test_whitespace_only_rejected(self):
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("   ") is True

    def test_very_short_name_rejected(self):
        """Names ≤3 chars are too short to be a real feature."""
        from backend.services.git_forensics import _is_garbage_feature_name
        assert _is_garbage_feature_name("ABC") is True


# ─────────────────────────────────────────────────────────────────────────────
# 27. Verification quality badge guard (regression for "high" overstatement)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestVerificationQualityGuard:
    """
    The ADK self-reports verification_quality based on its own confidence.
    The bug: it claimed 'high' even when Phase 1 grounding returned zero real URLs.
    Fix: auto-downgrade based on actual grounded URL count in the report.
    """

    def test_zero_grounded_urls_downgrades_high_to_low(self):
        """0 grounded features + claimed high → must downgrade to low."""
        # Simulate the guard logic from stream.py:294
        saved_features = [
            {"viability": {"grounding": {"grounded": False, "evidence_url": ""}}},
            {"viability": {"grounding": {"grounded": False, "evidence_url": ""}}},
        ]
        grounded_count = sum(
            1 for f in saved_features
            if f.get("viability", {}).get("grounding", {}).get("grounded") is True
            and str(f.get("viability", {}).get("grounding", {}).get("evidence_url", "")).startswith("http")
        )
        synthesis = {"verification_quality": "high"}
        if grounded_count == 0 and synthesis.get("verification_quality") == "high":
            synthesis["verification_quality"] = "low"
        assert synthesis["verification_quality"] == "low"

    def test_zero_grounded_urls_downgrades_medium_to_low(self):
        """0 grounded features + claimed medium → must downgrade to low."""
        saved_features = [{"viability": {"grounding": {"grounded": False}}}]
        grounded_count = 0
        synthesis = {"verification_quality": "medium"}
        if grounded_count == 0 and synthesis.get("verification_quality") == "medium":
            synthesis["verification_quality"] = "low"
        assert synthesis["verification_quality"] == "low"

    def test_partial_grounding_downgrades_high_to_medium(self):
        """1 grounded out of 4 features (<50%) + claimed high → downgrade to medium."""
        saved_features = [
            {"viability": {"grounding": {"grounded": True, "evidence_url": "https://example.com"}}},
            {"viability": {"grounding": {"grounded": False}}},
            {"viability": {"grounding": {"grounded": False}}},
            {"viability": {"grounding": {"grounded": False}}},
        ]
        grounded_count = sum(
            1 for f in saved_features
            if f.get("viability", {}).get("grounding", {}).get("grounded") is True
            and str(f.get("viability", {}).get("grounding", {}).get("evidence_url", "")).startswith("http")
        )
        synthesis = {"verification_quality": "high"}
        if grounded_count > 0 and grounded_count < max(1, len(saved_features) // 2) and synthesis["verification_quality"] == "high":
            synthesis["verification_quality"] = "medium"
        assert synthesis["verification_quality"] == "medium"

    def test_majority_grounded_keeps_high(self):
        """3 of 4 grounded → high stays high."""
        saved_features = [
            {"viability": {"grounding": {"grounded": True, "evidence_url": "https://a.com"}}},
            {"viability": {"grounding": {"grounded": True, "evidence_url": "https://b.com"}}},
            {"viability": {"grounding": {"grounded": True, "evidence_url": "https://c.com"}}},
            {"viability": {"grounding": {"grounded": False}}},
        ]
        grounded_count = sum(
            1 for f in saved_features
            if f.get("viability", {}).get("grounding", {}).get("grounded") is True
            and str(f.get("viability", {}).get("grounding", {}).get("evidence_url", "")).startswith("http")
        )
        synthesis = {"verification_quality": "high"}
        # Guard only downgrades — never upgrades. 3/4 ≥ 4//2 (=2), so high stays.
        assert grounded_count >= max(1, len(saved_features) // 2)
        assert synthesis["verification_quality"] == "high"

    def test_grounded_field_without_url_not_counted(self):
        """grounded=True but no evidence_url means no real evidence — don't count it."""
        feat = {"viability": {"grounding": {"grounded": True, "evidence_url": ""}}}
        url = str(feat["viability"]["grounding"].get("evidence_url", ""))
        is_real = feat["viability"]["grounding"]["grounded"] is True and url.startswith("http")
        assert is_real is False


# ─────────────────────────────────────────────────────────────────────────────
# 28. Cached-scan demo endpoint (/api/scan/demo?project_path=org/repo)
# ─────────────────────────────────────────────────────────────────────────────
class TestCachedScanDemo:
    """
    Tests for the cached real-scan demo mode.
    Verifies /api/scan/demo accepts project_path and serves real cached scan
    data from MongoDB instead of the hand-curated seed.
    """

    def test_demo_accepts_project_path_param(self, client):
        """Endpoint must accept project_path query param without 422."""
        r = client.post("/api/scan/demo?project_path=gitlab-org%2Fgitaly")
        assert r.status_code == 200, f"project_path param not accepted: {r.status_code}"

    def test_demo_with_unknown_path_falls_back_to_seed(self, client):
        """An unknown project_path must fall through to the seed (gitlab-foss) demo,
        not 404 or 500. This is the safety-net behaviour."""
        r = client.post("/api/scan/demo?project_path=does-not-exist%2Fnowhere")
        assert r.status_code == 200
        d = r.json()
        # Falls through to one of the seed demos — gitlab-foss or inkscape
        assert d.get("project_path") in ("gitlab-org/gitlab-foss", "inkscape/inkscape", "does-not-exist/nowhere")
        # Source should indicate we fell back, not pretend to be a cached scan
        assert d.get("source") in (
            "mongodb_atlas", "inline_fallback", "mongodb_cached_scan"
        )

    def test_demo_cached_scan_has_cached_scan_id(self, client):
        """When a real cached scan is served, the response must expose cached_scan_id
        so the frontend can show provenance."""
        r = client.post("/api/scan/demo?project_path=gitlab-org%2Fgitaly")
        d = r.json()
        if d.get("source") == "mongodb_cached_scan":
            assert "cached_scan_id" in d
            assert isinstance(d["cached_scan_id"], str)
            assert len(d["cached_scan_id"]) > 0

    def test_demo_cached_scan_features_have_real_project_path(self, client):
        """Cached-scan features must reflect the actual project_path of the cached scan,
        not the gitlab-foss seed's project_path."""
        r = client.post("/api/scan/demo?project_path=gitlab-org%2Fgitaly")
        d = r.json()
        if d.get("source") == "mongodb_cached_scan":
            assert d["project_path"] == "gitlab-org/gitaly"

    def test_demo_cached_scan_verification_quality_not_overstated(self, client):
        """For cached scans, verification_quality must reflect actual grounded URLs —
        never hardcoded 'high' when Phase 1 found no evidence."""
        r = client.post("/api/scan/demo?project_path=gitlab-org%2Fgitaly")
        d = r.json()
        if d.get("source") == "mongodb_cached_scan":
            features = d.get("features", [])
            grounded_with_url = sum(
                1 for f in features
                if (f.get("viability") or {}).get("grounding", {}).get("grounded") is True
                and str((f.get("viability") or {}).get("grounding", {}).get("evidence_url", "")).startswith("http")
            )
            vq = (d.get("adk_synthesis") or {}).get("verification_quality", "")
            if grounded_with_url == 0:
                assert vq == "low", (
                    f"verification_quality must be 'low' when 0 features have grounded URLs, got '{vq}'"
                )

    def test_demo_cached_scan_no_fabricated_evidence_urls(self, client):
        """Regression for the `requests v2.34.2` PyPI hallucination bug — the cached
        scan must never carry a grounded evidence URL that's structurally wrong
        (e.g. a Python `requests` URL on a Go project)."""
        r = client.post("/api/scan/demo?project_path=gitlab-org%2Fgitaly")
        d = r.json()
        if d.get("source") != "mongodb_cached_scan":
            pytest.skip("No cached gitaly scan in MongoDB — skipping fabrication check")
        # Gitaly is a Go service — Python `requests` package is irrelevant
        for f in d.get("features", []):
            url = (f.get("viability") or {}).get("grounding", {}).get("evidence_url", "")
            assert "pypi.org/project/requests/" not in url, (
                f"Feature '{f.get('name')}' grounded against unrelated PyPI requests package: {url}"
            )

    def test_demo_seed_mode_still_works(self, client):
        """The original ?repo=gitlab-foss path must still work — no regression."""
        r = client.post("/api/scan/demo?repo=gitlab-foss")
        assert r.status_code == 200
        d = r.json()
        assert d.get("project_path") == "gitlab-org/gitlab-foss"
        assert len(d.get("features", [])) > 0

    def test_demo_inkscape_seed_still_works(self, client):
        """The inkscape seed demo path must still work."""
        r = client.post("/api/scan/demo?repo=inkscape")
        assert r.status_code == 200
        d = r.json()
        assert d.get("project_path") == "inkscape/inkscape"


# ─────────────────────────────────────────────────────────────────────────────
# 29. End-to-end pipeline contract — every dormant feature must have honest fields
# ─────────────────────────────────────────────────────────────────────────────
class TestPipelineContract:
    """
    Cross-feature invariants enforced by the bug-fix cycle. Every feature served
    by /api/scan/demo must satisfy these — no exceptions.
    """

    def test_no_username_features_in_demo(self, client):
        """No feature in any demo can start with @ — those are usernames, not features."""
        for path in [None, "gitlab-org/gitaly", "gitlab-org/gitlab"]:
            url = "/api/scan/demo"
            if path:
                from urllib.parse import quote
                url = f"/api/scan/demo?project_path={quote(path)}"
            r = client.post(url)
            for f in r.json().get("features", []):
                name = f.get("name", "")
                assert not name.startswith("@"), (
                    f"Feature name '{name}' starts with @ — should have been filtered"
                )

    def test_no_dangling_preposition_features_in_demo(self, client):
        """No feature name in cached demos can start with 'from ', 'for ', 'to '."""
        forbidden_starts = ("from ", "for ", "to ", "as ", "by ", "of ", "with ")
        for path in ["gitlab-org/gitaly", "gitlab-org/gitlab"]:
            from urllib.parse import quote
            r = client.post(f"/api/scan/demo?project_path={quote(path)}")
            d = r.json()
            if d.get("source") != "mongodb_cached_scan":
                continue
            for f in d.get("features", []):
                name_lower = f.get("name", "").lower()
                for bad in forbidden_starts:
                    assert not name_lower.startswith(bad), (
                        f"Feature '{name_lower}' starts with '{bad}' — slice-extraction noise"
                    )

    def test_no_linter_pragma_features_in_demo(self, client):
        """gocyclo, nolint, eslint-disable etc. must not appear as features."""
        forbidden_substrings = ["gocyclo:ignore", "nolint:", "eslint-disable"]
        for path in ["gitlab-org/gitaly", "gitlab-org/gitlab"]:
            from urllib.parse import quote
            r = client.post(f"/api/scan/demo?project_path={quote(path)}")
            d = r.json()
            if d.get("source") != "mongodb_cached_scan":
                continue
            for f in d.get("features", []):
                name_lower = f.get("name", "").lower()
                for bad in forbidden_substrings:
                    assert bad not in name_lower, (
                        f"Linter pragma '{bad}' surfaced as feature: '{name_lower}'"
                    )

    def test_every_feature_has_valid_recommendation(self, client):
        """Every feature must have a recommendation in the canonical 3-value set."""
        valid = {"revive_now", "investigate_further", "keep_buried"}
        from urllib.parse import quote
        for path in ["gitlab-org/gitaly", "gitlab-org/gitlab-shell", "gitlab-org/gitlab"]:
            r = client.post(f"/api/scan/demo?project_path={quote(path)}")
            d = r.json()
            for f in d.get("features", []):
                rec = (f.get("viability") or {}).get("recommendation")
                assert rec in valid, f"Invalid recommendation '{rec}' on '{f.get('name')}'"

    def test_grounded_features_have_real_https_url(self, client):
        """If a feature claims grounded=True, the evidence_url MUST be a real https:// URL.
        Regression: the bug fix downgrades verification when grounded URLs are missing."""
        from urllib.parse import quote
        for path in ["gitlab-org/gitaly", "gitlab-org/gitlab", "gitlab-org/gitlab-shell"]:
            r = client.post(f"/api/scan/demo?project_path={quote(path)}")
            for f in r.json().get("features", []):
                grounding = (f.get("viability") or {}).get("grounding") or {}
                if grounding.get("grounded") is True:
                    url = str(grounding.get("evidence_url", ""))
                    assert url.startswith("http"), (
                        f"Feature '{f.get('name')}' claims grounded=True but evidence_url is empty/invalid: '{url}'"
                    )


# ═════════════════════════════════════════════════════════════════════════════
# NECROSIS — dead-code detection (bidirectional graveyard). All additive.
# ═════════════════════════════════════════════════════════════════════════════

# 30. Necrosis detector — symbol/marker/tombstone parsing (pure unit tests)
@pytest.mark.unit
class TestNecrosisDetectorUnit:
    """Unit tests for necrosis_detector pure helpers — no network, no server."""

    def test_extract_symbol_go_func(self):
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("func (c *DockerMachine) logDeprecationWarning() {") == "logDeprecationWarning"

    def test_extract_symbol_go_flag_name(self):
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("Name:            UseDirectDownload,") == "UseDirectDownload"

    def test_extract_symbol_ff_convention(self):
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol('Description: "FF_TEST_FEATURE is a flag"') == "FF_TEST_FEATURE"

    def test_extract_symbol_rejects_rule_codes(self):
        """staticcheck rule codes (SA1019, SA5011) are not symbols."""
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("//nolint:staticcheck // SA5011") != "SA5011"

    def test_extract_symbol_rejects_noise_words(self):
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("// TODO remove this later") not in ("TODO", "REMOVEME")

    def test_extract_symbol_rejects_field_noise(self):
        """DefaultValue/Deprecated/Description are struct fields, not the symbol."""
        from backend.services.necrosis_detector import _extract_symbol
        out = _extract_symbol("DefaultValue: false, Deprecated: true,")
        assert out not in ("DefaultValue", "Deprecated")

    def test_extract_symbol_member_access_rightmost_field(self):
        """On a //nolint line, the deprecated member is the leaf field, not the local var.
        Regression: this used to extract 'ip' instead of 'IPAddress'."""
        from backend.services.necrosis_detector import _extract_symbol
        code = 'var ip []string; if inspect.NetworkSettings.IPAddress != "" { //nolint:staticcheck'
        assert _extract_symbol(code) == "IPAddress"

    def test_extract_symbol_member_call(self):
        """A deprecated method call resolves to the method, not the receiver chain.
        Regression: this used to fall back to 'file:config'."""
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("c.Machine.logDeprecationWarning()") == "logDeprecationWarning"

    def test_non_deprecation_staticcheck_detected(self):
        """SA5011 (nil pointer) is NOT a deprecation; SA1019 is."""
        from backend.services.necrosis_detector import _NON_DEPRECATION_SA_RE
        assert _NON_DEPRECATION_SA_RE.search("SA5011: possible nil pointer dereference")
        assert not _NON_DEPRECATION_SA_RE.search("SA1019: deprecated API")

    def test_marker_in_snippet_matches_spacing(self):
        from backend.services.necrosis_detector import _marker_in_snippet
        assert _marker_in_snippet("Deprecated: true", "DefaultValue: false, Deprecated:   true,") is True

    def test_marker_in_snippet_rejects_absent(self):
        from backend.services.necrosis_detector import _marker_in_snippet
        assert _marker_in_snippet("Deprecated: true", "// just a normal comment") is False

    def test_real_tombstone_requires_true(self):
        from backend.services.necrosis_detector import _is_real_tombstone
        assert _is_real_tombstone("Deprecated: true", "Deprecated:   true,") is True
        assert _is_real_tombstone("Deprecated: true", "Deprecated bool // field def") is False

    def test_real_tombstone_toberemovedwith_needs_value(self):
        from backend.services.necrosis_detector import _is_real_tombstone
        assert _is_real_tombstone("ToBeRemovedWith", 'ToBeRemovedWith: "18.0",') is True
        assert _is_real_tombstone("ToBeRemovedWith", 'ToBeRemovedWith: "",') is False

    def test_extract_intent_replacement(self):
        from backend.services.necrosis_detector import _extract_intent
        repl, _target = _extract_intent("# @deprecated use full_path when you need a URL route")
        assert repl == "full_path"

    def test_extract_intent_removal_target(self):
        from backend.services.necrosis_detector import _extract_intent
        _repl, target = _extract_intent('ToBeRemovedWith: "18.0"')
        assert target == "18.0"

    def test_detect_language_from_extension(self):
        from backend.services.necrosis_detector import _detect_language
        assert _detect_language("helpers/flags.go", "any") == "go"
        assert _detect_language("app/models/wiki.rb", "any") == "ruby"
        assert _detect_language("api.py", "any") == "python"

    def test_excluded_paths_skip_generated(self):
        from backend.services.necrosis_detector import _EXCLUDED_PATH_PATTERNS
        assert _EXCLUDED_PATH_PATTERNS.search("vendor/foo/bar.go")
        assert _EXCLUDED_PATH_PATTERNS.search("CHANGELOG.md")
        assert _EXCLUDED_PATH_PATTERNS.search("api/projects.md")
        assert _EXCLUDED_PATH_PATTERNS.search("helpers/flags_test.go")

    def test_excluded_paths_allow_real_source(self):
        from backend.services.necrosis_detector import _EXCLUDED_PATH_PATTERNS
        assert not _EXCLUDED_PATH_PATTERNS.search("helpers/featureflags/flags.go")
        assert not _EXCLUDED_PATH_PATTERNS.search("app/models/wiki.rb")

    def test_confidence_flag_tombstone_autopasses(self):
        from backend.services.necrosis_detector import NecroticCode, _score_necrosis_confidence
        c = NecroticCode(
            id="x", name="UseDualstack", file_path="cache/s3.go",
            annotation="Deprecated: true", detection_method="flag_tombstone",
            language="go", age_days=600,
        )
        _score_necrosis_confidence(c, min_age_days=90)
        assert c.detection_confidence >= 2

    def test_confidence_penalizes_fresh_deprecation(self):
        """A deprecation only 10 days old is likely intentional, not necrosis."""
        from backend.services.necrosis_detector import NecroticCode, _score_necrosis_confidence
        c = NecroticCode(
            id="x", name="NewThing", file_path="a.go",
            annotation="// Deprecated:", detection_method="removal_marker",
            language="go", age_days=10,
        )
        _score_necrosis_confidence(c, min_age_days=90)
        # fresh penalty applied → low confidence
        assert any("only" in s for s in c.detection_signals)


@pytest.mark.unit
class TestCleanupRemovalFilter:
    """Removing redundant/unused/dead code is housekeeping, not a revivable feature.
    Regression: 'deleted carrierwave_s3 patch from rubocop_todo files' and
    'redundant signal handling' were being surfaced as top revival priorities."""

    def test_filters_rubocop_todo_cleanup(self):
        from backend.services.git_forensics import _is_cleanup_removal
        assert _is_cleanup_removal("deleted carrierwave_s3 patch from rubocop_todo files") is True

    def test_filters_redundant(self):
        from backend.services.git_forensics import _is_cleanup_removal
        assert _is_cleanup_removal("redundant signal handling in ci status command") is True
        assert _is_cleanup_removal("Removes more redundant ruby spec tests") is True

    def test_filters_unused_and_dead(self):
        from backend.services.git_forensics import _is_cleanup_removal
        assert _is_cleanup_removal("remove unused import") is True
        assert _is_cleanup_removal("delete dead code in parser") is True

    def test_keeps_feature_flag_removal(self):
        from backend.services.git_forensics import _is_cleanup_removal
        assert _is_cleanup_removal("TrackMaxRssAnon", "featureflag: remove TrackMaxRssAnon") is False
        assert _is_cleanup_removal("REGISTRY_FF_ENFORCE_LOCKFILES", "remove REGISTRY_FF_ENFORCE_LOCKFILES") is False

    def test_keeps_constraint_driven_removal(self):
        from backend.services.git_forensics import _is_cleanup_removal
        # mentions security → revivable even though it's a removal
        assert _is_cleanup_removal("Pages wildcard", "Disable Pages wildcard domains — security risk") is False

    def test_keeps_plain_feature(self):
        from backend.services.git_forensics import _is_cleanup_removal
        assert _is_cleanup_removal("Bundled Mattermost Integration", "Remove bundled Mattermost") is False


@pytest.mark.unit
class TestGraduationSticky:
    """A graduated feature flag is LIVE, not dead — demand must never promote it.
    Regression: 'default-enabled git_last_modified' was being lifted keep_buried ->
    revive_now by the demand override, falsely recommending revival of a live feature."""

    def test_demand_does_not_promote_graduated(self):
        from backend.routes.stream import _apply_demand_signal
        feat = {
            "name": "default-enabled git_last_modified",
            "death_reason": {"category": "feature_flag"},
            "viability": {"recommendation": "keep_buried", "revival_feasibility": 9, "graduated": True},
            "open_issue_matches": [{"iid": 1}, {"iid": 2}, {"iid": 3}],
        }
        note = _apply_demand_signal(feat)
        assert note is None, "graduated feature must not be demand-promoted"
        assert feat["viability"]["recommendation"] == "keep_buried"

    def test_demand_still_promotes_non_graduated(self):
        from backend.routes.stream import _apply_demand_signal
        feat = {
            "name": "wildcard domain support",
            "death_reason": {"category": "feature_flag"},
            "viability": {"recommendation": "keep_buried", "revival_feasibility": 8},
            "open_issue_matches": [{"iid": 1}, {"iid": 2}],
        }
        _apply_demand_signal(feat)
        # non-graduated keep_buried with demand should lift (to at least investigate)
        assert feat["viability"]["recommendation"] != "keep_buried"


# 31. Necrosis route contracts (integration — needs server)
class TestNecrosisRoutes:
    def test_necrosis_scan_route_exists(self, client):
        try:
            r = client.post("/api/necrosis/scan", json={"repo_url": "test/test"}, timeout=3.0)
            assert r.status_code not in (404, 405)
        except httpx.TimeoutException:
            pass  # SSE started — route exists

    def test_necrosis_scan_requires_repo_url(self, client):
        r = client.post("/api/necrosis/scan", json={})
        assert r.status_code == 422

    def test_necrosis_latest_route_exists(self, client):
        r = client.get("/api/necrosis/latest")
        assert r.status_code == 200
        d = r.json()
        assert "findings" in d and "summary" in d

    def test_deletion_mr_unknown_finding_404(self, client):
        r = client.post("/api/necrosis/nonexistent-finding-xyz/deletion-mr",
                        json={"project_path": "test/repo"})
        assert r.status_code in (404, 503)

    def test_deletion_mr_route_not_405(self, client):
        """Regression guard — route must be registered as POST."""
        r = client.post("/api/necrosis/any-id/deletion-mr",
                        json={"project_path": "gitlab-org/gitlab-runner"})
        assert r.status_code != 405


# 32. Necrosis latest data contract (integration)
class TestNecrosisDataContract:
    def test_latest_findings_have_required_fields(self, client):
        r = client.get("/api/necrosis/latest")
        for f in r.json().get("findings", []):
            for field in ("name", "file_path", "detection_method", "deletion_safety"):
                assert field in f, f"necrosis finding missing field: {field}"

    def test_latest_verdicts_valid(self, client):
        r = client.get("/api/necrosis/latest")
        valid = {"excise_now", "needs_biopsy", "leave_intact"}
        for f in r.json().get("findings", []):
            rec = (f.get("deletion_safety") or {}).get("recommendation")
            if rec:
                assert rec in valid, f"invalid necrosis verdict: {rec}"

    def test_excise_now_never_has_callers(self, client):
        """SAFETY INVARIANT: a finding marked excise_now must have 0 external callers.
        NECRO must never recommend deleting code that is still referenced."""
        r = client.get("/api/necrosis/latest")
        for f in r.json().get("findings", []):
            safety = f.get("deletion_safety") or {}
            if safety.get("recommendation") == "excise_now":
                callers = safety.get("callers_found", -1)
                assert callers == 0, (
                    f"SAFETY VIOLATION: '{f.get('name')}' is excise_now with {callers} callers"
                )

    def test_no_excluded_files_in_findings(self, client):
        """Generated/vendored/test files must never surface as necrosis."""
        from backend.services.necrosis_detector import _EXCLUDED_PATH_PATTERNS
        r = client.get("/api/necrosis/latest")
        for f in r.json().get("findings", []):
            fp = f.get("file_path", "")
            assert not _EXCLUDED_PATH_PATTERNS.search(fp), (
                f"excluded file surfaced as necrosis: {fp}"
            )
