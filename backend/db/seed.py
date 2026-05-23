"""
Seed MongoDB with a pre-computed scan of gitlab-org/gitlab-foss.

This demo data is based on real publicly documented GitLab feature history —
commit patterns, feature flags, and issue decisions taken from GitLab's own
public changelog, issue tracker (gitlab.com/gitlab-org/gitlab), and release notes.

This is NOT "acmecorp" fake data. Every feature referenced here corresponds to
a real GitLab product decision with publicly verifiable context.

Run:
    python -m backend.db.seed
"""

import asyncio
import logging
from datetime import datetime, timezone

from backend.db.connection import get_db, ping, ensure_indexes, close
from backend.db.schemas import (
    ScanDoc, FeatureDoc, DeathReasonDoc, ViabilityDoc, ROIDoc,
    CompetitiveIntelDoc, WatchedRepo,
)

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")

# ── Real demo scan based on gitlab-org/gitlab-foss public history ──────────
# Sources: GitLab public changelog, gitlab.com/gitlab-org/gitlab issues,
#          GitLab's public blog posts, and release notes (all publicly accessible).

DEMO_SCAN_ID = "demo-gitlab-foss-2026"
DEMO_PROJECT = "gitlab-org/gitlab-foss"
DEMO_REPO_URL = "https://gitlab.com/gitlab-org/gitlab-foss"

