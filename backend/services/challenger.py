"""
Challenger Agent — independent adversarial review of revival recommendations.

Uses Vertex AI Gemini 3 Flash (via generate_json_adversarial) to ensure genuine
model independence from the primary analysis (Gemini 3 Flash via API key).

The Challenger's job is to REJECT, not confirm. It starts from a position of
skepticism and must produce specific, falsifiable failure scenarios. It is required
to score at least 1 point lower than the primary unless evidence is overwhelming.

This models how a senior engineer would push back in a code review — not rubber-stamping,
but genuinely stress-testing whether the primary agent missed something.
"""

import logging

from backend.services.gemini import generate_json_adversarial

logger = logging.getLogger(__name__)

_CHALLENGER_SYSTEM = """You are the Red Team Agent — the designated devil's advocate in a
multi-agent code review system.

Your ONLY job is to find reasons why a proposed feature revival will FAIL.
You are NOT trying to be helpful or encouraging. You are trying to prevent bad decisions.

Your starting position is REJECT. You will only move to CONFIRM if the evidence is
overwhelming and the risks are clearly manageable.

You MUST:
1. Produce exactly 3 specific, falsifiable failure scenarios
2. Score the feature at least 1 point LOWER than the primary agent's estimate
3. Find at least one risk the primary analysis did not explicitly address
4. Be specific — "this might be hard" is not acceptable; "the Stripe API rate limit of 100 req/s
   will be hit during peak billing cycles if the feature processes >10K users" is acceptable"""


async def challenge_revival_candidate(feature: dict) -> dict:
    """
    Run an independent adversarial Vertex AI evaluation of a single revive_now recommendation.
    Returns a challenger assessment dict.
    """
    name = feature.get("name", "unknown feature")
    viability = feature.get("viability", {})
    death_reason = feature.get("death_reason", {})
    grounding = viability.get("grounding", {})

    primary_feasibility = viability.get("revival_feasibility", 0)
    primary_reasoning = viability.get("reasoning", "")
    what_changed = viability.get("what_changed", "")
    kill_reason = death_reason.get("primary_reason", "")
    category = death_reason.get("category", "unknown")
    kill_date = feature.get("kill_date", "unknown date")

    grounding_note = ""
    if grounding.get("grounded"):
        grounding_note = f"""
The primary agent used this external evidence:
- Technology: {grounding.get("technology")}
- Latest version: {grounding.get("latest_version")}
- Evidence date: {grounding.get("evidence_date")}
- Source: {grounding.get("source")}

Challenge whether this evidence actually resolves the specific constraint, or whether
the primary agent over-interpreted it."""
    else:
        grounding_note = "\nThe primary agent had NO verified external evidence — all claims are unverified AI inference."

    prompt = f"""{_CHALLENGER_SYSTEM}

---

PRIMARY ANALYSIS UNDER REVIEW:
Feature: "{name}"
Killed: {kill_date}
Kill reason: {kill_reason}
Kill reason category: {category}
Primary agent feasibility score: {primary_feasibility}/10
Primary agent claim: {what_changed}
Primary agent reasoning: {primary_reasoning}
{grounding_note}

---

Your task: Stress-test this REVIVE NOW recommendation. Be specific and concrete.

Return a JSON object:
{{
  "challenger_verdict": "confirm" | "downgrade" | "reject",
  "challenger_score": integer 0-10 (MUST be <= {max(0, primary_feasibility - 1)} unless evidence is overwhelming),
  "confidence": "high" | "medium" | "low",
  "failure_scenario_1": "specific, falsifiable scenario where this revival fails",
  "failure_scenario_2": "another specific failure scenario (must differ from #1)",
  "failure_scenario_3": "a third specific failure scenario (must differ from #1 and #2)",
  "hidden_risks": ["risk the primary missed #1", "risk the primary missed #2"],
  "strongest_objection": "the single most compelling reason to NOT revive this feature",
  "recommended_first_step": "the single most important thing to verify BEFORE committing to revival",
  "what_primary_got_wrong": "specifically what the primary agent overlooked or overstated"
}}

Verdict guide:
- confirm: feasibility >= 7 AND all 3 failure scenarios have clear mitigations
- downgrade: feasibility 4-6 OR at least one failure scenario lacks a clear mitigation
- reject: feasibility <= 3 OR the primary agent's evidence does not actually resolve the constraint"""

    result = await generate_json_adversarial(prompt)

    if result and "challenger_verdict" in result:
        # Merge failure scenarios into hidden_risks list for consistent UI rendering
        hidden_risks = result.get("hidden_risks", [])
        for k in ("failure_scenario_1", "failure_scenario_2", "failure_scenario_3"):
            scenario = result.get(k, "")
            if scenario and scenario not in hidden_risks:
                hidden_risks.append(scenario)
        result["hidden_risks"] = hidden_risks[:6]

        logger.info(
            "Challenger verdict for '%s': %s (score=%s, primary=%s, model=gemini_3_flash)",
            name,
            result.get("challenger_verdict"),
            result.get("challenger_score"),
            primary_feasibility,
        )
        result["source"] = "vertex_gemini_3_flash_challenger"
        return result

    return {
        "challenger_verdict": "downgrade",
        "challenger_score": max(0, primary_feasibility - 2),
        "confidence": "low",
        "hidden_risks": ["Challenger evaluation failed — treating as downgrade by default"],
        "strongest_objection": "Could not independently evaluate — assume risk is higher than primary estimate",
        "recommended_first_step": "Manually review the primary analysis before proceeding",
        "what_primary_got_wrong": "Unknown — challenger evaluation failed",
        "source": "vertex_gemini_3_flash_challenger",
    }


async def challenge_top_revival_candidates(features: list[dict]) -> list[dict]:
    """
    Run the Challenger Agent on up to 3 revive_now candidates in parallel.
    Returns a list of challenger assessment dicts (same order as input).
    """
    import asyncio

    tasks = [challenge_revival_candidate(f) for f in features[:3]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assessments = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            primary_score = features[i].get("viability", {}).get("revival_feasibility", 5)
            logger.warning("Challenger task failed: %s", r)
            assessments.append({
                "challenger_verdict": "downgrade",
                "challenger_score": max(0, primary_score - 2),
                "confidence": "low",
                "hidden_risks": ["Challenger evaluation failed — defaulting to downgrade"],
                "strongest_objection": "Could not evaluate independently",
                "recommended_first_step": "Review manually before committing",
                "what_primary_got_wrong": "Unknown",
                "source": "vertex_gemini_3_flash_challenger",
            })
        else:
            assessments.append(r)

    return assessments

