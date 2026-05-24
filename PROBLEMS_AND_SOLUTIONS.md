# NECRO — Red-Team Analysis & Fixes

This document records every identified weakness in NECRO's architecture, the root cause,
and the specific code change that fixes it. Written as a design record for future reference.

---

## Problem 1: Core detection is pattern-matching on commit messages

**Root cause**  
`git_forensics.py` Strategies 1–5 look for keywords like `disable`, `revert`, `flag.*off` in
commit messages and diffs. This is essentially `git log --grep`. High false-positive rate for
large repos. Misses features managed through native GitLab Feature Flags (which don't always
surface in commit messages).

**Why it matters to judges**  
GitLab's Senior Solutions Architect immediately recognizes that GitLab has a native Feature Flags
API (`GET /api/v4/projects/:id/feature_flags`) that returns exactly the data we're trying to
reverse-engineer from commits. Not using it looks naive.

**Fix — Strategy 6: GitLab Feature Flags API**  
Added `_detect_from_feature_flags_api()` in `git_forensics.py`.  
Added `list_feature_flags()` to `gitlab_mcp.py`.  
This queries the GitLab API directly for flags with `active=False`, returning confirmed disabled
features — not guesses from commit messages. Results are tagged `detection_method: "gitlab_feature_flags_api"`.

---

## Problem 2: "What changed" analysis is hallucinated from training data

**Root cause**  
`viability_scorer.py` uses a static `_KNOWN_IMPROVEMENTS` string embedded in the module at
write-time (e.g., "Stripe added custom billing intervals Nov 2023"). Gemini reads this static
text and generates a `what_changed` claim. The claim is never verified against a live data source.

**Why it matters to judges**  
A judge who picks any specific `what_changed` claim and opens a browser to verify it may find:
- The date is wrong
- The feature shipped earlier or later than stated
- The claim is too vague to verify

This destroys credibility for the entire analysis.

**Fix — `constraint_grounder.py`**  
New module that, given the `specific_constraint` text and kill date, does three things:
1. Identifies the technology referenced (e.g., "Stripe", "React 18", "npm package X")
2. Calls a real external API for that technology:
   - npm registry: `https://registry.npmjs.org/{package}/latest`
   - GitHub releases: `https://api.github.com/repos/{owner}/{repo}/releases/latest`
   - PyPI: `https://pypi.org/pypi/{package}/json`
3. Returns structured evidence: `evidence_date`, `evidence_url`, `latest_version`, `is_resolved`

The static `_KNOWN_IMPROVEMENTS` text is replaced with the dynamically fetched evidence injected
into the Gemini prompt as `VERIFIED EXTERNAL EVIDENCE`. The `what_changed` field in every report
now includes a `grounding` sub-object with source URL, release date, and verified flag.

---

## Problem 3: Challenger Agent is not genuinely independent

**Root cause**  
`challenger.py` calls `generate_json()` which uses Gemini 3 Flash — the same model as the primary
analysis. Asking the same model "do you agree?" with slightly different framing is not adversarial
verification; it's confirmation bias by design.

**Why it matters to judges**  
Multi-agent architecture is a key judging signal. If the "second agent" is just a second call to
the same model with a softer prompt, it provides no independent verification value.

**Fix — Truly adversarial challenger**  
`challenger.py` now uses `generate_json_adversarial()` which calls the **Vertex AI** client
(Gemini 2.5 Flash via Vertex) instead of the primary Gemini 3 Flash API key client.
Different model family, different temperature, different serving infrastructure.

The prompt is radically restructured: the Challenger starts from a position of REJECTION and must
justify any move toward acceptance. It's required to produce exactly 3 specific falsifiable failure
scenarios. Its score MUST differ from the primary by at least 1 point unless evidence is overwhelming.

---

## Problem 4: Demo loads pre-seeded MongoDB data, not real analysis

**Root cause**  
`stream.py` contained `_stream_demo()` and `_stream_demo_inkscape()` functions that loaded
pre-written data from MongoDB Atlas (seeded by `seed.py`). When a judge clicked "Load Demo",
they saw data we wrote manually, not what the agent actually found.

The `is_demo` flag was triggered by checking if the project path was `gitlab-org/gitlab-foss`
or `inkscape/inkscape` — meaning scanning these real repos also served fake data.

**Why it matters to judges**  
A judge who actually tries the demo receives our manually written results and believes they are
AI-generated. If they then try to reproduce by scanning a different repo, results look completely
different. This gap destroys trust.

**Fix — Remove demo path, always live**  
Removed `_stream_demo`, `_stream_demo_inkscape`, and the `is_demo` flag from `stream.py`.
All scans now go through `_stream_live` → ADK Runner.

