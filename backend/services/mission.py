"""
Autonomous Mission Orchestrator — NECRO's closed-loop agent.

This is the difference between a dashboard and an agent. Given one instruction
("run a code-lifecycle mission on repo X"), the agent autonomously:

  1. RECON   — scans the repo for revival candidates AND necrotic dead code (parallel)
  2. PLAN    — an ADK agent (Gemini via Google Cloud Agent Builder) reasons over ALL
               findings and DECIDES the mission objectives: the single highest-value
               feature to revive, the single safest dead-code to excise, and whether
               each is action-worthy. This is genuine agency, not a hardcoded sequence.
  3. CHALLENGE — the adversarial agent red-teams the plan before any action
  4. ACT     — executes the approved actions: creates the revival Ghost MR + the
               deletion Ghost MR via GitLab MCP write tools
  5. VERIFY  — reads the created artifacts back to confirm they exist
  6. REPORT  — opens a summary issue linking the artifacts + returns the mission log

Human oversight: dry_run=True plans and prepares everything but performs no writes —
the "keep you in control" checkpoint. Write failures (no Developer access on the
target) are reported honestly as "prepared, awaiting write access", never faked.

Reuses existing services only — git_forensics, death_reason, viability_scorer,
necrosis_detector, deletion_scorer, challenger, and the MR/issue builders. Touches
no existing code.
"""

import asyncio
import json
import logging
import uuid

logger = logging.getLogger(__name__)


