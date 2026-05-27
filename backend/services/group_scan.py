"""
Cross-Repository Graveyard Federation — Group-Level Resurrection Chains.

Scans every repository in a GitLab namespace and federates the feature graveyards
to reveal cross-repo patterns:

  "The 'redis-cluster-version' constraint killed 23 features across 14 repositories.
   Fix ONE infrastructure constraint — unlock 23 features in a single sprint."

This makes the invisible organizational dependency graph visible.
Features die along dependency lines — the graveyard IS the real architecture diagram.

Most valuable insight: teams working in silos on the same underlying problem.
One DevOps fix creates value across the entire engineering organization.
"""

import asyncio
import logging
import re
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# Same tech keywords as stream.py resurrection chains — extended for cross-repo
_CROSS_REPO_KEYWORDS = [
    "webpack", "angular", "react", "vue", "rails", "django", "flask",
    "postgres", "mysql", "redis", "elasticsearch", "kubernetes", "docker",
    "oauth", "graphql", "grpc", "websocket", "sidekiq", "celery",
    "kafka", "rabbitmq", "nginx", "node", "python", "ruby", "golang",
    "typescript", "safari", "firefox", "chrome", "ie11", "internet explorer",
    "openssl", "jwt", "cors", "csrf", "s3", "gcs", "azure",
    "terraform", "ansible", "ldap", "saml", "sso", "vault",
    "aws", "gcp", "cloudflare", "nginx", "haproxy", "envoy",
    "grpc", "protobuf", "thrift", "avro", "parquet",
    "cuda", "tensorflow", "pytorch", "openai",
]


async def scan_group(
    namespace: str,
    max_repos: int = 10,
    max_commits_per_repo: int = 100,
    lookback_months: int = 24,
) -> dict:
    """
    Scan all repositories in a GitLab group namespace.
    Returns federated cross-repo resurrection chains + per-repo summaries.

    Args:
        namespace:            GitLab group path (e.g. "gitlab-org" or "mycompany/backend")
        max_repos:            cap on repos to scan (default 10 to keep it fast)
        max_commits_per_repo: lightweight scan per repo (default 100)
        lookback_months:      how far back to look per repo
    """
    from backend.services.gitlab_mcp import mcp

    logger.info("[GroupScan] Starting group scan: %s (max %d repos)", namespace, max_repos)

    # List all projects in the namespace
    try:
        projects = await mcp.list_projects_in_group(namespace, per_page=max_repos)
    except Exception as exc:
        logger.warning("[GroupScan] list_projects_in_group failed: %s", exc)
        projects = []

    if not projects:
        return {
            "namespace": namespace,
            "error": f"No repositories found in namespace '{namespace}'. "
                     f"Check the namespace path and GitLab token permissions.",
            "repos_scanned": 0,
            "total_features": 0,
            "cross_repo_chains": [],
            "per_repo": [],
        }

    projects = projects[:max_repos]
    logger.info("[GroupScan] Found %d repos — scanning in parallel...", len(projects))

    # Parallel lightweight scan of all repos
    scan_tasks = [
        _scan_single_repo(
            p.get("path_with_namespace", p.get("path", "")),
            max_commits_per_repo,
            lookback_months,
        )
        for p in projects
        if p.get("path_with_namespace") or p.get("path")
    ]

    raw_results = await asyncio.gather(*scan_tasks, return_exceptions=True)

    per_repo: list[dict] = []
    all_features: list[dict] = []

    for i, result in enumerate(raw_results):
        project_path = projects[i].get("path_with_namespace", "")
        if isinstance(result, Exception):
            logger.warning("[GroupScan] Scan failed for %s: %s", project_path, result)
            per_repo.append({
                "project_path": project_path,
                "status": "error",
                "error": str(result),
                "features": [],
            })
        elif isinstance(result, dict):
            per_repo.append(result)
            all_features.extend(result.get("features", []))
        else:
            per_repo.append({"project_path": project_path, "status": "empty", "features": []})

    # Federate — find cross-repo patterns
    cross_repo_chains = _federate_graveyards(all_features)

    # Persist to MongoDB if available
    if settings.MONGODB_URI:
        asyncio.create_task(
            _persist_group_scan(namespace, all_features, cross_repo_chains)
        )

    revive_now_total = sum(
        1 for f in all_features
        if (f.get("viability") or {}).get("recommendation") == "revive_now"
    )

    logger.info(
        "[GroupScan] Complete — %d repos, %d features, %d cross-repo chains, %d revive_now",
        len(per_repo), len(all_features), len(cross_repo_chains), revive_now_total,
    )

    return {
        "namespace": namespace,
        "repos_scanned": len([r for r in per_repo if r.get("status") != "error"]),
        "repos_attempted": len(projects),
        "total_features": len(all_features),
        "revive_now_total": revive_now_total,
        "cross_repo_chains": cross_repo_chains,
        "per_repo": [
            {
                "project_path": r["project_path"],
                "status": r.get("status", "ok"),
                "features_found": len(r.get("features", [])),
                "revive_now": sum(
                    1 for f in r.get("features", [])
                    if (f.get("viability") or {}).get("recommendation") == "revive_now"
                ),
                "top_feature": (
                    r["features"][0].get("name", "") if r.get("features") else ""
                ),
            }
            for r in per_repo
        ],
        "orchestrated_by": "google_cloud_agent_builder_adk",
        "data_source": "gitlab_mcp",
    }


