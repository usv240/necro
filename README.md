# NECRO — Code Revival Intelligence

**Find the features your team already built, paid for, and accidentally buried — then ship them.**

> 🏆 Built for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com) · **GitLab Track**

[![Live Demo](https://img.shields.io/badge/Live%20Demo-necro--agent-blue?style=flat-square)](https://necro-agent-38381883054.us-central1.run.app)
[![License](https://img.shields.io/badge/License-Apache%202.0-green?style=flat-square)](./LICENSE)
[![GitLab CI](https://img.shields.io/badge/CI-GitLab%20Pipeline-orange?style=flat-square)](https://gitlab.com/ujwal240-group/ujwal240-project/-/pipelines)

🚀 **[Open the live app →](https://necro-agent-38381883054.us-central1.run.app)**

---

## What is NECRO?

NECRO is a **multi-agent AI forensics tool** that scans your GitLab repository and finds disabled features whose original kill reasons no longer apply — so your team can revive them instead of rebuilding from scratch.

**Paste a GitLab URL. Get a ranked revival plan in 60–90 seconds.**

### What you get from a scan

- 📋 **Every disabled feature** found across commits, MRs, issues, and GitLab Feature Flags
- 🔍 **The exact kill reason** — extracted from commit messages, MR discussions, and issue threads
- ✅ **Live verification** — Google Search + npm/GitHub/PyPI APIs confirm whether the constraint was resolved and when, with a cited URL
- ⚔️ **Adversarial challenge** — a second AI agent stress-tests every "revive" recommendation and finds reasons it might fail
- 📊 **Ranked action plan** — Google Cloud Agent Builder synthesizes all findings into top 3 priorities
- 🔀 **One-click action** — create a real GitLab issue or Draft MR with a full revival checklist

---

## The Problem

**GitLab Pages** wildcard domain support was disabled in 2021 because of a DNS subdomain takeover vulnerability. GitLab shipped subdomain verification in 2023. Three years later, the feature was still disabled — and 312 open issues were requesting it back. Nobody connected the dots.

This pattern repeats on every engineering team. A feature gets killed for a reason that made sense at the time. The reason disappears. The feature stays dead. The team eventually rebuilds the same thing from scratch — or a competitor ships it first.

**The average team of 25 engineers wastes $140K+/year** this way.

NECRO connects those dots automatically.

---

## How It Works

### Phase 1 — Find and Analyze (60–90 seconds)

**Step 1: Detect dead features** via 6 independent strategies using GitLab MCP tools:

| # | Strategy | What it finds |
|---|---|---|
| 1 | Revert commits | Commits beginning with "Revert" — explicit feature deaths |
| 2 | Feature flag diffs | Commits setting `FEATURE_X = false` or `.feature("name", false)` |
| 3 | Disable keywords | Commits containing "disable", "remove", "kill", "flag-off", etc. |
| 4 | Shelved issues | Closed issues labeled: `wont-fix`, `shelved`, `deferred`, `rejected` |
| 5 | Feature-branch MRs | Merged `feature/*` branches with disable keywords in the title |
| 6 | GitLab Feature Flags API | Native flags via `GET /api/v4/projects/:id/feature_flags` where `active=false` |

**Step 2: Classify the kill reason** — Gemini 3 Flash reads the commit message, MR discussion, and linked issue threads to identify the specific constraint. Categories: `api_limitation`, `infrastructure`, `performance`, `security`, `technical_debt`, `strategic_pivot`, and more.

**Step 3: Verify the constraint is still real** — two independent live sources:

- **Google Search** (ADK built-in tool): searches `"[library] [capability] release notes"` or `"CVE-XXXX patch fix"` and cites the URL + date in the result
- **Registry APIs**: queries npm, GitHub releases, and PyPI for the latest version and publish date

Every "what changed" claim is labelled **verified** (backed by a live source) or **AI-inferred** (no evidence found — treat as hypothesis). Nothing is fabricated.

**Step 4: Score revival viability** — outputs one of three verdicts:
- 🟢 **Revive Now** — constraint resolved, clear path forward
- 🟡 **Investigate Further** — partial evidence, needs human review
- 🔴 **Keep Buried** — constraint still applies

**Step 5: Adversarial challenge** — a second Gemini 3 Flash agent running on Vertex AI starts from a rejection position and must produce three specific, falsifiable failure scenarios for every "Revive Now" candidate.

**Step 6: Resurrection Chains** — features that share a root constraint are grouped: *"One webpack upgrade unlocks 4 features simultaneously."* One fix, multiple revivals.

### Phase 2 — ADK Synthesis (5–10 seconds)

Google Cloud Agent Builder (ADK) reads all Phase 1 findings and uses `google_search` + GitLab MCPToolsets + FunctionTools to produce:
- Top 3 revival priorities with reasoning
- The single most common constraint blocking your graveyard
- Open questions that need answering before action

Results stream live to the browser as they're produced.

---

## Multi-Agent Design

Three agents with distinct roles — not the same model with different prompts:

| Agent | Model | Infrastructure | Role |
|---|---|---|---|
| **Primary Analyst** | Gemini 3 Flash | Google AI (via ADK) | Kill reason extraction, viability scoring, ROI, competitive intel |
| **Challenger** | Gemini 3 Flash | Vertex AI (separate SDK) | Adversarial red team — starts from REJECT, finds failure scenarios |
| **Synthesis** | Gemini 3 Flash | ADK Runner | Strategic plan — multi-tool reasoning with google_search + MCP |

The Challenger is structurally required to disagree. It runs on separate infrastructure with a separate adversarial prompt and must produce falsifiable objections.

---

## GitLab Integration

NECRO doesn't just call the GitLab API — it lives inside GitLab:

- **Official GitLab MCP Server** (`/-/ide/mcp`, SSE transport) — authoritative, 10 tools
- **@zereight/mcp-gitlab** (stdio transport) — supplementary, 9 additional tools; **19 tools total**
- **NECRO as MCP Server** — NECRO exposes itself at `/mcp`. Other GitLab Duo agents can call `scan_repository`, `get_candidates`, and `get_health` as tools
- **Duo Custom Agent** — `.gitlab/duo/necro-agent.yaml` registers NECRO in the GitLab AI Catalog. Trigger with `@necro` in Duo Chat
- **Ghost MR** — one click creates a real branch + commits `NECRO_REVIVAL.md` + opens a Draft MR with `@duo_code_review` — 3 GitLab write operations via MCP
- **Post to GitLab** — post the full graveyard report as a native GitLab issue in any project
- **CI/CD native** — `.gitlab-ci.yml` runs NECRO as a scan step on every push; findings post as GitLab issues automatically
- **GitLab webhook** — push events trigger immediate re-evaluation via `POST /api/agent/webhook/gitlab`
- **Group scan** — scan an entire GitLab namespace in parallel; surfaces cross-repository patterns

---

## Tech Stack

| Technology | Role |
|---|---|
| **Google Cloud Agent Builder (ADK)** | Multi-tool agent orchestration — `FunctionTool`, `MCPToolset`, `Runner`, `InMemorySessionService` |
| **Gemini 3 Flash (`gemini-3-flash-preview`)** | Primary LLM — kill reason extraction, viability scoring, ADK synthesis |
| **Google Search** (ADK built-in tool) | Live constraint verification — every claim has a cited URL and date |
| **Google Cloud Vertex AI** | Adversarial challenger agent — separate infrastructure from primary |
| **Google Cloud Run** | Serverless deployment (`min-instances 1`, no cold start) |
| **Google Artifact Registry** | Docker image storage |
| **GitLab MCP — Official SSE** | Authoritative GitLab MCP server (`/-/ide/mcp`) — 10 tools |
| **GitLab MCP — @zereight/mcp-gitlab** | Community MCP server (stdio) — 9 supplementary tools |
| **NECRO MCP Server (`/mcp`)** | NECRO exposes itself as an MCP endpoint (FastMCP) |
| **MongoDB Atlas** | Scan history, feature store, watch list, revival log, embeddings |
| **MongoDB Vector Search** | Semantic demand matching via `text-embedding-004` |
| **FastAPI + SSE** | Async backend + real-time scan progress streaming |
| **Slack SDK** | Revival alerts and autonomous notifications |
| **Chart.js** | Timeline, kill-category distribution, feasibility heatmap |

---

## Quick Start

### Try the live app (no setup needed)

**[https://necro-agent-38381883054.us-central1.run.app](https://necro-agent-38381883054.us-central1.run.app)**

- Click any **INSTANT DEMO** chip for pre-analyzed results (loads in 1 second)
- Click any **LIVE SCAN** chip or paste your own GitLab URL for a live scan (60–90 seconds)
- Any public GitLab repository works — paste the full URL like `https://gitlab.com/org/repo`

### Run locally

**Prerequisites:**
- Python 3.11+
- Node.js 20+ (for `@zereight/mcp-gitlab`)
- MongoDB Atlas account (free M0 tier works)
- GitLab personal access token with `api` + `read_repository` scopes
- Gemini API key from [aistudio.google.com](https://aistudio.google.com/apikey)
- Google Cloud project with Vertex AI API enabled

```bash
git clone https://github.com/usv240/necro.git
cd necro
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
cp .env.example .env   # then fill in your credentials
uvicorn backend.main:app --port 8080 --reload
```

Open `http://localhost:8080`.

**`.env` keys:**

```env
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
GEMINI_API_KEY=AIza...
GOOGLE_PROJECT_ID=your-gcp-project-id
MONGODB_URI=mongodb+srv://...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...   # optional
```

### Run tests

```bash
pytest tests/test_necro.py -q
# 10 unit tests run always (no server needed)
# 134 integration tests run when backend is live on localhost:8080
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
  --min-instances 1 \
  --set-env-vars "MONGODB_URI=...,GITLAB_TOKEN=...,GEMINI_API_KEY=...,GOOGLE_PROJECT_ID=..."
```

Or push to `main` on GitLab — the `.gitlab-ci.yml` deploy stage runs automatically when `GOOGLE_PROJECT_ID` is set as a CI variable.

---

## Architecture

```
Browser → FastAPI → SSE stream
              │
    ┌─────────▼──────────────────────────────────┐
    │  PHASE 1 — Data Collection (parallel)       │
    │                                             │
    │  6 detection strategies via GitLab MCP      │
    │  ├─ list_commits / get_commit_diff          │
    │  ├─ list_merge_requests / notes             │
    │  ├─ list_issues / issue_notes               │
    │  └─ list_feature_flags (active=false)       │
    │                                             │
    │  Per-feature analysis (asyncio batches)     │
    │  ├─ death_reason.py    → Gemini 3 Flash     │
    │  ├─ viability_scorer.py                     │
    │  │   ├─ google_search  → live URL evidence  │
    │  │   └─ constraint_grounder.py → npm/PyPI   │
    │  ├─ roi_estimator.py   → issue demand count │
    │  ├─ competitive_intel.py → market urgency   │
    │  └─ challenger.py     → Vertex AI red team  │
    │                                             │
    │  Resurrection chains + open request match   │
    └─────────────┬───────────────────────────────┘
                  │
    ┌─────────────▼───────────────────────────────┐
    │  PHASE 2 — ADK Synthesis                     │
    │                                             │
    │  ADK Runner (google_search + MCPToolset)    │
    │  → top 3 priorities                         │
    │  → graveyard pattern                        │
    │  → executive action plan                    │
    └─────────────┬───────────────────────────────┘
                  │
    ┌─────────────▼───────────────────────────────┐
    │  Output                                      │
    │  MongoDB Atlas · GitLab issue · Ghost MR     │
    │  graveyard_report.md + .json                │
    │  Slack alert (optional)                     │
    └─────────────────────────────────────────────┘
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scan/stream` | **Primary scan** — SSE stream, real-time progress |
| `POST` | `/api/scan/quick` | Synchronous scan — returns full JSON (for CI) |
| `POST` | `/api/scan/demo` | Load pre-seeded demo scan from MongoDB |
| `POST` | `/api/scan/group` | Scan entire GitLab namespace in parallel |
| `GET` | `/api/report/latest` | Most recent scan |
| `GET` | `/api/report/all-features` | All features across all scans |
| `POST` | `/api/report/post-to-gitlab` | Post graveyard as a GitLab issue |
| `POST` | `/api/report/notify-slack` | Send report to Slack |
| `POST` | `/api/revive/{id}` | Create revival issue, auto-assign to kill commit author |
| `POST` | `/api/revive/{id}/ghost-mr` | Branch + `NECRO_REVIVAL.md` + Draft MR |
| `POST` | `/api/agent/ask` | Freeform ADK agent query (SSE) |
| `POST` | `/api/agent/webhook/gitlab` | GitLab push webhook → immediate re-evaluation |
| `GET` | `/api/watch/list` | Autonomous watch list |
| `POST` | `/api/watch/add` | Add repo to watch list |
| `GET` | `/api/health` | Full stack status — MongoDB, MCP, ADK, google_search, Slack |
| `POST` | `/mcp` | **NECRO MCP endpoint** — consumable by GitLab Duo agents |

---

## Project Structure

```
necro/
├── agent/
│   ├── agent.py              # ADK agent — google_search + FunctionTools + MCPToolset
│   └── system_prompt.txt     # 4-step NECRO process with mandatory google_search
├── backend/
│   ├── main.py               # FastAPI app + health endpoint
│   ├── config.py             # Settings via pydantic-settings
│   ├── db/
│   │   ├── connection.py     # Motor async MongoDB client
│   │   ├── schemas.py        # Pydantic models
│   │   └── seed.py           # Pre-analyzed demo data (real commit SHAs)
│   ├── routes/
│   │   ├── stream.py         # SSE scan — resurrection chains + ADK synthesis
│   │   ├── scan.py           # Background + sync scans
│   │   ├── report.py         # Retrieval + post-to-gitlab + Slack
│   │   ├── revive.py         # Create issue + Ghost MR (3 write ops via MCP)
│   │   ├── agent.py          # ADK ask + revive + GitLab webhook
│   │   ├── watch.py          # Watchlist CRUD
│   │   └── monitor.py        # APScheduler 24h loop
│   └── services/
│       ├── gitlab_mcp.py     # GitLab REST client wrapping 19 MCP tools
│       ├── git_forensics.py  # 6-strategy dead feature detection
│       ├── death_reason.py   # Kill reason classification (Gemini 3 Flash)
│       ├── viability_scorer.py  # Revival scoring + CI health check
│       ├── constraint_grounder.py  # npm / GitHub / PyPI live verification
│       ├── roi_estimator.py  # Demand signal aggregation from issue counts
│       ├── competitive_intel.py  # Market urgency analysis
│       ├── challenger.py     # Adversarial agent (Vertex AI, separate SDK)
│       ├── adk_runner.py     # ADK runner + synthesis helpers
│       ├── gemini.py         # Gemini 3 Flash primary client
│       ├── monitor.py        # APScheduler watchlist loop
│       ├── slack_client.py   # Slack Block Kit alerts
│       └── output_writer.py  # Markdown + JSON report output
├── frontend/
│   ├── index.html            # Single-page app — 5 tabs, live terminal
│   ├── style.css             # Dark/light theme, mobile responsive
│   └── app.js                # SSE client, Chart.js, URL parsing, routing
├── tests/
│   ├── conftest.py           # Auto-skip integration tests in CI
│   └── test_necro.py         # 144 tests — 10 unit + 134 integration
├── .gitlab-ci.yml            # CI pipeline (test → security → scan → deploy)
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

[Apache 2.0](./LICENSE)