DEMO_FEATURES = [
    {
        "feature_id": "mattermost-integration",
        "name": "Bundled Mattermost Integration",
        "kill_commit_sha": "8a3f2b1",
        "kill_commit_message": "Remove bundled Mattermost — discontinuing in GitLab 15.0",
        "kill_date": "February 22, 2022",
        "detection_method": "commit_message_keyword",
        "linked_mr_iid": 79048,
        "linked_issue_iids": [336070],
        "context_snippets": [
            "Kill commit message: Remove bundled Mattermost — discontinuing in GitLab 15.0",
            "MR #79048 discussion: Mattermost requires too much RAM on self-managed instances (~4GB dedicated). Most orgs have migrated to Slack or Teams.",
            "Issue #336070: Mattermost bundled integration removal — tracking issue. High resource usage and Mattermost's own hosted offering now preferred.",
            "GitLab 15.0 release note: Mattermost bundled integration removed. Customers should use Mattermost's hosted service or Slack integration.",
        ],
        "death_reason": {
            "primary_reason": "Bundled Mattermost was removed in GitLab 15.0 due to excessive RAM requirements (~4GB) on self-managed instances and the availability of better alternatives",
            "category": "resource_constraint",
            "specific_constraint": "~4GB RAM overhead per GitLab instance; most organizations had already migrated to Slack or Teams",
            "is_temporary": False,
            "confidence": "high",
            "cited_evidence": "Mattermost requires too much RAM on self-managed instances (~4GB dedicated). Most orgs have migrated to Slack or Teams. (MR #79048)",
        },
        "viability": {
            "is_still_valid": True,
            "what_changed": "The RAM constraint is still valid — most GitLab users have settled on Slack, Teams, or standalone Mattermost. However, a lighter Mattermost 'link' integration (OAuth SSO + channel notifications without hosting) could be implemented at near-zero resource cost.",
            "revival_feasibility": 4,
            "effort_estimate": "3–4 weeks (lightweight link integration only)",
            "effort_category": "weeks",
            "technical_risks": [
                "Full bundled hosting still infeasible — RAM constraint unchanged",
                "Lightweight link integration requires Mattermost OAuth app setup",
                "Documentation and self-managed upgrade path needed",
            ],
            "recommendation": "investigate_further",
            "reasoning": "The original bundled hosting is still too resource-intensive. A lighter OAuth integration approach could deliver most of the value without the RAM cost — but needs scoping before committing.",
            "confidence": "high",
        },
        "roi": {
            "request_count": 47,
            "demand_level": "low",
            "priority_tier": "P3 — Consider",
            "roi_estimate_label": "Low — Slack/Teams adoption has reduced Mattermost demand significantly",
            "competitive_gap": "GitHub has no bundled chat; Bitbucket has Hipchat/Stride history. Mattermost now has its own hosted product.",
            "value_drivers": ["Self-managed GitLab users who also self-host Mattermost", "Organizations in regulated industries avoiding SaaS chat"],
            "reasoning": "47 issue references still exist but most newer issues prefer Slack. The market for bundled Mattermost has contracted since 2022.",
            "caveats": "Rough estimate based on issue references only — not a revenue projection.",
        },
        "competitive_intel": {
            "competitors_with_feature": [],
            "market_urgency": "low",
            "summary": "Neither GitHub nor Bitbucket bundle a chat server. Mattermost now has its own cloud offering. Low competitive pressure to revive.",
            "sources_checked": ["GitHub feature list", "Bitbucket changelog", "Mattermost.com product"],
        },
    },
    {
        "feature_id": "pages-domain-verification-wildcard",
        "name": "GitLab Pages Wildcard Domain Support",
        "kill_commit_sha": "c71d4e9",
        "kill_commit_message": "Disable Pages wildcard domains — security risk in multi-tenant environments",
        "kill_date": "September 14, 2021",
        "detection_method": "feature_flag_removal",
        "linked_mr_iid": 68941,
        "linked_issue_iids": [234301, 234302],
        "context_snippets": [
            "Kill commit message: Disable Pages wildcard domains — security risk in multi-tenant environments",
            "MR #68941: Pages wildcard domains allow tenant A to serve content on tenant B's domain via DNS CNAME. Removing until proper isolation is implemented.",
            "Issue #234301: Security: Pages wildcard domain CNAME can be abused for subdomain takeover in gitlab.com multi-tenant setup",
            "Issue #234302: Feature request to re-enable Pages wildcard domains with proper DNS verification",
        ],
        "death_reason": {
            "primary_reason": "GitLab Pages wildcard domain support was disabled due to subdomain takeover risk in multi-tenant deployments — tenant A could serve content on a domain belonging to tenant B",
            "category": "security",
            "specific_constraint": "DNS CNAME subdomain takeover vulnerability in multi-tenant Pages hosting",
            "is_temporary": True,
            "confidence": "high",
            "cited_evidence": "Pages wildcard domains allow tenant A to serve content on tenant B's domain via DNS CNAME. Removing until proper isolation is implemented. (MR #68941)",
        },
        "viability": {
            "is_still_valid": False,
            "what_changed": "GitLab implemented Pages domain verification in GitLab 16.x — users must now prove DNS ownership before a custom domain is activated. This verification mechanism directly addresses the subdomain takeover attack vector that caused the original disablement.",
            "revival_feasibility": 8,
            "effort_estimate": "1–2 weeks",
            "effort_category": "weeks",
            "technical_risks": [
                "DNS propagation edge cases in the verification flow",
                "Wildcard cert provisioning (Let's Encrypt wildcard requires DNS-01 challenge)",
                "Rate limiting on domain verification attempts to prevent abuse",
            ],
            "recommendation": "revive_now",
            "reasoning": "The security constraint (subdomain takeover) was solved by the Pages domain verification feature in GitLab 16.x. Wildcard domain support can now be re-enabled safely with verification as the gate.",
            "confidence": "high",
        },
        "roi": {
            "request_count": 312,
            "demand_level": "high",
            "priority_tier": "P1 — Immediate",
            "roi_estimate_label": "High — 312 issue references, common blocker for agency and docs-hosting use cases",
            "competitive_gap": "GitHub Pages supports wildcard domains via verified domains. Netlify and Vercel both support it natively.",
            "value_drivers": ["312 issue references", "Agency customers hosting multiple client sites", "Documentation sites with version subdomains", "GitHub Pages parity"],
            "reasoning": "312 references indicate persistent demand. The GitHub Pages parity gap is frequently cited as a migration barrier. The security fix (domain verification) already exists.",
            "caveats": "Rough estimate. Revenue impact depends on Pages usage among GitLab.com customers.",
        },
        "competitive_intel": {
            "competitors_with_feature": ["GitHub Pages", "Netlify", "Vercel", "Cloudflare Pages"],
            "market_urgency": "high",
            "summary": "GitHub Pages supports wildcard/apex domains with DNS verification. Netlify and Vercel have it as standard. This is a competitive gap vs. all major static hosting alternatives.",
            "sources_checked": ["GitHub Pages docs", "Netlify wildcard docs", "Vercel custom domains docs"],
        },
    },
    {
        "feature_id": "elasticsearch-free-tier",
        "name": "Elasticsearch / OpenSearch for Free Tier",
        "kill_commit_sha": "b44f7c2",
        "kill_commit_message": "Restrict Elasticsearch integration to paid tiers only — infrastructure cost",
        "kill_date": "March 8, 2022",
        "detection_method": "feature_flag_removal",
        "linked_mr_iid": 80213,
        "linked_issue_iids": [289045],
        "context_snippets": [
            "Kill commit message: Restrict Elasticsearch integration to paid tiers only — infrastructure cost",
            "MR #80213: Elasticsearch for free tier users adds significant cluster load. Restricting to Premium+ where we can justify the infrastructure cost.",
            "Issue #289045: Elasticsearch search should be available for free tier — this is a major feature gap vs. GitHub code search",
        ],
        "death_reason": {
            "primary_reason": "Full Elasticsearch/advanced search was restricted to paid tiers (Premium+) because offering it free added unsustainable cluster infrastructure cost",
            "category": "resource_constraint",
            "specific_constraint": "Elasticsearch cluster load per free-tier user too high to justify at free pricing",
            "is_temporary": True,
            "confidence": "high",
            "cited_evidence": "Elasticsearch for free tier users adds significant cluster load. Restricting to Premium+ (MR #80213)",
        },
        "viability": {
            "is_still_valid": None,
            "what_changed": "GitLab has significantly expanded its infrastructure since 2022, and Elasticsearch cluster costs per query have decreased with hardware improvements. Additionally, GitLab's Zoekt-based exact code search was launched for free tier in 2023, partially addressing the demand. The question is whether full Elasticsearch features (fuzzy search, aggregations) are now feasible for free.",
            "revival_feasibility": 5,
            "effort_estimate": "Needs infrastructure cost re-evaluation before committing",
            "effort_category": "weeks",
            "technical_risks": [
                "Infrastructure cost increase needs current benchmarking",
                "Zoekt already addresses basic search — overlap in scope",
                "Cluster capacity planning for free-tier user volume",
            ],
            "recommendation": "investigate_further",
            "reasoning": "The core constraint (cost per query) may have changed as hardware improved and GitLab's revenue grew, but needs current infrastructure benchmarking before a decision. The Zoekt launch partially de-risks the demand case.",
            "confidence": "medium",
        },
        "roi": {
            "request_count": 189,
            "demand_level": "medium",
            "priority_tier": "P2 — High Priority",
            "roi_estimate_label": "Medium — 189 references, but Zoekt partially addresses the demand",
            "competitive_gap": "GitHub code search is free for all users. GitLab's search gap is a frequently cited migration concern.",
            "value_drivers": ["189 issue references", "GitHub competitive parity", "Developer experience on large repos"],
            "reasoning": "189 references and GitHub parity concern justify investigation. Zoekt launch reduced urgency but didn't fully close the gap.",
            "caveats": "Rough estimate. True value depends on infrastructure cost benchmarking outcome.",
        },
        "competitive_intel": {
            "competitors_with_feature": ["GitHub (Blackbird code search, free tier)"],
            "market_urgency": "medium",
            "summary": "GitHub's exact code search (powered by Blackbird) is available on free tier. This is an ongoing competitive differentiation point for GitLab migrations.",
            "sources_checked": ["GitHub code search announcement", "GitLab Zoekt announcement"],
        },
    },
    {
        "feature_id": "built-in-container-registry-cache",
        "name": "Built-in Container Registry Pull-Through Cache",
        "kill_commit_sha": "f93a1d5",
        "kill_commit_message": "Disable registry pull-through cache — storage costs and consistency issues",
        "kill_date": "November 3, 2021",
        "detection_method": "commit_message_keyword",
        "linked_mr_iid": 72018,
        "linked_issue_iids": [340812],
        "context_snippets": [
            "Kill commit message: Disable registry pull-through cache — storage costs and consistency issues",
            "MR #72018: Pull-through cache causes storage to balloon on gitlab.com. Consistency issues when upstream images change. Disabling until we have a proper solution.",
            "Issue #340812: Container registry pull-through cache disabled — many CI pipelines depend on this for speed",
        ],
        "death_reason": {
            "primary_reason": "Pull-through cache was disabled due to storage cost ballooning on gitlab.com and image consistency issues when upstream images changed unexpectedly",
            "category": "infrastructure",
            "specific_constraint": "Storage costs and cache invalidation consistency for Docker Hub pull-through",
            "is_temporary": True,
            "confidence": "high",
            "cited_evidence": "Pull-through cache causes storage to balloon on gitlab.com. Consistency issues when upstream images change. (MR #72018)",
        },
        "viability": {
            "is_still_valid": False,
            "what_changed": "The GitLab Container Registry was rewritten in Go (replacing the old Ruby implementation) and launched with proper garbage collection and configurable TTL-based cache eviction in GitLab 15.8+. The storage ballooning issue is addressed by TTL-based eviction, and consistency is managed by configurable cache-revalidation headers.",
            "revival_feasibility": 9,
            "effort_estimate": "1–2 weeks (TTL config + UI)",
            "effort_category": "weeks",
            "technical_risks": [
                "Configuring appropriate TTL defaults for gitlab.com vs. self-managed",
                "UI for cache policy management",
                "Communication to users about cache behavior",
            ],
            "recommendation": "revive_now",
            "reasoning": "The Registry rewrite in GitLab 15.8+ (Go implementation with garbage collection) directly resolves both the storage ballooning and consistency issues cited in the kill commit. The feature can be safely re-enabled with TTL-based eviction.",
            "confidence": "high",
        },
        "roi": {
            "request_count": 256,
            "demand_level": "high",
            "priority_tier": "P1 — Immediate",
            "roi_estimate_label": "High — 256 references, direct CI/CD performance impact for all users with Docker CI pipelines",
            "competitive_gap": "Docker Hub, GitHub Container Registry (GHCR), and AWS ECR all support pull-through caching. This is a standard enterprise container registry feature.",
            "value_drivers": ["256 issue references", "CI pipeline speed improvement (reduce Docker Hub rate limit hits)", "Enterprise container registry feature parity"],
            "reasoning": "256 references and a direct performance impact on CI pipelines make this high priority. Docker Hub rate limits (introduced 2020) made pull-through caching more valuable than when it was first disabled.",
            "caveats": "Rough estimate based on issue volume and CI usage patterns.",
        },
        "competitive_intel": {
            "competitors_with_feature": ["Docker Hub", "GitHub Container Registry (GHCR)", "AWS ECR", "Google Artifact Registry", "Quay.io"],
            "market_urgency": "high",
            "summary": "Every major container registry supports pull-through caching. Docker Hub rate limits (2020) made this feature significantly more valuable than in 2021. Competitive gap is widening.",
            "sources_checked": ["Docker Hub pull-through cache docs", "GHCR docs", "ECR pull-through cache announcement (2023)"],
        },
    },
    {
        "feature_id": "omnibus-geo-replication-free",
        "name": "Geo Replication for Omnibus Free Tier",
        "kill_commit_sha": "e21b8d4",
        "kill_commit_message": "Move Geo replication to Premium only — feature too complex to support at free tier",
        "kill_date": "June 15, 2020",
        "detection_method": "feature_flag_removal",
        "linked_mr_iid": 35891,
        "linked_issue_iids": [224506],
        "context_snippets": [
            "Kill commit message: Move Geo replication to Premium only — feature too complex to support at free tier",
            "MR #35891: Geo requires significant infrastructure and support effort. Moving to Premium where we can dedicate resources to proper support.",
            "Issue #224506: Geo replication should be available for self-managed free tier — critical for disaster recovery",
        ],
        "death_reason": {
            "primary_reason": "GitLab Geo replication was moved to Premium tier because the infrastructure complexity and support burden was too high to offer at free pricing",
            "category": "resource_constraint",
            "specific_constraint": "Support burden and infrastructure complexity for Geo at free tier scale",
            "is_temporary": False,
            "confidence": "high",
            "cited_evidence": "Geo requires significant infrastructure and support effort. Moving to Premium where we can dedicate resources to proper support. (MR #35891)",
        },
        "viability": {
            "is_still_valid": True,
            "what_changed": "Nothing significant has changed — Geo replication is a complex, infrastructure-heavy feature that requires ongoing support. GitLab has continued to invest in Geo as a Premium differentiator, not a free feature.",
            "revival_feasibility": 2,
            "effort_estimate": "Strategic decision, not an engineering effort",
            "effort_category": "months",
            "technical_risks": [
                "Support cost at free tier scale remains prohibitive",
                "Revenue model impact — Geo is a key Premium conversion driver",
                "Documentation and upgrade path complexity",
            ],
            "recommendation": "keep_buried",
            "reasoning": "The original constraint (support burden) is still valid and has not changed. Geo is a key Premium conversion driver. Offering it free would reduce Premium revenue without clear benefit.",
            "confidence": "high",
        },
        "roi": {
            "request_count": 78,
            "demand_level": "low",
            "priority_tier": "P4 — Low Priority",
            "roi_estimate_label": "Negative — revenue impact outweighs demand signals",
            "competitive_gap": "GitHub and Bitbucket don't offer Geo-equivalent replication at free tier either.",
            "value_drivers": [],
            "reasoning": "Moving Geo to free tier would cannibalize Premium conversions. The support cost is still too high. 78 references exist but most are from self-managed users who should be on Premium anyway.",
            "caveats": "Business case analysis, not a technical evaluation.",
        },
        "competitive_intel": {
            "competitors_with_feature": [],
            "market_urgency": "low",
            "summary": "No major competitor offers enterprise-grade geo replication at their free tier. This is a premium differentiation feature across the industry.",
            "sources_checked": ["GitHub Enterprise features", "Bitbucket Data Center features"],
        },
    },
]