async def _scan_single_repo(
    project_path: str,
    max_commits: int,
    lookback_months: int,
) -> dict:
    """
    Lightweight NECRO scan for one repo — forensics only, no ADK synthesis.
    Fast enough to run 10 repos in parallel.
    """
    if not project_path:
        return {"project_path": project_path, "status": "skip", "features": []}

    try:
        from backend.services.git_forensics import detect_dead_features
        from backend.services.death_reason import extract_death_reason
        from backend.services.viability_scorer import score_revival_viability
        from backend.routes.stream import _compute_revival_score

        features = await detect_dead_features(
            project_path, max_commits=max_commits, lookback_months=lookback_months
        )

        results = []
        for feat in features[:8]:  # cap per repo to keep federation fast
            try:
                feat.death_reason = await extract_death_reason(feat)
                feat.viability = await score_revival_viability(feat, feat.death_reason)

                feat_dict = {
                    "feature_id": feat.id,
                    "name": feat.name,
                    "project_path": project_path,
                    "kill_commit_message": feat.kill_commit_message,
                    "kill_date": feat.kill_date,
                    "detection_method": feat.detection_method,
                    "death_reason": feat.death_reason,
                    "viability": feat.viability,
                }
                feat_dict["revival_score"] = _compute_revival_score(feat_dict)
                results.append(feat_dict)
            except Exception as feat_err:
                logger.debug("[GroupScan] Feature analysis error in %s: %s", project_path, feat_err)

        return {
            "project_path": project_path,
            "status": "scanned",
            "features": results,
            "commits_scanned": max_commits,
        }

    except Exception as exc:
        logger.warning("[GroupScan] Repo scan failed for %s: %s", project_path, exc)
        return {"project_path": project_path, "status": "error", "error": str(exc), "features": []}


def _federate_graveyards(all_features: list[dict]) -> list[dict]:
    """
    Cross-repository resurrection chains.

    Groups features by shared constraint keyword across ALL repos.
    Only surfaces patterns that appear in ≥2 different repositories —
    these are organizational-level constraints, not repo-specific issues.

    Returns chains sorted by cross_repo_count descending.
    """
    if not all_features:
        return []

    def extract_constraint_keys(feat: dict) -> set[str]:
        dr = feat.get("death_reason") or {}
        vi = feat.get("viability") or {}
        text = " ".join([
            dr.get("specific_constraint", ""),
            dr.get("primary_reason", ""),
            feat.get("kill_commit_message", ""),
            vi.get("what_changed", ""),
        ]).lower()

        keys = set()
        for kw in _CROSS_REPO_KEYWORDS:
            if kw in text:
                keys.add(kw)

        # also pull first significant word from specific_constraint
        constraint = dr.get("specific_constraint", "").strip()
        if constraint:
            words = [w for w in re.split(r"\W+", constraint.lower()) if len(w) > 4]
            if words:
                keys.add(words[0])

        return keys

    # keyword → list of (project_path, feature_dict)
    keyword_map: dict[str, list[dict]] = {}
    for feat in all_features:
        for key in extract_constraint_keys(feat):
            keyword_map.setdefault(key, []).append(feat)

    chains = []
    seen: set[frozenset] = set()

    for keyword, matching_feats in sorted(
        keyword_map.items(), key=lambda x: len(x[1]), reverse=True
    ):
        if len(matching_feats) < 2:
            continue

        # Only surface cross-REPO patterns (not just cross-feature within same repo)
        repos_affected = {f.get("project_path", "") for f in matching_feats}
        if len(repos_affected) < 2:
            continue  # Same repo only — already covered by single-repo resurrection chains

        fid_set = frozenset(
            f"{f.get('project_path', '')}::{f.get('feature_id', f.get('name', ''))}"
            for f in matching_feats
        )
        if fid_set in seen:
            continue
        seen.add(fid_set)

        revivable = [
            f for f in matching_feats
            if (f.get("viability") or {}).get("recommendation") in ("revive_now", "investigate_further")
        ]

        # Estimate org-level ROI
        total_demand = sum(
            (f.get("roi") or {}).get("request_count", 0) for f in revivable
        )

        what_changed_examples = [
            f.get("viability", {}).get("what_changed", "")
            for f in matching_feats if f.get("viability", {}).get("what_changed")
        ]
        fix_suggestion = (
            what_changed_examples[0][:120]
            if what_changed_examples
            else f"Resolve the {keyword} constraint across all affected services"
        )

        impact = "critical" if len(repos_affected) >= 4 else "high" if len(repos_affected) >= 2 else "medium"

        chains.append({
            "constraint_key": keyword,
            "cross_repo_count": len(repos_affected),
            "feature_count": len(matching_feats),
            "revivable_count": len(revivable),
            "repos_affected": sorted(repos_affected),
            "features": [
                {"name": f.get("name", "?"), "repo": f.get("project_path", "?")}
                for f in matching_feats[:8]
            ],
            "fix_suggestion": fix_suggestion,
            "total_demand_signals": total_demand,
            "impact": impact,
            "org_unlock": (
                f"Fix {keyword} once → unlock {len(matching_feats)} features "
                f"across {len(repos_affected)} repositories"
            ),
        })

    return chains[:8]  # top 8 cross-repo chains


async def _persist_group_scan(
    namespace: str,
    features: list[dict],
    chains: list[dict],
) -> None:
    """Persist group scan results to MongoDB for historical comparison."""
    try:
        from backend.db.connection import get_db
        from datetime import datetime, timezone
        db = get_db()
        await db["group_scans"].insert_one({
            "namespace": namespace,
            "scanned_at": datetime.now(timezone.utc),
            "total_features": len(features),
            "cross_repo_chains": chains,
            "revive_now_count": sum(
                1 for f in features
                if (f.get("viability") or {}).get("recommendation") == "revive_now"
            ),
        })
    except Exception as exc:
        logger.debug("[GroupScan] Persist failed: %s", exc)
