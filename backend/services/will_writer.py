"""
Feature Will Generator — ADK-powered analysis at the moment of feature death.

When a GitLab MR kills a feature, NECRO intercepts via webhook and:
  1. Analyzes the kill reason using ADK (Gemini 3 Flash) with full MR context
  2. Predicts whether the kill is temporary or permanent
  3. Identifies the exact, testable revival condition
  4. Creates a Revival Contract issue in GitLab via Official MCP (create_issue)
  5. Auto-assigns the engineer who killed it (engineer attribution)
  6. Stores the contract in MongoDB with text-embedding-004 vector embedding
     so semantically related contracts are findable via $vectorSearch

This preserves institutional knowledge at 100% fidelity — the moment it exists
at maximum clarity — rather than trying to recover it archaeologically months later
when the engineer has moved on and the context has decayed to ~5%.

The Revival Contract is a living document: NECRO's autonomous monitor watches
the revival conditions and automatically reopens the issue when they are met.
"""

import logging
import re
import uuid
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# MR title/description keywords that signal a feature is being killed
KILL_KEYWORDS = {
    "remove", "disable", "revert", "deprecate", "kill", "drop", "delete",
    "turn off", "flag off", "clean up", "cleanup", "sunset", "retire",
    "decommission", "shut down", "phase out", "rollback", "undo", "abandon",
    "comment out", "stub out", "feature flag off", "ff off",
}


def _looks_like_feature_kill(title: str, description: str) -> bool:
    """Heuristic: does this MR look like it's disabling / removing a feature?"""
    text = (title + " " + (description or "")).lower()
    return any(kw in text for kw in KILL_KEYWORDS)


async def generate_revival_will(
    project_path: str,
    mr_iid: int,
    mr_title: str,
    mr_description: str,
    author_name: str,
    author_email: str,
) -> Optional[dict]:
    """
    Core will generation pipeline.

    Returns the Revival Contract dict (without embedding) if successful,
    None if this MR does not look like a feature kill.
    """
    if not _looks_like_feature_kill(mr_title, mr_description):
        logger.debug("[Will] MR !%d in %s — not a feature kill, skipping", mr_iid, project_path)
        return None

    logger.info("[Will] 🪦 Feature kill detected — MR !%d in %s", mr_iid, project_path)

    # Step 1: ADK Gemini analysis — understand why and what
    will = await _adk_analyze_kill(project_path, mr_iid, mr_title, mr_description)
    if not will:
        return None

    # Step 2: Engineer attribution — find original author's GitLab user ID
    author_gitlab_id = await _resolve_gitlab_user(author_name, author_email)
    if author_gitlab_id:
        logger.info("[Will] Engineer attributed: %s (ID %s)", author_name, author_gitlab_id)

    # Step 3: Create Revival Contract issue in GitLab via MCP
    issue = await _create_contract_issue(project_path, will, mr_iid, author_gitlab_id, author_name)

    # Step 4: Store in MongoDB with vector embedding
    contract = await _store_contract(
        project_path, mr_iid, mr_title, will, issue, author_name, author_gitlab_id
    )

    return contract


