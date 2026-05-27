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
    grounding = await ground_constraint(
        constraint_text=specific_constraint or primary_reason,
        kill_date=kill_date,
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

Evaluate based on general knowledge of the software ecosystem as of May 2026,
but mark confidence as "low" and is_still_valid as true if uncertain."""

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
  "confidence": "high" if grounded evidence confirms resolution, "medium" if partial, "low" if no external evidence
}}

Recommendation guide:
- revive_now: feasibility >= 7 AND verified evidence shows constraint is resolved
- investigate_further: feasibility 4-6 OR constraint is partially resolved OR no external evidence
- keep_buried: feasibility <= 3 OR constraint clearly still applies

IMPORTANT: Only cite specific version numbers or dates that appear in the VERIFIED EXTERNAL EVIDENCE block above."""

    result = await generate_json(prompt, thinking_budget=1024)

    if result and "recommendation" in result:
        result["grounding"] = grounding
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