async def run_mission(
    emit,
    repo: str,
    action_repo: str | None = None,
    max_commits: int = 120,
    lookback_months: int = 36,
    dry_run: bool = False,
) -> dict:
    """
    Execute one autonomous code-lifecycle mission. Streams phase updates via emit().
    Returns the final mission report dict.

    action_repo: where ACT writes land. Defaults to `repo`. Point at a repo you own
                 for a live demo (revival + deletion MRs get created there).
    dry_run:     plan + prepare everything, perform no writes (oversight checkpoint).
    """
    from backend.services.gitlab_mcp import mcp

    mission_id = uuid.uuid4().hex[:8]
    target = action_repo or repo
    log: list[dict] = []

    def record(phase: str, status: str, detail: str, **extra):
        entry = {"phase": phase, "status": status, "detail": detail, **extra}
        log.append(entry)
        return entry

    await emit(f"[MISSION {mission_id}] Autonomous code-lifecycle mission on {repo}")
    await emit(f"[MISSION] Action target: {target}" + ("  (DRY RUN — no writes)" if dry_run else ""))

    # ── PHASE 1: RECON ────────────────────────────────────────────────────────
    await emit("━━ PHASE 1 / RECON ━━ scanning for revival candidates + necrotic code (parallel)...")
    revival_candidates, necrosis_candidates = await asyncio.gather(
        _recon_revival(emit, repo, max_commits, lookback_months),
        _recon_necrosis(emit, repo),
    )
    record("recon", "done",
           f"{len(revival_candidates)} revival candidate(s), {len(necrosis_candidates)} necrosis candidate(s)",
           revival_count=len(revival_candidates), necrosis_count=len(necrosis_candidates))
    await emit(f"━━ RECON complete ━━ {len(revival_candidates)} revival, {len(necrosis_candidates)} necrosis candidates")

    # ── PHASE 2: PLAN (ADK agent decides the objectives) ─────────────────────
    await emit("━━ PHASE 2 / PLAN ━━ Google Cloud Agent Builder reasoning over all findings...")
    plan = await _plan_mission(emit, repo, revival_candidates, necrosis_candidates)
    record("plan", "done", plan.get("mission_summary", ""), plan=plan)
    await emit(f"━━ PLAN ━━ {plan.get('mission_summary', '')[:160]}")

    revive_target = _pick_revival(revival_candidates, plan)
    excise_target = _pick_excision(necrosis_candidates, plan)

    if revive_target:
        await emit(f"[PLAN] Revival objective: '{revive_target['name']}' — {plan.get('revival_reason','')[:100]}")
    else:
        await emit("[PLAN] No action-worthy revival candidate found.")
    if excise_target:
        await emit(f"[PLAN] Excision objective: '{excise_target['name']}' — {plan.get('excision_reason','')[:100]}")
    else:
        await emit("[PLAN] No safe-to-excise candidate found.")

    # ── PHASE 3: CHALLENGE (adversarial review before acting) ─────────────────
    challenge = {}
    if revive_target:
        await emit("━━ PHASE 3 / CHALLENGE ━━ adversarial agent red-teaming the revival plan...")
        challenge = await _challenge_revival(revive_target)
        verdict = challenge.get("challenger_verdict", "n/a")
        record("challenge", "done", f"challenger verdict: {verdict}", challenge=challenge)
        await emit(f"━━ CHALLENGE ━━ verdict: {verdict.upper()} — {challenge.get('strongest_objection','')[:120]}")
        if verdict == "reject":
            await emit("[CHALLENGE] Challenger REJECTED the revival — downgrading to issue-only (no Ghost MR).")

    # ── PHASE 4: ACT ──────────────────────────────────────────────────────────
    actions: list[dict] = []
    if dry_run:
        await emit("━━ PHASE 4 / ACT ━━ DRY RUN — preparing artifacts without writing...")
        if revive_target:
            actions.append({"type": "revival_mr", "status": "prepared",
                            "feature": revive_target["name"],
                            "detail": "Revival Ghost MR prepared (dry run — not created)"})
        if excise_target:
            actions.append({"type": "deletion_mr", "status": "prepared",
                            "symbol": excise_target["name"],
                            "detail": "Deletion Ghost MR prepared (dry run — not created)"})
    else:
        await emit(f"━━ PHASE 4 / ACT ━━ executing actions on {target} via GitLab MCP write tools...")
        if revive_target:
            # Respect the challenger: a REJECT means NECRO does not commit a Draft MR;
            # it opens a lower-commitment discussion issue instead. The agent honours
            # its own adversarial review — this is "keeping you in control".
            if challenge.get("challenger_verdict") == "reject":
                await emit("[ACT] Challenger rejected the revival → opening a discussion issue instead of a Draft MR.")
                actions.append(await _act_revival_issue(emit, mcp, target, revive_target, challenge))
            else:
                actions.append(await _act_revival(emit, mcp, target, revive_target, challenge, mission_id))
        if excise_target:
            actions.append(await _act_deletion(emit, mcp, target, excise_target, mission_id))
    for a in actions:
        record("act", a.get("status", "?"), a.get("detail", ""), action=a)

    # ── PHASE 5: VERIFY ───────────────────────────────────────────────────────
    # "created" covers revival_mr, deletion_mr, and revival_issue (challenger path).
    created = [a for a in actions if a.get("status") == "created"
               and (a.get("mr_iid") or a.get("iid"))]
    # Only MR-type artifacts can be verified by reading a file back from a branch.
    # Issues (revival_issue) are verified by their creation response being non-error.
    verifiable_mrs = [a for a in created if a.get("type") in ("revival_mr", "deletion_mr") and a.get("branch")]
    verifiable_issues = [a for a in created if a.get("type") == "revival_issue"]
    if not dry_run:
        if verifiable_mrs or verifiable_issues:
            await emit("━━ PHASE 5 / VERIFY ━━ confirming created artifacts...")
        for a in verifiable_mrs:
            ok = await _verify_artifact(emit, mcp, target, a)
            a["verified"] = ok
            record("verify", "ok" if ok else "unverified",
                   f"{a['type']} !{a.get('mr_iid')} verified={ok}")
        for a in verifiable_issues:
            iid = a.get("mr_iid") or a.get("iid", "?")
            await emit(f"[VERIFY] revival_issue #{iid}: confirmed (created by GitLab MCP) ✓")
            a["verified"] = True
            record("verify", "ok", f"revival_issue #{iid} confirmed via creation response")
        if not verifiable_mrs and not verifiable_issues and not dry_run:
            await emit("━━ PHASE 5 / VERIFY ━━ skipped (no MR artifacts to verify)")

    # ── PHASE 6: REPORT (summary issue linking the mission) ───────────────────
    summary_issue = None
    if not dry_run and created:
        await emit("━━ PHASE 6 / REPORT ━━ opening mission summary issue...")
        summary_issue = await _post_summary_issue(emit, mcp, target, repo, plan, actions)
        if summary_issue:
            record("report", "created", f"summary issue {summary_issue.get('web_url','')}",
                   issue=summary_issue)

    excise_ct = sum(1 for a in actions if a["type"] == "deletion_mr" and a.get("status") == "created")
    # revival_issue (challenger-rejected path) is a real created artifact — count it.
    revive_ct = sum(1 for a in actions
                    if a["type"] in ("revival_mr", "revival_issue") and a.get("status") == "created")
    await emit(
        f"━━ MISSION COMPLETE ━━ {revive_ct} revival + {excise_ct} excision artifact(s) created, "
        f"{len(log)} steps logged"
    )

    return {
        "mission_id": mission_id,
        "repo": repo,
        "action_repo": target,
        "dry_run": dry_run,
        "objectives": {
            "revival": revive_target["name"] if revive_target else None,
            "excision": excise_target["name"] if excise_target else None,
        },
        "plan": plan,
        "challenge": challenge,
        "actions": actions,
        "summary_issue": summary_issue,
        "log": log,
        "revival_candidates": revival_candidates,
        "necrosis_candidates": necrosis_candidates,
    }


