# NECRO — The Code Necromancer

**Live:** https://necro-agent-38381883054.us-central1.run.app  
**Repo:** https://gitlab.com/ujwal240-group/ujwal240-project

---

Every codebase has a graveyard. Features that worked, then got disabled — for good reasons at the time. A DNS vulnerability. A library that was too slow. An infrastructure cost that didn't make sense at the team's then-current scale.

The problem is that reasons expire. The library shipped a fix. The infrastructure got upgraded. The team grew. But the feature flag stays `false` forever, because nobody tracks *why* something was killed — only *that* it was.

NECRO reads your GitLab repository, finds those dead features, checks whether the original kill reason is still valid today, and tells you which ones are worth bringing back — with a verifiable evidence trail, not guesswork.

---

## What it does

A scan works in two phases:

**Phase 1 — Data collection.** Six detection strategies run against the commit history, merged MRs, closed issues, and GitLab's native Feature Flags API. Each dead feature gets enriched with the actual code lines that were removed, linked MR discussions, and issue thread context — all pulled from GitLab via MCP. Then, for each candidate, the analysis pipeline runs: kill reason extraction, viability scoring, demand signal aggregation, and competitive gap analysis.

**Phase 2 — ADK synthesis.** Google Cloud Agent Builder (ADK) reads the full analysis and produces an executive-level summary: top 3 revival priorities, the common pattern in the graveyard, and the highest-confidence actions. This is where multi-agent orchestration happens — the ADK runner's output appears in the UI alongside the individual feature cards.

Results stream to the browser in real time over SSE. Every feature card shows the kill date, kill reason, what changed, feasibility score, demand signals, and a direct link to the kill commit. Click *Ghost MR* on any candidate and NECRO creates an actual draft merge request in GitLab — with a revival plan, checklist, and `@duo_code_review` triggered automatically.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser → FastAPI → SSE stream                                          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│  PHASE 1 — Data Collection                                               │
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
│    │    └─ constraint_grounder.py → npm / GitHub releases / PyPI live    │
│    ├─ roi_estimator.py   → open + closed issue demand counts via MCP     │
│    ├─ competitive_intel.py → market urgency (Gemini 3 Flash)             │
│    └─ challenger.py     → Vertex AI Gemini 2.5 Flash adversarial review  │
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

## Detection strategies

Six independent signals, not just grep on commit messages.

| # | Strategy | MCP tool | Signal |
|---|----------|----------|--------|
| 1 | Revert commits | `list_commits` | Any commit whose title begins with "Revert" — the most explicit form of feature death |
| 2 | Feature flag diffs | `get_commit` + `get_commit_diff` | Commits where diff lines match patterns like `FEATURE_X = false` or `.feature("name", false)` |
| 3 | Disable keywords | `list_commits` | Commit messages containing "disable", "remove", "kill", "bury", "flag-off", "roll-back", etc. |
| 4 | Shelved issues | `list_issues` | Closed issues with labels: disabled, wont-fix, wontfix, shelved, deferred, rejected |
| 5 | Feature-branch MRs | `list_merge_requests` | Merged `feature/*` or `feat/*` branches whose title contains disable keywords |
| 6 | GitLab Feature Flags API | `list_feature_flags` | Native GitLab flags where `active=false` — this is ground truth, not inference |

After detection, every feature with a kill commit SHA gets enriched: MR discussion notes and issue comments are fetched and attached as context snippets, and the actual diff lines that were removed are extracted and stored as `diff_excerpt`.

---

## Analysis pipeline

Once detection is complete, each dead feature passes through five analysis steps concurrently (viability, ROI, and competitive intelligence run in parallel once the kill reason is known):

### Kill reason classification

Gemini 3 Flash reads the kill commit message, linked MR notes, and issue threads and classifies the death into one of nine categories: `api_limitation`, `infrastructure`, `performance`, `resource_constraint`, `low_adoption`, `strategic_pivot`, `regulatory`, `technical_debt`, or `security`. It identifies the specific constraint and whether the kill was meant to be temporary.

### Viability scoring with live external verification

This is the most important step, and the one most AI tools get wrong: they use training data to guess whether a constraint is still valid. NECRO instead queries live external APIs before asking Gemini to evaluate.

