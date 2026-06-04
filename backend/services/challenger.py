"""
Challenger Agent — independent adversarial review of revival recommendations.

Uses Vertex AI Gemini 2.5 Flash (via generate_json_adversarial) to ensure genuine
model independence from the primary analysis (Gemini 3 Flash via AI Studio API key).

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

Your default posture is deep skepticism, but channel it correctly: REJECT only when the
original blocker still stands (the constraint is not actually resolved). When the blocker
has demonstrably cleared but real risks remain, DOWNGRADE and load your objections into the
risks — do not reject a feature whose constraint is genuinely gone just because revival is
hard work. Only CONFIRM when the constraint is resolved AND the risks are clearly manageable.

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

Verdict guide — choose the verdict by WHAT your objection is about:
- reject: ONLY when the original blocking constraint is NOT actually resolved (the
    evidence doesn't prove the specific blocker is gone), OR feasibility <= 3, OR the
    kill reason is a permanent/legal/security blocker that still applies. "Reject" means
    "the thing that killed this feature is still true."
- downgrade: the constraint IS resolved, but revival carries real cost or risk — large
    migration effort, breaking changes, performance/ops concerns, ecosystem upgrades.
    These are reasons to be CAUTIOUS, not reasons the feature is dead. Use downgrade here.
- confirm: constraint resolved AND the listed risks have clear mitigations.

CRITICAL: migration size and upgrade effort are DOWNGRADE concerns, never REJECT grounds.
If the original constraint is genuinely resolved (e.g. the API/version that was missing
now exists and shipped after the kill date), do NOT reject just because the upgrade is a
big project — raise those as hidden_risks and downgrade instead. Reserve reject for
"the blocker is still real." Your skepticism belongs in the risks, not in over-rejecting
features whose constraint has demonstrably cleared."""

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
            "Challenger verdict for '%s': %s (score=%s, primary=%s, model=vertex_gemini_2_5_flash)",
            name,
            result.get("challenger_verdict"),
            result.get("challenger_score"),
            primary_feasibility,
        )
        result["source"] = "vertex_gemini_2_5_flash_challenger"
        return result

    return {
        "challenger_verdict": "downgrade",
        "challenger_score": max(0, primary_feasibility - 2),
        "confidence": "low",
        "hidden_risks": ["Challenger evaluation failed — treating as downgrade by default"],
        "strongest_objection": "Could not independently evaluate — assume risk is higher than primary estimate",
        "recommended_first_step": "Manually review the primary analysis before proceeding",
        "what_primary_got_wrong": "Unknown — challenger evaluation failed",
        "source": "vertex_gemini_2_5_flash_challenger",
    }


async def challenge_top_revival_candidates(features: list[dict], limit: int = 3) -> list[dict]:
    """
    Run the Challenger Agent on up to `limit` candidates in parallel.
    Returns a list of challenger assessment dicts (same order as input).

    The caller decides which candidates to pass — typically all revive_now
    recommendations plus the highest-feasibility investigate_further ones, so
    cautious-but-wrong verdicts also get an independent adversarial review.
    """
    import asyncio

    selected = features[:max(0, limit)]
    tasks = [challenge_revival_candidate(f) for f in selected]
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
                "source": "vertex_gemini_2_5_flash_challenger",
            })
        else:
            assessments.append(r)

    return assessments

