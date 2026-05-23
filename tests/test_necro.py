"""
NECRO end-to-end test suite — 42 tests across 8 categories.

Run:
    python -m pytest tests/test_necro.py -v
    python -m pytest tests/test_necro.py -v -k "TestMongoDB"
    python -m pytest tests/test_necro.py -v -k "not live"
"""

import asyncio
import json
import re
import time
import pytest
import httpx

BASE = "http://localhost:8080"
CLIENT_TIMEOUT = 30.0


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE, timeout=CLIENT_TIMEOUT) as c:
        yield c


# ── 1. Health & Startup ──────────────────────────────────────────────────────
class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"

    def test_health_contains_service_name(self, client):
        r = client.get("/api/health")
        assert "necro" in r.json()["service"]

    def test_gemini_primary_is_gemini3(self, client):
        r = client.get("/api/health")
        assert "gemini-3" in r.json().get("gemini_primary", "")

    def test_gemini_fallback_is_vertex(self, client):
        r = client.get("/api/health")
        assert "vertex" in r.json().get("gemini_fallback", "").lower()

    def test_health_reports_mcp_status(self, client):
        r = client.get("/api/health")
        d = r.json()
        assert "gitlab_mcp" in d

    def test_health_reports_monitor_status(self, client):
        r = client.get("/api/health")
        d = r.json()
        assert "monitor" in d

    def test_health_reports_slack_status(self, client):
        r = client.get("/api/health")
        d = r.json()
        assert "slack" in d