`constraint_grounder.py` identifies the technology in the kill reason and calls the appropriate registry:

| Identified technology | API called | Evidence returned |
|-----------------------|------------|-------------------|
| npm packages (React, Stripe, Webpack, Zod, etc.) | `registry.npmjs.org/{pkg}` | Latest version + exact publish date |
| Open-source tools (Postgres, Redis, Docker, K8s, etc.) | `api.github.com/repos/{owner}/{repo}/releases/latest` | Release tag + publish date + URL |
| Python packages (Django, FastAPI, Pydantic, etc.) | `pypi.org/pypi/{pkg}/json` | Latest version + upload date |

Results are cached per constraint text so that multiple features sharing the same root cause (e.g. "webpack 4 incompatibility") only trigger one external API call per scan.

The grounding result gets injected verbatim into the Gemini prompt, along with an explicit instruction not to fabricate version numbers or dates outside what the API returned. Every `what_changed` claim in the report is labelled either **verified** (backed by a live API call with a source URL) or **AI-inferred** (no external evidence found, treat as hypothesis).

Viability scoring also pulls live CI pipeline status via `list_pipelines`. If the most recent pipeline failed, that fact goes into the prompt and a broken-CI risk is prepended to `technical_risks`. A `revive_now` recommendation won't stand against a broken CI baseline — it gets downgraded to `investigate_further`.

### Demand signals and ROI

`roi_estimator.py` fetches open and closed issues via MCP and keyword-matches them against the feature name. The result is a real count of issue references, not a number Gemini invented. Priority tier is P1–P4, demand level is high/medium/low/unknown. No dollar figures are fabricated — the report says things like "8 open issues are actively requesting this" rather than "$200K/year estimate."

A separate pass in `stream.py` (`_match_open_requests`) does token-overlap matching between the feature name and every open issue's title and body, producing an explicit list of open requests that are asking for something you already built and killed. When that list is non-empty, it appears as a red "Open Requests" section on the feature card.

### Competitive intelligence

Gemini 3 Flash assesses whether competitors have shipped the feature since the kill date. Returns market urgency (Critical / High / Medium / Low) and a brief gap description. This is opinion-level analysis, not grounded verification — it's clearly labelled as such.

### Adversarial challenge

Every `revive_now` candidate gets reviewed by a second, independent agent: **Vertex AI Gemini 2.5 Flash**, running on a different model family and different serving infrastructure. The challenger's prompt starts from a rejection position — it's required to:

- Score at least 1 point lower than the primary recommendation
- Produce exactly 3 specific, falsifiable failure scenarios
- State what the primary analysis got wrong

The challenger's verdict, score, strongest objection, and recommended first step all appear in the report and in the Ghost MR description. If the primary and challenger disagree significantly, that disagreement is surfaced in the ADK synthesis panel.

---

## Resurrection Chains

When two or more dead features share the same root constraint, NECRO groups them into a Resurrection Chain: *"webpack constraint: 1 upgrade unlocks 4 features simultaneously."*

`_compute_resurrection_chains()` scans every death reason and constraint text for 47 technology keywords and clusters features by shared constraint key. The chain panel shows the constraint, how many features it blocks, how many are revivable, an estimated combined impact, and a suggested fix. This is the systemic view — the insight that turns "revive one feature" into "fix one thing and unlock several."

---

## GitLab MCP tools

NECRO uses 19 GitLab MCP tools across the pipeline. The ADK agent carries a `MCPToolset` (via `@zereight/mcp-gitlab` over stdio, PAT auth) for agent-native tool calls. Backend routes use the GitLab REST API v4 directly via `httpx` for route-level operations and write actions.