async def _adk_analyze_kill(
    project_path: str,
    mr_iid: int,
    mr_title: str,
    mr_description: str,
) -> Optional[dict]:
    """
    ADK Gemini 3 Flash analyzes the MR kill and produces a structured will.
    Falls back to a heuristic extraction from the MR title if ADK is unavailable.
    """
    import json as _json

    try:
        from agent.agent import get_runner
        from google.genai import types as genai_types

        runner = get_runner()
        session_id = f"will-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name="necro", user_id="necro-will", session_id=session_id
        )

        prompt = f"""You are NECRO analyzing a GitLab Merge Request that is killing a feature.

Project: {project_path}
MR !{mr_iid}: "{mr_title}"

MR Description:
{(mr_description or "No description provided.")[:1000]}

Your task — generate a Feature Revival Will with maximum precision:
1. Identify the feature being killed — give it a clear, human-readable name (not the MR title)
2. Determine the ROOT constraint that forced this kill (not symptoms)
3. Is this constraint temporary (will likely resolve) or permanent (product direction)?
4. What EXACT, TESTABLE condition would allow safe revival? Be specific — name the library version,
   the issue number, the infrastructure component, or the business condition.
5. Estimated effort to revive WHEN that condition is met (days / weeks / months)
6. What demand signals suggest users will want this back?

Return ONLY valid JSON, no markdown fences, no explanation:
{{
  "feature_name": "clear human-readable name of what is being killed (not the MR title)",
  "kill_reason": "the root cause — one specific sentence",
  "kill_category": "security|resource_constraint|technical_debt|performance|product_direction|dependency",
  "is_temporary": true or false,
  "revival_condition": "Revive when: [specific, testable condition — name exact version/issue/threshold]",
  "revival_effort": "X days|weeks|months",
  "demand_signal": "who will ask for this back and why",
  "confidence": "high|medium|low"
}}"""

        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=prompt)],
        )

        response_text = ""
        async for event in runner.run_async(
            user_id="necro-will",
            session_id=session_id,
            new_message=message,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = (event.content.parts[0].text or "").strip()

        if response_text:
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                result = _json.loads(match.group(0))
                logger.info(
                    "[Will] ADK analysis complete — feature: '%s', temporary: %s",
                    result.get("feature_name", "?"), result.get("is_temporary")
                )
                return result

    except Exception as exc:
        logger.warning("[Will] ADK analysis failed: %s — heuristic fallback", exc)

    # Heuristic fallback — still better than nothing
    clean_name = re.sub(
        r"^(remove|disable|revert|deprecate|kill|drop|delete|sunset)\s+",
        "", mr_title, flags=re.IGNORECASE
    ).strip()
    return {
        "feature_name": clean_name or mr_title,
        "kill_reason": f"Killed via MR !{mr_iid}: {mr_title}",
        "kill_category": "unknown",
        "is_temporary": True,
        "revival_condition": "Revive when: the original blocker is resolved — review MR context",
        "revival_effort": "unknown",
        "demand_signal": "Monitor open issues for requests related to this feature",
        "confidence": "low",
    }


async def _resolve_gitlab_user(author_name: str, author_email: str) -> Optional[int]:
    """
    Resolve a commit author to a GitLab user ID for auto-assignment.
    Tries email first (most precise), then display name.
    """
    try:
        from backend.services.gitlab_mcp import mcp
        for query in filter(None, [author_email, author_name]):
            users = await mcp.search_users(query, per_page=3)
            if users:
                return users[0].get("id")
    except Exception as exc:
        logger.debug("[Will] User resolution failed: %s", exc)
    return None


async def _create_contract_issue(
    project_path: str,
    will: dict,
    mr_iid: int,
    author_gitlab_id: Optional[int],
    author_name: str,
) -> Optional[dict]:
    """
    Create the Revival Contract GitLab issue via the Official MCP Server.
    Auto-assigns to the engineer who killed the feature (attribution).
    """
    from backend.services.gitlab_mcp import mcp

    feature_name  = will.get("feature_name", "Unknown Feature")
    kill_category = will.get("kill_category", "unknown").replace("_", " ").title()
    is_temporary  = will.get("is_temporary", False)
    revival_cond  = will.get("revival_condition", "To be determined")
    revival_effort = will.get("revival_effort", "unknown")
    demand_signal  = will.get("demand_signal", "")
    confidence     = will.get("confidence", "medium")
    kill_reason    = will.get("kill_reason", "")
    temp_label     = "⏳ Temporary constraint — will resolve" if is_temporary else "🔒 Long-term constraint"

    title = f"🪦 Revival Contract: {feature_name}"

    description = f"""## Feature Will — Auto-Generated by NECRO at Moment of Death

> *This issue was automatically created by NECRO when MR !{mr_iid} killed this feature.*
> *It captures institutional knowledge at the moment it exists at maximum fidelity.*
> *Without this will, this context decays to ~5% within 18 months.*

---

### ⚰️ What Was Killed
| Field | Value |
|-------|-------|
| **Feature** | {feature_name} |
| **Killed by** | MR !{mr_iid} |
| **Kill category** | {kill_category} |
| **Constraint type** | {temp_label} |
| **Root cause** | {kill_reason} |

---

### 🌱 Revival Conditions
> **{revival_cond}**

**Estimated effort at revival time:** {revival_effort}
**Confidence in assessment:** {confidence}

---

### 📣 Demand Signal
{demand_signal or "Monitor open issues for requests related to this feature."}

---

### 🔁 What Happens Next
NECRO's autonomous monitor is now watching for the revival condition above.
When the condition is met, this issue will be automatically **reopened** and
the original engineer will be notified.

You can also track this in the [NECRO Dashboard]({settings.APP_URL}).

---

*🤖 Generated by NECRO — powered by Google Cloud Agent Builder + GitLab Official MCP*
*Engineer attribution: {author_name}*"""

    labels = ["necro:revival-contract", "necro:monitored"]
    if is_temporary:
        labels.append("necro:temporary-kill")
    if kill_category.lower() == "security":
        labels.append("security")

    try:
        issue = await mcp.create_issue(
            project_path,
            title=title,
            description=description,
            labels=labels,
            assignee_ids=[author_gitlab_id] if author_gitlab_id else [],
        )
        if issue:
            logger.info(
                "[Will] ✅ Revival Contract created: %s (assigned to ID %s)",
                issue.get("web_url", ""), author_gitlab_id
            )
            return issue
    except Exception as exc:
        logger.warning("[Will] Issue creation failed: %s", exc)

    return None


async def _store_contract(
    project_path: str,
    mr_iid: int,
    mr_title: str,
    will: dict,
    issue: Optional[dict],
    author_name: str,
    author_gitlab_id: Optional[int],
) -> dict:
    """
    Persist the Revival Contract in MongoDB.
    Generates a text-embedding-004 vector of the kill context for semantic search —
    so `find_similar_issues()` can also find semantically related contracts.
    """
    from datetime import datetime, timezone

    contract = {
        "contract_id": f"will-{uuid.uuid4().hex[:8]}",
        "project_path": project_path,
        "mr_iid": mr_iid,
        "mr_title": mr_title,
        "feature_name": will.get("feature_name", ""),
        "kill_reason": will.get("kill_reason", ""),
        "kill_category": will.get("kill_category", "unknown"),
        "is_temporary": will.get("is_temporary", False),
        "revival_condition": will.get("revival_condition", ""),
        "revival_effort": will.get("revival_effort", ""),
        "demand_signal": will.get("demand_signal", ""),
        "confidence": will.get("confidence", "medium"),
        "author_name": author_name,
        "author_gitlab_id": author_gitlab_id,
        "issue_url": issue.get("web_url", "") if issue else "",
        "issue_iid": issue.get("iid") if issue else None,
        "status": "active",   # active | fulfilled | abandoned
        "created_at": datetime.now(timezone.utc),
    }

    if settings.MONGODB_URI:
        try:
            from backend.db.connection import get_db
            db = get_db()

            # Embed kill context for semantic search
            if settings.GEMINI_API_KEY:
                try:
                    from backend.services.vector_search import embed_text
                    kill_text = (
                        f"{will.get('feature_name', '')} "
                        f"{will.get('kill_reason', '')} "
                        f"{will.get('revival_condition', '')}"
                    )
                    contract["embedding"] = await embed_text(kill_text)
                except Exception as emb_err:
                    logger.debug("[Will] Embedding skipped: %s", emb_err)

            await db["revival_contracts"].insert_one({**contract})
            contract.pop("embedding", None)  # don't expose in API response
            contract.pop("_id", None)
            logger.info("[Will] Contract persisted: %s", contract["contract_id"])

        except Exception as exc:
            logger.warning("[Will] MongoDB storage failed: %s", exc)

    return contract


async def get_contracts(project_path: str, status: str = "active") -> list[dict]:
    """Return revival contracts for a project — used by the graveyard and monitor."""
    if not settings.MONGODB_URI:
        return []
    try:
        from backend.db.connection import get_db
        db = get_db()
        query: dict = {"project_path": project_path}
        if status != "all":
            query["status"] = status
        docs = await db["revival_contracts"].find(
            query, {"_id": 0, "embedding": 0}
        ).sort("created_at", -1).limit(50).to_list(length=50)
        return docs
    except Exception as exc:
        logger.warning("[Will] get_contracts failed: %s", exc)
        return []


async def fulfill_contract(contract_id: str, resolved_by: str = "") -> bool:
    """Mark a Revival Contract as fulfilled — called by monitor when conditions met."""
    if not settings.MONGODB_URI:
        return False
    try:
        from backend.db.connection import get_db
        from datetime import datetime, timezone
        db = get_db()
        await db["revival_contracts"].update_one(
            {"contract_id": contract_id},
            {"$set": {"status": "fulfilled", "fulfilled_at": datetime.now(timezone.utc), "resolved_by": resolved_by}},
        )
        return True
    except Exception:
        return False
