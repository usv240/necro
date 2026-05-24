# NECRO — The Code Necromancer

**Live demo:** https://necro-agent-38381883054.us-central1.run.app  
**GitLab:** https://gitlab.com/ujwal240-group/ujwal240-project

> Every codebase has a graveyard of disabled features. Most of them died for reasons that no longer exist. NECRO is an AI agent that reads your GitLab repository, finds those dead features, and tells you which ones are worth bringing back to life — with verifiable, externally-grounded evidence.

---

## The Problem

Engineering teams disable features for a reason. But reasons expire. Stripe adds an API. A library ships a major version. Your infrastructure gets upgraded. The feature flag stays `false` forever because nobody tracks *why* it was killed — only *that* it was.

The institutional knowledge lives in a 3-year-old merge request that nobody will ever find.

**NECRO fixes that.** It reads your GitLab repository using MCP, extracts the kill reason via Gemini 3 Flash, checks whether that reason is still valid using **live external API evidence**, and recommends: **Revive Now / Investigate / Keep Buried** — with a full, clickable evidence trail.

---

## What Makes NECRO Different

1. **Six detection strategies** — revert commits, feature flag diffs, disable-keyword messages, closed shelved issues, feature-branch MRs, and **GitLab's native Feature Flags API** (`/api/v4/projects/:id/feature_flags`). Six independent signals, not just grep.

2. **Externally-grounded viability analysis** — the `what_changed` claim in every report is backed by a real API call. For npm packages: npm registry. For open-source tools: GitHub releases API. For Python packages: PyPI. Each claim is labelled **✓ verified** (with source URL) or **AI-inferred** (low confidence). No static knowledge bases.

3. **GitLab MCP in the critical path** — every commit, diff, MR discussion, issue, and feature flag is fetched via `@zereight/mcp-gitlab` (MCP over stdio, PAT auth). Every scan report includes a `mcp_calls_log` showing exactly which MCP tools fired and how many times.

4. **Google Cloud Agent Builder orchestrates every scan** — the primary scan goes through `runner.run_async()` with a natural-language prompt. The agent calls `scan_repository` via its FunctionTool, which uses the GitLab MCPToolset. Progress from inside the tool streams back to the SSE client via Python `contextvars`.

5. **Genuinely adversarial Challenger Agent** — after the primary analysis (Gemini 3 Flash via API key), a second model instance (Vertex AI Gemini 2.5 Flash — different model family, different serving infrastructure) adversarially stress-tests every `revive_now` recommendation. It is required to score at least 1 point lower and produce 3 specific, falsifiable failure scenarios.

6. **Post report as a GitLab issue** — after scanning, one click posts the entire graveyard report as a native GitLab issue in the scanned repository. NECRO becomes a GitLab citizen, not an external tool.

7. **Real write action** — creates individual GitLab revival issues via ADK agent MCPToolset `create_issue`, logged to MongoDB Atlas. Not just reading — taking action.

8. **Autonomous watching** — APScheduler re-scans watched repos every 24 hours. GitLab webhook endpoint triggers immediate re-evaluation on push. Slack alerts when new revival candidates appear.

9. **MongoDB Atlas persistence** — all scans, features, and revival logs stored in Atlas. Nothing in memory, nothing hardcoded.