| Tool | Where it's called | What it does |
|------|-------------------|--------------|
| `list_commits` | `git_forensics.py` | Paginated commit fetch — up to 500 commits across strategies 1–3 |
| `get_commit` | `git_forensics.py`, `revive.py` | Read diff for feature flag patterns; resolve kill commit author |
| `get_commit_diff` | `git_forensics.py` | Fetch unified diffs per file; extract removed code lines as evidence |
| `list_merge_requests` | `git_forensics.py` | Feature-branch MR detection (strategy 5) |
| `list_merge_request_notes` | `git_forensics.py` | MR discussion threads — kill context extraction |
| `list_issues` | `git_forensics.py`, `roi_estimator.py` | Closed shelved issues (strategy 4) + demand signal counts |
| `list_open_issues` | `stream.py` | All open issues for demand matching |
| `list_issue_notes` | `git_forensics.py` | Issue comment threads — additional kill context |
| `list_feature_flags` | `git_forensics.py` | GitLab native Feature Flags (`active=false`) |
| `list_pipelines` | `viability_scorer.py` | Live CI health check before scoring revival feasibility |
| `search_users` | `revive.py` | Resolve kill commit author email → GitLab user ID for auto-assignment |
| `list_project_members` | `gitlab_mcp.py` | Project member access-level queries |
| `get_file` | `gitlab_mcp.py` | Fetch file content at any ref |
| `get_user_by_username` | `gitlab_mcp.py` | Exact username lookup |
| `search_code` | `roi_estimator.py` | Code and MR references to a feature name |
| `get_project` | `revive.py` (Ghost MR) | Resolve default branch before branch creation |
| `create_issue` | `revive.py` | Create revival issue, auto-assign to kill commit author |
| `create_branch` | `revive.py` (Ghost MR) | Create `necro/revival/{slug}` branch |
| `create_file` | `revive.py` (Ghost MR) | Commit `NECRO_REVIVAL.md` with full checklist to branch |
| `create_merge_request` | `revive.py` (Ghost MR) | Open Draft MR, trigger `@duo_code_review` |

Every scan report includes a `mcp_calls_log` — a complete audit trail of which tools fired, against which repo, with result counts.

---

## Multi-agent model

Three agents, three roles, two independent model families:

| Agent | Model | Role |
|-------|-------|------|
| Primary Analyst | Gemini 3 Flash (`gemini-3-flash-preview`) | Kill reason extraction, viability scoring with `thinking_budget=1024`, ROI estimation, competitive intel |
| Challenger | Vertex AI Gemini 2.5 Flash | Adversarial review — starts from REJECT, must score lower, must produce falsifiable failure scenarios |
| Synthesis | ADK Runner + Gemini 3 Flash | Executive plan via `runner.run_async()` — top 3 priorities, graveyard pattern, open questions |

The Challenger uses a separate model family (Gemini 2.5 vs Gemini 3) on a different serving infrastructure (Vertex AI vs API key). This isn't just architectural: a challenger running on the same model as the primary would tend to agree with it. The disagreement only has value when it's genuinely independent.

---

## Ghost MR

The most concrete output NECRO can produce is a Ghost MR — a real draft merge request in your repository that scaffolds the revival.

When you click "Ghost MR" on a feature card, NECRO:

1. Creates branch `necro/revival/{feature-slug}` from the project's default branch
2. Commits `NECRO_REVIVAL.md` to that branch — a step-by-step revival checklist with the full analysis, kill commit reference, what changed, effort estimate, technical risks, and rollout plan
3. Opens a Draft MR from that branch, with the challenger's verdict in the description
4. Appends `@duo_code_review please review this revival scaffold` to the MR description — GitLab Duo's AI code review triggers automatically on every NECRO-created MR

The MR isn't just a report artifact. It's an actionable work item: review the plan, write the code, remove the `Draft:` prefix, and merge.

---

## GitLab integration

NECRO is built to live inside GitLab, not just call its API.

**CI/CD pipeline** — `.gitlab-ci.yml` runs seven stages: `build` (Docker image) → `test` (pytest) → `security` (SAST + Secret Detection + Dependency Scanning via GitLab built-in templates) → `upload` (Google Artifact Registry via Workload Identity Federation, no service account keys) → `deploy` (Cloud Run) → `necro-scan` (self-dogfooding scan via `POST /api/scan/quick`) → `necro-report` (post graveyard findings as a GitLab issue).

**Duo Custom Agent** — `.gitlab/duo/necro-agent.yaml` registers NECRO in the AI Catalog with system prompt, suggested prompts ("What can we revive?", "Show Resurrection Chains", "Are open issues requesting dead features?"), triggers (`@necro`, `necro-scan` label), and an external API hook pointing at the live Cloud Run URL.

