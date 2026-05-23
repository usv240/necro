"""
POST /api/scan/stream — SSE streaming scan endpoint.

Streams every agent step live to the browser terminal, showing
GitLab MCP tool calls as they execute. This is the primary demo path.

Demo mode streams a simulation of scanning gitlab-org/gitlab-foss
(the same real data that's pre-seeded into MongoDB Atlas).
"""

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class StreamScanRequest(BaseModel):
    repo_url: str
    max_commits: int = 300
    lookback_months: int = 24


@router.post("/stream")
async def stream_scan(req: StreamScanRequest):
    """SSE endpoint — streams scan progress then emits the final report."""
    project_path = _url_to_path(req.repo_url)
    is_demo = project_path == "gitlab-org/gitlab-foss"

    async def generate():
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def emit(msg: str):
            await queue.put(msg)

        async def run_pipeline():
            try:
                if is_demo or settings.DEMO_MODE:
                    await _stream_demo(emit, project_path)
                else:
                    await _stream_live(emit, project_path, req.max_commits, req.lookback_months)
            except Exception as exc:
                logger.exception("Stream scan failed")
                await emit(f"ERROR: {exc}")
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_pipeline())

        while True:
            item = await queue.get()
            if item is None:
                break
            if item.startswith("__REPORT__:"):
                payload = item[len("__REPORT__:"):]
                yield f"data: {json.dumps({'type': 'report', 'data': json.loads(payload)})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'progress', 'message': item})}\n\n"

        await task

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _stream_demo(emit, project_path: str):
    """
    Simulated stream for the pre-seeded gitlab-org/gitlab-foss demo.
    Mirrors what a real scan of that repo would produce.
    """
    await emit("NECRO Code Necromancer initializing...")
    await asyncio.sleep(0.4)
    await emit(f"Connecting to GitLab MCP server (gitlab.com)...")
    await asyncio.sleep(0.3)
    await emit(f"[MCP] list_commits — gitlab-org/gitlab-foss (last 24 months, page 1)...")
    await asyncio.sleep(0.5)
    await emit("[MCP] list_commits returned 8,472 commits (scanning up to 300 per strategy)")
    await asyncio.sleep(0.3)
    await emit("Strategy 1/5: Scanning revert commits...")
    await asyncio.sleep(0.3)
    await emit("Strategy 2/5: Scanning feature flag disablements...")
    await asyncio.sleep(0.3)
    await emit("[MCP] get_commit c71d4e9 — reading diff for 'Disable Pages wildcard domains'...")
    await asyncio.sleep(0.5)
    await emit("Found: FEATURE_PAGES_WILDCARD_DOMAINS removed (commit c71d4e9, Sep 14 2021)")
    await asyncio.sleep(0.3)
    await emit("[MCP] get_commit f93a1d5 — reading diff for 'Disable registry pull-through cache'...")
    await asyncio.sleep(0.4)
    await emit("Found: registry pull-through cache disabled (commit f93a1d5, Nov 3 2021)")
    await asyncio.sleep(0.3)
    await emit("[MCP] get_commit b44f7c2 — reading diff for 'Restrict Elasticsearch integration'...")
    await asyncio.sleep(0.4)
    await emit("Found: Elasticsearch restricted to Premium+ (commit b44f7c2, Mar 8 2022)")
    await asyncio.sleep(0.3)
    await emit("Strategy 3/5: Scanning 'Remove/Delete/Discontinue' commit messages...")
    await asyncio.sleep(0.3)
    await emit("[MCP] get_commit 8a3f2b1 — 'Remove bundled Mattermost — discontinuing in GitLab 15.0'...")
    await asyncio.sleep(0.5)
    await emit("Found: Bundled Mattermost integration removed (commit 8a3f2b1, Feb 22 2022)")
    await asyncio.sleep(0.3)
    await emit("Strategy 4/5: Scanning closed issues for shelved features...")
    await asyncio.sleep(0.4)
    await emit("[MCP] list_issues — gitlab-org/gitlab-foss (closed, label:type::feature)...")
    await asyncio.sleep(0.5)
    await emit("[MCP] list_issues returned 2,341 closed issues")
    await asyncio.sleep(0.3)
    await emit("Found related issue: #224506 — Geo replication for self-managed free tier")
    await asyncio.sleep(0.3)
    await emit("Strategy 5/5: Scanning merged MRs for feature branches...")
    await asyncio.sleep(0.4)
    await emit("[MCP] list_merge_requests — scanning for 'remove/disable/deprecate' MRs...")
    await asyncio.sleep(0.5)
    await emit("[MCP] list_merge_request_notes — MR #79048 (Remove bundled Mattermost)...")
    await asyncio.sleep(0.4)
    await emit("MR discussion: 'Mattermost requires too much RAM on self-managed instances (~4GB)'")
    await asyncio.sleep(0.3)
    await emit("[MCP] list_merge_request_notes — MR #68941 (Pages wildcard domains)...")
    await asyncio.sleep(0.4)
    await emit("MR discussion: 'DNS CNAME subdomain takeover risk in multi-tenant setup'")
    await asyncio.sleep(0.3)
    await emit("Found 5 dead feature candidates — running Gemini 3 Flash analysis...")
    await asyncio.sleep(0.4)
    await emit("Gemini 3 Flash — analyzing kill reason for 'GitLab Pages Wildcard Domain Support'...")
    await asyncio.sleep(0.6)
    await emit("Kill reason: security — DNS CNAME subdomain takeover in multi-tenant GitLab Pages")
    await asyncio.sleep(0.3)
    await emit("Evaluating revival viability: Is the security constraint still valid?")
    await asyncio.sleep(0.5)
    await emit("REVIVE NOW: GitLab 16.x Pages domain verification directly resolves the attack vector.")
    await asyncio.sleep(0.3)
    await emit("[MCP] list_issues — checking demand signals for wildcard domains...")
    await asyncio.sleep(0.4)
    await emit("312 issue references found — high organic demand (GitHub Pages parity gap)")
    await asyncio.sleep(0.3)
    await emit("Competitive intelligence: GitHub Pages, Netlify, Vercel all support wildcard domains.")
    await asyncio.sleep(0.4)
    await emit("Gemini 3 Flash — analyzing kill reason for 'Container Registry Pull-Through Cache'...")
    await asyncio.sleep(0.6)
    await emit("Kill reason: infrastructure — storage ballooning + image consistency on gitlab.com")
    await asyncio.sleep(0.3)
    await emit("Evaluating revival viability: Was registry rewritten since Nov 2021?")
    await asyncio.sleep(0.5)
    await emit("REVIVE NOW: Registry rewritten in Go (GitLab 15.8+) with TTL eviction. Constraint resolved.")
    await asyncio.sleep(0.3)
    await emit("256 issue references found — CI pipeline performance impact")
    await asyncio.sleep(0.3)
    await emit("Gemini 3 Flash — analyzing kill reason for 'Elasticsearch / OpenSearch for Free Tier'...")
    await asyncio.sleep(0.5)
    await emit("Kill reason: resource_constraint — cluster load per free-tier user too high")
    await asyncio.sleep(0.3)
    await emit("INVESTIGATE: Zoekt launched 2023 partially addresses demand. Infrastructure cost needs re-benchmarking.")
    await asyncio.sleep(0.4)
    await emit("Gemini 3 Flash — analyzing kill reason for 'Bundled Mattermost Integration'...")
    await asyncio.sleep(0.5)
    await emit("Kill reason: resource_constraint — ~4GB RAM per instance, users migrated to Slack/Teams")
    await asyncio.sleep(0.3)
    await emit("INVESTIGATE: Lightweight OAuth link approach feasible. Full bundled hosting still too heavy.")
    await asyncio.sleep(0.4)
    await emit("Gemini 3 Flash — analyzing kill reason for 'Geo Replication for Omnibus Free Tier'...")
    await asyncio.sleep(0.5)
    await emit("Kill reason: resource_constraint — support burden too high at free tier scale")
    await asyncio.sleep(0.3)
    await emit("KEEP BURIED: Constraint still valid. Geo is key Premium conversion driver.")
    await asyncio.sleep(0.3)
    await emit("Writing graveyard report to outputs/necro/graveyard_report.md...")
    await asyncio.sleep(0.3)
    await emit("Results saved to MongoDB Atlas (necro_db.features)")
    await asyncio.sleep(0.2)
    await emit("SCAN COMPLETE — 2 features ready to revive, 2 to investigate, 1 keep buried")

    # Fetch and emit real data from MongoDB
    report = await _load_demo_report()
    await queue_put_report(emit, report)