10. **Zero fake demo data** — every Quick Scan button performs a real live scan of a real public GitLab repository using GitLab MCP. No pre-seeded data.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NECRO Stack                                 │
│                                                                          │
│  ┌─────────────────┐   ┌────────────────────────────────────────────┐   │
│  │  GitLab Repo    │──▶│  Google Cloud Agent Builder (ADK Runner)    │   │
│  │  (any public    │   │  runner.run_async() ── scan_repository tool │   │
│  │   or private)   │   │  Gemini 3 Flash · MCPToolset (GitLab MCP)  │   │
│  └─────────────────┘   └──────────────┬─────────────────────────────┘   │
│                                        │ contextvars → SSE progress      │
│  ┌─────────────────────────────────────▼────────────────────────────┐   │
│  │  GitLab MCP (@zereight/mcp-gitlab · stdio · PAT auth)            │   │
│  │  list_commits · get_commit · list_merge_requests                 │   │
│  │  list_merge_request_notes · list_issues · list_feature_flags     │   │
│  │  create_issue                                                     │   │
│  └─────────────────────────────┬────────────────────────────────────┘   │
│                                 │                                         │
│  ┌──────────────────────────────▼────────────────────────────────────┐  │
│  │  Analysis Pipeline                                                  │  │
│  │  git_forensics (6 strategies) → death_reason → viability_scorer  │  │
│  │  constraint_grounder (npm/GitHub/PyPI APIs) → roi_estimator       │  │
│  │  competitive_intel → Challenger (Vertex AI Gemini 2.5)            │  │
│  └──────────────────────────────┬────────────────────────────────────┘  │
│                                 │                                         │
│  ┌──────────────────────────────▼────────────────────────────────────┐  │
│  │  MongoDB Atlas (necro_db)                                          │  │
│  │  scans · features · watch_list · revival_log                      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  APScheduler ──24h──▶ re-scan repos ──▶ Slack alerts                    │
│  GitLab Webhook ──push──▶ re-evaluate buried features                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Constraint Grounding — Verifiable Evidence

The most common reason `revive_now` recommendations aren't trusted is that the `what_changed` claim is unverifiable. NECRO addresses this by querying real external APIs before asking Gemini to evaluate.

| Technology identified | API queried | Evidence returned |
|-----------------------|-------------|-------------------|
| npm package (React, Stripe, etc.) | `registry.npmjs.org/{pkg}` | Latest version + release date |
| Open-source tool (Postgres, Redis, etc.) | `api.github.com/repos/{owner}/{repo}/releases/latest` | Release tag + publish date + URL |
| Python package (Django, FastAPI, etc.) | `pypi.org/pypi/{pkg}/json` | Latest version + upload date |

Every `what_changed` claim in the report is labelled:
- **✓ verified** — backed by a real API response with a clickable source URL
- **AI-inferred** — no matching external API found; treat as hypothesis, not fact

---

## Detection Strategies

| # | Strategy | Data Source | What It Finds |
|---|----------|-------------|---------------|
| 1 | Revert commits | `list_commits` (GitLab MCP) | Features that were merged then immediately reverted |
| 2 | Feature flag diffs | `get_commit` diffs (GitLab MCP) | Code patterns like `FEATURE_X = False` removed from diffs |
| 3 | Disable-keyword messages | `list_commits` (GitLab MCP) | Commit messages containing "disable", "remove", "kill", etc. |
| 4 | Shelved issues | `list_issues` (GitLab MCP) | Closed issues with "shelved", "wontfix", "deferred" labels |
| 5 | Feature-branch MRs | `list_merge_requests` (GitLab MCP) | `feature/*` branches merged with disable keywords in title |
| 6 | **GitLab Feature Flags API** | `/api/v4/projects/:id/feature_flags` | Native GitLab flags with `active=False` — confirmed, not inferred |

---

## Multi-Agent Architecture

```
Primary Agent (Gemini 3 Flash · API key)
  └─ scan_repository tool → 6-strategy detection → Gemini analysis
  └─ viability_scorer → constraint_grounder (npm/GitHub/PyPI) → grounded evidence
  └─ roi_estimator → real issue count from GitLab MCP

Challenger Agent (Vertex AI Gemini 2.5 Flash — INDEPENDENT model)
  └─ Required to start from REJECT position
  └─ Must score ≤ primary_score - 1
  └─ Must produce 3 specific, falsifiable failure scenarios
  └─ Returns: confirm / downgrade / reject + what_primary_got_wrong
```

---

## Setup

### Environment Variables

