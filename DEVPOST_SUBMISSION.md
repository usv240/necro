# NECRO — Devpost Submission Text

## Short Description (tagline, 1 sentence)
NECRO uses Google Cloud Agent Builder + GitLab MCP to find disabled features in your codebase whose kill reasons no longer exist — so your team stops reinventing what they already built.

---

## What It Does (the story paragraph — paste this first)

GitLab Pages wildcard domain support was disabled in 2021 because of a DNS subdomain takeover vulnerability. GitLab shipped subdomain verification in 2023. Three years later, the feature was still disabled — and 312 open issues were asking for it back. Nobody connected those dots.

NECRO does. In 45 seconds.

NECRO is an AI agent that reads your entire GitLab commit history, closed issues, merge requests, and Feature Flags API — then identifies every feature your team disabled for a reason that no longer exists. For each dead feature it finds, NECRO:

1. **Extracts the exact kill reason** from commit messages, MR descriptions, and linked issues (Gemini 3 Flash)
2. **Verifies the claim externally** — checks npm registry, GitHub releases, and PyPI to confirm whether the cited dependency/security/compatibility constraint was actually resolved (and when)
3. **Scores revival viability** with a confidence-weighted recommendation: Revive Now / Investigate Further / Keep Buried
4. **Stress-tests the recommendation** using an independent Challenger Agent on Vertex AI Gemini 2.5 Flash — a different model with an adversarial "Red Team" prompt that must find reasons why revival will fail
5. **Synthesizes the full picture** via Google Cloud Agent Builder (ADK Runner) — the agent reasons holistically over all findings to produce an executive action plan and surface the top 3 priorities
6. **Closes the loop natively in GitLab** — posts the Graveyard Report as a GitLab issue directly in the scanned repository, and integrates via `.gitlab-ci.yml` so the scan runs automatically on every push

No hardcoded data. No demos. Every scan is live against real GitLab repositories using real MCP tool calls.

---

## How We Built It

**Stack:**
- Google Cloud Agent Builder (ADK) — `google-adk` Python SDK for the synthesis agent
- Gemini 3 Flash (`gemini-3-flash-preview`) — primary LLM for kill reason extraction and viability scoring
- Vertex AI Gemini 2.5 Flash — Challenger Agent (adversarial verification, genuinely different model)
- GitLab MCP Server (`@zereight/mcp-gitlab`) — 6 MCP tools: `list_commits`, `get_commit`, `list_issues`, `list_merge_requests`, `list_merge_request_notes`, `list_feature_flags`
- MongoDB Atlas Vector Search — scan persistence and graveyard history
- FastAPI + Server-Sent Events — real-time streaming terminal in the browser
- Google Cloud Run — containerized deployment
- Chart.js + vanilla JS frontend

**Architecture (two-phase):**

Phase 1 — Data Collection: The GitLab MCP tools (via REST) run the six detection strategies in parallel: commit message scanning, feature flag keyword detection, revert commit analysis, merged MR scanning, closed issue scanning, and GitLab native Feature Flags API (`/api/v4/projects/:id/feature_flags`). This produces raw `DeadFeature` objects with full git context.

Phase 2 — ADK Synthesis: The ADK Runner receives all Phase 1 findings and performs multi-step holistic reasoning — validating recommendations across all features, identifying the highest-priority revivals, and flagging inconsistencies between the primary Gemini analysis and the adversarial Challenger assessment. The executive summary and action plan are entirely agent-generated.

**What makes this genuinely multi-agent:**
- Agent 1 (Primary): Gemini 3 Flash, optimistic analyst
- Agent 2 (Challenger): Vertex AI Gemini 2.5 Flash, adversarial Red Team
- Agent 3 (Synthesis): Google Cloud Agent Builder ADK Runner, strategic synthesizer
- Each agent is independent: different models, different prompts, different reasoning goals

---

## Challenges We Ran Into

**The ADK subprocess problem:** `@zereight/mcp-gitlab` runs as a Node.js subprocess that ADK's MCPToolset spawns. On Cloud Run (no persistent filesystem, no Node.js runtime by default), this subprocess fails silently. The naive fix is "don't use ADK" — but the correct fix is to restructure: use REST for data collection (reliable) and ADK Runner for synthesis (the reasoning phase). ADK is now genuinely doing what it's built for.

**Hardcoded viability claims:** The first version had a dict of known improvements (`_KNOWN_IMPROVEMENTS = {"webpack": "...", "redux": "..."}`) — completely fake. Replaced with `constraint_grounder.py`, which calls npm registry, GitHub releases API, and PyPI to get real version numbers and real release dates, then computes whether the cited constraint was resolved after the feature's kill date.

**The challenger agent echo chamber problem:** Early versions used the same Gemini 3 Flash model for both primary analysis and "adversarial" verification — just with a different prompt. A different prompt on the same model produces marginally different outputs, not genuinely independent review. Fixed by routing the Challenger Agent through `generate_json_adversarial()` which explicitly uses the Vertex AI client (Gemini 2.5 Flash).

---

## Accomplishments We're Proud Of

- **6 detection strategies**, including GitLab's native Feature Flags API — most dead feature tools only parse commit messages
- **Externally verified claims** — every "what changed" claim is backed by a real npm/GitHub/PyPI API response with a URL and a release date
- **True multi-model multi-agent** — three agents, three different reasoning goals, two different LLM models
- **GitLab native** — posts findings as GitLab issues, ships with `.gitlab-ci.yml` for pipeline integration, and includes a `.gitlab/duo/necro-agent.yaml` for Duo Agent Platform deployment
- **Zero fake data** — all "Quick Scan" examples trigger real live scans of public GitLab repositories

---

## What We Learned

The hardest part of building an AI agent is not the AI — it's the data. Every impressive-looking output is only as trustworthy as the evidence chain behind it. NECRO's main architectural lesson: separate what the agent *fetches* from what the agent *reasons about*. GitLab MCP does the fetching reliably. ADK does the reasoning clearly. Don't conflate them.

---

## What's Next

- **Duo Chat native:** Register NECRO in the GitLab AI Catalog as a Custom Agent so developers can trigger scans directly from Duo Chat: "@necro What can we revive in this codebase?"
- **MR-level scanning:** Detect when a merge request re-introduces a pattern that was deliberately removed — "revival detection at commit time"
- **Cross-project graveyard:** If 12 separate GitLab projects all killed the same feature for the same reason, NECRO should surface that as a platform-wide signal

---

## Built With

`google-cloud-agent-builder` `google-adk` `gemini-3-flash` `vertex-ai` `gitlab-mcp` `mongodb-atlas` `cloud-run` `fastapi` `python` `server-sent-events` `javascript`