# ── RECON helpers (reuse existing scan pipelines, lightweight) ────────────────

async def _recon_revival(emit, repo, max_commits, lookback_months) -> list[dict]:
    """Focused revival scan — detect + score the top candidates only."""
    from backend.services.git_forensics import detect_dead_features
    from backend.services.death_reason import extract_death_reason
    from backend.services.viability_scorer import score_revival_viability
    from backend.services.roi_estimator import estimate_revival_roi

    try:
        feats = await detect_dead_features(repo, max_commits, lookback_months, progress_cb=emit)
    except Exception as exc:
        logger.warning("[Mission] revival recon failed: %s", exc)
        return []

    # Analyze the top 6 by detection confidence to keep the mission fast.
    feats = sorted(feats, key=lambda f: getattr(f, "detection_confidence", 0), reverse=True)[:6]
    out: list[dict] = []

    async def analyze(feat):
        try:
            dr = await extract_death_reason(feat)
            vi = await score_revival_viability(feat, dr, repo)
            roi = await estimate_revival_roi(feat, repo)
            return {
                "feature_id": feat.id, "name": feat.name,
                "kill_commit_sha": feat.kill_commit_sha,
                "kill_date": feat.kill_date, "detection_method": feat.detection_method,
                "death_reason": dr, "viability": vi, "roi": roi,
                "project_path": repo,
                "linked_issue_iids": feat.linked_issue_iids,
                "context_snippets": feat.context_snippets,
            }
        except Exception as exc:
            logger.debug("[Mission] revival analyze failed: %s", exc)
            return None

    results = await asyncio.gather(*[analyze(f) for f in feats], return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            out.append(r)
    return out


async def _recon_necrosis(emit, repo) -> list[dict]:
    """Focused necrosis scan — detect + score deletion safety on top candidates."""
    from backend.services.necrosis_detector import detect_necrosis
    from backend.services.deletion_scorer import score_deletion_safety

    try:
        cands = await detect_necrosis(repo, max_findings=25, min_age_days=90, progress_cb=emit, age_top_n=8)
    except Exception as exc:
        logger.warning("[Mission] necrosis recon failed: %s", exc)
        return []

    cands = cands[:6]
    out: list[dict] = []

    async def score(cand):
        try:
            safety = await score_deletion_safety(cand, repo)
            return {
                "finding_id": cand.id, "name": cand.name, "file_path": cand.file_path,
                "annotation": cand.annotation, "detection_method": cand.detection_method,
                "language": cand.language, "age_days": cand.age_days,
                "replacement": cand.replacement, "removal_target": cand.removal_target,
                "deletion_safety": safety, "project_path": repo,
            }
        except Exception as exc:
            logger.debug("[Mission] necrosis score failed: %s", exc)
            return None

    results = await asyncio.gather(*[score(c) for c in cands], return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            out.append(r)
    return out


# ── PLAN (ADK agent decides the mission objectives) ───────────────────────────

async def _plan_mission(emit, repo, revival, necrosis) -> dict:
    """ADK agent reasons over all findings and picks the mission objectives.

    Genuine agent decision via Google Cloud Agent Builder. Falls back to a
    deterministic best-pick if ADK is unavailable, so the mission always completes.
    """
    # Build compact findings summary for the agent
    rev_summary = [{
        "name": f["name"],
        "recommendation": f.get("viability", {}).get("recommendation"),
        "feasibility": f.get("viability", {}).get("revival_feasibility"),
        "demand": f.get("roi", {}).get("request_count"),
        "kill_reason": f.get("death_reason", {}).get("primary_reason", "")[:80],
    } for f in revival]
    nec_summary = [{
        "name": f["name"],
        "recommendation": f.get("deletion_safety", {}).get("recommendation"),
        "callers": f.get("deletion_safety", {}).get("callers_found"),
        "age_days": f.get("age_days"),
        "risk": f.get("deletion_safety", {}).get("deletion_risk"),
    } for f in necrosis]

    try:
        from agent.agent import get_synthesis_runner
        from google.genai import types as genai_types
        runner = get_synthesis_runner()
        sid = f"mission-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(app_name="necro", user_id="necro-mission", session_id=sid)

        prompt = (
            "You are NECRO's autonomous mission planner for the repository '" + repo + "'.\n\n"
            "You have two sets of findings from a code-lifecycle scan.\n\n"
            "REVIVAL candidates (dead features that might be worth bringing back):\n"
            + json.dumps(rev_summary, indent=2) + "\n\n"
            "NECROSIS candidates (deprecated code still present that might be safe to delete):\n"
            + json.dumps(nec_summary, indent=2) + "\n\n"
            "Decide the mission objectives. Pick AT MOST ONE revival objective (the highest-value "
            "feature to bring back) and AT MOST ONE excision objective (the safest dead code to remove). "
            "A revival objective should be recommended 'revive_now' or 'investigate_further' with real demand "
            "or feasibility. An excision objective MUST be 'excise_now' with 0 callers — never pick code that "
            "is still referenced. If nothing qualifies on either side, return null for that objective.\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "revival_objective": "exact name or null",\n'
            '  "revival_reason": "why this one is the highest-value revival",\n'
            '  "excision_objective": "exact name or null",\n'
            '  "excision_reason": "why this one is the safest to delete",\n'
            '  "mission_summary": "2-sentence plan an engineering lead would read"\n'
            "}"
        )
        msg = genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])
        text = ""
        async for event in runner.run_async(user_id="necro-mission", session_id=sid, new_message=msg):
            if event.is_final_response() and event.content and event.content.parts:
                text = " ".join((p.text or "") for p in event.content.parts if getattr(p, "text", None)).strip()
        if text:
            import re
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                plan = json.loads(m.group(0))
                plan["planner"] = "google_cloud_agent_builder_adk"
                return plan
    except Exception as exc:
        logger.warning("[Mission] ADK planning failed: %s — using deterministic fallback", exc)
        await emit("[PLAN] ADK planner unavailable — using deterministic best-pick fallback")

    # Deterministic fallback
    best_rev = _best_revival(revival)
    best_exc = _best_excision(necrosis)
    return {
        "revival_objective": best_rev["name"] if best_rev else None,
        "revival_reason": "Highest revival score with live demand." if best_rev else "",
        "excision_objective": best_exc["name"] if best_exc else None,
        "excision_reason": "Safe to delete: 0 callers, aged past threshold." if best_exc else "",
        "mission_summary": (
            f"Revive '{best_rev['name']}'" if best_rev else "No revival"
        ) + " and " + (
            f"excise '{best_exc['name']}'." if best_exc else "no excision."
        ),
        "planner": "deterministic_fallback",
    }