```env
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx    # Personal Access Token (api + read_repository)
GITLAB_URL=https://gitlab.com
GEMINI_API_KEY=AIza...                      # Gemini 3 Flash (primary agent + analysis)
GOOGLE_PROJECT_ID=your-gcp-project-id      # Vertex AI (Challenger Agent — Gemini 2.5 Flash)
GOOGLE_LOCATION=us-central1
MONGODB_URI=mongodb+srv://...               # Atlas connection string
MONGODB_DB_NAME=necro_db
SLACK_BOT_TOKEN=xoxb-...                   # Optional — autonomous alerts
SLACK_CHANNEL_ID=C...                       # Optional
NECRO_WEBHOOK_SECRET=...                   # Optional — validate GitLab webhook payloads
APP_URL=https://your-deployment-url.run.app
```

### Local Development

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in your credentials
python -m uvicorn backend.main:app --reload --port 8080
```

### Deploy to Cloud Run

```bash
gcloud run deploy necro-agent \
  --source . \
  --project YOUR_PROJECT_ID \
  --region us-central1 \
  --env-vars-file deploy_env.yaml \
  --allow-unauthenticated
```

---

## GitLab CI Integration

Add NECRO scanning to any GitLab CI pipeline:

```yaml
# .gitlab-ci.yml
necro-graveyard-scan:
  stage: review
  image: curlimages/curl:latest
  script:
    - |
      curl -s -X POST https://necro-agent-38381883054.us-central1.run.app/api/scan/stream \
        -H "Content-Type: application/json" \
        -d "{\"repo_url\": \"$CI_PROJECT_URL\", \"max_commits\": 100, \"lookback_months\": 12}" \
        | grep "revive_now" | head -20
  allow_failure: true
  only:
    - schedules
```

This runs NECRO as a weekly scheduled job and surfaces revival candidates directly in CI.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scan/stream` | POST | SSE streaming scan (ADK Runner orchestrated) |
| `/api/report/latest` | GET | Most recent scan result from MongoDB |
| `/api/report/post-to-gitlab` | POST | Post graveyard as native GitLab issue |
| `/api/report/download` | GET | Download report as Markdown |
| `/api/agent/ask` | POST | Freeform ADK agent query |
| `/api/agent/revive` | POST | Create revival issue via ADK + MCPToolset |
| `/api/agent/webhook/gitlab` | POST | GitLab push webhook → re-evaluate repo |
| `/api/revive/{feature_id}` | POST | Direct revival issue creation |
| `/api/watch/add` | POST | Add repo to autonomous watch list |
| `/api/health` | GET | Service health + ADK/MCP/MongoDB status |

---

## License

MIT — see [LICENSE](LICENSE)


Engineering teams disable features for a reason. But reasons expire. Stripe adds an API. Your infrastructure gets upgraded. A regulation changes. The feature flag stays `false` forever because nobody tracks *why* it was killed — only *that* it was.

The institutional knowledge lives in a 3-year-old merge request that nobody will ever find.

**NECRO fixes that.** It reads your commit history using GitLab MCP, extracts the kill reason via Gemini 3 Flash, checks whether that reason is still valid, and recommends: **Revive Now / Investigate / Keep Buried** — with the full evidence trail attached.

---

## What Makes NECRO Different

