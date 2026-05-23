"""
Evaluate whether the reason a feature was disabled is still valid today.

Uses Gemini 3 Flash with known capability improvements as context.
Returns a structured viability assessment — NOT fabricated numbers,
but a reasoned evaluation of what has changed since the kill date.
"""

import logging

from backend.services.gemini import generate_json

logger = logging.getLogger(__name__)

# Known capability improvements since 2020 that commonly resolved historical blockers.
# This is the "current context" the viability scorer uses to evaluate constraints.
_KNOWN_IMPROVEMENTS = """
Known capability improvements since 2020 (use to evaluate if specific constraints are resolved):

APIs:
- Stripe: Added custom billing intervals (Nov 2023), usage-based billing (2023), expanded webhook support
- Twilio: Launched Startup pricing tier at significant discount (2023), improved reliability
- SendGrid: Improved deliverability, new template engine (2022)
- Plaid: Expanded bank coverage, improved OAuth flow stability (2022)
- Stripe Connect: Improved payout scheduling (2023)

Infrastructure:
- PostgreSQL 15: Major bulk insert performance improvements, better partitioning (released 2022)
- PostgreSQL 16: Further query planner improvements (2023)
- Redis Cluster: Improved stability and throughput (2022+)
- AWS RDS Aurora Serverless v2: Handles much higher connection loads vs v1 (2022)
- Kubernetes: Improved autoscaling, reduced cold start latency (2022-2024)
- Cloudflare Workers: Higher CPU limits, better cold start (2022-2024)

Frontend/Libraries:
- React 18: Concurrent rendering, Suspense improvements, reduced re-renders (2022)
- D3.js v7: Resolved many v4/v5 compatibility issues (2021)
- Next.js 13+: App router, server components, dramatically improved bundle size (2022-2023)
- Vite: Near-instant HMR, faster builds than webpack (2021-2023)

AI/ML:
- GPT-4 / Gemini: Quality vastly improved vs GPT-3 era for content generation (2023-2024)
- Embeddings: Open-source alternatives widely available (2023-2024)

Costs:
- Cloud storage costs: Down ~40% since 2021
- LLM API costs: Down ~90% since GPT-4 launch for equivalent quality
- SMS costs: Competitive pricing from multiple providers
"""


async def score_revival_viability(feature, death_reason: dict) -> dict:
    """
    Evaluate if the kill reason is still valid today.
    Returns: is_still_valid, what_changed, revival_feasibility (0-10),
             effort_estimate, risks, recommendation, reasoning.
    """
    category = death_reason.get("category", "unknown")
    constraint = death_reason.get("specific_constraint", "")
    kill_date = feature.kill_date or "unknown date"

    prompt = f"""A software feature called "{feature.name}" was disabled on {kill_date}.

Kill reason: {death_reason.get("primary_reason", "unknown")}
Category: {category}
Specific constraint: {constraint or "not specified"}
Was it meant to be temporary: {death_reason.get("is_temporary", False)}

{_KNOWN_IMPROVEMENTS}

Evaluate whether this feature should be considered for revival today (May 2026).

Return a JSON object with these exact fields:
{{
  "is_still_valid": true or false (is the original kill reason still a real constraint?),
  "what_changed": "specific explanation of what has changed since {kill_date} that affects this constraint (or 'Nothing significant has changed' if the constraint still applies)",
  "revival_feasibility": 0 to 10 (10 = trivial to revive, 0 = impossible),
  "effort_estimate": "rough estimate like '2-3 days' or '2-3 weeks' or 'major refactor (months)'",
  "effort_category": "days" or "weeks" or "months",
  "technical_risks": ["list", "of", "specific", "technical", "risks"],
  "recommendation": "revive_now" or "investigate_further" or "keep_buried",
  "reasoning": "2-3 sentence explanation of the recommendation",
  "confidence": "high", "medium", or "low"
}}

Recommendation guide:
- revive_now: feasibility >= 7 AND original constraint is clearly resolved
- investigate_further: feasibility 4-6 OR constraint is partially resolved OR unclear
- keep_buried: feasibility <= 3 OR constraint still fully applies

Base your assessment on the known improvements above. Do not invent specific version numbers or dates not listed above."""

    result = await generate_json(prompt)
    if result and "recommendation" in result:
        logger.info(
            "Viability: %s (feasibility=%s, recommendation=%s)",
            feature.name,
            result.get("revival_feasibility"),
            result.get("recommendation"),
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
    }
