"""
Evaluate whether the reason a feature was disabled is still valid today.

Uses Gemini 3 Flash with LIVE-GROUNDED evidence from real external APIs
(npm registry, GitHub releases, PyPI) via constraint_grounder.py.

Unlike a static knowledge base, each claim is backed by a real API response
with a source URL that can be independently verified.
"""

import logging

from backend.services.constraint_grounder import ground_constraint
from backend.services.gemini import generate_json

logger = logging.getLogger(__name__)


# Kill-reason categories where a dependency/platform version bump is NOT evidence the
# original constraint cleared. A feature killed for an unknown reason, a strategic pivot,
# or a deliberate security/legal decision is not "resolved" just because some incidentally
# named tech shipped a new release (e.g. grounding a gitlab-workhorse feature against
# "gitlab v19.0.1"). Categories like api_limitation / technical_debt / infrastructure are
# absent on purpose — for those a version bump genuinely can resolve the blocker.
_VERSION_IRRELEVANT_CATEGORIES = {
    "unknown", "strategic_pivot", "security", "regulatory", "legal", "compliance",
}


def _suppress_tangential_grounding(grounding: dict, category: str) -> bool:
    """Strip the grounded/resolved framing from `grounding` (in place) when a version
    bump is irrelevant to the kill reason. Deprecation groundings are never touched.

    Returns True if suppression was applied. (Bug #3/#8 class — tangential evidence)
    """
    if (
        grounding.get("grounded")
        and not grounding.get("deprecated")
        and category in _VERSION_IRRELEVANT_CATEGORIES
    ):
        grounding["grounded"] = False
        grounding["is_resolved"] = False
        grounding["tangential"] = True
        # Clear the evidence-display fields too — otherwise the timeline still renders a
        # "2026-05-26 · gitlab v19.0.1" line under the AI-inferred badge, which reads like
        # evidence for a constraint the version bump never addressed.
        grounding["evidence_date"] = ""
        grounding["evidence_url"] = ""
        grounding["latest_version"] = ""
        grounding["technology"] = ""
        return True
    return False


