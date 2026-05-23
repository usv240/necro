"""
Estimate the business value of reviving a dead feature.

All estimates are explicitly framed as rough signal-based estimates,
not precise predictions. This avoids the "fabricated stats" problem
that ORACLE's Decision Auditor has.
"""

import logging

from backend.services.gemini import generate_json
from backend.services.gitlab_mcp import mcp

logger = logging.getLogger(__name__)


async def estimate_revival_roi(feature, project_path: str) -> dict:
    """
    Gather demand signals from GitLab (user requests in issues, search) then
    ask Gemini to estimate the rough business value.

    Returns: request_count, demand_signals, priority_tier, roi_estimate_label,
             competitive_gap, reasoning.
    """
    # Count feature requests in issue tracker via MCP
    request_count = 0
    demand_signals: list[str] = []

    if project_path:
        logger.info("[MCP] search_code — searching for '%s' feature requests in issues...", feature.name)
        results = await mcp.search_code(project_path, feature.name, per_page=20)
        if results:
            request_count = len(results)
            demand_signals.append(f"{request_count} code/issue references found for '{feature.name}'")

    # Add context snippets as demand signals
    for snippet in feature.context_snippets[:4]:
        demand_signals.append(snippet)

    prompt = f"""A software feature called "{feature.name}" was disabled and is now being evaluated for revival.

Available demand signals from the repository:
{chr(10).join(f"- {s}" for s in demand_signals) if demand_signals else "- No direct demand signals found in repository"}

Feature kill reason: {getattr(feature.death_reason, 'primary_reason', 'unknown') if hasattr(feature, 'death_reason') and feature.death_reason else 'unknown'}
Kill date: {feature.kill_date or 'unknown'}
Revival feasibility: {feature.viability.get('revival_feasibility', 'unknown') if feature.viability else 'unknown'}/10

Estimate the business value of reviving this feature. IMPORTANT: All estimates must be clearly labeled as rough signal-based estimates, not precise predictions.

Return a JSON object with these exact fields:
{{
  "request_count": {request_count} (use this exact number from repository search),
  "demand_level": "high", "medium", "low", or "unknown",
  "priority_tier": "P1 — Immediate", "P2 — High Priority", "P3 — Consider", or "P4 — Low Priority",
  "roi_estimate_label": "a rough range like '$50K–$200K/year estimate' or 'Hard to quantify without revenue data' — never a precise number",
  "competitive_gap": "brief note on whether competitors typically have this feature (based on feature name and category only)",
  "value_drivers": ["list", "of", "what", "drives", "value"],
  "reasoning": "2-3 sentences explaining the value estimate based on the signals above",
  "caveats": "note that this is a rough estimate based on limited signals, not a precise business case"
}}

Base estimates ONLY on the demand signals provided. Do not fabricate user counts, revenue figures, or NPS data not mentioned in the signals."""

    result = await generate_json(prompt)
    if result and "demand_level" in result:
        result["request_count"] = request_count
        logger.info("ROI estimate: %s → %s", feature.name, result.get("roi_estimate_label"))
        return result

    return {
        "request_count": request_count,
        "demand_level": "unknown",
        "priority_tier": "P3 — Consider",
        "roi_estimate_label": "Insufficient data to estimate",
        "competitive_gap": "Unknown",
        "value_drivers": [],
        "reasoning": "Insufficient demand signal data to estimate business value.",
        "caveats": "Rough estimate based on limited repository signals.",
    }