Frontend updated: removed auto-load on first visit, removed seed-data demo buttons. Added
"Quick Scan" examples that perform real scans of public GitLab repos with reduced depth
(50 commits, 6 months) for speed. Any result shown to judges is real.

---

## Problem 5: NECRO is an external tool, not a GitLab citizen

**Root cause**  
The GitLab resources page directs builders toward Custom Agents, Custom Flows, and AI Catalog —
all of which live *inside* GitLab Duo. NECRO is a standalone web app that uses GitLab as a
data source. This is architecturally misaligned with how GitLab envisions partner integrations.

**Why it matters to judges**  
Nick Veenhof (Director, Contributor Success) and Regnard Raquedan (Senior Solutions Architect)
are looking for agents that *extend* the GitLab platform, not external apps that scrape it.

**Fix — "Post Graveyard to GitLab" + CI integration**  
Added `POST /api/report/post-to-gitlab` endpoint that:
1. Takes the latest scan report
2. Uses ADK agent's `create_issue` tool to create a **master summary issue** in the scanned repo
3. The issue body is rich Markdown: executive summary, revive_now table, ROI estimate, agent attribution

Added `.necro-ci.yml` template that shows how to run NECRO as a **GitLab CI stage** — so the
graveyard report becomes a pipeline artifact. This makes NECRO feel native to DevOps workflows.

Added "Post to GitLab" button in the UI after every scan.

---

## Problem 6: ROI numbers are hallucinated dollar figures

**Root cause**  
`roi_estimator.py` asks Gemini to estimate revenue impact without access to the company's actual
revenue, user counts, or market data. The `$50K–$200K/year` labels are creative fiction.

**Why it matters to judges**  
If a judge asks "how do you calculate $500K/year?", the answer is "we asked Gemini to guess."
This undermines every other number in the report.

**Fix — Demand-signal-only ROI, no dollar fabrication**  
`roi_estimator.py` now returns ONLY:
- Real issue/MR count from the repository (GitLab MCP `list_issues` call with feature name search)
- Real comment count from linked issues
- A qualitative priority tier (P1/P2/P3/P4)
- A qualitative demand level (high/medium/low/unknown)

Dollar estimates are completely removed from the primary report. The ROI bar in the UI now
shows "demand signals" instead of fabricated dollar ranges. The label is `N issue references`
(real count from GitLab MCP) with `(est.)` only when confidence is low.

---

## Problem 7: ADK Runner fallback means ADK may silently not run

**Root cause**  
After the `runner.run_async()` → `_stream_live` wiring, if the ADK Runner throws any exception
(MCP subprocess not starting, timeout, model error), the `except` clause silently runs the
direct pipeline. The user sees identical output but ADK was never actually used.

**Why it matters to judges**  
A judge reviewing Cloud Run logs might see ADK errors with the pipeline running via fallback,
meaning "Google Cloud Agent Builder" in the UI is a lie.

**Fix — Explicit ADK status in report**  
The report now includes `"orchestrated_by": "google_cloud_agent_builder_adk"` vs
`"orchestrated_by": "direct_pipeline_fallback"` depending on which path ran.
The terminal stream shows `[ADK] ✓ Agent Builder completed successfully` or
`[ADK] ⚠ Fallback: [reason]` so there is no hiding which path ran.

---

## Problem 8: No working scan without the user providing credentials

**Root cause**  
The scan form requires a GitLab token unless the server has GITLAB_TOKEN set. Judges visiting the
live URL without a token see an empty scan form with no guidance.

**Fix — Pre-configured quick scan examples**  
Frontend now shows three pre-configured "Quick Scan" buttons for well-known public GitLab repos.
The server's `GITLAB_TOKEN` (configured in Cloud Run secret manager) handles authentication for
public repos. Judges get real scan results with zero credential setup.

---

## What was done (committed and deployed)

| Fix | Files Changed | Status |
|-----|--------------|--------|
| GitLab Feature Flags API (Strategy 6) | `gitlab_mcp.py`, `git_forensics.py` | ✅ Done |
| Constraint grounder with real APIs | `constraint_grounder.py` (new), `viability_scorer.py` | ✅ Done |
| Adversarial challenger (different model) | `challenger.py`, `gemini.py` | ✅ Done |
| Remove fake demo paths | `stream.py` | ✅ Done |
| Post to GitLab (CI citizen) | `routes/report.py`, `app.js` | ✅ Done |
| Demand-only ROI (no dollar fabrication) | `roi_estimator.py` | ✅ Done |
| ADK status transparency | `stream.py`, `app.js` | ✅ Done |
| Quick Scan examples | `app.js`, `index.html` | ✅ Done |
