"""
Deterministic regression tests for NECRO's accuracy guards ("Bucket A").

Every test here locks a specific verdict-logic fix that was found by manual scan review.
They are PURE: no running server, no GitLab/Gemini/Vertex calls, no network (the one
grounding-fallback test monkeypatches the registry lookup). They run in well under a
second and are marked `unit` so conftest runs them even when no backend is up.

What they protect (and the bug each maps to):
  - deprecation gate ............ HTTP/2 Server Push, Flash, etc. -> keep_buried   (#1/#11)
  - tangential suppression ...... "gitlab v19.0.1" not "constraint resolved"        (#3/#8)
  - synthesis verdict guard ..... challenger-reject not silently re-promoted        (#4)
                                  low-feasibility buried not exhumed; honest badge  (#2/#8)
  - challenger application ...... reject demotes revive->investigate; investigate advisory (#10)
  - feature-name extraction ..... 'Remove "-/" ...' keeps balanced quotes           (#9)
  - grounding feature-name fallback  React grounds even when constraint text omits it
"""

import asyncio
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


async def _noop_emit(_msg):
    """Async emit stub for the synthesis/streaming helpers."""
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Permanent-deprecation gate
# ─────────────────────────────────────────────────────────────────────────────
class TestDeprecationGate:
    def test_http2_server_push_detected_from_constraint(self):
        from backend.services.constraint_grounder import _check_deprecation
        d = _check_deprecation("blocked because HTTP/2 server push was removed")
        assert d is not None
        assert d["label"] == "HTTP/2 Server Push"
        assert d["url"].startswith("http")

    def test_http2_detected_via_feature_name_only(self):
        # The constraint text mentions only the grpc library; the deprecation must still
        # be caught from the feature NAME ("HTTP/2 server push").
        from backend.services.constraint_grounder import _check_deprecation
        d = _check_deprecation("HTTP/2 server push (blocked by a grpc library flow-control bug)")
        assert d is not None and d["label"] == "HTTP/2 Server Push"

    def test_adobe_flash_detected(self):
        from backend.services.constraint_grounder import _check_deprecation
        d = _check_deprecation("Adobe Flash content embed")
        assert d is not None and d["label"] == "Adobe Flash"

    def test_live_react_not_flagged_as_deprecated(self):
        from backend.services.constraint_grounder import _check_deprecation
        assert _check_deprecation("blocked by React 17, no renderToPipeableStream") is None

    def test_openssl_not_flagged_as_deprecated(self):
        from backend.services.constraint_grounder import _check_deprecation
        assert _check_deprecation("OpenSSL 1.x lacking Kyber support") is None

    def test_ground_constraint_short_circuits_deprecated(self):
        # ground_constraint must return the deprecation record BEFORE any network lookup.
        from backend.services.constraint_grounder import ground_constraint
        g = asyncio.run(ground_constraint(
            "blocked by a grpc library flow-control bug", "November 20, 2025",
            feature_name="HTTP/2 server push (blocked by a grpc library flow-control bug)",
        ))
        assert g["deprecated"] is True
        assert g["is_resolved"] is False
        assert g["source"] == "ecosystem_deprecation"
        assert g["evidence_url"].startswith("http")

    def test_viability_deprecation_forces_keep_buried(self):
        # Full viability path short-circuits to keep_buried for a deprecated feature —
        # no Gemini call, no network (deprecation gate returns first).
        from backend.services.viability_scorer import score_revival_viability
        feat = SimpleNamespace(
            name="HTTP/2 server push (blocked by a grpc library flow-control bug)",
            kill_date="November 20, 2025", detection_method="revert_commit",
        )
        dr = {"category": "technical_debt",
              "specific_constraint": "blocked by a grpc library flow-control bug",
              "primary_reason": "grpc flow-control bug", "is_temporary": True}
        r = asyncio.run(score_revival_viability(feat, dr, project_path=""))
        assert r["recommendation"] == "keep_buried"
        assert r["revival_feasibility"] <= 2
        assert r["confidence"] == "high"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tangential-evidence suppression
