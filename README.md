# NECRO — Dormant Code Recovery

**NECRO finds the features your team already built, paid for, and accidentally buried — then tells you which ones are worth digging up.**

> Built for the Google Cloud Rapid Agent Hackathon · GitLab Track  
> Powered by Google Cloud Agent Builder · Gemini 3 Flash · GitLab MCP · MongoDB Atlas

---

## The Problem

Every codebase has a graveyard.

A feature gets disabled in 2022 because a library was too slow. The team moves on. Two years later, the library ships a fix — but nobody circles back, because nobody tracked *why* the feature was killed, only *that* it was killed. The feature flag stays `false` forever. A competitor ships the same thing in 2024 and calls it a differentiator.

This happens on every engineering team, every year. The average team of 25 wastes **$140K+/year** rebuilding work that already exists in their own codebase, or shipping inferior products because a recoverable feature is sitting dead in a commit from three years ago.

NECRO solves this. Paste a GitLab repo URL. NECRO reads the commit history, finds every dead feature, checks whether the original kill reason still applies today using live external APIs — and tells you exactly which ones are ready to ship again.

---

## What It Does

A scan runs in two phases:

**Phase 1 — Forensic archaeology.** Six independent detection strategies sweep the repository via GitLab MCP: revert commits, feature flag diffs, disable-keyword commit messages, shelved issues, feature-branch MRs, and the GitLab native Feature Flags API. Every candidate gets enriched with the actual diff lines that were removed, linked MR discussions, and issue thread context. Then the analysis pipeline runs in parallel: kill reason classification, viability scoring with live external API verification, demand signal aggregation from real open issues, competitive gap analysis, and an independent adversarial challenge that stress-tests every revival recommendation from a skeptical position.

**Phase 2 — ADK synthesis.** Google Cloud Agent Builder (ADK) reads all the findings and produces a ranked executive action plan — top revival priorities, the common pattern in the graveyard (often one constraint killing many features at once), and the highest-confidence next steps.

Results stream to the browser live over SSE. Every feature card shows the kill date, kill reason, what changed since then, a feasibility score, demand signals from real open issues, and a direct link to the commit that killed it. One click creates a real GitLab issue assigned to the engineer who disabled the feature, or a Ghost MR — a draft merge request with a full revival checklist, ready to review and merge.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser → FastAPI → SSE stream                                          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│  PHASE 1 — Forensic Data Collection                                      │
│                                                                          │
│  git_forensics.py — 6 detection strategies                               │
│    ├─ list_commits      → revert commits + keyword scan                  │
│    ├─ get_commit        → diff inspection for feature flag patterns      │
│    ├─ get_commit_diff   → extract removed code lines as evidence         │
│    ├─ list_merge_requests → feature-branch MRs with disable keywords     │
│    ├─ list_merge_request_notes → MR discussion context                   │
│    ├─ list_issues        → closed shelved/wontfix issues                 │
│    ├─ list_issue_notes   → issue thread context                          │
│    └─ list_feature_flags → GitLab native Feature Flags API (active=false)│
│                                                                          │
│  Per-feature analysis pipeline (asyncio.gather — parallel batches of 5) │
│    ├─ death_reason.py    → Gemini 3 Flash: classify kill reason          │
│    ├─ viability_scorer.py                                                │
│    │    ├─ list_pipelines → live CI health (broken CI = lower score)     │
│    │    └─ constraint_grounder.py → npm / GitHub / PyPI live APIs        │
│    ├─ roi_estimator.py   → open + closed issue demand counts via MCP     │
│    ├─ competitive_intel.py → market urgency (Gemini 3 Flash)             │
│    └─ challenger.py     → Gemini 3 Flash adversarial review (Vertex AI)  │
│                                                                          │
│  stream.py extras                                                        │
│    ├─ _match_open_requests()       → active issues requesting dead feature│
│    └─ _compute_resurrection_chains() → features sharing a root constraint│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│  PHASE 2 — ADK Synthesis (Google Cloud Agent Builder)                    │
│                                                                          │
│  adk_runner.py → runner.run_async()                                      │
│    Input:  full analysis from Phase 1                                    │
│    Output: top 3 priorities, graveyard pattern, executive summary,       │
│            challenger disagreements, verification questions              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│  Persistence & Output                                                    │
│  MongoDB Atlas — scans, features, revival_log, watch_list               │
│  graveyard_report.md + .json written to outputs/                        │
│  Optional: post to GitLab issue · Ghost MR · Slack alert                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Detection Strategies