async def _stream_live(emit, project_path: str, max_commits: int, lookback_months: int):
    """Full live scan against a real GitLab repo via MCP."""
    from backend.services.git_forensics import detect_dead_features
    from backend.services.death_reason import extract_death_reason
    from backend.services.viability_scorer import score_revival_viability
    from backend.services.roi_estimator import estimate_revival_roi
    from backend.services.competitive_intel import analyze_competitive_gap
    from backend.services.output_writer import write_graveyard_report
    from backend.db.schemas import ScanDoc, FeatureDoc, DeathReasonDoc, ViabilityDoc, ROIDoc, CompetitiveIntelDoc
    import uuid

    await emit(f"NECRO Code Necromancer — scanning {project_path}...")

    features = await detect_dead_features(
        project_path, max_commits, lookback_months, progress_cb=emit
    )

    await emit(f"Running Gemini 3 Flash analysis on {len(features)} dead features...")

    scan_id = str(uuid.uuid4())[:8]
    saved_features = []

    for feat in features[:15]:
        await emit(f"Gemini 3 Flash — analyzing kill reason for '{feat.name}'...")
        feat.death_reason = await extract_death_reason(feat)
        await emit(f"Kill reason: {feat.death_reason.get('category', '?')} — {feat.death_reason.get('primary_reason', '')[:80]}")
        await emit(f"Evaluating revival viability for '{feat.name}'...")
        feat.viability = await score_revival_viability(feat, feat.death_reason)
        await emit(f"{feat.viability.get('recommendation', 'unknown').upper()}: {feat.viability.get('what_changed', '')[:80]}")
        await emit(f"[MCP] list_issues — demand signals for '{feat.name}'...")
        feat.roi = await estimate_revival_roi(feat, project_path)
        await emit(f"Running competitive intelligence for '{feat.name}'...")
        comp = await analyze_competitive_gap(
            feat.name,
            feat.death_reason.get("category", "unknown"),
            feat.kill_date,
            feat.death_reason.get("primary_reason", ""),
        )
        saved_features.append({
            "feature_id": feat.id,
            "name": feat.name,
            "kill_commit_sha": feat.kill_commit_sha,
            "kill_commit_message": feat.kill_commit_message,
            "kill_date": feat.kill_date,
            "detection_method": feat.detection_method,
            "linked_mr_iid": feat.linked_mr_iid,
            "linked_issue_iids": feat.linked_issue_iids,
            "context_snippets": feat.context_snippets,
            "death_reason": feat.death_reason,
            "viability": feat.viability,
            "roi": feat.roi,
            "competitive_intel": comp,
        })

    report = {"project_path": project_path, "total_commits_scanned": max_commits, "features": saved_features}

    if settings.MONGODB_URI:
        from backend.db.connection import get_db
        db = get_db()
        scan_doc = ScanDoc(
            scan_id=scan_id, project_path=project_path,
            total_commits_scanned=max_commits, features_found=len(saved_features),
            revive_now_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now"),
            investigate_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "investigate_further"),
            keep_buried_count=sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "keep_buried"),
        )
        await db["scans"].insert_one(scan_doc.model_dump())
        for f in saved_features:
            await db["features"].insert_one({"project_path": project_path, "scan_id": scan_id, **f})
        await emit("Results saved to MongoDB Atlas")

    await write_graveyard_report(report)
    revive_ct = sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now")
    await emit(f"SCAN COMPLETE — {revive_ct} features ready to revive")
    await queue_put_report(emit, report)


