"""
Extract the reason a feature was disabled using Gemini 3 Flash.

All input evidence is cited from GitLab MCP data so the analysis is
grounded in real repository history, not hallucinated.
"""

import json
import logging

from backend.services.gemini import generate_json

logger = logging.getLogger(__name__)

REASON_CATEGORIES = [
    "feature_flag",         # Explicitly behind a feature flag that was disabled/removed
    "api_limitation",       # External API didn't support it
    "infrastructure",       # DB, server, queue couldn't handle it
    "performance",          # Too slow, too expensive to run
    "resource_constraint",  # Cost, team size, budget
    "low_adoption",         # Users didn't want it
    "strategic_pivot",      # Company direction changed
    "regulatory",           # Legal or compliance blocker
    "technical_debt",       # Code quality, dependencies
    "security",             # Security vulnerability
    "unknown",              # Can't determine from available evidence
]


async def extract_death_reason(feature) -> dict:
    """
    Given a DeadFeature with context_snippets, ask Gemini to classify the
    kill reason. Returns a structured dict with primary_reason, category,
    specific_constraint, is_temporary, confidence.
    """
    if not feature.context_snippets and not feature.kill_commit_message:
        return _unknown_reason()

    # Safely coerce all snippets to strings and filter out empty/None values
    safe_snippets = [str(s) for s in (feature.context_snippets or []) if s]
    context = "\n\n".join(filter(None, [
        f"Kill commit message: {feature.kill_commit_message or '(none)'}",
        f"Kill date: {feature.kill_date or 'unknown'}",
        *safe_snippets,
    ]))

    prompt = f"""A software feature called "{feature.name}" was deliberately disabled in a GitLab repository.

Here is all available evidence about why it was disabled:

{context}

Analyze this evidence and return a JSON object with these exact fields:
{{
  "primary_reason": "one clear sentence explaining why the feature was disabled",
  "category": "one of: {', '.join(REASON_CATEGORIES)}",
  "specific_constraint": "the exact technical limitation, API name, cost figure, or business reason if mentioned (empty string if not mentioned)",
  "is_temporary": true or false,
  "confidence": "high", "medium", or "low",
  "cited_evidence": "the exact quote from the evidence that best explains the kill reason"
}}

Be precise and cite only what the evidence actually says. Do not speculate beyond what is written."""

    result = await generate_json(prompt)
    if result and "primary_reason" in result:
        # Normalise category — reject anything Gemini invented that isn't in our list
        if result.get("category") not in REASON_CATEGORIES:
            result["category"] = "unknown"
        logger.info("Death reason extracted: %s (%s)", result.get("category"), result.get("confidence"))
        return result

    logger.warning("Death reason extraction failed for '%s' — using fallback", feature.name)
    return _unknown_reason()


def _unknown_reason() -> dict:
    return {
        "primary_reason": "Kill reason could not be determined from available commit and issue data",
        "category": "unknown",
        "specific_constraint": "",
        "is_temporary": False,
        "confidence": "low",
        "cited_evidence": "",
    }