def _best_revival(revival: list[dict]) -> dict | None:
    ranked = [f for f in revival if f.get("viability", {}).get("recommendation") in ("revive_now", "investigate_further")]
    if not ranked:
        return None
    return max(ranked, key=lambda f: (
        f.get("viability", {}).get("recommendation") == "revive_now",
        f.get("viability", {}).get("revival_feasibility", 0),
        f.get("roi", {}).get("request_count", 0),
    ))


def _best_excision(necrosis: list[dict]) -> dict | None:
    safe = [f for f in necrosis
            if f.get("deletion_safety", {}).get("recommendation") == "excise_now"
            and f.get("deletion_safety", {}).get("callers_found", -1) == 0]
    if not safe:
        return None
    return min(safe, key=lambda f: f.get("deletion_safety", {}).get("deletion_risk", 10))


def _pick_revival(revival: list[dict], plan: dict) -> dict | None:
    name = plan.get("revival_objective")
    if name:
        for f in revival:
            if f["name"] == name:
                return f
    return _best_revival(revival)


def _pick_excision(necrosis: list[dict], plan: dict) -> dict | None:
    name = plan.get("excision_objective")
    if name:
        for f in necrosis:
            # Honour the safety invariant even if the planner slipped
            if f["name"] == name and f.get("deletion_safety", {}).get("callers_found", -1) == 0:
                return f
    return _best_excision(necrosis)


