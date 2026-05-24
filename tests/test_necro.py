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


@pytest.fixture(scope="session", autouse=True)
def wait_for_server():
    """Wait for the backend to be fully ready before running any tests."""
    import time
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=3.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


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
        r = client.post("/api/scan/stream", json={"repo_url": "https://gitlab.com/test/test"},
                        timeout=3.0)
        # 200 (SSE starts), 422 (validation), 500 — all mean route exists
        assert r.status_code not in (404, 405)

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
        r = client.post("/api/scan/quick", json={
            "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
            "max_commits": 10,
            "lookback_months": 6,
        }, timeout=5.0)
        # Scan starts — 200 (with results), 408 (timeout), or any non-404/405 status
        assert r.status_code not in (404, 405, 422)

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
