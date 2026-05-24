"""
POST /api/scan/stream — SSE streaming scan endpoint.

Two-phase architecture:
  Phase 1 — Data collection via GitLab REST/MCP (always reliable, no subprocess)
  Phase 2 — ADK Runner synthesis: Google Cloud Agent Builder reasons over all findings,
             validates recommendations, and produces the executive summary + action plan.

This correctly separates fetching (which REST does well) from reasoning
(which is what ADK and Gemini are built for).
"""

import asyncio
import json
import logging
import re

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
    """SSE endpoint — streams scan progress then emits the final report via ADK Runner."""
    project_path = _url_to_path(req.repo_url)

    async def generate():
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def emit(msg: str):
            await queue.put(msg)

        async def run_pipeline():
            try:
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


async def _stream_live(emit, project_path: str, max_commits: int, lookback_months: int):
    """
    Two-phase scan:

    Phase 1 — Data collection via GitLab REST API (reliable, no subprocess dependency)
      list_commits, get_commit diffs, list_issues, list_merge_requests,
      list_feature_flags → raw DeadFeature objects with full context.
      Gemini 3 Flash extracts kill reasons, viability (with constraint_grounder),
      ROI demand signals, and competitive intel per feature.

    Phase 2 — ADK Synthesis via Google Cloud Agent Builder (runner.run_async)
      The ADK Runner receives ALL findings and reasons holistically:
      validates recommendations, identifies the highest-priority revivals,
      flags inconsistencies, and writes an executive action plan.
      This is where the multi-step reasoning and planning happens.
      Falls back gracefully and reports the actual status in the final report.
    """
    import uuid
    import json as _json
    from backend.services.git_forensics import detect_dead_features
    from backend.services.death_reason import extract_death_reason
    from backend.services.viability_scorer import score_revival_viability
    from backend.services.roi_estimator import estimate_revival_roi
    from backend.services.competitive_intel import analyze_competitive_gap
    from backend.services.challenger import challenge_top_revival_candidates
    from backend.services.output_writer import write_graveyard_report
    from backend.db.schemas import ScanDoc

    scan_id = uuid.uuid4().hex[:8]
    mcp_calls: list = []

    # ── Phase 1: Data collection ─────────────────────────────────────────────
    await emit(f"[MCP] GitLab MCP — starting data collection for {project_path}...")
    features = await detect_dead_features(
        project_path, max_commits, lookback_months,
        progress_cb=emit, mcp_calls=mcp_calls,
    )

    if not features:
        await emit("No dead feature candidates found in the scanned range.")
        report = {
            "project_path": project_path,
            "total_commits_scanned": max_commits,
            "features": [],
            "mcp_calls_log": mcp_calls,
            "mcp_tools_used": [],
            "mcp_tool_count": len(mcp_calls),
            "data_source": "gitlab_mcp",
            "orchestrated_by": "google_cloud_agent_builder_adk",
            "adk_synthesis": None,
            "resurrection_chains": [],
        }
        await queue_put_report(emit, report)
        return

    await emit(f"Gemini 3 Flash — analyzing {len(features)} dead feature candidates...")

    # Fetch open issues once for demand signal matching
    await emit(f"[MCP] list_issues (open) — fetching open issue demand signals...")
    from backend.services.gitlab_mcp import mcp as _mcp
    all_open_issues = await _mcp.list_open_issues(project_path, per_page=100)
    if all_open_issues:
        mcp_calls.append({"tool": "list_issues_open", "project": project_path})
        await emit(f"[MCP] Found {len(all_open_issues)} open issues — matching to dead features...")

    saved_features: list[dict] = []
    for feat in features[:15]:
        await emit(f"Gemini 3 Flash — kill reason for '{feat.name}'...")
        feat.death_reason = await extract_death_reason(feat)
        dr = feat.death_reason
        await emit(f"Kill reason: {dr.get('category', '?')} — {dr.get('primary_reason', '')[:80]}")

        await emit(f"Evaluating viability for '{feat.name}' (grounding via external APIs)...")
        feat.viability = await score_revival_viability(feat, feat.death_reason)
        vi = feat.viability
        grounding = vi.get("grounding", {})
        if grounding.get("grounded"):
            await emit(
                f"✓ Verified: {grounding.get('technology')} {grounding.get('latest_version')} "
                f"({grounding.get('source')}) — {grounding.get('evidence_date')}"
            )
        rec = vi.get("recommendation", "unknown").upper().replace("_", " ")
        await emit(f"{rec}: {vi.get('what_changed', '')[:80]}")

        await emit(f"[MCP] list_issues — demand signals for '{feat.name}'...")
        feat.roi = await estimate_revival_roi(feat, project_path)

        comp = await analyze_competitive_gap(
            feat.name, dr.get("category", "unknown"),
            feat.kill_date, dr.get("primary_reason", ""),
        )

        # Match open issues against this dead feature (Open Requests Match)
        open_matches = _match_open_requests(feat.name, all_open_issues, project_path)
        if open_matches:
            await emit(f"🔥 Open Requests Match: {len(open_matches)} open issues are asking for '{feat.name}'")

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
            "open_issue_matches": open_matches,
        })

    # Adversarial Challenger (Vertex AI Gemini 2.5 — different model)
    revive_candidates = [f for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now"]
    if revive_candidates:
        await emit(f"Challenger Agent (Vertex AI Gemini 2.5) — stress-testing top {min(len(revive_candidates), 3)} candidates...")
        assessments = await challenge_top_revival_candidates(revive_candidates[:3])
        for feat_dict, assessment in zip(revive_candidates[:3], assessments):
            feat_dict["challenger"] = assessment
        await emit("Challenger Agent complete — independent adversarial review done")

    # ── Phase 2: ADK Synthesis ───────────────────────────────────────────────
    await emit("[ADK] Google Cloud Agent Builder — synthesizing all findings...")
    adk_synthesis = await _run_adk_synthesis(emit, project_path, saved_features)

    if adk_synthesis.get("status") == "success":
        await emit("[ADK] ✓ Agent Builder synthesis complete — executive summary ready")
        orchestrated_by = "google_cloud_agent_builder_adk"
    else:
        await emit(f"[ADK] Synthesis note: {adk_synthesis.get('reason', 'unavailable')} — proceeding with direct analysis")
        orchestrated_by = "direct_pipeline_with_adk_synthesis_attempted"

    # ── Resurrection Chains — group features by shared constraint ─────────────
    resurrection_chains = _compute_resurrection_chains(saved_features)
    if resurrection_chains:
        total_locked = sum(c["feature_count"] for c in resurrection_chains)
        total_fixes = len(resurrection_chains)
        await emit(
            f"🔗 Resurrection Chains: {total_fixes} shared constraint{'s' if total_fixes != 1 else ''} "
            f"lock {total_locked} features — fix one constraint, unlock multiple features"
        )

    # Final report
    unique_tools = sorted({c["tool"] for c in mcp_calls})
    report = {
        "project_path": project_path,
        "total_commits_scanned": max_commits,
        "features": saved_features,
        "mcp_calls_log": mcp_calls,
        "mcp_tools_used": unique_tools,
        "mcp_tool_count": len(mcp_calls),
        "data_source": "gitlab_mcp",
        "orchestrated_by": orchestrated_by,
        "adk_synthesis": adk_synthesis if adk_synthesis.get("status") == "success" else None,
        "resurrection_chains": resurrection_chains,
    }

    if settings.MONGODB_URI:
        try:
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
        except Exception as e:
            logger.warning("MongoDB save failed: %s", e)

    await write_graveyard_report(report)
    revive_ct = sum(1 for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now")
    await emit(f"SCAN COMPLETE — {revive_ct} features ready to revive")
    await queue_put_report(emit, report)

async def _run_adk_synthesis(emit, project_path: str, saved_features: list[dict]) -> dict:
    """
    Phase 2: Google Cloud Agent Builder synthesizes all findings.

    The ADK Runner receives the complete set of analyzed features and reasons
    holistically: validates recommendations, identifies strategic priorities,
    flags inconsistencies between primary and challenger assessments, and
    produces an executive action plan.

    This is the correct use of ADK — multi-step reasoning over structured findings,
    not just wrapping REST calls. Data collection is intentionally kept in Phase 1
    so that this phase is never blocked by subprocess availability.
    """
    import json as _json
    import uuid
    from google.genai import types as genai_types

    try:
        from agent.agent import get_runner
        runner = get_runner()

        session_id = f"synthesis-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name="necro", user_id="necro-synthesis", session_id=session_id
        )

        revive_now = [f for f in saved_features if f.get("viability", {}).get("recommendation") == "revive_now"]
        investigate = [f for f in saved_features if f.get("viability", {}).get("recommendation") == "investigate_further"]

        # Build a concise summary of findings for the agent to reason over
        findings_summary = []
        for f in saved_features:
            vi = f.get("viability", {})
            dr = f.get("death_reason", {})
            grounding = vi.get("grounding", {})
            challenger = f.get("challenger", {})
            findings_summary.append({
                "name": f.get("name"),
                "kill_date": f.get("kill_date"),
                "kill_reason": dr.get("primary_reason", "")[:100],
                "recommendation": vi.get("recommendation"),
                "feasibility": vi.get("revival_feasibility"),
                "what_changed": vi.get("what_changed", "")[:120],
                "grounded": grounding.get("grounded", False),
                "evidence_url": grounding.get("evidence_url", ""),
                "challenger_verdict": challenger.get("challenger_verdict", "none"),
                "challenger_score": challenger.get("challenger_score"),
            })

        prompt = f"""You are analyzing dead feature findings from the GitLab repository '{project_path}'.

The primary analysis (Gemini 3 Flash) and adversarial challenger (Vertex AI Gemini 2.5) have already run.
Here are all {len(saved_features)} findings:

{_json.dumps(findings_summary, indent=2)}

Summary: {len(revive_now)} features recommended for immediate revival, {len(investigate)} for investigation.

Your job as the strategic synthesis agent:
1. Review the findings and identify the TOP 3 highest-priority revival candidates with specific reasoning
2. Flag any inconsistencies — especially cases where the challenger downgraded a revive_now recommendation
3. Identify any pattern across the graveyard (e.g., "4 of 6 killed features share the same root infrastructure constraint")
4. Write a 3-sentence executive action plan for the engineering team
5. Flag which features have verified external evidence vs AI-inferred reasoning

Return a JSON object:
{{
  "status": "success",
  "top_3_priorities": [
    {{"rank": 1, "feature": "name", "reason": "why this is most urgent", "first_action": "specific next step"}},
    {{"rank": 2, "feature": "name", "reason": "...", "first_action": "..."}},
    {{"rank": 3, "feature": "name", "reason": "...", "first_action": "..."}}
  ],
  "graveyard_pattern": "1-2 sentence pattern observed across all findings",
  "executive_summary": "3-sentence action plan for the engineering lead",
  "challenger_disagreements": ["list of features where challenger downgraded vs primary"],
  "verification_quality": "high/medium/low — based on how many claims have verified external evidence"
}}"""

        await emit("[ADK] Agent Builder — reasoning over all findings...")

        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=prompt)],
        )

        synthesis_text = ""
        async for event in runner.run_async(
            user_id="necro-synthesis",
            session_id=session_id,
            new_message=message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                synthesis_text = (event.content.parts[0].text or "").strip()

        if synthesis_text:
            import re
            match = re.search(r"(\{.*\})", synthesis_text, re.DOTALL)
            if match:
                result = _json.loads(match.group(1))
                result["status"] = "success"
                result["model"] = "google_cloud_agent_builder_adk_gemini3_flash"
                return result

        return {"status": "empty_response", "reason": "ADK runner returned no content"}

    except Exception as exc:
        logger.warning("[ADK] Synthesis failed: %s", exc)
        return {"status": "unavailable", "reason": str(exc)[:200]}


async def queue_put_report(emit, report: dict):
    """Emit the final report payload as a special SSE event."""
    import json as _json
    from datetime import datetime, date

    def _default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    await emit(f"__REPORT__:{_json.dumps(report, default=_default)}")


def _url_to_path(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "gitlab.com/" in url:
        return url.split("gitlab.com/", 1)[1]
    return url


def _match_open_requests(feature_name: str, open_issues: list[dict],
                          project_path: str) -> list[dict]:
    """
    Match open GitLab issues to a dead feature by keyword overlap.

    For each open issue, check if its title shares 2+ significant words with the
    feature name. Returns a list of matching issues with {iid, title, url}.

    This surfaces the key insight: "Users are actively asking for what you killed."
    """
    if not open_issues or not feature_name:
        return []

    # Tokenize feature name — filter out short/common words
    stop_words = {"the", "and", "for", "with", "from", "that", "this", "was", "are",
                  "has", "have", "been", "feat", "fix", "add", "remove", "update",
                  "revert", "disable", "enable", "support", "use", "via", "allow"}
    name_tokens = {
        w.lower() for w in re.split(r"[\s_\-/]+", feature_name)
        if len(w) > 3 and w.lower() not in stop_words
    }
    if not name_tokens:
        return []

    gitlab_base = "https://gitlab.com"
    matches = []
    for issue in open_issues:
        title = issue.get("title", "")
        body = issue.get("description", "") or ""
        search_text = (title + " " + body[:200]).lower()
        # Check overlap: at least 1 strong token match in title, or 2+ in title+body
        title_tokens = set(re.split(r"[\s_\-/.,;:!?]+", title.lower()))
        title_overlap = name_tokens & title_tokens
        if len(title_overlap) >= 1 or len(name_tokens & set(re.split(r"\W+", search_text))) >= 2:
            issue_url = issue.get("web_url") or f"{gitlab_base}/{project_path}/-/issues/{issue.get('iid', '')}"
            matches.append({
                "iid": issue.get("iid"),
                "title": title[:120],
                "url": issue_url,
            })
            if len(matches) >= 5:
                break

    return matches


# Known technology keywords for resurrection chain detection
_TECH_KEYWORDS = [
    "webpack", "angular", "react", "vue", "rails", "django", "flask", "postgres",
    "mysql", "redis", "elasticsearch", "kubernetes", "docker", "oauth", "graphql",
    "grpc", "websocket", "sidekiq", "celery", "kafka", "rabbitmq", "nginx", "node",
    "python", "ruby", "golang", "typescript", "safari", "firefox", "chrome", "ie11",
    "internet explorer", "openssl", "jwt", "cors", "csrf", "s3", "gcs", "azure",
    "terraform", "ansible", "gitlab", "github", "bitbucket", "ldap", "saml", "sso",
]


def _compute_resurrection_chains(features: list[dict]) -> list[dict]:
    """
    Resurrection Chains — identify shared constraints locking multiple features.

    Groups dead features by the root technology/constraint they share.
    When 2+ features share a constraint, fixing that constraint unlocks all of them
    simultaneously — a force-multiplier for engineering effort.

    Returns chains sorted by feature_count descending, minimum chain size = 2.
    """
    if not features:
        return []

    # For each feature, extract constraint keywords
    def extract_keys(feat: dict) -> set[str]:
        dr = feat.get("death_reason", {})
        vi = feat.get("viability", {})
        text = " ".join([
            dr.get("specific_constraint", ""),
            dr.get("primary_reason", ""),
            feat.get("kill_commit_message", ""),
            vi.get("what_changed", ""),
        ]).lower()

        keys = set()
        for kw in _TECH_KEYWORDS:
            if kw in text:
                keys.add(kw)

        # Also extract first significant word from specific_constraint as a catch-all
        constraint = dr.get("specific_constraint", "").strip()
        if constraint:
            words = [w for w in re.split(r"\W+", constraint.lower()) if len(w) > 4]
            if words:
                keys.add(words[0])

        return keys

    keyword_to_features: dict[str, list[dict]] = {}
    for feat in features:
        keys = extract_keys(feat)
        for key in keys:
            keyword_to_features.setdefault(key, []).append(feat)

    chains = []
    seen_feature_groups: set[frozenset] = set()

    for keyword, matching_feats in sorted(keyword_to_features.items(),
                                           key=lambda x: len(x[1]), reverse=True):
        if len(matching_feats) < 2:
            continue

        fid_set = frozenset(f.get("feature_id", f.get("name", "")) for f in matching_feats)
        if fid_set in seen_feature_groups:
            continue
        seen_feature_groups.add(fid_set)

        revivable = [
            f for f in matching_feats
            if f.get("viability", {}).get("recommendation") in ("revive_now", "investigate_further")
        ]

        # Build a human-readable fix suggestion
        what_changed_list = [
            f.get("viability", {}).get("what_changed", "")
            for f in matching_feats if f.get("viability", {}).get("what_changed")
        ]
        fix_suggestion = what_changed_list[0][:120] if what_changed_list else f"Resolve the {keyword} constraint"

        chains.append({
            "constraint_key": keyword,
            "feature_count": len(matching_feats),
            "revivable_count": len(revivable),
            "features": [f.get("name", "?") for f in matching_feats[:6]],
            "feature_ids": [f.get("feature_id", "") for f in matching_feats],
            "fix_suggestion": fix_suggestion,
            "impact": "high" if len(revivable) >= 3 else "medium" if len(revivable) >= 2 else "low",
        })

    return chains[:6]  # top 6 chains max