Six independent signals — not just grep on commit messages.

| # | Strategy | MCP tool | Signal |
|---|----------|----------|--------|
| 1 | Revert commits | `list_commits` | Any commit whose title begins with "Revert" — the most explicit form of feature death |
| 2 | Feature flag diffs | `get_commit` + `get_commit_diff` | Commits where diff lines match patterns like `FEATURE_X = false` or `.feature("name", false)` |
| 3 | Disable keywords | `list_commits` | Commit messages containing "disable", "remove", "kill", "bury", "flag-off", "roll-back", etc. |
| 4 | Shelved issues | `list_issues` | Closed issues with labels: disabled, wont-fix, wontfix, shelved, deferred, rejected |
| 5 | Feature-branch MRs | `list_merge_requests` | Merged `feature/*` branches whose title contains disable keywords |
| 6 | GitLab Feature Flags API | `list_feature_flags` | Native GitLab flags where `active=false` — ground truth, not inference |

After detection, every candidate gets enriched: MR discussion notes and issue comments are fetched for context, and the actual diff lines that were removed are extracted and stored as `diff_excerpt`.

---

## Analysis Pipeline

Once detection completes, each dead feature passes through five concurrent analysis steps:

### Kill reason classification
Gemini 3 Flash reads the kill commit message, linked MR notes, and issue threads and classifies the death into one of nine categories: `api_limitation`, `infrastructure`, `performance`, `resource_constraint`, `low_adoption`, `strategic_pivot`, `regulatory`, `technical_debt`, or `security`. It identifies the specific constraint and whether the kill was meant to be temporary.

### Viability scoring with live external verification
This is the step most AI tools get wrong. Rather than asking Gemini to guess whether a constraint is still valid from training data, NECRO queries live external APIs first.

`constraint_grounder.py` identifies the technology in the kill reason and calls the appropriate registry:

| Technology identified | API called | Evidence returned |
|-----------------------|------------|-------------------|
| npm packages (React, Stripe, Webpack, etc.) | `registry.npmjs.org/{pkg}` | Latest version + exact publish date |
| Open-source tools (Postgres, Redis, Docker, etc.) | `api.github.com/repos/{owner}/{repo}/releases/latest` | Release tag + publish date + URL |
| Python packages (Django, FastAPI, Pydantic, etc.) | `pypi.org/pypi/{pkg}/json` | Latest version + upload date |

The grounding result goes verbatim into the Gemini prompt, with an explicit instruction not to fabricate version numbers or dates beyond what the API returned. Every `what_changed` claim is labelled **verified** (backed by a live API call) or **AI-inferred** (no external evidence found — treat as hypothesis).

Viability scoring also checks live CI pipeline status. A broken CI baseline will downgrade `revive_now` to `investigate_further` — there's no point reviving a feature if the pipeline is already red.

### Demand signals and ROI
`roi_estimator.py` fetches real open and closed issues via MCP and keyword-matches them against the feature name. The result is a real count of issue references. No fabricated dollar figures — the report says things like "8 open issues are actively requesting this" rather than made-up estimates.

A separate pass (`_match_open_requests`) does token-overlap matching between the feature name and every open issue, producing an explicit list of open requests for things you already built and killed. When that list is non-empty, it appears as a highlighted section on the feature card.

### Competitive intelligence
Gemini 3 Flash assesses whether competitors have shipped the feature since the kill date. Returns market urgency and a gap description. This is opinion-level analysis, clearly labelled as such.

### Adversarial challenge
Every `revive_now` candidate gets a second opinion from an independent challenger agent — Gemini 3 Flash running on Vertex AI with an adversarial system prompt. It starts from a rejection position and must produce exactly three specific, falsifiable failure scenarios. The challenger's verdict and strongest objection appear on the feature card and in Ghost MR descriptions.

---

## Resurrection Chains

When multiple dead features share the same root constraint, NECRO groups them into a Resurrection Chain: *"One webpack upgrade unlocks 4 features simultaneously."*

`_compute_resurrection_chains()` scans every death reason for 47 technology keywords and clusters features by shared constraint. The chain panel shows the constraint, how many features it blocks, how many are revivable, estimated combined impact, and the suggested fix. This turns "revive one feature" into "fix one thing, unlock several."