1. **GitLab MCP in the critical path** — every commit, diff, MR discussion, and issue is fetched via `@zereight/mcp-gitlab` (MCP over stdio, PAT auth). No scraping, no static snapshots. Every scan report includes a `mcp_calls_log` showing exactly which MCP tools fired.
2. **Five detection strategies** — revert commits, feature flag diffs, disable-keyword messages, closed shelved issues, and feature-branch MRs. Five independent signals cross-checked.
3. **Every claim is cited** — commit SHA, MR number, or issue reference for every dead feature. No hallucinated reasons.
4. **Challenger Agent** — after the primary analysis, a second independent Gemini 3 Flash instance adversarially stress-tests every `revive_now` recommendation. Surfaces hidden risks the primary agent may have missed.
5. **Competitive intelligence** — Gemini 3 Flash checks whether competitors have shipped the feature since you killed it. Urgency: Critical → High → Medium → Low.
6. **Real write action** — creates a GitLab issue via MCP `create_issue`, logged to MongoDB Atlas. Not just reading — taking action on what it finds.
7. **Autonomous monitoring** — APScheduler re-scans watched repos every 24 hours and fires Slack alerts when new revival candidates appear.
8. **MongoDB Atlas persistence** — all scans, features, and revival logs stored in Atlas. Nothing in memory, nothing hardcoded.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          NECRO Stack                                 │
│                                                                      │
│  ┌─────────────────┐   ┌──────────────────────────────────────────┐  │
│  │  GitLab Repo    │──▶│  Google ADK Agent (Gemini 3 Flash)       │  │
│  │  (any public    │   │  ┌────────────────┐ ┌─────────────────┐  │  │
│  │   or private)   │   │  │ scan_repository│ │ save_report     │  │  │
│  └─────────────────┘   │  │   tool         │ │   tool          │  │  │
│                         │  └────────────────┘ └─────────────────┘  │  │
│                         │  ┌────────────────┐ ┌─────────────────┐  │  │
│                         │  │ create_issue   │ │ MCPToolset      │  │  │
│                         │  │   tool         │ │ (GitLab MCP)    │  │  │
│                         │  └────────────────┘ └─────────────────┘  │  │
│                         └──────────────────────────────────────────┘  │
│                                      │                                 │
│  ┌───────────────────────────────────▼────────────────────────────┐   │
│  │  GitLab MCP (@zereight/mcp-gitlab · stdio · PAT auth)          │   │
│  │  list_commits · get_commit · list_merge_requests               │   │
│  │  list_merge_request_notes · list_issues · create_issue         │   │
│  └────────────────────────────┬───────────────────────────────────┘   │
│                                │                                       │
│  ┌─────────────────────────────▼──────────────────────────────────┐   │
│  │  Analysis Pipeline                                              │   │
│  │  git_forensics → death_reason → viability_scorer → roi_est.   │   │
│  │  competitive_intel (Gemini 3) → output_writer                  │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                │                                       │
│  ┌─────────────────────────────▼──────────────────────────────────┐   │
│  │  MongoDB Atlas (necro_db)                                       │   │
│  │  scans · features · watch_list · revival_log                   │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                │                                       │
│  ┌─────────────────────────────▼──────────────────────────────────┐   │
│  │  FastAPI Backend (Cloud Run · us-central1 · 1Gi RAM)            │   │
│  │  /api/scan /api/report /api/revive /api/watch /api/monitor     │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                │                                       │
│  ┌─────────────────────────────▼──────────────────────────────────┐   │
│  │  Frontend (Vanilla JS + Chart.js 4.4)                           │   │
│  │  Graveyard · Timeline · Watch List · Revival Log                │   │
│  │  URL hash routing · light/dark theme · real-time SSE terminal  │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  APScheduler ──24h──▶ re-scan watched repos ──▶ Slack alerts        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Demo Scenarios

**Two pre-scanned repos** — load either with one click.

| Feature | Repo | Killed | Reason | Assessment |
|---|---|---|---|---|
| 💎 **Pages Wildcard Domains** | gitlab-foss | Sep 2021 | DNS CNAME subdomain takeover risk | **REVIVE NOW** — GitLab 16.x domain verification resolves the attack vector |
| 💎 **Container Registry Pull-Through Cache** | gitlab-foss | Nov 2021 | Storage ballooning + consistency | **REVIVE NOW** — Registry rewritten in Go (GitLab 15.8+) with TTL eviction |
| 🔍 **Elasticsearch for Free Tier** | gitlab-foss | Mar 2022 | Infrastructure cost per user | **INVESTIGATE** — Zoekt launched 2023; cost needs re-benchmarking |
| 🔍 **Bundled Mattermost** | gitlab-foss | Feb 2022 | ~4GB RAM per instance | **INVESTIGATE** — Lightweight OAuth link approach feasible |
| ⚰ **Geo for Omnibus Free Tier** | gitlab-foss | Jun 2020 | Support burden too high | **KEEP BURIED** — Still valid; Geo is key Premium conversion driver |
| 💎 **LPE Real-Time Preview** | inkscape | May 2022 | UI thread hangs 10-30s | **REVIVE NOW** — Inkscape 1.2+ threading refactor resolves the root cause |
| 🔍 **Ghostscript PDF Import** | inkscape | Apr 2021 | Text rasterizes to curves | **INVESTIGATE** — Fallback import for Poppler-unreadable PDFs is feasible |
| ⚰ **GTK2 Rendering Backend** | inkscape | Jan 2020 | GTK2 EOL, blocks GTK4 | **KEEP BURIED** — 6 years EOL, unpatched CVEs |
| ⚰ **Windows XP/Vista Build** | inkscape | Mar 2018 | Blocked Cairo/Pango upgrades | **KEEP BURIED** — Zero viable user base |