# ── CHALLENGE ─────────────────────────────────────────────────────────────────

async def _challenge_revival(revive_target: dict) -> dict:
    from backend.services.challenger import challenge_top_revival_candidates
    try:
        assessments = await challenge_top_revival_candidates([revive_target])
        return assessments[0] if assessments else {}
    except Exception as exc:
        logger.debug("[Mission] challenge failed: %s", exc)
        return {}


# ── ACT ─────────────────────────────────────────────────────────────────────

def _is_err(result) -> bool:
    return isinstance(result, dict) and result.get("_error") is True


def _err_msg(result) -> str:
    if isinstance(result, dict):
        return str(result.get("message") or result.get("_status_code") or "unknown")[:120]
    return "no response"


async def _act_revival(emit, mcp, target, feat, challenge, mission_id: str = "") -> dict:
    """Create the revival Ghost MR (branch + NECRO_REVIVAL.md + Draft MR)."""
    import re
    from backend.routes.revive import _build_ghost_mr_plan, _build_description

    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]", "-", feat["name"].lower())).strip("-")[:40] or "revival"
    # Suffix with the mission_id so each run gets a unique branch — no manual
    # cleanup needed between runs, and each branch is traceable to its mission.
    suffix = f"-{mission_id[:6]}" if mission_id else ""
    branch = f"necro/revival/{slug}{suffix}"
    await emit(f"[ACT] Revival → creating branch {branch} on {target}...")
    default_branch = await mcp.get_default_branch(target)
    br = await mcp.create_branch(target, branch, ref=default_branch)
    if _is_err(br) or not br:
        msg = _err_msg(br)
        hint = (f"branch already exists from a prior run — delete {branch} to reuse"
                if "already exists" in msg.lower()
                else f"need Developer access on {target}")
        await emit(f"[ACT] Revival MR prepared but not created — {msg} ({hint})")
        return {"type": "revival_mr", "status": "prepared", "feature": feat["name"],
                "branch": branch, "detail": f"Prepared; write blocked: {msg}"}

    plan = _build_ghost_mr_plan(feat, target)
    await mcp.create_file(target, file_path="NECRO_REVIVAL.md", content=plan, branch=branch,
                          commit_message=f"necro: revival plan for {feat['name']}")
    desc = _build_description(feat, feat.get("death_reason", {}), feat.get("viability", {}))
    desc += "\n\n---\n_Autonomous NECRO mission — revival scaffold. @duo_code_review please review._"
    mr = await mcp.create_merge_request(target, title=f"Revival: {feat['name']}", description=desc,
                                        source_branch=branch, target_branch=default_branch,
                                        labels=["revival-candidate", "necro-mission", "draft"], draft=True)
    if _is_err(mr) or not mr:
        return {"type": "revival_mr", "status": "prepared", "feature": feat["name"],
                "branch": branch, "detail": f"Branch created; MR blocked: {_err_msg(mr)}"}
    await emit(f"[ACT] ✓ Revival Ghost MR created: {mr.get('web_url','')}")
    return {"type": "revival_mr", "status": "created", "feature": feat["name"],
            "branch": branch, "mr_url": mr.get("web_url", ""), "mr_iid": mr.get("iid"),
            "detail": f"Revival Ghost MR !{mr.get('iid')}"}