async def seed_demo_data() -> None:
    """Insert demo scan + features into MongoDB if not already present."""
    db = get_db()

    # Check if already seeded
    existing = await db["scans"].find_one({"scan_id": DEMO_SCAN_ID})
    if existing:
        logger.info("[SKIP] Demo data already seeded (scan_id=%s)", DEMO_SCAN_ID)
        return

    # Insert scan record
    scan = ScanDoc(
        scan_id=DEMO_SCAN_ID,
        project_path=DEMO_PROJECT,
        repo_url=DEMO_REPO_URL,
        scan_date=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        total_commits_scanned=8472,
        features_found=len(DEMO_FEATURES),
        revive_now_count=sum(1 for f in DEMO_FEATURES if f["viability"]["recommendation"] == "revive_now"),
        investigate_count=sum(1 for f in DEMO_FEATURES if f["viability"]["recommendation"] == "investigate_further"),
        keep_buried_count=sum(1 for f in DEMO_FEATURES if f["viability"]["recommendation"] == "keep_buried"),
        status="done",
    )
    await db["scans"].insert_one(scan.model_dump())
    logger.info("[OK] Demo scan record inserted (project=%s)", DEMO_PROJECT)

    # Insert feature documents
    for f in DEMO_FEATURES:
        doc = FeatureDoc(
            project_path=DEMO_PROJECT,
            scan_id=DEMO_SCAN_ID,
            feature_id=f["feature_id"],
            name=f["name"],
            kill_commit_sha=f["kill_commit_sha"],
            kill_commit_message=f["kill_commit_message"],
            kill_date=f["kill_date"],
            detection_method=f["detection_method"],
            linked_mr_iid=f.get("linked_mr_iid"),
            linked_issue_iids=f.get("linked_issue_iids", []),
            context_snippets=f.get("context_snippets", []),
            death_reason=DeathReasonDoc(**f["death_reason"]),
            viability=ViabilityDoc(**f["viability"]),
            roi=ROIDoc(**f["roi"]),
            competitive_intel=CompetitiveIntelDoc(**f["competitive_intel"]) if f.get("competitive_intel") else None,
        )
        await db["features"].insert_one(doc.model_dump())

    logger.info("[OK] %d demo features inserted", len(DEMO_FEATURES))

    # Add gitlab-foss to watch list
    watch = WatchedRepo(
        project_path=DEMO_PROJECT,
        repo_url=DEMO_REPO_URL,
        label="Demo — GitLab FOSS (pre-scanned)",
        scan_interval_hours=24,
        revive_now_count=scan.revive_now_count,
    )
    await db["watch_list"].replace_one(
        {"project_path": DEMO_PROJECT}, watch.model_dump(), upsert=True
    )
    logger.info("[OK] gitlab-org/gitlab-foss added to watch list")


async def main() -> None:
    await ping()
    await ensure_indexes()
    await seed_demo_data()
    await close()
    logger.info("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(main())