Every finding references a real commit SHA, MR number, or issue ID.

---

## Agent Pipeline

```
Browser → FastAPI → Google ADK Agent (gemini-3-flash-preview)
              │
              ├─ Tool 1: scan_repository_tool
              │     ├─► GitLab MCP: list_commits (5 detection strategies)
              │     ├─► GitLab MCP: get_commit (diffs, feature flags)
              │     ├─► GitLab MCP: list_merge_request_notes (kill context)
              │     ├─► GitLab MCP: list_issues (demand signals)
              │     ├─► Gemini 3 Flash: extract kill reason
              │     ├─► Gemini 3 Flash: score revival viability
              │     ├─► Gemini 3 Flash: estimate ROI
              │     └─► Gemini 3 Flash: analyze competitive gap
              │
              ├─ Tool 2: save_report_tool
              │     ├─► MongoDB Atlas: insert scan + features
              │     └─► write graveyard_report.md to disk
              │
              └─ Tool 3: create_revival_issue_tool
                    ├─► GitLab REST: create_issue (write action)
                    ├─► MongoDB Atlas: insert revival_log entry
                    └─► Slack: issue-created notification
```

The ADK agent also carries a **GitLab MCPToolset** (`StdioConnectionParams` → `@zereight/mcp-gitlab`) giving it direct access to native MCP tools: `list_commits`, `create_issue`, `get_project`, `search_code`, and more.

**Step 1 — Detect.** Five parallel strategies scan the commit history via GitLab MCP: revert commits, feature flag diffs, "remove/disable/discontinue" keywords, closed shelved issues, and feature-branch MRs.

**Step 2 — Diagnose.** For each dead feature, Gemini 3 Flash reads the kill commit diff, MR discussions, and linked issues to extract: kill reason category, specific constraint, whether it's temporary.

**Step 3 — Evaluate.** Gemini 3 Flash checks whether the original constraint is still valid, using a curated list of known industry changes (Stripe API additions, PostgreSQL upgrades, etc.). Returns feasibility score 0–10.

**Step 4 — Challenge.** A second independent Gemini 3 Flash instance (the Challenger Agent) adversarially stress-tests every `revive_now` recommendation. Asks: "What could cause this revival to fail?" and surfaces hidden risks the primary analysis may have missed. This is independent parallel execution — not a retry.

**Step 5 — Compete.** Gemini 3 Flash assesses whether competitors have shipped the feature since the kill date. Rates market urgency: Critical / High / Medium / Low.

**Step 6 — Report.** ADK `save_report` tool persists all findings to MongoDB Atlas and writes a markdown report to disk. Every report includes `mcp_calls_log` — a full audit trail of GitLab MCP tool calls (tool name, repo, result count).

**Step 7 — Act.** On user request, ADK `create_issue` tool creates a real GitLab issue with the full revival assessment and logs it to the `revival_log` MongoDB collection.

---

## GitLab MCP Integration

The ADK agent uses `MCPToolset` with `StdioConnectionParams` to connect to `@zereight/mcp-gitlab` — a PAT-authenticated MCP server running over stdio. No OAuth browser flow required; works server-side.

