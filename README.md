# NECRO — Code Lifecycle Intelligence

NECRO reads your GitLab history and your live codebase, then helps you decide what your
dead code deserves: a second life, or a proper burial. It doesn't just point at problems —
it reasons about them, checks the evidence, and opens the merge request to act on it.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-necro--agent-blue?style=flat-square)](https://necro-agent-38381883054.us-central1.run.app)
[![License](https://img.shields.io/badge/License-Apache%202.0-green?style=flat-square)](./LICENSE)

**[Open the live app →](https://necro-agent-38381883054.us-central1.run.app)**

---

## The idea

Every codebase carries two kinds of dead weight:

1. **Features that were killed** for a reason that no longer applies. A flag was turned off
   because a library couldn't do something in 2021. The library can do it now. Nobody went
   back. The team eventually rebuilds it from scratch.
2. **Code that was deprecated but never removed.** A `@deprecated` annotation, a `TODO: remove`,
   a feature flag marked `Deprecated: true`. It's been sitting there for years, adding noise
   and risk, because deleting code is scary and nobody's sure it's safe.

NECRO handles both directions of that lifecycle:

```
  shipped ──► killed ──┬──► is the kill reason still valid?  ──► REVIVE
                       │
                       └──► deprecated but never deleted? ───► EXCISE
```

Same engine, mirror-imaged. One side asks *"should this come back?"*, the other asks
*"is it finally safe to delete this?"* — and both back every answer with live evidence.

---

## What it does

### 1. Revival — bring back what's worth saving

Paste a GitLab URL. NECRO finds disabled features across commits, merge requests, issues, and
feature flags, works out *why* each was killed, then checks whether that reason still holds:

- **Live verification** — Google Search + npm/GitHub/PyPI APIs confirm whether the blocking
  constraint was resolved, and when, with a citable URL. Claims are labelled *verified* or
  *AI-inferred* — nothing is presented as fact without a source.
- **Demand signals** — matches open issues that are still asking for the feature.
- **Adversarial challenge** — a second model argues *against* each revival and has to produce
  specific reasons it might fail.
- **Verdict** — Revive Now / Investigate / Keep Buried, with effort and risk.

### 2. Necrosis — excise what's been dead too long

NECRO scans the *live codebase* (not just history) for deprecation markers — `@deprecated`,
`Deprecated: true`, `TODO: remove`, `//nolint:staticcheck`, and more. For each one it:

- Dates the annotation with per-line `git blame` (how long has it actually been undead?).
- Counts live callers via code search — **if anything still references it, NECRO will not tell
  you to delete it.**
- Returns Excise Now / Needs Biopsy / Leave Intact, plus the blast radius.

### 3. Mission — let the agent finish the job

Give NECRO one instruction and it runs the whole loop on its own:

```
RECON → PLAN → CHALLENGE → ACT → VERIFY → REPORT
```

It scans for both revivals and dead code, the planning agent picks the single highest-value
feature to revive and the safest code to excise, the adversarial agent red-teams the plan,
and then NECRO **acts** — it opens real GitLab Draft MRs (a revival scaffold and a deletion
plan), verifies the files landed, and posts a summary issue linking everything. If the
challenger rejects a revival, NECRO respects that and opens a discussion issue instead of a
merge request. A dry-run mode plans and prepares everything without writing — you stay in
control.

---

## How it's built

Three models with distinct jobs, not one model behind three prompts:

| Role | What it does |
|---|---|
| **Analyst** | Extracts kill reasons, scores revival viability and deletion safety |
| **Challenger** | Starts from "reject" and must find falsifiable reasons an action will fail |
| **Synthesis / Planner** | Reasons over all findings, picks priorities, plans the mission |

The analyst and planner run on Google Cloud Agent Builder (ADK) with Gemini and the
`google_search` tool; the challenger runs on separate infrastructure so its disagreement is
structural, not cosmetic.

### GitLab integration

NECRO lives inside GitLab rather than just calling its API:

- **GitLab MCP tools** — `list_commits`, `get_commit`, `get_commit_diff`, `list_issues`,
  `list_merge_requests`, `list_feature_flags`, `search_blobs` (live code search),
  `get_file_blame` (per-line dating), `create_branch`, `create_file`, `create_merge_request`,
  `create_issue`, and more.
- **NECRO as an MCP server** — exposes `scan_repository`, `get_candidates`, `get_health` at
  `/mcp` so other tools can call it.
- **Duo Custom Agent** — `.gitlab/duo/necro-agent.yaml` registers NECRO in the GitLab AI
  Catalog; trigger it with `@necro` in Duo Chat.
- **Ghost MRs** — one click (or one mission) creates a real branch, commits a plan file, and
  opens a Draft MR with `@duo_code_review`.
- **CI** — `.gitlab-ci.yml` runs a scan on every push and can post findings as issues.

### Stack

| | |
|---|---|
| **Google Cloud Agent Builder (ADK)** | Multi-tool agent orchestration |
| **Gemini** | Kill-reason extraction, viability + deletion scoring, mission planning |
| **Google Search** | Live constraint verification with cited URLs |
| **Vertex AI** | The adversarial challenger (separate from the primary) |
| **Google Cloud Run** | Serverless hosting |
| **MongoDB Atlas + Vector Search** | Scan history, findings, demand matching via embeddings |
| **FastAPI + SSE** | Async backend with real-time scan streaming |

---

## Quick start

### Try it live

**[https://necro-agent-38381883054.us-central1.run.app](https://necro-agent-38381883054.us-central1.run.app)**

- **Instant demo** chips load pre-analyzed results in about a second.
- **Live scan** chips (or any public GitLab URL) run the real pipeline in 60–120 seconds.
- **Mission Control** runs the full autonomous loop.

### Run locally

**Prerequisites:** Python 3.11+, Node 20+, a MongoDB Atlas account (free tier is fine), a
GitLab personal access token with `api` + `read_repository`, a Gemini API key, and a Google
Cloud project with Vertex AI enabled.

```bash
git clone https://github.com/usv240/necro.git
cd necro
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
cp .env.example .env   # fill in your credentials
uvicorn backend.main:app --port 8080 --reload
```

Open `http://localhost:8080`.

`.env` keys:

```env
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
GEMINI_API_KEY=AIza...
GOOGLE_PROJECT_ID=your-gcp-project-id
MONGODB_URI=mongodb+srv://...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...   # optional
```

### Run tests

```bash
pytest tests/test_necro.py -q          # full suite
pytest tests/test_necro.py -m unit     # pure-Python units, no server needed
```

The unit tests run without a backend; integration tests run when the server is live on
`localhost:8080`.

---

## API reference

| Method | Endpoint | What it does |
|--------|----------|--------------|
| `POST` | `/api/scan/stream` | Revival scan — SSE stream with live progress |
| `POST` | `/api/scan/demo` | Load a cached revival scan (instant) |
| `POST` | `/api/scan/group` | Scan an entire GitLab namespace |
| `POST` | `/api/necrosis/scan` | Dead-code scan — SSE stream |
| `POST` | `/api/necrosis/demo` | Load a cached necrosis scan (instant) |
| `POST` | `/api/agent/mission` | Autonomous mission — SSE stream |
| `GET`  | `/api/agent/mission/latest` | Replay the most recent mission |
| `POST` | `/api/revive/{id}` | Create a revival issue |
| `POST` | `/api/revive/{id}/ghost-mr` | Branch + plan file + Draft MR |
| `POST` | `/api/necrosis/{id}/deletion-mr` | Branch + deletion plan + Draft MR |
| `GET`  | `/api/health` | Full stack status |
| `POST` | `/mcp` | NECRO's own MCP endpoint |

---

## Project structure

```
necro/
├── agent/                      # ADK agent + system prompt
├── backend/
│   ├── main.py                 # FastAPI app + health
│   ├── routes/
│   │   ├── stream.py           # revival SSE scan
│   │   ├── scan.py             # background + cached demo scans
│   │   ├── necrosis.py         # dead-code scan + deletion MR
│   │   ├── agent.py            # ADK ask + autonomous mission + webhook
│   │   ├── revive.py           # revival issue + Ghost MR
│   │   ├── report.py · watch.py · monitor.py
│   └── services/
│       ├── git_forensics.py        # dead-feature detection (history)
│       ├── necrosis_detector.py    # dead-code detection (live codebase)
│       ├── death_reason.py         # kill-reason classification
│       ├── viability_scorer.py     # revival scoring + constraint check
│       ├── deletion_scorer.py      # deletion-safety scoring + caller count
│       ├── constraint_grounder.py  # npm / GitHub / PyPI verification
│       ├── challenger.py           # adversarial agent
│       ├── mission.py              # autonomous closed-loop orchestrator
│       ├── adk_runner.py · gemini.py · gitlab_mcp.py · ...
├── frontend/                   # single-page app (revival, necrosis, mission)
├── tests/                      # unit + integration suite
├── .gitlab/duo/necro-agent.yaml
├── .gitlab-ci.yml
└── LICENSE
```

---

## License

[Apache 2.0](./LICENSE)