# ── 2. Demo (MongoDB-backed) ─────────────────────────────────────────────────
class TestDemo:
    def test_demo_endpoint_returns_200(self, client):
        r = client.post("/api/scan/demo")
        assert r.status_code == 200

    def test_demo_has_features(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        assert "features" in d
        assert len(d["features"]) > 0

    def test_demo_uses_real_gitlab_foss(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        assert "gitlab" in d["project_path"].lower()

    def test_demo_has_revive_now_candidates(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        features = d["features"]
        revive = [f for f in features if (f.get("viability") or {}).get("recommendation") == "revive_now"]
        assert len(revive) >= 1

    def test_demo_features_have_competitive_intel(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        features = d["features"]
        has_ci = any(f.get("competitive_intel") for f in features)
        assert has_ci, "At least one demo feature should have competitive intelligence"

    def test_demo_features_have_cited_evidence(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        features = d["features"]
        has_evidence = any(
            (f.get("death_reason") or {}).get("cited_evidence")
            for f in features
        )
        assert has_evidence, "Demo features must cite evidence from repo history"

    def test_demo_features_have_roi_data(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        features = d["features"]
        has_roi = any(f.get("roi") for f in features)
        assert has_roi

    def test_demo_has_no_acmecorp_data(self, client):
        r = client.post("/api/scan/demo")
        text = r.text.lower()
        assert "acmecorp" not in text, "Demo must not contain fake 'acmecorp' data"

    def test_demo_features_have_real_commit_shas(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        shas = [f.get("kill_commit_sha", "") for f in d["features"]]
        valid_shas = [s for s in shas if s and len(s) >= 7]
        assert len(valid_shas) >= 3


# ── 3. MongoDB persistence ───────────────────────────────────────────────────
class TestMongoDB:
    def test_report_latest_endpoint(self, client):
        r = client.get("/api/report/latest")
        # Either 200 (MongoDB present) or 503 (not configured)
        assert r.status_code in (200, 503, 404)

    def test_report_scans_list(self, client):
        r = client.get("/api/report/scans")
        assert r.status_code == 200
        d = r.json()
        assert "scans" in d

    def test_report_feature_by_id(self, client):
        # Load demo first
        demo_r = client.post("/api/scan/demo")
        features = demo_r.json().get("features", [])
        if not features:
            pytest.skip("No features in demo")
        feature_id = features[0].get("feature_id") or features[0].get("id")
        r = client.get(f"/api/report/feature/{feature_id}")
        assert r.status_code in (200, 404, 503)

    def test_revival_log_endpoint(self, client):
        r = client.get("/api/report/revival-log")
        assert r.status_code == 200
        d = r.json()
        assert "entries" in d

    def test_report_latest_has_no_hardcoded_data(self, client):
        r = client.get("/api/report/latest")
        if r.status_code == 200:
            text = r.text.lower()
            assert "acmecorp" not in text, "Production report must not contain hardcoded 'acmecorp' data"


# ── 4. Scan endpoints ────────────────────────────────────────────────────────
class TestScan:
    def test_start_scan_requires_url(self, client):
        r = client.post("/api/scan/start", json={})
        assert r.status_code == 422

    def test_start_scan_returns_scan_id(self, client):
        r = client.post("/api/scan/start", json={"repo_url": "https://gitlab.com/gitlab-org/gitlab-foss"})
        assert r.status_code == 200
        d = r.json()
        assert "scan_id" in d

    def test_scan_status_unknown_id(self, client):
        r = client.get("/api/scan/status/nonexistent-id")
        assert r.status_code == 200
        d = r.json()
        assert "error" in d

    def test_scan_status_known_id(self, client):
        start_r = client.post("/api/scan/start", json={"repo_url": "https://gitlab.com/gitlab-org/gitlab-foss"})
        scan_id = start_r.json()["scan_id"]
        status_r = client.get(f"/api/scan/status/{scan_id}")
        assert status_r.status_code == 200
        d = status_r.json()
        assert "status" in d
        assert d["status"] in ("running", "done", "error")

    def test_scan_extracts_gitlab_path(self, client):
        r = client.post("/api/scan/start", json={"repo_url": "https://gitlab.com/my-org/my-repo"})
        d = r.json()
        assert d.get("project_path") == "my-org/my-repo"


# ── 5. Watch list ────────────────────────────────────────────────────────────
class TestWatchList:
    def test_watch_list_returns_200(self, client):
        r = client.get("/api/watch/list")
        assert r.status_code == 200

    def test_watch_list_has_repos_key(self, client):
        r = client.get("/api/watch/list")
        d = r.json()
        assert "repos" in d

    def test_watch_gitlab_foss_in_list(self, client):
        r = client.get("/api/watch/list")
        d = r.json()
        paths = [repo.get("project_path", "") for repo in d.get("repos", [])]
        # gitlab-org/gitlab-foss should be pre-seeded
        has_foss = any("gitlab-foss" in p for p in paths)
        assert has_foss, "gitlab-org/gitlab-foss should be in watch list after seeding"

    def test_add_watch_requires_url(self, client):
        r = client.post("/api/watch/add", json={})
        assert r.status_code == 422

    def test_remove_nonexistent_watch(self, client):
        r = client.request("DELETE", "/api/watch/nonexistent-org/nonexistent-repo")
        assert r.status_code in (404, 503)


# ── 6. Monitor ───────────────────────────────────────────────────────────────
class TestMonitor:
    def test_monitor_status_endpoint(self, client):
        r = client.get("/api/monitor/status")
        assert r.status_code == 200
        d = r.json()
        assert "running" in d

    def test_monitor_reports_interval(self, client):
        r = client.get("/api/monitor/status")
        d = r.json()
        assert "interval_hours" in d
        assert d["interval_hours"] > 0

    def test_monitor_run_endpoint(self, client):
        r = client.post("/api/monitor/run")
        assert r.status_code == 200
        d = r.json()
        assert "checked_repos" in d or "errors" in d

    def test_health_includes_monitor_state(self, client):
        r = client.get("/api/health")
        d = r.json()
        monitor = d.get("monitor", {})
        assert "running" in monitor


# ── 7. Revive endpoint ───────────────────────────────────────────────────────
class TestRevive:
    def test_revive_nonexistent_feature(self, client):
        r = client.post("/api/revive/nonexistent-feature-id", json={"project_path": "test/repo"})
        assert r.status_code == 404

    def test_revive_keep_buried_rejected(self, client):
        """Features marked keep_buried must be rejected."""
        # Try to revive the Geo demo feature (known keep_buried)
        r = client.post("/api/revive/omnibus-geo-replication-free", json={"project_path": "gitlab-org/gitlab-foss"})
        # 400 if found and keep_buried; 404 if not in DB yet; 502 if MCP not configured
        assert r.status_code in (400, 404, 502)

    def test_revive_requires_project_path(self, client):
        r = client.post("/api/revive/some-feature", json={})
        # Either 404 (feature not found) or 400 (project_path logic)
        assert r.status_code in (400, 404)

    def test_revive_generates_proper_description(self, client):
        """Mock: verify description builder logic in revive.py."""
        from backend.routes.revive import _build_description
        feat = {"name": "Test Feature", "kill_commit_sha": "abc1234", "kill_date": "2022-01-01",
                "linked_mr_iid": 123, "linked_issue_iids": [456], "project_path": "test/repo"}
        dr = {"cited_evidence": "Test evidence", "primary_reason": "Test reason", "category": "test"}
        vi = {"what_changed": "Things changed", "revival_feasibility": 8, "effort_estimate": "2 weeks",
              "effort_category": "weeks", "technical_risks": ["Risk 1", "Risk 2"],
              "recommendation": "revive_now", "reasoning": "Good idea"}
        desc = _build_description(feat, dr, vi)
        assert "Test Feature" in desc
        assert "NECRO" in desc
        assert "gitlab_mcp" in desc.lower() or "MCP" in desc


# ── 8. Competitive intelligence ──────────────────────────────────────────────
class TestCompetitiveIntel:
    def test_demo_has_competitive_urgency(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        features_with_ci = [f for f in d.get("features", []) if f.get("competitive_intel")]
        assert len(features_with_ci) >= 1

    def test_demo_competitive_urgency_is_valid(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        valid_urgencies = {"critical", "high", "medium", "low", "unknown"}
        for feat in d.get("features", []):
            ci = feat.get("competitive_intel")
            if ci:
                assert ci.get("market_urgency") in valid_urgencies

    def test_demo_revive_now_features_have_competitor_analysis(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        revive_features = [f for f in d.get("features", []) if (f.get("viability") or {}).get("recommendation") == "revive_now"]
        if revive_features:
            for feat in revive_features:
                ci = feat.get("competitive_intel")
                assert ci is not None, f"Feature '{feat.get('name')}' marked revive_now must have competitive intel"

    def test_competitive_intel_has_caveat(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        for feat in d.get("features", []):
            ci = feat.get("competitive_intel")
            if ci:
                assert ci.get("caveat") or ci.get("summary"), "CI must have a summary or caveat to be honest about estimate quality"


# ── 9. ROI estimates integrity ───────────────────────────────────────────────
class TestROIIntegrity:
    def test_roi_estimates_have_caveats(self, client):
        """ROI estimates must be clearly labelled as rough signal-based estimates."""
        r = client.post("/api/scan/demo")
        d = r.json()
        for feat in d.get("features", []):
            roi = feat.get("roi") or {}
            if roi.get("roi_estimate_label"):
                caveat = roi.get("caveats", "")
                assert caveat, f"Feature '{feat.get('name')}' ROI estimate missing caveats disclaimer"

    def test_roi_request_count_is_non_negative(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        for feat in d.get("features", []):
            roi = feat.get("roi") or {}
            assert roi.get("request_count", 0) >= 0

    def test_no_fabricated_revenue_numbers(self, client):
        """ROI estimates should not contain fabricated dollar revenue figures."""
        r = client.post("/api/scan/demo")
        text = r.text
        # Should NOT contain patterns like "$5.2M ARR" or "$10M revenue"
        bad_pattern = re.compile(r'\$\d+\.?\d*[MB]\s*(ARR|MRR|revenue)', re.IGNORECASE)
        assert not bad_pattern.search(text), "ROI estimates must not contain fabricated revenue figures"


# ── 10. Data integrity ───────────────────────────────────────────────────────
class TestDataIntegrity:
    def test_no_hardcoded_data_in_scan_response(self, client):
        r = client.post("/api/scan/demo")
        text = r.text.lower()
        forbidden = ["acmecorp", "lorem ipsum", "test company", "fake company", "placeholder"]
        for word in forbidden:
            assert word not in text, f"Response contains forbidden hardcoded placeholder: '{word}'"

    def test_demo_data_references_real_gitlab_issues(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        issue_refs = []
        for feat in d.get("features", []):
            issue_refs.extend(feat.get("linked_issue_iids", []))
        assert len(issue_refs) >= 3, "Demo data should reference at least 3 real GitLab issue numbers"

    def test_demo_data_references_real_mr_numbers(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        mr_refs = [f.get("linked_mr_iid") for f in d.get("features", []) if f.get("linked_mr_iid")]
        assert len(mr_refs) >= 3, "Demo data should reference at least 3 real GitLab MR numbers"

    def test_features_have_all_required_fields(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        required = ["name", "kill_commit_sha", "kill_date", "death_reason", "viability", "roi"]
        for feat in d.get("features", []):
            for field in required:
                assert field in feat, f"Feature missing required field: {field}"

    def test_viability_recommendation_is_valid(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        valid = {"revive_now", "investigate_further", "keep_buried"}
        for feat in d.get("features", []):
            rec = (feat.get("viability") or {}).get("recommendation")
            assert rec in valid, f"Invalid recommendation: {rec}"

    def test_death_reason_category_is_present(self, client):
        r = client.post("/api/scan/demo")
        d = r.json()
        for feat in d.get("features", []):
            cat = (feat.get("death_reason") or {}).get("category")
            assert cat, f"Feature '{feat.get('name')}' missing death_reason.category"