```python
# agent/agent.py
MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["--yes", "@zereight/mcp-gitlab"],
            env={
                "GITLAB_PERSONAL_ACCESS_TOKEN": token,
                "GITLAB_API_URL": "https://gitlab.com/api/v4",
            },
        )
    ),
    tool_filter=["create_issue", "list_commits", "get_commit",
                 "list_merge_requests", "list_issues", "get_project"],
)
```

Backend routes (revive endpoint) call the GitLab REST API v4 directly via `httpx` for issue creation and audit logging. The health endpoint reports both paths.

MCP tools used across the pipeline:

| MCP Tool | Used in |
|---|---|
| `list_commits` | `git_forensics.py` — detect dead features |
| `get_commit` | `git_forensics.py` — read diff for feature flags |
| `list_merge_requests` | `git_forensics.py` — detect feature branches |
| `list_merge_request_notes` | `git_forensics.py` — extract kill context |
| `list_issues` | `git_forensics.py` — demand signals |
| `create_issue` | `revive.py` — write action |

---

## Tech Stack

| Technology | Role |
|---|---|
| **Gemini 3 Flash (`gemini-3-flash-preview`)** | ADK orchestration, kill reason analysis, viability scoring, competitive intel |
| **Google ADK** | Agent framework — FunctionTools + MCPToolset, Runner, InMemorySessionService |
| **Gemini 2.5 Flash (Vertex AI)** | Fallback model under rate limits |
| **GitLab MCP (`@zereight/mcp-gitlab`)** | Stdio MCP server — PAT auth, repo forensics + issue creation |
| **GitLab REST API** | Backend routes — issue creation, audit logging |
| **MongoDB Atlas** | Primary store — scans, features, watch_list, revival_log |
| **Motor** | Async MongoDB driver |
| **FastAPI + SSE** | Async backend + real-time progress streaming |
| **APScheduler** | Autonomous 24h re-scan loop |
| **Slack SDK** | Revival candidate alerts + issue-created notifications |
| **Chart.js 4.4** | Timeline, feasibility distribution, kill category charts |
| **Google Cloud Run** | Serverless deployment, auto-scaling |

---

## Project Structure

