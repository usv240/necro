# NECRO: Code Lifecycle Intelligence

NECRO reads your GitLab history and your live codebase, then helps you decide what your
dead code deserves: a second life, or a proper burial. It does not just point at problems.
It reasons about them, checks the evidence, and opens the merge request to act on it.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-necro--agent-blue?style=flat-square)](https://necro-agent-38381883054.us-central1.run.app)
[![License](https://img.shields.io/badge/License-Apache%202.0-green?style=flat-square)](./LICENSE)

**[Open the live app](https://necro-agent-38381883054.us-central1.run.app)**

---

## The idea

Every codebase carries two kinds of dead weight:

1. **Features that were killed** for a reason that no longer applies. A flag was turned off
   because a library could not do something in 2021. The library can do it now. Nobody went
   back. The team eventually rebuilds it from scratch.
2. **Code that was deprecated but never removed.** A `@deprecated` annotation, a `TODO: remove`,
   a feature flag marked `Deprecated: true`. It has been sitting there for years, adding noise
   and risk, because deleting code is scary and nobody is sure it is safe.

NECRO handles both directions of that lifecycle:

```
  shipped --> killed --+--> is the kill reason still valid?  --> REVIVE
                       |
                       +--> deprecated but never deleted?    --> EXCISE
```

Same engine, mirror-imaged. One side asks "should this come back?", the other asks
"is it finally safe to delete this?" and both back every answer with live evidence.

---

## What it does

### 1. Revival: bring back what is worth saving

Paste a GitLab URL. NECRO finds disabled features across commits, merge requests, issues, and
feature flags, works out why each was killed, then checks whether that reason still holds:

- **Live verification.** Google Search and npm/GitHub/PyPI APIs confirm whether the blocking
  constraint was resolved, and when, with a citable URL. Claims are labelled "verified" or
  "AI-inferred" and nothing is presented as fact without a source.
- **Demand signals.** Matches open issues that are still asking for the feature.
- **Adversarial challenge.** A second model argues against each revival and has to produce
  specific reasons it might fail.
- **Verdict.** Revive Now, Investigate, or Keep Buried, with effort and risk.

### 2. Necrosis: excise what has been dead too long

NECRO scans the live codebase (not just history) for deprecation markers: `@deprecated`,
`Deprecated: true`, `TODO: remove`, `//nolint:staticcheck`, and more. For each one it:

- Dates the annotation with per-line `git blame` (how long has it actually been undead?).
- Counts live callers via code search. If anything still references it, NECRO will not tell
  you to delete it.
- Returns Excise Now, Needs Biopsy, or Leave Intact, plus the blast radius.

### 3. Mission: let the agent finish the job

Give NECRO one instruction and it runs the whole loop on its own:

```
RECON --> PLAN --> CHALLENGE --> ACT --> VERIFY --> REPORT
```

It scans for both revivals and dead code, the planning agent picks the single highest-value
feature to revive and the safest code to excise, the adversarial agent red-teams the plan,
and then NECRO acts. It opens real GitLab Draft MRs (a revival scaffold and a deletion
plan), verifies the files landed, and posts a summary issue linking everything. A dry-run
mode plans and prepares everything without writing so you stay in control.

---

## Architecture

### The three-model design

NECRO uses three models with distinct, non-overlapping jobs. They do not share context.

```
User submits GitLab URL
        |
        v
+------------------+
|   Analyst        |  Gemini 3 Flash (Google AI Studio)
|                  |  - Reads GitLab history via MCP tools
|                  |  - Extracts kill reasons
|                  |  - Scores revival viability / deletion safety
+------------------+
        |
        | Candidates that pass the threshold
        v
+------------------+
|   Challenger     |  Gemini Flash (Vertex AI, separate infrastructure)
|                  |  - Starts from "reject"
|                  |  - Finds specific, falsifiable failure reasons
|                  |  - If it cannot find one, the candidate survives
+------------------+
        |
        | Surviving candidates
        v
+------------------+
|   Planner        |  Gemini 3 Flash + Google ADK
|                  |  - Ranks all findings
|                  |  - Writes the mission plan
|                  |  - Opens GitLab Draft MRs and issues
+------------------+
        |
        v
   Report delivered to browser via SSE stream
```

The challenger runs on Vertex AI rather than the same endpoint as the analyst. This is
intentional. They are structurally independent, not just different prompts on the same backend.
See [ADR 001](./adr/001-multi-agent-architecture.md) and [ADR 002](./adr/002-adversarial-challenger.md).

### How a scan works, step by step

1. You paste a GitLab URL and click Run.
2. The backend starts an async scan and opens an SSE stream to your browser.
3. The analyst calls GitLab MCP tools to read commit history, issues, feature flags, and merge requests.
4. It identifies patterns that look like deliberate disablements (for revival) or deprecation markers (for necrosis).
5. For each candidate, it calls Google Search to verify whether the original blocker still applies.
6. For revival candidates above the confidence threshold, the challenger model is invoked separately to argue against the proposal.
7. The planner synthesises everything into a ranked report.
8. If you are in Mission mode, the planner opens real Draft MRs on GitLab and posts a summary issue.
9. The final report is stored in MongoDB Atlas and appears in your browser.

### GitLab integration: bidirectional MCP

NECRO does not just call GitLab. GitLab can call NECRO back.

```
NECRO --calls--> GitLab MCP Server (19 tools: commits, blobs, issues, MRs, blame...)
                         |
GitLab Duo  <--calls---  NECRO MCP Server at /mcp
                         (scan_repository, get_candidates, get_health)
```

This means NECRO can be registered as a tool in GitLab Duo Agent Platform. A developer
can trigger it with `@necro` in Duo Chat without leaving GitLab.
See [ADR 003](./adr/003-gitlab-mcp-integration.md) and [ADR 005](./adr/005-necro-as-mcp-server.md).

### Data flow

```
GitLab repo
    |
    | (MCP: list_commits, get_commit_diff, search_blobs, get_file_blame, ...)
    v
NECRO backend (FastAPI + async)
    |
    +---> Gemini 3 Flash       (analysis + planning)
    +---> Google Search        (live constraint verification)
    +---> Gemini Flash/Vertex  (adversarial challenger)
    |
    v
MongoDB Atlas                  (scan history, findings, watchlist)
    |
    v
Browser                        (SSE stream --> live progress --> final report)
    |
    v
GitLab                         (Draft MRs, issues, via MCP write tools)
```

### Technology choices

| Component | Technology | Why |
|---|---|---|
| Agent orchestration | Google Cloud ADK | Multi-tool agent with MCP toolset |
| Primary AI model | Gemini 3 Flash | Analysis, planning, mission loop |
| Adversarial model | Gemini Flash on Vertex AI | Structurally independent from the analyst |
| Live verification | Google Search (built-in ADK tool) | Citable URLs, not training-data guesses |
| GitLab integration | Official GitLab MCP Server + @zereight/mcp-gitlab | 19 tools, full read and write access |
| Database | MongoDB Atlas with Vector Search | Document-shaped data, semantic demand matching |
| Backend | FastAPI + Server-Sent Events | Async, real-time streaming |
| Hosting | Google Cloud Run | Serverless, auto-scaling |
| Frontend | Vanilla HTML/CSS/JS | No build step, fast to iterate |

---

## Architecture decisions

The `adr/` folder contains the reasoning behind the key design choices:

- [ADR 001: Three separate models instead of one](./adr/001-multi-agent-architecture.md)
- [ADR 002: The challenger runs on separate infrastructure](./adr/002-adversarial-challenger.md)
- [ADR 003: GitLab MCP over the REST API](./adr/003-gitlab-mcp-integration.md)
- [ADR 004: MongoDB Atlas for persistence](./adr/004-mongodb-atlas.md)
- [ADR 005: NECRO exposes its own MCP endpoint](./adr/005-necro-as-mcp-server.md)
- [ADR 006: Server-Sent Events for real-time scan output](./adr/006-sse-streaming.md)
- [ADR 007: Two registries, one shared engine](./adr/007-dual-registry-design.md)

---

## How it is built

### GitLab integration

NECRO lives inside GitLab rather than just calling its API:

- **GitLab MCP tools:** `list_commits`, `get_commit`, `get_commit_diff`, `list_issues`,
  `list_merge_requests`, `list_feature_flags`, `search_blobs` (live code search),
  `get_file_blame` (per-line dating), `create_branch`, `create_file`, `create_merge_request`,
  `create_issue`, and more.
- **NECRO as an MCP server:** exposes `scan_repository`, `get_candidates`, `get_health` at
  `/mcp` so other tools can call it.
- **Duo Custom Agent:** `.gitlab/duo/necro-agent.yaml` registers NECRO in the GitLab AI
  Catalog so you can trigger it with `@necro` in Duo Chat.
- **Ghost MRs:** one click (or one mission) creates a real branch, commits a plan file, and
  opens a Draft MR with `@duo_code_review`.
- **CI:** `.gitlab-ci.yml` runs a scan on every push and can post findings as issues.

---

## Quick start

### Try it live

**[https://necro-agent-38381883054.us-central1.run.app](https://necro-agent-38381883054.us-central1.run.app)**

- Instant demo chips load pre-analyzed results in about a second.
- Live scan chips (or any public GitLab URL) run the real pipeline in 60 to 120 seconds.
- Mission Control runs the full autonomous loop.

### Run locally

Prerequisites: Python 3.11+, a MongoDB Atlas account (free tier is fine), a
GitLab personal access token with `api` and `read_repository` scope, a Gemini API key,
and a Google Cloud project with Vertex AI enabled.

```bash
git clone https://github.com/usv240/necro.git
cd necro
pip install -r requirements.txt
npm install -g @zereight/mcp-gitlab
cp .env.example .env   # fill in your credentials
uvicorn backend.main:app --port 8080 --reload
```

Open `http://localhost:8080`.

Required `.env` keys:

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

Unit tests run without a backend. Integration tests run when the server is live on
`localhost:8080`.

---

## API reference

| Method | Endpoint | What it does |
|--------|----------|--------------|
| `POST` | `/api/scan/stream` | Revival scan, SSE stream with live progress |
| `POST` | `/api/scan/demo` | Load a cached revival scan (instant) |
| `POST` | `/api/scan/group` | Scan an entire GitLab namespace |
| `POST` | `/api/necrosis/scan` | Dead-code scan, SSE stream |
| `POST` | `/api/necrosis/demo` | Load a cached necrosis scan (instant) |
| `POST` | `/api/agent/mission` | Autonomous mission, SSE stream |
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
├── adr/                        # Architecture decision records
├── agent/                      # ADK agent and system prompt
├── backend/
│   ├── main.py                 # FastAPI app and health endpoint
│   ├── routes/
│   │   ├── stream.py           # Revival SSE scan
│   │   ├── scan.py             # Background and cached demo scans
│   │   ├── necrosis.py         # Dead-code scan and deletion MR
│   │   ├── agent.py            # ADK ask, autonomous mission, webhook
│   │   ├── revive.py           # Revival issue and Ghost MR
│   │   └── report.py, watch.py, monitor.py
│   └── services/
│       ├── git_forensics.py        # Dead-feature detection (history)
│       ├── necrosis_detector.py    # Dead-code detection (live codebase)
│       ├── death_reason.py         # Kill-reason classification
│       ├── viability_scorer.py     # Revival scoring and constraint check
│       ├── deletion_scorer.py      # Deletion-safety scoring and caller count
│       ├── constraint_grounder.py  # npm, GitHub, PyPI verification
│       ├── challenger.py           # Adversarial agent
│       ├── mission.py              # Autonomous closed-loop orchestrator
│       └── adk_runner.py, gemini.py, gitlab_mcp.py, ...
├── frontend/                   # Single-page app (revival, necrosis, mission)
├── tests/                      # Unit and integration suite
├── .gitlab/duo/necro-agent.yaml
├── .gitlab-ci.yml
└── LICENSE
```

---

## Contact

Ujwal Suresh: ujwalsureshv@gmail.com

---

## License

[Apache 2.0](./LICENSE)