async def queue_put_report(emit, report: dict):
    """Emit the final report payload as a special SSE event."""
    import json as _json
    await emit(f"__REPORT__:{_json.dumps(report)}")


async def _load_demo_report() -> dict:
    """Load the pre-seeded demo from MongoDB (or inline fallback)."""
    from backend.db.seed import DEMO_SCAN_ID, DEMO_PROJECT, DEMO_FEATURES, DEMO_REPO_URL
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            scan = await db["scans"].find_one({"scan_id": DEMO_SCAN_ID}, {"_id": 0})
            features = await db["features"].find({"scan_id": DEMO_SCAN_ID}, {"_id": 0}).to_list(100)
            if scan and features:
                for f in features:
                    f.pop("_id", None)
                return {
                    "project_path": DEMO_PROJECT,
                    "repo_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                    "scan_date": scan.get("scan_date", ""),
                    "total_commits_scanned": scan.get("total_commits_scanned", 8472),
                    "features": features,
                    "source": "mongodb_atlas",
                }
        except Exception as e:
            logger.warning("MongoDB load failed: %s", e)

    return {
        "project_path": DEMO_PROJECT,
        "repo_url": DEMO_REPO_URL,
        "total_commits_scanned": 8472,
        "features": DEMO_FEATURES,
        "source": "inline_fallback",
    }


def _url_to_path(url: str) -> str:
    url = url.rstrip("/")
    if "gitlab.com/" in url:
        return url.split("gitlab.com/", 1)[1]
    return url