---

## Ghost MR

The most concrete output NECRO produces is a Ghost MR — a real draft merge request in your repository that scaffolds the revival work.

When you click "Ghost MR" on a feature card, NECRO:

1. Creates branch `necro/revival/{feature-slug}` from the project's default branch
2. Commits `NECRO_REVIVAL.md` to that branch — a step-by-step revival checklist with the full analysis, kill commit reference, what changed, effort estimate, technical risks, and rollout plan
3. Opens a Draft MR from that branch with the challenger's verdict in the description
4. Appends `@duo_code_review please review this revival scaffold` — GitLab Duo's AI code review triggers automatically on every NECRO-created MR

The MR is a real work item: review the plan, write the code, remove `Draft:`, merge.

---

## GitLab MCP Tools

NECRO uses 19 GitLab MCP tools across the pipeline. The ADK agent carries a `MCPToolset` for agent-native tool calls. Backend routes call the GitLab REST API v4 directly via `httpx` for route-level operations and write actions.

| Tool | Used in | Purpose |
|------|---------|---------|
| `list_commits` | `git_forensics.py` | Paginated commit fetch — up to 500 commits across strategies 1–3 |
| `get_commit` | `git_forensics.py` | Read diff for feature flag patterns; resolve kill commit author |
| `get_commit_diff` | `git_forensics.py` | Fetch unified diffs; extract removed code lines as evidence |
| `list_merge_requests` | `git_forensics.py` | Feature-branch MR detection |
| `list_merge_request_notes` | `git_forensics.py` | MR discussion threads — kill context |
| `list_issues` | `git_forensics.py`, `roi_estimator.py` | Closed shelved issues + demand signal counts |
| `list_open_issues` | `stream.py` | All open issues for demand matching |
| `list_issue_notes` | `git_forensics.py` | Issue comment threads — additional kill context |
| `list_feature_flags` | `git_forensics.py` | GitLab native Feature Flags (`active=false`) |
| `list_pipelines` | `viability_scorer.py` | Live CI health check before scoring |
| `search_users` | `revive.py` | Resolve kill commit author → GitLab user ID for auto-assignment |
| `list_project_members` | `gitlab_mcp.py` | Project member access-level queries |
| `get_file` | `gitlab_mcp.py` | Fetch file content at any ref |
| `get_user_by_username` | `gitlab_mcp.py` | Exact username lookup |
| `search_code` | `roi_estimator.py` | Code references to a feature name |
| `get_project` | `revive.py` | Resolve default branch before Ghost MR creation |
| `create_issue` | `revive.py` | Create revival issue, auto-assign to kill commit author |
| `create_branch` | `revive.py` | Create `necro/revival/{slug}` branch |
| `create_file` | `revive.py` | Commit `NECRO_REVIVAL.md` with revival checklist |
| `create_merge_request` | `revive.py` | Open Draft MR, trigger `@duo_code_review` |

Every scan report includes a complete `mcp_calls_log` — a verifiable audit trail of which tools fired, against which repo, with result counts.

---

## Multi-Agent Model

Three agents, three roles:

| Agent | Model | Role |
|-------|-------|------|
| Primary Analyst | Gemini 3 Flash | Kill reason extraction, viability scoring, ROI estimation, competitive intel |
| Challenger | Gemini 3 Flash (Vertex AI) | Adversarial review — starts from REJECT, must score lower, must produce falsifiable failure scenarios |
| Synthesis | ADK Runner + Gemini 3 Flash | Executive plan via `runner.run_async()` — top 3 priorities, graveyard pattern, open questions |

The Challenger runs on Vertex AI with a separate adversarial system prompt, providing genuinely independent review. The disagreement only has value when the agent is structurally required to find fault.

---

## GitLab-Native Integration

NECRO doesn't just call the GitLab API — it lives inside GitLab.

**CI/CD pipeline** — `.gitlab-ci.yml` runs seven stages: `build` → `test` → `security` (SAST + Secret Detection + Dependency Scanning via GitLab built-in templates) → `upload` (Google Artifact Registry via Workload Identity Federation) → `deploy` (Cloud Run) → `necro-scan` (self-dogfooding scan) → `necro-report` (post graveyard findings as a native GitLab issue).

