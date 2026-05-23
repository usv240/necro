"""
Competitive intelligence layer — checks if competitors have shipped
a feature that NECRO identified as a dead revival candidate.

Uses Gemini 3 Flash to reason about competitive landscape based on
the feature name, category, and kill date. All findings are clearly
labelled as AI-assisted estimates, not verified competitive research.
"""

import logging

from backend.services.gemini import generate_json

logger = logging.getLogger(__name__)

# Known competitor product lines for common GitLab use cases
_COMPETITOR_CONTEXT = """
Primary GitLab competitors (for DevSecOps / source code management):
- GitHub (github.com) — owned by Microsoft. Largest by user count.
- Bitbucket (bitbucket.org) — owned by Atlassian
- Azure DevOps (dev.azure.com) — Microsoft's enterprise DevOps platform
- Gitea / Forgejo — self-hosted open source alternatives
- JetBrains Space — development platform

For specific feature categories:
- Container registries: Docker Hub, GitHub Container Registry (GHCR), AWS ECR, Google Artifact Registry
- CI/CD: Jenkins, CircleCI, GitHub Actions, Buildkite, Harness
- Security scanning: Snyk, SonarQube, Checkmarx
- Pages / static hosting: GitHub Pages, Netlify, Vercel, Cloudflare Pages
- Chat / notifications: Slack, Microsoft Teams, Discord
"""


async def analyze_competitive_gap(
    feature_name: str,
    death_reason_category: str,
    kill_date: str,
    death_reason_summary: str,
) -> dict:
    """
    Assess whether competitors have shipped this feature since it was disabled.
    Returns structured competitive intelligence.
    """
    prompt = f"""You are analyzing competitive intelligence for a feature that was removed from a GitLab-like DevOps platform.

Feature name: "{feature_name}"
Kill date: {kill_date}
Kill reason category: {death_reason_category}
Kill reason summary: {death_reason_summary}

Context about competitors:
{_COMPETITOR_CONTEXT}

Based on your knowledge of the DevOps/source code management market:

1. Do any of the listed competitors currently offer this feature or a close equivalent?
2. When (approximately) did they add it, relative to the kill date?
3. What is the competitive urgency of reviving this feature?

Return a JSON object with these exact fields:
{{
  "competitors_with_feature": ["list of competitor names that have this feature"],
  "market_urgency": "critical" | "high" | "medium" | "low" | "unknown",
  "summary": "2-3 sentence competitive assessment",
  "sources_checked": ["list of products/sources considered in your assessment"],
  "confidence": "high" | "medium" | "low"
}}

IMPORTANT: 
- Only list competitors you are confident have this feature based on your training data
- If uncertain, use an empty list and note the uncertainty in summary
- Label this as an AI estimate, not verified competitive research
- "market_urgency" = critical if multiple major competitors have it and it's a core feature"""

    result = await generate_json(prompt)

    if result and "competitors_with_feature" in result:
        result["source"] = "gemini_3_flash_estimate"
        result["caveat"] = "AI-assisted estimate based on known competitor features — not verified competitive research"
        logger.info("Competitive intel: %s → urgency=%s, competitors=%d",
                    feature_name, result.get("market_urgency"), len(result.get("competitors_with_feature", [])))
        return result

    return {
        "competitors_with_feature": [],
        "market_urgency": "unknown",
        "summary": "Could not assess competitive landscape — insufficient context",
        "sources_checked": [],
        "confidence": "low",
        "source": "gemini_3_flash_estimate",
        "caveat": "AI-assisted estimate — not verified competitive research",
    }