**Post to GitLab** — one click posts the full graveyard report as a native GitLab issue in any project you have write access to, with a formatted table of all revival candidates.

**Autonomous watching** — add any repo to the watch list and APScheduler re-scans it every 24 hours. Slack alerts fire when new revival candidates appear.

**GitLab webhook** — `POST /api/agent/webhook/gitlab` re-evaluates a repo immediately on push events.

---

## Tech stack

| Technology | Role |
|---|---|
| **Gemini 3 Flash (`gemini-3-flash-preview`)** | Primary analysis — kill reasons, viability scoring, competitive intel, ADK synthesis |
| **Google ADK** | Agent orchestration — FunctionTools, MCPToolset, Runner, InMemorySessionService |
| **Vertex AI Gemini 2.5 Flash** | Adversarial challenger agent |
| **Google Cloud Run** | Serverless deployment, auto-scaling |
| **Google Artifact Registry** | Docker image storage |
| **GitLab MCP (`@zereight/mcp-gitlab`)** | Stdio MCP server — repo forensics, write operations |
| **GitLab REST API v4** | Backend routes — direct httpx calls |
| **MongoDB Atlas** | Primary store — scans, features, watch_list, revival_log |
| **Motor** | Async MongoDB driver |
| **FastAPI + SSE** | Async backend + real-time progress streaming |
| **APScheduler** | 24h autonomous re-scan loop |
| **Slack SDK** | Revival alerts + issue-created notifications |
| **Chart.js 4.4** | Timeline, feasibility distribution, kill category, cost-benefit scatter |
| **npm/GitHub/PyPI APIs** | Live constraint verification |

---

## Setup

### Prerequisites

```
Python 3.11+
Node.js 20+            — for @zereight/mcp-gitlab
MongoDB Atlas account  — free M0 tier works fine
GitLab account         — personal access token with `api` scope
Google Cloud project   — Vertex AI API enabled
Gemini API key         — from aistudio.google.com/apikey
```

### Install

```bash
git clone https://gitlab.com/ujwal240-group/ujwal240-project necro
cd necro
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
```

### Configure

```bash
cp .env.example .env
```

Open `.env` and fill in:

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

Open `http://localhost:8080`. The pre-scanned demo repos (`gitlab-org/gitlab-foss`, `inkscape/inkscape`) load instantly. Real scans stream live and take 60–120 seconds depending on repo size.

### Test

```bash
pytest tests/test_necro.py -q
# 95 non-live tests across 15 categories
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

Or push to the `master` branch and let the `.gitlab-ci.yml` pipeline handle it — the deploy stage runs automatically on default branch merges via Workload Identity Federation.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scan/stream` | SSE live scan — streams progress in real time |
| `POST` | `/api/scan/quick` | Synchronous scan — returns full JSON (for CI integration) |
| `POST` | `/api/scan/start` | Background scan — returns scan_id, poll for status |
| `GET` | `/api/scan/status/{id}` | Poll background scan progress |
| `POST` | `/api/scan/demo` | Load pre-seeded scan from MongoDB |
| `GET` | `/api/report/latest` | Most recent scan from MongoDB |
| `GET` | `/api/report/scans` | All past scan summaries |
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
| `GET` | `/api/health` | Full stack status — MongoDB, MCP, ADK, Slack, Gemini models |

---

## Project structure

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
│       ├── challenger.py     # Vertex AI adversarial agent
│       ├── adk_runner.py     # ADK runner initialization + synthesis helpers
│       ├── gemini.py         # Gemini 3 Flash client (primary + thinking budget)
│       ├── monitor.py        # APScheduler 24h watchlist loop
│       ├── slack_client.py   # Slack Block Kit alerts
│       └── output_writer.py  # Markdown + JSON report files
├── frontend/
│   ├── index.html            # Single-page app — 4 tabs, status overlay, repo browser
│   ├── style.css             # Dark/light theme, full design system
│   └── app.js                # SSE client, Chart.js charts, URL hash routing
├── tests/
│   └── test_necro.py         # 95 non-live tests across 15 categories
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