async def _act_revival_issue(emit, mcp, target, feat, challenge) -> dict:
    """Challenger rejected the revival → open a discussion issue (not a Draft MR).
    The agent respects its own adversarial review instead of committing code."""
    from backend.routes.revive import _build_description
    desc = _build_description(feat, feat.get("death_reason", {}), feat.get("viability", {}))
    obj = challenge.get("strongest_objection", "")
    desc += (
        "\n\n---\n## ⚔ Challenger raised a concern\n\n"
        f"NECRO's adversarial agent **rejected** auto-creating a Draft MR for this revival:\n\n"
        f"> {obj}\n\n"
        "Opening this as a discussion issue for human judgement instead of committing code. "
        "_Autonomous NECRO mission — the agent respects its own red-team review._"
    )
    res = await mcp.create_issue(
        target, title=f"Revival (needs review): {feat['name']}",
        description=desc, labels=["revival-candidate", "necro-mission", "challenger-flagged"],
    )
    if _is_err(res) or not res:
        return {"type": "revival_issue", "status": "prepared", "feature": feat["name"],
                "detail": f"Prepared; write blocked: {_err_msg(res)}"}
    await emit(f"[ACT] ✓ Revival discussion issue created: {res.get('web_url','')}")
    return {"type": "revival_issue", "status": "created", "feature": feat["name"],
            "issue_url": res.get("web_url", ""), "mr_iid": res.get("iid"),
            "detail": f"Discussion issue #{res.get('iid')} (challenger-flagged)"}