# ─────────────────────────────────────────────────────────────────────────────
class TestTangentialSuppression:
    def _grounded(self):
        return {
            "grounded": True, "technology": "gitlab", "evidence_date": "2026-05-26",
            "latest_version": "v19.0.1", "evidence_url": "https://github.com/x",
            "is_resolved": True, "deprecated": False, "source": "github_tags",
        }

    @pytest.mark.parametrize("category", ["unknown", "strategic_pivot", "security", "regulatory", "legal"])
    def test_irrelevant_categories_suppress(self, category):
        from backend.services.viability_scorer import _suppress_tangential_grounding
        g = self._grounded()
        assert _suppress_tangential_grounding(g, category) is True
        assert g["grounded"] is False
        assert g["is_resolved"] is False
        assert g["tangential"] is True
        # evidence display fields cleared so the UI shows no false "verified" date line
        assert g["evidence_date"] == "" and g["latest_version"] == "" and g["technology"] == ""

    @pytest.mark.parametrize("category", ["api_limitation", "technical_debt", "infrastructure", "performance"])
    def test_relevant_categories_keep_grounding(self, category):
        from backend.services.viability_scorer import _suppress_tangential_grounding
        g = self._grounded()
        assert _suppress_tangential_grounding(g, category) is False
        assert g["grounded"] is True
        assert g["technology"] == "gitlab"  # untouched

    def test_deprecated_grounding_never_suppressed(self):
        from backend.services.viability_scorer import _suppress_tangential_grounding
        g = self._grounded()
        g["deprecated"] = True
        # even with an "irrelevant" category, a deprecation record stays intact
        assert _suppress_tangential_grounding(g, "unknown") is False
        assert g["grounded"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. ADK synthesis verdict guard
# ─────────────────────────────────────────────────────────────────────────────
class TestSynthesisVerdictGuard:
    def _run(self, feats, synthesis):
        from backend.routes.stream import _apply_synthesis_verdicts
        asyncio.run(_apply_synthesis_verdicts(feats, synthesis, _noop_emit))
        return feats

    def test_challenger_reject_blocks_upgrade(self):
        feats = [{
            "name": "PQ TLS", "death_reason": {"category": "api_limitation"},
            "challenger": {"challenger_verdict": "reject"},
            "viability": {"recommendation": "investigate_further", "revival_feasibility": 8,
                          "grounding": {"grounded": False, "source": "unverified"}},
        }]
        synth = {"feature_verdicts": [{"feature": "PQ TLS", "constraint_resolved": "yes",
                                       "evidence_url": "https://github.com/x/y",
                                       "recommendation": "revive_now"}]}
        self._run(feats, synth)
        # rejected feature stays investigate; not re-promoted, and grounding not faked
        assert feats[0]["viability"]["recommendation"] == "investigate_further"
        assert feats[0]["viability"]["grounding"].get("grounded") is False

    def test_low_feasibility_keep_buried_not_exhumed(self):
        feats = [{
            "name": "debian route", "death_reason": {"category": "unknown"},
            "viability": {"recommendation": "keep_buried", "revival_feasibility": 2,
                          "grounding": {"grounded": False, "source": "unverified"}},
        }]
        synth = {"feature_verdicts": [{"feature": "debian route", "constraint_resolved": "yes",
                                       "evidence_url": "https://github.com/gitlabhq/gitlabhq",
                                       "recommendation": "investigate_further"}]}
        self._run(feats, synth)
        assert feats[0]["viability"]["recommendation"] == "keep_buried"

    def test_legit_upgrade_sets_synthesis_verified_not_grounded(self):
        feats = [{
            "name": "Streaming SSR", "death_reason": {"category": "api_limitation"},
            "viability": {"recommendation": "investigate_further", "revival_feasibility": 8,
                          "grounding": {"grounded": False, "source": "unverified"}},
        }]
        synth = {"feature_verdicts": [{"feature": "Streaming SSR", "constraint_resolved": "yes",
                                       "evidence_url": "https://github.com/facebook/react/releases",
                                       "recommendation": "revive_now"}]}
        self._run(feats, synth)
        vi = feats[0]["viability"]
        assert vi["recommendation"] == "revive_now"
        assert vi.get("synthesis_verified") is True
        # must NOT fake the registry-grounded flag (that drives the green "✓ verified" badge)
        assert vi["grounding"].get("grounded") is False

    def test_revive_now_requires_feasibility_7(self):
        feats = [{
            "name": "low feas feat", "death_reason": {"category": "api_limitation"},
            "viability": {"recommendation": "investigate_further", "revival_feasibility": 5,
                          "grounding": {"grounded": False, "source": "unverified"}},
        }]
        synth = {"feature_verdicts": [{"feature": "low feas feat", "constraint_resolved": "yes",
                                       "evidence_url": "https://github.com/x/y",
                                       "recommendation": "revive_now"}]}
        self._run(feats, synth)
        # feasibility 5 < 7 -> capped at investigate, never revive_now
        assert feats[0]["viability"]["recommendation"] == "investigate_further"

    def test_graduated_feature_not_upgraded(self):
        feats = [{
            "name": "graduated flag", "death_reason": {"category": "feature_flag"},
            "viability": {"recommendation": "keep_buried", "revival_feasibility": 9,
                          "graduated": True, "grounding": {"grounded": False}},
        }]
        synth = {"feature_verdicts": [{"feature": "graduated flag", "constraint_resolved": "yes",
                                       "evidence_url": "https://github.com/x/y",
                                       "recommendation": "revive_now"}]}
        self._run(feats, synth)
        assert feats[0]["viability"]["recommendation"] == "keep_buried"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Challenger verdict application (advisory, reject-aware)
# ─────────────────────────────────────────────────────────────────────────────
class TestChallengerVerdictApplication:
    def test_reject_demotes_revive_to_investigate(self):
        from backend.routes.stream import _apply_challenger_verdict
        f = {"viability": {"recommendation": "revive_now"}}
        _apply_challenger_verdict(f, {"challenger_verdict": "reject", "challenger_score": 2})
        assert f["viability"]["recommendation"] == "investigate_further"
        assert f["challenger"]["challenger_score"] == 2  # assessment attached

    def test_reject_on_investigate_is_advisory(self):
        from backend.routes.stream import _apply_challenger_verdict
        f = {"viability": {"recommendation": "investigate_further"}}
        _apply_challenger_verdict(f, {"challenger_verdict": "reject"})
        # stays investigate — the by-design-skeptical challenger must not bury every candidate
        assert f["viability"]["recommendation"] == "investigate_further"

    def test_downgrade_leaves_revive_unchanged(self):
        from backend.routes.stream import _apply_challenger_verdict
        f = {"viability": {"recommendation": "revive_now"}}
        _apply_challenger_verdict(f, {"challenger_verdict": "downgrade"})
        assert f["viability"]["recommendation"] == "revive_now"

    def test_confirm_leaves_revive_unchanged(self):
        from backend.routes.stream import _apply_challenger_verdict
        f = {"viability": {"recommendation": "revive_now"}}
        _apply_challenger_verdict(f, {"challenger_verdict": "confirm"})
        assert f["viability"]["recommendation"] == "revive_now"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Feature-name extraction (balanced quotes)
# ─────────────────────────────────────────────────────────────────────────────
class TestFeatureNameExtraction:
    def test_quoted_token_keeps_balanced_quotes(self):
        from backend.services.git_forensics import _extract_feature_name_from_message
        name = _extract_feature_name_from_message('Remove "-/" section from the debian upload route')
        # the closing quote of the "-/" token must survive (no dangling '-/"')
        assert name == '"-/" section from the debian upload route'
        assert name.count('"') % 2 == 0  # balanced

    def test_wrapping_quotes_stripped(self):
        from backend.services.git_forensics import _extract_feature_name_from_message
        assert _extract_feature_name_from_message("Revert 'Add dark mode support'") == "Add dark mode support"

    def test_remove_prefix_stripped(self):
        from backend.services.git_forensics import _extract_feature_name_from_message
        assert _extract_feature_name_from_message("Remove deprecated payment gateway") == "deprecated payment gateway"

    def test_no_leading_dangling_quote(self):
        from backend.services.git_forensics import _extract_feature_name_from_message
        name = _extract_feature_name_from_message('Remove "upload params" from body params')
        assert not name.startswith('-')  # regression: never leave a mangled leading fragment
        assert name.count('"') % 2 == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Grounding falls back to the feature name for tech identification
# ─────────────────────────────────────────────────────────────────────────────
class TestGroundingFeatureNameFallback:
    def test_identify_react_from_feature_name(self):
        from backend.services.constraint_grounder import _identify_technology
        # constraint text alone has no tech keyword
        assert _identify_technology("lack of renderToPipeableStream support") == ("", "")
        # feature name carries it
        tech, _ = _identify_technology("Streaming SSR (blocked by React 17, no renderToPipeableStream support)")
        assert tech == "react"

    def test_ground_constraint_uses_feature_name(self, monkeypatch):
        # Constraint text has no tech; feature name does. Patch the GitHub lookup so the
        # test is deterministic and never touches the network.
        import backend.services.constraint_grounder as cg

        async def _fake_releases(repo):
            assert repo == "facebook/react"
            return {"version": "v19.2.7", "release_date": "2026-06-01",
                    "url": "https://github.com/facebook/react/releases/tag/v19.2.7",
                    "description": "react v19.2.7", "source": "github_releases"}

        monkeypatch.setattr(cg, "_check_github_releases", _fake_releases)
        cg._GROUNDER_CACHE.clear()
        g = asyncio.run(cg.ground_constraint(
            "lack of renderToPipeableStream support", "October 05, 2025",
            feature_name="Streaming SSR (blocked by React 17, no renderToPipeableStream support)",
        ))
        assert g["grounded"] is True
        assert g["technology"] == "react"
        assert g["latest_version"] == "v19.2.7"
        assert g["is_resolved"] is True  # released after the Oct 2025 kill date


# ─────────────────────────────────────────────────────────────────────────────
# 7. Necrosis: never recommend deleting a USAGE of a deprecated symbol
#    (the load-bearing-code safety promise — e.g. option.WithCredentialsFile)
# ─────────────────────────────────────────────────────────────────────────────
class TestNecrosisUsageGuard:
    def test_symbol_kind_classification(self):
        from backend.services.necrosis_detector import _extract_symbol_kinded
        assert _extract_symbol_kinded("func (c *T) logDeprecationWarning() {")[1] == "declaration"
        # //nolint-suppressed external calls are USAGES, not deletable definitions
        assert _extract_symbol_kinded("tlsConfig.BuildNameToCertificate()")[1] == "usage"
        assert _extract_symbol_kinded("option.WithCredentialsFile(a.config.CredentialsFile)")[1] == "usage"
        assert _extract_symbol_kinded("ip := inspect.NetworkSettings.IPAddress")[1] == "usage"

    def test_extract_symbol_backcompat_returns_string(self):
        # existing callers/tests rely on the bare-string signature
        from backend.services.necrosis_detector import _extract_symbol
        assert _extract_symbol("func (c *T) logDeprecationWarning() {") == "logDeprecationWarning"

    def _necrotic(self, **kw):
        from backend.services.necrosis_detector import NecroticCode
        base = dict(
            id="x", name="WithCredentialsFile", file_path="cache/gcsv2/adapter.go",
            annotation="// nolint:staticcheck", detection_method="suppressed_deprecation",
            language="go", symbol_kind="usage", age_days=2000,
        )
        base.update(kw)
        return NecroticCode(**base)

    def _patch(self, monkeypatch, gemini_verdict):
        import backend.services.deletion_scorer as ds

        async def _fake_generate_json(*a, **k):
            return gemini_verdict

        async def _fake_search_blobs(*a, **k):
            return []  # 0 in-repo callers (it's an external symbol)

        async def _fake_pipelines(*a, **k):
            return [{"status": "success"}]

        async def _fake_ground(*a, **k):
            return {"grounded": False, "technology": "", "latest_version": "",
                    "evidence_date": "", "evidence_url": "", "description": "",
                    "source": "unverified", "is_resolved": None}

        monkeypatch.setattr(ds, "generate_json", _fake_generate_json)
        monkeypatch.setattr(ds, "ground_constraint", _fake_ground)
        monkeypatch.setattr(ds.mcp, "search_blobs", _fake_search_blobs)
        monkeypatch.setattr(ds.mcp, "list_pipelines", _fake_pipelines)

    def test_usage_never_excised_even_if_model_says_excise(self, monkeypatch):
        # Gemini (wrongly) says excise_now with 0 risk; the deterministic guard must
        # downgrade because this is a deprecated-API usage, not dead code.
        from backend.services.deletion_scorer import score_deletion_safety
        self._patch(monkeypatch, {
            "is_safe_to_delete": True, "deletion_risk": 1,
            "blast_radius": "nothing", "effort_estimate": "30 min",
            "technical_risks": [], "recommendation": "excise_now",
            "reasoning": "0 callers", "confidence": "high",
        })
        r = asyncio.run(score_deletion_safety(self._necrotic(), project_path="org/repo"))
        assert r["recommendation"] == "needs_biopsy"
        assert r["deletion_risk"] >= 5

    def test_suppressed_deprecation_method_forces_usage(self, monkeypatch):
        # Even if symbol_kind were mislabeled, detection_method=suppressed_deprecation
        # must force the usage guard.
        from backend.services.deletion_scorer import score_deletion_safety
        self._patch(monkeypatch, {
            "is_safe_to_delete": True, "deletion_risk": 1, "blast_radius": "nothing",
            "effort_estimate": "30 min", "technical_risks": [],
            "recommendation": "excise_now", "reasoning": "0 callers", "confidence": "high",
        })
        n = self._necrotic(symbol_kind="declaration", detection_method="suppressed_deprecation")
        r = asyncio.run(score_deletion_safety(n, project_path="org/repo"))
        assert r["recommendation"] == "needs_biopsy"

    def test_genuine_declaration_can_still_excise(self, monkeypatch):
        # A real in-repo func definition with 0 callers, old, low risk -> excise stays.
        from backend.services.deletion_scorer import score_deletion_safety
        self._patch(monkeypatch, {
            "is_safe_to_delete": True, "deletion_risk": 1, "blast_radius": "nothing",
            "effort_estimate": "30 min", "technical_risks": [],
            "recommendation": "excise_now", "reasoning": "0 callers", "confidence": "high",
        })
        n = self._necrotic(name="logDeprecationWarning", file_path="common/config.go",
                           annotation="// Deprecated: no longer used",
                           detection_method="annotation_scan", symbol_kind="declaration")
        r = asyncio.run(score_deletion_safety(n, project_path="org/repo"))
        assert r["recommendation"] == "excise_now"