**Duo Custom Agent** — `.gitlab/duo/necro-agent.yaml` registers NECRO in the AI Catalog with suggested prompts, triggers (`@necro`, `necro-scan` label), and an external API hook.

**Post to GitLab** — one click posts the full graveyard report as a native GitLab issue in any project with write access, with a formatted revival candidate table.

**Autonomous watching** — add any repo to the watch list and NECRO re-scans it every 24 hours. Slack alerts fire when new revival candidates appear.

**GitLab webhook** — `POST /api/agent/webhook/gitlab` re-evaluates a repo immediately on push events.

**Group scan** — paste a GitLab namespace (e.g. `gitlab-org`) and NECRO federates across all repos in parallel, identifying cross-repository patterns where one constraint kills features in multiple codebases.

---

## Tech Stack

| Technology | Role |
|---|---|
| **Google Cloud Agent Builder (ADK)** | Agent orchestration — FunctionTools, MCPToolset, Runner, InMemorySessionService |
| **Gemini 3 Flash (`gemini-3-flash-preview`)** | Primary analysis — kill reasons, viability scoring, competitive intel, ADK synthesis |
| **Google Cloud Vertex AI** | Adversarial challenger agent serving |
| **Google Cloud Run** | Serverless deployment, auto-scaling |
| **Google Artifact Registry** | Docker image storage |
| **GitLab MCP (official SSE + @zereight/mcp-gitlab stdio)** | 19 MCP tools — repo forensics, write operations |
| **GitLab REST API v4** | Backend routes — direct httpx calls |
| **MongoDB Atlas** | Primary store — scans, features, watch_list, revival_log, issue_embeddings |
| **MongoDB Vector Search** | Semantic demand matching — Google text-embedding-004 embeddings |
| **Motor** | Async MongoDB driver |
| **FastAPI + SSE** | Async backend + real-time progress streaming |
| **APScheduler** | 24h autonomous re-scan loop |
| **Slack SDK** | Revival alerts + issue-created notifications |
| **Chart.js 4.4** | Timeline analytics, kill category distribution, feasibility heatmap |

---

## Setup

### Prerequisites

```
Python 3.11+
Node.js 20+            — for @zereight/mcp-gitlab
MongoDB Atlas account  — free M0 tier works fine
GitLab account         — personal access token with api scope
Google Cloud project   — Vertex AI API enabled
Gemini API key         — from aistudio.google.com/apikey
```

### Install

```bash
git clone https://github.com/usv240/necro.git
cd necro
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
```

### Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```env
GITLAB_TOKEN=glpat-xxxxxxxxxxxx       # api + read_repository scopes
GITLAB_URL=https://gitlab.com
GEMINI_API_KEY=AIza...
GOOGLE_PROJECT_ID=your-gcp-project-id
GOOGLE_LOCATION=us-central1
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=necro_db
SLACK_WEBHOOK_URL=https://hooks.slack.com/...  # optional
APP_URL=http://localhost:8080
```

### Run

```bash
uvicorn backend.main:app --port 8080 --reload
```

Open `http://localhost:8080`. Pre-scanned demo repos load instantly. Live scans stream in real time and take 60–120 seconds depending on repo size.

### Test

```bash
pytest tests/test_necro.py -q
# 95 tests across 15 categories
```

---

## Deploy to Cloud Run

```bash
gcloud run deploy necro-agent \
  --source . \
  --project YOUR_PROJECT_ID \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --set-env-vars "MONGODB_URI=...,GITLAB_TOKEN=...,GEMINI_API_KEY=...,GOOGLE_PROJECT_ID=..."
```