async def _act_deletion(emit, mcp, target, finding, mission_id: str = "") -> dict:
    """Create the deletion Ghost MR (branch + NECRO_DELETION.md + Draft MR)."""
    import re
    from backend.routes.necrosis import _build_deletion_plan, _build_deletion_mr_description

    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]", "-", finding["name"].lower())).strip("-")[:40] or "necrosis"
    suffix = f"-{mission_id[:6]}" if mission_id else ""
    branch = f"necro/deletion/{slug}{suffix}"
    await emit(f"[ACT] Excision → creating branch {branch} on {target}...")
    default_branch = await mcp.get_default_branch(target)
    br = await mcp.create_branch(target, branch, ref=default_branch)
    if _is_err(br) or not br:
        msg = _err_msg(br)
        hint = (f"branch already exists from a prior run — delete {branch} to reuse"
                if "already exists" in msg.lower()
                else f"need Developer access on {target}")
        await emit(f"[ACT] Deletion MR prepared but not created — {msg} ({hint})")
        return {"type": "deletion_mr", "status": "prepared", "symbol": finding["name"],
                "branch": branch, "detail": f"Prepared; write blocked: {msg}"}

    plan = _build_deletion_plan(finding, target)
    await mcp.create_file(target, file_path="NECRO_DELETION.md", content=plan, branch=branch,
                          commit_message=f"necro: deletion plan for {finding['name']}")
    desc = _build_deletion_mr_description(finding, target)
    mr = await mcp.create_merge_request(target, title=f"Excise dead code: {finding['name']}", description=desc,
                                        source_branch=branch, target_branch=default_branch,
                                        labels=["necrosis", "dead-code-removal", "necro-mission", "draft"], draft=True)
    if _is_err(mr) or not mr:
        return {"type": "deletion_mr", "status": "prepared", "symbol": finding["name"],
                "branch": branch, "detail": f"Branch created; MR blocked: {_err_msg(mr)}"}
    await emit(f"[ACT] ✓ Deletion Ghost MR created: {mr.get('web_url','')}")
    return {"type": "deletion_mr", "status": "created", "symbol": finding["name"],
            "branch": branch, "mr_url": mr.get("web_url", ""), "mr_iid": mr.get("iid"),
            "detail": f"Deletion Ghost MR !{mr.get('iid')}"}


# ── VERIFY ────────────────────────────────────────────────────────────────────

async def _verify_artifact(emit, mcp, target, action) -> bool:
    """Read the created MR's file back to confirm the artifact really exists."""
    try:
        branch = action.get("branch", "")
        fname = "NECRO_REVIVAL.md" if action["type"] == "revival_mr" else "NECRO_DELETION.md"
        f = await mcp.get_file(target, fname, ref=branch)
        ok = bool(f and isinstance(f, dict) and (f.get("decoded_content") or f.get("content")))
        await emit(f"[VERIFY] {action['type']} {fname}@{branch}: {'confirmed ✓' if ok else 'not found'}")
        return ok
    except Exception as exc:
        logger.debug("[Mission] verify failed: %s", exc)
        return False


# ── REPORT ────────────────────────────────────────────────────────────────────

async def _post_summary_issue(emit, mcp, target, repo, plan, actions) -> dict | None:
    created = [a for a in actions if a.get("status") == "created"]
    if not created:
        return None
    lines = [
        f"# NECRO Autonomous Mission Report — `{repo}`",
        "",
        plan.get("mission_summary", ""),
        "",
        "## Artifacts created this mission",
    ]
    for a in created:
        name = a.get("feature") or a.get("symbol", "")
        iid = a.get("mr_iid") or a.get("iid", "")
        if a["type"] == "revival_mr":
            label, link = "Revival (Draft MR)", f"[!{iid}]({a.get('mr_url', '')})"
        elif a["type"] == "revival_issue":
            label, link = "Revival (discussion issue — challenger-flagged)", f"[#{iid}]({a.get('issue_url', '')})"
        else:
            label, link = "Excision (Draft MR)", f"[!{iid}]({a.get('mr_url', '')})"
        lines.append(f"- **{label}:** `{name}` → {link}")
    lines += [
        "",
        "## How NECRO decided",
        f"- Revival objective: {plan.get('revival_reason', 'n/a')}",
        f"- Excision objective: {plan.get('excision_reason', 'n/a')}",
        f"- Planner: {plan.get('planner', 'n/a')}",
        "",
        "---",
        "_Generated autonomously by NECRO — scan → plan → challenge → act → verify, "
        "via Google Cloud Agent Builder + GitLab MCP._",
    ]
    body = "\n".join(lines)
    res = await mcp.create_issue(target, title=f"NECRO mission: {len(created)} lifecycle action(s) on {repo}",
                                 description=body, labels=["necro-mission", "necro-identified"])
    if _is_err(res) or not res:
        await emit(f"[REPORT] Summary issue prepared but not created — {_err_msg(res)}")
        return None
    await emit(f"[REPORT] ✓ Summary issue created: {res.get('web_url','')}")
    return res