async def score_revival_viability(feature, death_reason: dict, project_path: str = "") -> dict:
    """
    Evaluate if the kill reason is still valid today.

    Steps:
    1. Call constraint_grounder to get real external evidence for the constraint
    2. Fetch live GitLab CI pipeline status via MCP (list_pipelines)
    3. Inject grounded evidence + CI health into the Gemini prompt
    4. Ask Gemini to evaluate using the real evidence (not training data speculation)

    Returns: is_still_valid, what_changed, revival_feasibility, effort_estimate,
             technical_risks, recommendation, reasoning, confidence, grounding.
    """
    category = death_reason.get("category", "unknown")
    specific_constraint = death_reason.get("specific_constraint", "")
    primary_reason = death_reason.get("primary_reason", "unknown")
    kill_date = feature.kill_date or "unknown date"

    # Ground the constraint in real external API data
    try:
        grounding = await ground_constraint(
            constraint_text=specific_constraint or primary_reason,
            kill_date=kill_date,
            feature_name=feature.name,
        )
    except Exception as exc:
        logger.warning("Constraint grounding failed for '%s': %s — continuing without evidence", feature.name, exc)
        grounding = {
            "grounded": False, "technology": "", "latest_version": "",
            "evidence_date": "", "evidence_url": "", "description": "",
            "source": "error", "is_resolved": False,
        }

    # Permanent-deprecation gate: if the feature depends on a platform capability that
    # was removed from the ecosystem (HTTP/2 Server Push, Flash, Web SQL, …), no library
    # version bump revives it. Short-circuit to a deterministic keep_buried verdict with
    # the citable deprecation evidence — this is the class of kill reason the version
    # lookups miss, and the reason HTTP/2 Server Push was wrongly "investigate". (Bug #11/#1)
    if grounding.get("deprecated"):
        tech = grounding.get("technology", "the underlying platform capability")
        note = grounding.get("description", "")
        logger.info("Deprecation gate: '%s' depends on %s — forcing keep_buried", feature.name, tech)
        return {
            "is_still_valid": True,
            "what_changed": f"{tech} is permanently deprecated. {note}",
            "revival_feasibility": 1,
            "effort_estimate": "not viable",
            "effort_category": "months",
            "technical_risks": [
                f"{tech} has been removed from the ecosystem — there is no supported path to revive it",
                "A newer library release cannot restore a removed platform/browser capability",
            ],
            "recommendation": "keep_buried",
            "reasoning": (
                f"The capability this feature depends on ({tech}) is permanently deprecated, "
                f"not a temporary constraint. {note} A newer dependency version does not bring "
                "back a removed platform feature, so this should stay buried."
            ),
            "confidence": "high",
            "deprecated": True,
            "grounding": grounding,
        }

    # Tangential-evidence guard (see _suppress_tangential_grounding): when the kill
    # category is one where a dependency/platform version bump is irrelevant, strip the
    # grounded/resolved framing so the UI doesn't show a false "verified" badge and Gemini
    # doesn't reason from irrelevant version evidence. (Bug #3/#8 class)
    if _suppress_tangential_grounding(grounding, category):
        logger.info(
            "Tangential grounding for '%s': version bump irrelevant to a '%s' kill — "
            "not treating as constraint resolution", feature.name, category,
        )

    # Check GitLab CI health — a broken pipeline signals the codebase is unstable
    ci_health_block = ""
    ci_broken = False
    if project_path:
        from backend.services.gitlab_mcp import mcp as _gl
        try:
            pipelines = await _gl.list_pipelines(project_path, per_page=3)
            if pipelines:
                last_status = pipelines[0].get("status", "unknown")
                all_statuses = [p.get("status", "unknown") for p in pipelines]
                failing = sum(1 for s in all_statuses if s == "failed")
                ci_broken = last_status == "failed"
                ci_health_block = f"""
GITLAB CI STATUS (live from GitLab MCP list_pipelines):
- Most recent pipeline: {last_status.upper()}
- Last {len(pipelines)} pipelines: {', '.join(all_statuses)}
- Failing: {failing}/{len(pipelines)}
{"- RISK: CI is currently broken — reviving code into a broken pipeline raises deployment risk" if ci_broken else "- CI healthy — safe environment to introduce revived code"}
"""
                logger.info("[MCP] CI health for %s: last=%s", project_path, last_status)
        except Exception as exc:
            logger.debug("CI pipeline check skipped: %s", exc)

    # Build evidence block for the prompt
    if grounding["grounded"]:
        source_label = grounding["source"].replace("_", " ")
        evidence_block = f"""VERIFIED EXTERNAL EVIDENCE (source: {source_label}):
- Technology: {grounding["technology"]}
- Latest version: {grounding["latest_version"]}
- Latest release date: {grounding["evidence_date"] or "unknown"}
- Evidence URL: {grounding["evidence_url"]}
- Summary: {grounding["description"]}
- Released AFTER feature was killed: {grounding["is_resolved"]}

Use this real evidence when evaluating whether the constraint is resolved.
Do NOT fabricate release dates or version numbers — only use what is listed above."""
        logger.info(
            "Constraint grounded for '%s': %s v%s (%s)",
            feature.name,
            grounding["technology"],
            grounding["latest_version"],
            grounding["evidence_date"],
        )
    else:
        evidence_block = f"""EXTERNAL API LOOKUP: No specific package or library could be identified
from the constraint text ("{specific_constraint or primary_reason}").

Evaluate based on general knowledge of the software ecosystem as of May 2026.
Without verified external evidence:
- Mark confidence as "low"
- Do NOT score revival_feasibility above 6 unless you have very strong ecosystem evidence
- Prefer "investigate_further" over "revive_now" — unverified assumptions are not safe grounds for immediate action"""

    prompt = f"""A software feature called "{feature.name}" was disabled on {kill_date}.

Kill reason: {primary_reason}
Category: {category}
Specific constraint: {specific_constraint or "not specified"}
Was it meant to be temporary: {death_reason.get("is_temporary", False)}

{evidence_block}
{ci_health_block}
Evaluate whether this feature should be considered for revival today (May 2026).

Return a JSON object with these exact fields:
{{
  "is_still_valid": true or false (is the original kill reason still a real constraint?),
  "what_changed": "specific explanation using the evidence above, or 'No verified external evidence found' if evidence_block shows unverified",
  "revival_feasibility": 0 to 10 (10 = trivial to revive, 0 = impossible),
  "effort_estimate": "rough estimate like '2-3 days', '2-3 weeks', or 'major refactor (months)'",
  "effort_category": "days" or "weeks" or "months",
  "technical_risks": ["list", "of", "specific", "technical", "risks"],
  "recommendation": "revive_now" or "investigate_further" or "keep_buried",
  "reasoning": "2-3 sentence explanation citing the evidence above where available",
  "confidence": "high" if grounded evidence confirms resolution, "medium" if plausible based on ecosystem knowledge, "low" if truly uncertain
}}

Recommendation guide:
- revive_now: ALL of the following must hold:
    * feasibility >= 7
    * confidence is "medium" or "high" (low confidence → investigate_further at best)
    * kill reason category is NOT "unknown" — if the reason the feature was disabled
      is unknown, you cannot confirm the original constraint resolved; use investigate_further
    * AND one of: verified external evidence shows constraint resolved; OR category is
      "feature_flag" with a clear temporary rationale; OR category is technical_debt /
      workaround / performance with ecosystem evidence the constraint no longer applies
- investigate_further: feasibility 4-7; OR kill reason is unknown regardless of feasibility;
    OR no verified evidence and confidence is "low"; OR constraint may still apply
- keep_buried: feasibility <= 3; OR the kill reason clearly still applies today (active
    security issue, hard platform limit, intentional strategic pivot, legal/compliance blocker)

IMPORTANT: "Unknown kill reason" is a red flag, not a green light. Do NOT reason that
"unknown = not permanently blocked = safe to revive_now". Unknown means you lack the
evidence to make a confident call — default to investigate_further.

IMPORTANT: Only cite specific version numbers or dates that appear in the VERIFIED EXTERNAL EVIDENCE block above."""

    result = await generate_json(prompt, thinking_budget=1024)

    if result and "recommendation" in result:
        result["grounding"] = grounding

        # ── Graduation detector (runs FIRST, overrides everything else) ──────────
        # A feature flag removed because the feature BECAME THE DEFAULT is a
        # graduation event — the feature is live and active, NOT dead.
        # These must never be surfaced as revival candidates.
        _GRADUATION_SIGNALS = [
            "already enabled by default",
            "enabled by default",
            "default-enabled",
            "became default",
            "rolled out to all",
            "fully rolled out",
            "standard lifecycle",
            "lifecycle completion",
            "already active by default",
            "removed as it is now default",
        ]
        _primary_lower = primary_reason.lower()
        _name_lower = feature.name.lower()
        _is_graduated = category == "feature_flag" and (
            any(sig in _primary_lower for sig in _GRADUATION_SIGNALS)
            or _name_lower.startswith("default-enabled")
            or _name_lower.startswith("enable-by-default")
        )
        if _is_graduated:
            result["recommendation"] = "keep_buried"
            result["confidence"] = "high"
            result["is_still_valid"] = True
            # Sticky flag: a graduated feature is LIVE, not dead. Downstream demand
            # overrides and synthesis upgrades must never promote it to revive_now —
            # demand for an already-shipped feature is not a reason to "revive" it.
            result["graduated"] = True
            result["reasoning"] = (
                "This feature flag was removed because the feature was already enabled "
                "by default — a graduation event, not a death. The feature is currently "
                "active in production and does not need revival."
            )
            result["what_changed"] = "Feature graduated to default — flag cleanup only, feature is live."

        # Feature flags are temporary by design, BUT a flag being removed does not by
        # itself prove the original constraint resolved — it may have graduated, been
        # abandoned, or the blocker may persist. So we only treat a feature flag as a
        # confident revive_now when there is VERIFIED external evidence (grounding).
        # Ungrounded flags stay/become investigate_further — which is the honest
        # verdict the ADK synthesis also reaches. (ADK google_search can still upgrade
        # a verified one to revive_now later via _apply_synthesis_verdicts.)
        if (
            result.get("recommendation") == "revive_now"
            and category == "feature_flag"
            and not grounding.get("grounded")
            and not _is_graduated
        ):
            result["recommendation"] = "investigate_further"
            result["reasoning"] = (
                result.get("reasoning", "") +
                " Downgraded to investigate: no verified external evidence that the original "
                "constraint resolved — the flag's removal alone doesn't prove the feature is revivable."
            )

        # Post-processing guarantee: revert commits are also explicitly temporary actions.
        # Someone deliberately undid a merge for a specific stated reason (e.g. "no consensus yet",
        # "breaks CI", "needs more review"). If feasibility ≥ 7, the original feature was viable
        # once and can be viable again — Gemini's boundary-case flip between revive/investigate
        # should resolve to revive_now for high-feasibility reverts.
        if (
            feature.detection_method == "revert_commit"
            and result.get("revival_feasibility", 0) >= 7
            and result.get("recommendation") == "investigate_further"
        ):
            result["recommendation"] = "revive_now"
            result["reasoning"] = (
                result.get("reasoning", "") +
                " Revert commits are explicitly temporary — the feature was working and reverted for a specific, revisitable reason."
            )

        # Safety net: if Gemini says keep_buried but feasibility is very high (≥ 8) for a
        # feature_flag_removal detection, the model likely contradicted itself. A feasibility
        # of 8-10 means "trivially revivable" which cannot coexist with "keep buried" unless
        # the kill reason is ironclad. Upgrade to investigate_further so a human can decide.
        # SKIP for graduated flags — high feasibility is CORRECT for graduated flags (they
        # are trivially "revivable" since the feature is already live, but should stay buried).
        if (
            feature.detection_method == "feature_flag_removal"
            and result.get("revival_feasibility", 0) >= 8
            and result.get("recommendation") == "keep_buried"
            and result.get("confidence") != "high"
            and not _is_graduated
        ):
            result["recommendation"] = "investigate_further"
            result["reasoning"] = (
                result.get("reasoning", "") +
                " High feasibility for a feature flag removal — escalated to investigate_further for human review."
            )

        # Unknown kill reason must never yield high confidence or revive_now.
        # Without knowing WHY a feature was disabled there may be a very good reason
        # invisible in git history (legal, security, contract, architecture decision).
        # All existing guards key on specific categories (feature_flag, revert_commit
        # etc.) and skip when category is "unknown" — this is the safety net.
        if category == "unknown" and not grounding.get("grounded"):
            if result.get("revival_feasibility", 0) > 6:
                result["revival_feasibility"] = 6
            if result.get("recommendation") == "revive_now":
                result["recommendation"] = "investigate_further"
                result["reasoning"] = (
                    result.get("reasoning", "") +
                    " Feasibility capped: kill reason is unknown — the original disable "
                    "rationale may still apply and cannot be verified from commit history alone."
                )
            if result.get("confidence") not in ("low",):
                result["confidence"] = "low"

        # Downgrade recommendation if CI is currently broken — revival into broken CI is risky
        if ci_broken:
            risks = result.get("technical_risks", [])
            ci_risk = "CI pipeline is currently failing — fix CI before merging revived code"
            if ci_risk not in risks:
                risks.insert(0, ci_risk)
            result["technical_risks"] = risks
            if result.get("recommendation") == "revive_now":
                result["recommendation"] = "investigate_further"
                result["reasoning"] = (result.get("reasoning", "") +
                    " Note: downgraded from 'revive now' because CI is currently broken.")
        logger.info(
            "Viability: %s (feasibility=%s, recommendation=%s, grounded=%s, ci_broken=%s)",
            feature.name,
            result.get("revival_feasibility"),
            result.get("recommendation"),
            grounding.get("grounded"),
            ci_broken,
        )
        return result

    return {
        "is_still_valid": True,
        "what_changed": "Could not evaluate — insufficient context",
        "revival_feasibility": 3,
        "effort_estimate": "unknown",
        "effort_category": "weeks",
        "technical_risks": ["Insufficient context to assess risks"],
        "recommendation": "investigate_further",
        "reasoning": "Insufficient evidence to make a confident recommendation.",
        "confidence": "low",
        "grounding": grounding,
    }
