"""
POST /api/necrosis/scan — SSE streaming necrosis (dead-code) scan.

The mirror of /api/scan/stream, but for the DELETE side of the lifecycle.
Scans the live codebase for deprecated-but-present code, scores each finding
for deletion safety, and streams progress + a final report over SSE.

Reuses:
  - necrosis_detector.detect_necrosis   (Phase 1 — annotation/flag detection)
  - deletion_scorer.score_deletion_safety (Phase 2 — caller-count + safety verdict)
  - stream._url_to_path                  (shared URL parsing helper)

Does NOT touch the existing revival pipeline. Purely additive.
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


class NecrosisScanRequest(BaseModel):
    repo_url: str
    max_findings: int = 40
    min_age_days: int = 90


@router.post("/scan")
async def necrosis_scan(req: NecrosisScanRequest):
    """SSE endpoint — streams necrosis scan progress, then emits the final report."""
    from backend.routes.stream import _url_to_path
    project_path = _url_to_path(req.repo_url)

    async def generate():
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def emit(msg: str):
            await queue.put(msg)

        async def run_pipeline():
            try:
                await _stream_necrosis(emit, project_path, req.max_findings, req.min_age_days)
            except Exception as exc:
                logger.exception("Necrosis scan failed")
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


async def _stream_necrosis(emit, project_path: str, max_findings: int, min_age_days: int):
    """Run the two-phase necrosis pipeline and emit a final report."""
    import uuid
    from backend.services.necrosis_detector import detect_necrosis
    from backend.services.deletion_scorer import score_deletion_safety

    scan_id = uuid.uuid4().hex[:8]
    mcp_calls: list = []

    await emit(f"[Necrosis] Scanning live codebase of {project_path} for dead code...")

    candidates = await detect_necrosis(
        project_path, max_findings=max_findings, min_age_days=min_age_days,
        progress_cb=emit, mcp_calls=mcp_calls,
    )

    if not candidates:
        await emit("Clean codebase — no lingering deprecated code detected.")
        report = _build_report(project_path, [], mcp_calls, scan_id, clean=True)
        await _emit_report(emit, report)
        return

    await emit(f"Scoring {len(candidates)} necrosis candidates for deletion safety...")

    # Score in parallel batches of 5 (mirror of the revival pipeline cadence).
    findings: list[dict] = []
    total = min(len(candidates), 15)

    async def _score_one(cand, idx: int) -> dict:
        await emit(f"[{idx}/{total}] Analyzing '{cand.name}' ({cand.file_path})...")
        safety = await score_deletion_safety(cand, project_path)
        rec = safety.get("recommendation", "needs_biopsy")
        callers = safety.get("callers_found", -1)
        verb = {"excise_now": "EXCISE NOW", "needs_biopsy": "NEEDS BIOPSY",
                "leave_intact": "LEAVE INTACT"}.get(rec, rec.upper())
        caller_note = f"{callers} caller(s)" if callers >= 0 else "callers unknown"
        await emit(f"[{idx}/{total}] {verb}: {cand.name} — {caller_note}, risk {safety.get('deletion_risk','?')}/10")
        return _necrotic_to_dict(cand, safety)

    _BATCH = 5
    for start in range(0, total, _BATCH):
        batch = candidates[start:start + _BATCH]
        results = await asyncio.gather(
            *[_score_one(c, start + i + 1) for i, c in enumerate(batch)],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, dict):
                findings.append(r)
            elif isinstance(r, Exception):
                logger.warning("Necrosis scoring failed: %s", r)

    report = _build_report(project_path, findings, mcp_calls, scan_id)

    # Persist to MongoDB (separate collections — never touch revival collections)
    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            excise = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "excise_now")
            biopsy = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "needs_biopsy")
            intact = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "leave_intact")
            await db["necrosis_scans"].insert_one({
                "scan_id": scan_id, "project_path": project_path,
                "findings_count": len(findings),
                "excise_now_count": excise, "needs_biopsy_count": biopsy,
                "leave_intact_count": intact,
            })
            for f in findings:
                await db["necrosis_findings"].insert_one(
                    {"project_path": project_path, "scan_id": scan_id, **f}
                )
            await emit("Results saved to MongoDB Atlas")
        except Exception as exc:
            logger.warning("Necrosis MongoDB save failed: %s", exc)

    excise_ct = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "excise_now")
    await emit(f"NECROSIS SCAN COMPLETE — {excise_ct} candidate(s) safe to excise now")
    await _emit_report(emit, report)


def _necrotic_to_dict(cand, safety: dict) -> dict:
    return {
        "finding_id": cand.id,
        "name": cand.name,
        "file_path": cand.file_path,
        "annotation": cand.annotation,
        "detection_method": cand.detection_method,
        "language": cand.language,
        "context_snippet": cand.context_snippet,
        "age_days": cand.age_days,
        "annotation_date": cand.annotation_date,
        "replacement": cand.replacement,
        "removal_target": cand.removal_target,
        "last_commit_sha": cand.last_commit_sha,
        "startline": cand.startline,
        "ref": cand.ref,
        "detection_confidence": cand.detection_confidence,
        "detection_signals": cand.detection_signals,
        "deletion_safety": safety,
    }


def _build_report(project_path, findings, mcp_calls, scan_id, clean=False) -> dict:
    unique_tools = sorted({c["tool"] for c in mcp_calls}) if mcp_calls else []
    excise = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "excise_now")
    biopsy = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "needs_biopsy")
    intact = sum(1 for f in findings if f["deletion_safety"]["recommendation"] == "leave_intact")
    return {
        "mode": "necrosis",
        "project_path": project_path,
        "scan_id": scan_id,
        "findings": findings,
        "summary": {
            "total": len(findings),
            "excise_now": excise,
            "needs_biopsy": biopsy,
            "leave_intact": intact,
        },
        "mcp_calls_log": mcp_calls,
        "mcp_tools_used": unique_tools,
        "mcp_tool_count": len(mcp_calls),
        "data_source": "gitlab_mcp_blobs",
        "clean_scan": clean,
    }


async def _emit_report(emit, report: dict):
    import json as _json
    await emit(f"__REPORT__:{_json.dumps(report)}")


class DeletionMRRequest(BaseModel):
    project_path: str | None = None


@router.post("/{finding_id}/deletion-mr")
async def create_deletion_mr(finding_id: str, req: DeletionMRRequest):
    """
    Ghost Deletion MR — the mirror of the revival Ghost MR.

    NECRO creates a real Draft GitLab MR that scaffolds the REMOVAL of necrotic code:
      1. Creates branch  necro/deletion/{slug}
      2. Commits NECRO_DELETION.md — a step-by-step removal checklist + safety evidence
      3. Opens a Draft MR with the deletion plan, caller analysis, and @duo_code_review

    Only excise_now / needs_biopsy findings are eligible — leave_intact is blocked.
    MCP tools: get_default_branch, create_branch, create_file, create_merge_request.
    """
    from fastapi import HTTPException
    from backend.services.gitlab_mcp import mcp

    finding = await _get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail=f"Necrosis finding '{finding_id}' not found.")

    safety = finding.get("deletion_safety", {})
    if safety.get("recommendation") == "leave_intact":
        raise HTTPException(
            status_code=400,
            detail="This code is 'Leave Intact' — it still has active callers. Deletion MR blocked.",
        )

    project_path = req.project_path or finding.get("project_path", "")
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path required.")

    import re, time
    slug = re.sub(r"[^a-z0-9-]", "-", (finding.get("name", "") or "code").lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:40] or "necrosis"
    branch_name = f"necro/deletion/{slug}-{int(time.time()) % 100000}"

    default_branch = await mcp.get_default_branch(project_path)
    logger.info("[Deletion MR] default_branch=%s project=%s", default_branch, project_path)

    branch_result = await mcp.create_branch(project_path, branch_name, ref=default_branch)
    if _is_err(branch_result):
        raise HTTPException(
            status_code=_err_status(branch_result, 502),
            detail=(f"Failed to create branch '{branch_name}': {_err_msg(branch_result)}. "
                    "Check GITLAB_TOKEN has 'api' scope + Developer role on this project."),
        )

    plan = _build_deletion_plan(finding, project_path)
    file_result = await mcp.create_file(
        project_path,
        file_path="NECRO_DELETION.md",
        content=plan,
        branch=branch_name,
        commit_message=f"necro: deletion plan for {finding.get('name')}",
    )
    if _is_err(file_result):
        logger.warning("[Deletion MR] NECRO_DELETION.md commit failed: %s — continuing", _err_msg(file_result))

    mr_description = _build_deletion_mr_description(finding, project_path)
    mr_title = f"Excise dead code: {finding.get('name')}"
    mr_result = await mcp.create_merge_request(
        project_path,
        title=mr_title,
        description=mr_description,
        source_branch=branch_name,
        target_branch=default_branch,
        labels=["necrosis", "dead-code-removal", "necro-ghost-mr", "draft"],
        draft=True,
    )
    if _is_err(mr_result) or not mr_result:
        raise HTTPException(
            status_code=_err_status(mr_result, 502),
            detail=(f"GitLab MR creation failed: {_err_msg(mr_result)}. "
                    "Check GITLAB_TOKEN has 'api' scope with Developer+ role."),
        )

    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()
            await db["necrosis_deletions"].insert_one({
                "finding_id": finding_id,
                "name": finding.get("name"),
                "project_path": project_path,
                "mr_url": mr_result.get("web_url", ""),
                "mr_iid": mr_result.get("iid"),
                "branch": branch_name,
            })
        except Exception as exc:
            logger.warning("Deletion MR log failed: %s", exc)

    logger.info("[Deletion MR] Created: %s", mr_result.get("web_url", ""))
    return {
        "status": "created",
        "mr_url": mr_result.get("web_url", ""),
        "mr_iid": mr_result.get("iid"),
        "branch_name": branch_name,
        "title": f"Draft: {mr_title}",
        "plan_file": "NECRO_DELETION.md",
        "via": "gitlab_mcp_ghost_deletion_mr",
    }


def _is_err(result) -> bool:
    """GitLab _post returns {'_error': True, ...} on failure — a truthy dict that
    must NOT be mistaken for success. Returns True if the write failed."""
    return isinstance(result, dict) and result.get("_error") is True


def _err_status(result, default: int) -> int:
    if isinstance(result, dict):
        sc = result.get("_status_code")
        # surface auth/permission problems clearly; otherwise 502 upstream failure
        if sc in (401, 403):
            return 403
    return default


def _err_msg(result) -> str:
    if isinstance(result, dict):
        return str(result.get("message") or result.get("_status_code") or "unknown error")[:120]
    return "no response from GitLab"


async def _get_finding(finding_id: str) -> dict | None:
    """Fetch a necrosis finding from MongoDB by finding_id (most recent scan)."""
    if not settings.MONGODB_URI:
        return None
    try:
        from backend.db.connection import get_db
        db = get_db()
        return await db["necrosis_findings"].find_one(
            {"finding_id": finding_id}, {"_id": 0}, sort=[("_id", -1)]
        )
    except Exception as exc:
        logger.warning("_get_finding failed: %s", exc)
        return None


def _build_deletion_plan(finding: dict, project_path: str) -> str:
    """Build NECRO_DELETION.md — the step-by-step removal checklist."""
    safety = finding.get("deletion_safety", {})
    name = finding.get("name", "unknown")
    file_path = finding.get("file_path", "")
    age = finding.get("age_days", 0)
    callers = safety.get("callers_found", -1)
    caller_files = safety.get("caller_files", [])
    replacement = finding.get("replacement", "")
    rec = safety.get("recommendation", "needs_biopsy")
    risks = safety.get("technical_risks", [])

    lines = [
        f"# NECRO Deletion Plan: `{name}`",
        "",
        f"**Verdict:** {rec.replace('_', ' ').title()}",
        f"**Deletion risk:** {safety.get('deletion_risk', '?')}/10",
        f"**Confirmed by NECRO** via live GitLab MCP analysis.",
        "",
        "## What this is",
        f"`{name}` in `{file_path}` has carried a deprecation annotation for "
        f"**{age} days** but was never removed — necrotic code in a living codebase.",
        "",
        f"> {finding.get('annotation', '')}",
        "",
        "## Why it is (or isn't) safe to remove",
    ]
    if callers == 0:
        lines.append(f"- **0 external callers** found via GitLab `search_blobs` — nothing else references `{name}`.")
    elif callers > 0:
        lines.append(f"- **{callers} external caller(s)** still reference `{name}` — these MUST be migrated first:")
        for cf in caller_files[:10]:
            lines.append(f"  - [ ] migrate `{cf}`")
    if replacement:
        lines.append(f"- Stated replacement: **{replacement}** — migrate call sites to this.")
    lines += [
        "",
        f"**Blast radius:** {safety.get('blast_radius', 'unknown')}",
        "",
        "## Removal checklist",
        f"- [ ] Confirm no new callers since this scan (`grep -r {name}`)",
        f"- [ ] Remove `{name}` from `{file_path}`",
        "- [ ] Remove its tests / specs",
        "- [ ] Remove now-unused imports",
        "- [ ] Run the full test suite — all green",
        "- [ ] Confirm no DeprecationWarning in logs",
        "",
        "## Removal risks",
    ]
    lines += ([f"- {r}" for r in risks] if risks else ["- None identified beyond the caller migration above."])
    lines += [
        "",
        "## Reasoning",
        safety.get("reasoning", ""),
        "",
        "---",
        "_Auto-generated by NECRO — Necrosis Detection. Caller analysis via GitLab MCP "
        "`search_blobs`; annotation age via per-line `blame`._",
    ]
    return "\n".join(lines)


def _build_deletion_mr_description(finding: dict, project_path: str) -> str:
    safety = finding.get("deletion_safety", {})
    name = finding.get("name", "unknown")
    callers = safety.get("callers_found", -1)
    caller_note = (f"{callers} external caller(s)" if callers >= 0 else "caller count unknown")
    return (
        f"## Ghost Deletion MR — NECRO Necrosis Removal\n\n"
        f"This Draft MR was auto-created by **NECRO** to scaffold the removal of "
        f"`{name}` — deprecated code that has lingered in the codebase for "
        f"**{finding.get('age_days', 0)} days**.\n\n"
        f"**Deletion verdict:** {safety.get('recommendation', '').replace('_', ' ').title()} "
        f"(risk {safety.get('deletion_risk', '?')}/10, {caller_note})\n\n"
        f"`NECRO_DELETION.md` on this branch contains the full removal checklist and "
        f"caller-migration list.\n\n"
        f"**To complete:** work through the checklist, remove the code, drop the `Draft:` "
        f"prefix, and merge.\n\n"
        f"_MCP tools used: `search_blobs` (detection + caller analysis), `get_file_blame` "
        f"(annotation age), `get_default_branch`, `create_branch`, `create_file`, "
        f"`create_merge_request`._\n\n"
        f"---\n\n"
        f"@duo_code_review please verify the caller analysis is complete and the removal is safe."
    )


@router.post("/demo")
async def necrosis_demo(project_path: str | None = None):
    """
    Instant necrosis demo — serve the best cached necrosis scan for a project_path
    from MongoDB (most excise_now findings, tie-break recency). Mirror of the revival
    /api/scan/demo cached mode. Falls back to the most recent scan of any repo.
    """
    if not settings.MONGODB_URI:
        return {"findings": [], "summary": {}, "available": False, "source": "no_db"}
    try:
        from backend.db.connection import get_db
        db = get_db()
        query = {"project_path": project_path} if project_path else {}
        # Most recent scan that found something — recency reflects the current
        # pipeline, avoiding stale results from before a fix.
        scans = await db["necrosis_scans"].find(query, {"_id": 0}).sort("_id", -1).limit(20).to_list(length=20)
        best = next((s for s in scans if s.get("findings_count", 0) > 0), scans[0] if scans else None)
        if not best and project_path:
            # No scan for this exact repo — fall back to most recent of any repo
            best = await db["necrosis_scans"].find_one({}, {"_id": 0}, sort=[("_id", -1)])
        if not best:
            return {"findings": [], "summary": {}, "available": True, "source": "empty"}
        findings = await db["necrosis_findings"].find(
            {"scan_id": best["scan_id"]}, {"_id": 0}
        ).to_list(length=100)
        return {
            "project_path": best.get("project_path"),
            "findings": findings,
            "summary": {
                "total": best.get("findings_count", 0),
                "excise_now": best.get("excise_now_count", 0),
                "needs_biopsy": best.get("needs_biopsy_count", 0),
                "leave_intact": best.get("leave_intact_count", 0),
            },
            "available": True,
            "source": "mongodb_cached_scan",
            "cached_scan_id": best["scan_id"],
        }
    except Exception as exc:
        logger.warning("necrosis_demo failed: %s", exc)
        return {"findings": [], "summary": {}, "available": False, "source": "error"}


@router.get("/latest")
async def necrosis_latest():
    """Most recent necrosis scan from MongoDB (for the registry view)."""
    if not settings.MONGODB_URI:
        return {"findings": [], "summary": {}, "available": False}
    try:
        from backend.db.connection import get_db
        db = get_db()
        scan = await db["necrosis_scans"].find_one(
            {}, {"_id": 0}, sort=[("_id", -1)]
        )
        if not scan:
            return {"findings": [], "summary": {}, "available": True}
        findings = await db["necrosis_findings"].find(
            {"scan_id": scan["scan_id"]}, {"_id": 0}
        ).to_list(length=100)
        return {
            "project_path": scan.get("project_path"),
            "findings": findings,
            "summary": {
                "total": scan.get("findings_count", 0),
                "excise_now": scan.get("excise_now_count", 0),
                "needs_biopsy": scan.get("needs_biopsy_count", 0),
                "leave_intact": scan.get("leave_intact_count", 0),
            },
            "available": True,
        }
    except Exception as exc:
        logger.warning("necrosis_latest failed: %s", exc)
        return {"findings": [], "summary": {}, "available": False}
