"""
Challenger Agent — second Gemini 3 Flash pass that independently verifies
top revive_now recommendations from the primary analysis.

Inspired by adversarial verification patterns: a second model instance
independently stress-tests the primary agent's findings, asking specifically
"what could cause this revival to fail?" This surfaces risks the primary
analysis may have been too optimistic about.

Called after the main pipeline finishes, for up to 3 top-confidence
revive_now candidates.
"""

import logging

from backend.services.gemini import generate_json

logger = logging.getLogger(__name__)


async def challenge_revival_candidate(feature: dict) -> dict:
    """
    Run an independent adversarial Gemini 3 Flash evaluation of a single
    revive_now recommendation. Returns a challenger assessment dict.
    """
    name = feature.get("name", "unknown feature")
    viability = feature.get("viability", {})
    death_reason = feature.get("death_reason", {})

    primary_rec = viability.get("recommendation", "unknown")
    primary_feasibility = viability.get("revival_feasibility", 0)
    primary_reasoning = viability.get("reasoning", "")
    what_changed = viability.get("what_changed", "")
    kill_reason = death_reason.get("primary_reason", "")
    category = death_reason.get("category", "unknown")

    prompt = f"""You are the Challenger Agent — a second AI evaluator independently reviewing a revival recommendation.

The primary analysis has recommended: REVIVE NOW

Feature: "{name}"
Original kill reason: {kill_reason}
Kill reason category: {category}
Primary agent's feasibility score: {primary_feasibility}/10
Primary agent's reasoning: {primary_reasoning}
What the primary agent says has changed: {what_changed}

Your job is to independently stress-test this recommendation. Be skeptical. Ask:
- What hidden risks did the primary analysis miss?
- What technical dependencies or migration costs were not accounted for?
- Is the "what_changed" claim actually accurate? Could the constraint still apply?
- What would need to go wrong for this revival to fail?

Return a JSON object with these exact fields:
{{
  "challenger_verdict": "confirm" | "downgrade" | "reject",
  "confidence": "high" | "medium" | "low",
  "hidden_risks": ["list of specific risks the primary analysis may have missed"],
  "strongest_objection": "the single most compelling reason this revival might fail",
  "recommended_first_step": "the single most important thing to verify before committing to revival",
  "challenger_score": 0 to 10 (challenger's independent feasibility estimate — be honest if it differs from {primary_feasibility})
}}

challenger_verdict guide:
- confirm: agree with revive_now (risks are manageable)
- downgrade: downgrade to investigate_further (meaningful risks exist that need scoping first)
- reject: downgrade to keep_buried (primary analysis was too optimistic)"""

    result = await generate_json(prompt)

    if result and "challenger_verdict" in result:
        logger.info(
            "Challenger verdict for '%s': %s (score=%s, primary=%s)",
            name,
            result.get("challenger_verdict"),
            result.get("challenger_score"),
            primary_feasibility,
        )
        result["source"] = "gemini_3_flash_challenger"
        return result

    return {
        "challenger_verdict": "confirm",
        "confidence": "low",
        "hidden_risks": ["Challenger evaluation failed — treating primary analysis as final"],
        "strongest_objection": "Could not evaluate independently",
        "recommended_first_step": "Manually review the primary analysis",
        "challenger_score": primary_feasibility,
        "source": "gemini_3_flash_challenger",
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
    for r in results:
        if isinstance(r, Exception):
            logger.warning("Challenger task failed: %s", r)
            assessments.append({
                "challenger_verdict": "confirm",
                "confidence": "low",
                "hidden_risks": [],
                "strongest_objection": "Evaluation failed",
                "recommended_first_step": "Review manually",
                "challenger_score": 5,
                "source": "gemini_3_flash_challenger",
            })
        else:
            assessments.append(r)

    return assessments