```
necro/
├── agent/
│   ├── agent.py              # Google ADK agent — FunctionTools + MCPToolset
│   └── system_prompt.txt     # Agent system prompt (6-step NECRO process)
├── backend/
│   ├── main.py               # FastAPI app — MongoDB + APScheduler at startup
│   ├── config.py             # Settings (pydantic-settings + .env)
│   ├── db/
│   │   ├── connection.py     # Motor async client + index creation
│   │   ├── schemas.py        # Pydantic models (FeatureDoc, ScanDoc, etc.)
│   │   └── seed.py           # Seed demo data (gitlab-org/gitlab-foss real history)
│   ├── routes/
│   │   ├── scan.py           # POST /api/scan/start · /demo · GET /status
│   │   ├── stream.py         # POST /api/scan/stream — SSE real-time pipeline
│   │   ├── report.py         # GET /api/report/latest · /scans · /feature · /revival-log
│   │   ├── revive.py         # POST /api/revive/{id} — create_issue + MongoDB log
│   │   ├── watch.py          # GET/POST/DELETE /api/watch/*
│   │   └── monitor.py        # GET /api/monitor/status · POST /api/monitor/run
│   └── services/
│       ├── gitlab_mcp.py     # GitLab REST client (backend routes)
│       ├── git_forensics.py  # 5-strategy dead feature detection
│       ├── death_reason.py   # Gemini 3 kill reason extraction
│       ├── viability_scorer.py # Gemini 3 revival feasibility scoring
│       ├── roi_estimator.py  # Gemini 3 demand signal + ROI estimation
│       ├── competitive_intel.py # Gemini 3 competitive gap analysis
│       ├── monitor.py        # APScheduler autonomous monitoring loop
│       ├── slack_client.py   # Slack notifications
│       ├── gemini.py         # Gemini 3 Flash client (primary + Vertex fallback)
│       ├── adk_runner.py     # Lazy ADK runner initialization
│       └── output_writer.py  # Markdown + JSON report writer
├── frontend/
│   ├── index.html            # Single-page app (4 tabs)
│   ├── style.css             # Dark/light theme, full design system
│   └── app.js                # URL routing, Chart.js, real-time SSE, toast notifications
├── tests/
│   └── test_necro.py         # 42-test suite across 10 categories
├── requirements.txt
├── Dockerfile
├── LICENSE                   # Apache 2.0
└── README.md
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/scan/start` | Start background scan, returns scan_id |
| `GET` | `/api/scan/status/{id}` | Poll scan progress |
| `POST` | `/api/scan/demo` | Load pre-seeded gitlab-foss scan from MongoDB |
| `POST` | `/api/scan/stream` | SSE streaming — live agent pipeline output |
| `GET` | `/api/report/latest` | Most recent scan from MongoDB |
| `GET` | `/api/report/scans` | All past scans (history) |
| `GET` | `/api/report/feature/{id}` | Single feature with full competitive intel |
| `GET` | `/api/report/revival-log` | All revival issues created via NECRO |
| `GET` | `/api/report/download` | Download latest as markdown |
| `POST` | `/api/revive/{id}` | Create GitLab issue + log to MongoDB |
| `GET` | `/api/watch/list` | All watched repos |
| `POST` | `/api/watch/add` | Add repo to watch list |
| `DELETE` | `/api/watch/{path}` | Remove from watch list |
| `GET` | `/api/monitor/status` | APScheduler loop status + last run |
| `POST` | `/api/monitor/run` | Trigger monitor cycle immediately |
| `GET` | `/api/health` | Full stack status |

Health check response:
```json
{
  "status": "ok",
  "service": "necro-code-necromancer",
  "mongodb": "connected",
  "features_in_db": 5,
  "gitlab_mcp": "rest (ADK MCPToolset handles MCP in agent)",
  "adk_agent": "initialized",
  "slack": "configured",
  "monitor": { "running": true, "interval_hours": 24, "last_run": "..." },
  "gemini_primary": "gemini-3-flash-preview",
  "gemini_fallback": "gemini-2.5-flash (vertex-ai)"
}
```

---

## Setup

### Prerequisites

```
Python 3.11+
Node.js 20+            (for @zereight/mcp-gitlab)
MongoDB Atlas account  — cloud.mongodb.com (free M0 tier works)
GitLab account         — gitlab.com (personal access token: api scope)
Google Cloud project   — console.cloud.google.com
Gemini API key         — aistudio.google.com/apikey
```

### Install

```bash
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
```

### Configure

```bash
cp .env.example .env
# Fill in: GITLAB_TOKEN, MONGODB_URI, GOOGLE_PROJECT_ID, GEMINI_API_KEY
```

### Run

```bash
uvicorn backend.main:app --port 8080 --reload
# [OK] MongoDB connected (necro_db)
# [OK] GitLab REST client ready
# [OK] Autonomous monitor started (interval: 24h)
# Application startup complete.
```

Open `http://localhost:8080`. Click **"gitlab-org/gitlab-foss (pre-scanned)"** to load the demo.

### Test

```bash
python -m pytest tests/test_necro.py -v
# 42 tests across 10 categories
```

---

## Deploy to Cloud Run

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/necro-agent

gcloud run deploy necro-agent \
  --image gcr.io/PROJECT_ID/necro-agent \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --set-env-vars "MONGODB_URI=...,GITLAB_TOKEN=...,GEMINI_API_KEY=...,GOOGLE_PROJECT_ID=..."
```

---

## License

Apache 2.0 — see [LICENSE](./LICENSE)

Built with Gemini 3 Flash · Google ADK · GitLab MCP · MongoDB Atlas · APScheduler · Slack · Chart.js · Cloud Run