Or push to `main` and let `.gitlab-ci.yml` handle it — the deploy stage runs automatically via Workload Identity Federation.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scan/stream` | SSE live scan — streams progress in real time |
| `POST` | `/api/scan/quick` | Synchronous scan — returns full JSON (for CI integration) |
| `POST` | `/api/scan/start` | Background scan — returns scan_id, poll for status |
| `GET` | `/api/scan/status/{id}` | Poll background scan progress |
| `POST` | `/api/scan/demo` | Load pre-seeded scan from MongoDB |
| `GET` | `/api/report/latest` | Most recent scan from MongoDB |
| `GET` | `/api/report/scans` | All past scan summaries |
| `GET` | `/api/report/all-features` | All features across all scans (used by Timeline Forensics) |
| `GET` | `/api/report/feature/{id}` | Single feature with full competitive intel |
| `GET` | `/api/report/revival-log` | All revival issues and Ghost MRs created |
| `GET` | `/api/report/download` | Download latest report as markdown |
| `POST` | `/api/report/post-to-gitlab` | Post graveyard as a native GitLab issue |
| `POST` | `/api/report/notify-slack` | Send current report to Slack |
| `POST` | `/api/revive/{id}` | Create revival issue, auto-assign to kill commit author |
| `POST` | `/api/revive/{id}/ghost-mr` | Create branch + plan + Draft MR with `@duo_code_review` |
| `POST` | `/api/agent/ask` | Freeform ADK agent query (SSE) |
| `POST` | `/api/agent/revive` | ADK-orchestrated revival issue creation |
| `POST` | `/api/agent/webhook/gitlab` | GitLab push webhook — triggers immediate re-evaluation |
| `GET` | `/api/watch/list` | All repos on the autonomous watch list |
| `POST` | `/api/watch/add` | Add repo to watch list |
| `DELETE` | `/api/watch/{path}` | Remove from watch list |
| `GET` | `/api/monitor/status` | APScheduler loop status + last run time |
| `POST` | `/api/monitor/run` | Trigger a monitor cycle immediately |
| `GET` | `/api/health` | Full stack status — MongoDB, MCP, ADK, Slack, Gemini |

---

## Project Structure

```
necro/
├── agent/
│   ├── agent.py              # ADK agent — FunctionTools + MCPToolset definition
│   └── system_prompt.txt     # Agent system prompt — 4-step NECRO process
├── backend/
│   ├── main.py               # FastAPI app — lifespan, middleware, route registration
│   ├── config.py             # Settings via pydantic-settings + .env
│   ├── db/
│   │   ├── connection.py     # Motor async client + index creation
│   │   ├── schemas.py        # Pydantic models — FeatureDoc, ScanDoc, RevivalLogEntry
│   │   └── seed.py           # Pre-analyzed demo data (real commit SHAs, real dates)
│   ├── routes/
│   │   ├── stream.py         # SSE scan — chains + open match + ADK synthesis
│   │   ├── scan.py           # Background scan + quick sync scan for CI
│   │   ├── report.py         # Report retrieval + post-to-gitlab + Slack notify
│   │   ├── revive.py         # Create issue (auto-assign) + Ghost MR (3 write ops)
│   │   ├── agent.py          # ADK ask + ADK revive + GitLab webhook
│   │   ├── watch.py          # Watchlist CRUD
│   │   └── monitor.py        # APScheduler trigger + status
│   └── services/
│       ├── gitlab_mcp.py     # GitLab REST client — 19 MCP tools
│       ├── git_forensics.py  # 6-strategy dead feature detection + enrichment
│       ├── death_reason.py   # Kill reason classification (Gemini 3 Flash)
│       ├── viability_scorer.py # Revival scoring + CI health + constraint grounding
│       ├── constraint_grounder.py # npm / GitHub releases / PyPI live verification
│       ├── roi_estimator.py  # Demand signal aggregation from real issue counts
│       ├── competitive_intel.py # Market urgency analysis
│       ├── challenger.py     # Gemini 3 Flash adversarial agent (Vertex AI)
│       ├── adk_runner.py     # ADK runner initialization + synthesis helpers
│       ├── gemini.py         # Gemini 3 Flash client (primary + thinking budget)
│       ├── monitor.py        # APScheduler 24h watchlist loop
│       ├── slack_client.py   # Slack Block Kit alerts
│       └── output_writer.py  # Markdown + JSON report files
├── frontend/
│   ├── index.html            # Single-page app — 5 tabs, live terminal, repo browser
│   ├── style.css             # Dark/light theme, full design system
│   └── app.js                # SSE client, Chart.js charts, URL hash routing
├── tests/
│   └── test_necro.py         # 95 tests across 15 categories
├── .gitlab-ci.yml            # 7-stage pipeline (build→test→security→upload→deploy→scan→report)
├── .gitlab/duo/
│   └── necro-agent.yaml      # GitLab Duo Custom Agent registration
├── .env.example
├── Dockerfile
├── requirements.txt
├── pytest.ini
└── LICENSE                   # Apache 2.0
```

---

## License

Apache 2.0 — see [LICENSE](./LICENSE)
