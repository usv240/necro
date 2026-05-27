# NECRO — Depth Document
## Idea Depth · Technical Depth · Implementation Depth

---

## The Core Reframe (Say This In Every Demo)

Every other tool in this hackathon helps engineers build new things faster.
NECRO asks a completely different question:

> **"What has already been built that can be recovered?"**

That single reframe puts NECRO in a category with zero competitors.
Not a faster shovel. A treasure map.

---

## The Three Deep Insights (Idea Depth)

### Insight 1 — Information Decays Exponentially From The Moment Of Death

When a feature is killed, the information about *why it should come back* exists
at maximum fidelity at exactly one moment: **the moment of death.**

The engineer is sitting at their keyboard. They know:
- The exact dependency that blocked it
- The workaround that was considered and rejected
- The customer segment still asking for it
- The infrastructure change that would unlock it

**Information fidelity decay curve:**
```
Moment of kill:        100% — engineer knows everything
1 month later:          80% — mostly remembers
6 months later:         40% — remembers the gist
12 months later:        15% — vague recollection
18 months later:         5% — archaeological guesswork
Engineer leaves co.:     0% — gone forever
```

What every dead code tool (including NECRO today) does: archaeology at the 5% point.
What the Feature Will Generator does: capture at 100%.

This is not a feature improvement. It is a different point on the information curve entirely.
Nobody built this because everyone assumed the problem was "finding dead features."
The real problem is **information loss at the moment of death.**

---

### Insight 2 — Software Systems Fail In Coordinated Patterns, Not Isolated Ones

A Redis version constraint doesn't kill one feature in one repo.
It kills every feature depending on Redis across every repo simultaneously.
But monitoring is per-repo — so that one coordinated failure appears to
14 different teams as 14 independent problems. Nobody connects them.

**The graveyard IS your actual organizational dependency graph**
because features die along dependency lines.

Your architecture diagram shows what services are *supposed* to depend on.
Your cross-repo graveyard shows what they *actually* depend on —
because every surprise dependency created a coordinated kill event.

You can reverse-engineer your real system architecture from your feature graveyard.
If 8 repos all killed their caching layer in the same 3-month window, you have
a hidden coupling. That coupling is not in any diagram. It is only visible in
the pattern of deaths.

This turns NECRO from "find things to revive" into:
**"Show me the hidden architecture of my organization."**

---

### Insight 3 — Git History Is A Balance Sheet Of Frozen Assets, Not An Audit Log

In physical manufacturing, scrapped raw materials are gone. Sunk cost — truly sunk.

In software, **nothing you build ever physically disappears.**
The code is in git forever. The tests might still be there.
The architecture decisions are in commit messages.
The original engineer might still be at the company.

Standard financial thinking: "Ignore sunk costs."
NECRO's insight: **In software, sunk costs are not sunk. They are frozen assets
on a balance sheet that nobody audits.**

The question is not "how much did it cost to build?"
The question is: **"What does it cost to thaw it, and what is it worth thawed?"**

That is why the revival score (40% feasibility + 30% demand + 15% effort + 15%
competitive) makes economic sense — it is a thaw-cost vs. thawed-value calculation,
not a "should we build this new feature" calculation.
A fundamentally different economic decision.

Every VC, every engineering VP, every CTO immediately understands this when you say it.
Nobody has said it before because nobody built the tool that makes frozen assets visible.

---

### Insight 4 — Advisory AI vs. Structural AI

Every AI tool in this hackathon is advisory. It gives information. The engineer can ignore it.

The Feature Will Generator embedded in a GitLab Custom Flow is structural enforcement.
When a developer merges an MR that kills a feature, the Revival Contract exists —
whether they thought to check NECRO or not. The institutional knowledge is preserved
whether the engineer remembered to document it or not.

- A nutritionist = advisory. You can ignore it.
- A seatbelt = structural. It happens whether you think about it or not.

**Every other AI tool in this hackathon is a nutritionist.
NECRO with Custom Flows is a seatbelt.**

GitLab judges built Custom Flows specifically for structural enforcement of team practices.
Seeing NECRO use it for knowledge preservation will hit exactly right.

---

## The Four Ideas To Build / Ship

---

### IDEA 1: The Feature Will Generator (MOST IMPORTANT)
**Intercept features at the moment of death. Write their will.**

#### What It Does
When a developer opens a GitLab MR that kills a feature (disables a flag,
removes a code path, comments out a block), NECRO intercepts via GitLab webhook
in real-time — before the MR merges.

ADK analyzes the kill:
1. Reads the diff + MR description + linked issues via GitLab Official MCP
2. Determines: is this temporary or permanent?
3. Identifies: what condition would allow revival?
4. Estimates: what effort to revive when that condition is met?

Then automatically creates a GitLab **Revival Contract** issue containing:
- Why it was killed (Gemini's analysis of the kill context)
- The exact revival condition: "Revive when: Redis cluster upgraded to v7.0+"
- Effort estimate at revival time
- Links to the killing MR and any demand issues
- Labels: `necro:revival-contract`, `necro:monitored`

MongoDB stores the contract with a vector embedding of the kill context
(text-embedding-004, 768-dim) so semantically related contracts are findable later.

NECRO's autonomous monitor (APScheduler) watches the revival condition.
When the condition is met (related issue closed, dependency version merged),
it reopens the Revival Contract issue and pings the original engineer.

#### Why This Is Deep
- Solves the information loss problem at the source (100% fidelity, not 5%)
- Closes the loop: kill → preserve → monitor → resurrect, fully autonomous
- The graveyard fills itself — engineers don't need to remember to document
- Every feature death creates an asset, not a void

#### Technical Depth
- GitLab Push / MR webhook → `/api/agent/webhook/gitlab`
- ADK `_run_adk_will_analysis(diff, mr_description, linked_issues)` → structured will
- GitLab Official MCP `create_issue` with `necro:revival-contract` label
- MongoDB `revival_contracts` collection with `vector embedding` of kill context
- APScheduler condition monitor: watches linked issues, dependency versions
- Revival condition matching: vector similarity against open issues + semantic parsing

#### Implementation Plan
```
backend/routes/agent.py       — enhance webhook handler with will generation
backend/services/will_writer.py — new: ADK-powered will analysis + creation
backend/db/schemas.py         — new: RevivalContractDoc model
backend/services/monitor.py   — enhance: watch revival conditions per contract
```

---

### IDEA 2: Cross-Repository Graveyard Federation
**One constraint killing 23 features across 14 repos. Fix once. Unlock everything.**

#### What It Does
`POST /api/scan/group` — scans every repository in a GitLab group/namespace.

For each repo: lightweight NECRO scan (100 commits, keyword detection only).
MongoDB Atlas aggregation: `$group by constraint_keyword across project_paths`.

Returns cross-repo resurrection chains:
> "The 'redis-cluster-version' constraint killed 23 features across 14 repositories.
> Fix one infrastructure upgrade, unlock 23 features in a single sprint."

Also shows: which teams are working in silos on the same underlying problem.

#### Why This Is Deep
- Makes hidden organizational coupling visible
- Graveyard-as-architecture-diagram: shows real dependencies, not documented ones
- ROI is not "$50K for one repo" — it is "$2M for the entire organization"
- The most impactful single fix in an org's history might be invisible without this

#### Technical Depth
- GitLab MCP `list_projects(group_id)` → enumerate all repos in namespace
- Parallel lightweight scans (asyncio.gather, 100 commits each)
- MongoDB `$group` aggregation: constraint_keyword → list of (project_path, feature_name, kill_date)
- Minimum cluster size: 2 repos sharing a constraint = surfaced as cross-repo chain
- Deduplication: same feature killed in forked repos counted once

#### Implementation Plan
```
backend/routes/scan.py        — new: POST /api/scan/group endpoint
backend/services/group_scan.py — new: parallel multi-repo scan + federation
frontend/app.js               — new: group scan UI panel, org-level chains view
```

---

### IDEA 3: GitLab Custom Flows + AI Catalog (NO CODE — CONFIG ONLY)
**The deepest GitLab platform integration nobody else will use.**

#### What It Does
**Custom Flow** (Beta): YAML-defined multi-step automated workflow triggered by MR events.
```
Trigger: MR opened touching feature_flags/ or containing "disable"/"remove"/"revert"
Step 1:  NECRO scans the diff for kill patterns (calls POST /api/scan/quick)
Step 2:  Checks graveyard for related dead features (vector search)
Step 3:  Auto-comments on MR: "⚠️ This kills a feature with 183 open user requests"
Step 4:  Creates revival contract issue with conditions embedded
```

**AI Catalog** (GA): Publishes NECRO as a discoverable AI capability.
Any engineer in the org can ask Duo: "Is anything in our graveyard related to
authentication?" and Duo routes to NECRO automatically.

#### Why This Is Deep
- Custom Flows: structural enforcement, not advisory AI
- AI Catalog: NECRO becomes part of the GitLab Duo knowledge graph for the org
- GitLab judges built these features — they will recognize deep platform usage instantly
- Custom Flows are Beta — very likely zero other submissions use them

#### Files To Create
```
.gitlab/flows/necro-will-flow.yml    — Custom Flow YAML definition
ai_catalog_entry.yml                  — AI Catalog registration YAML
```

---

### IDEA 4: MongoDB Feature Vitality Time-Series
**The Feature EKG — see when a feature started getting sick before it died.**

#### What It Does
MongoDB time-series collection: every feature gets periodic vitality snapshots.

Tracked signals over time:
- Test failure rate
- Issue reference velocity (are people mentioning it more or less?)
- Commit touch frequency (is anyone maintaining it?)
- Open demand count (how many users are asking for it?)
- MR review lag (are PRs touching it getting merged or stalling?)

**The Feature EKG chart** shows:
- The decay curve before death (when did it start getting sick?)
- The demand recovery curve after death (when did users start asking for it back?)
- The revival window: where decay reason has resolved AND demand is rising

The optimal revival window is the intersection:
`decay_reason_resolved AND demand_rising AND competitor_gap_widening`

#### Why This Is Deep
- MongoDB time-series collection: the right data model, not just a list of features
- Shows the problem was visible weeks/months before the kill commit
- Predictive: if a current feature has the same vitality curve, it will die soon
- NECRO can flag features that are about to die, not just features that already died

#### Technical Depth
- MongoDB time-series collection: `timeseries: { timeField: "timestamp", metaField: "feature_id" }`
- Daily/weekly snapshot job (APScheduler IntervalTrigger)
- Atlas Charts or Chart.js for EKG visualization
- Anomaly detection: flag features whose vitality curve matches historical kill patterns

#### Implementation Plan
```
backend/db/schemas.py           — VitalitySnapshot time-series doc
backend/services/vitality.py    — snapshot collection + trend computation
frontend/app.js                 — EKG chart per feature card (sparkline)
```

---

## The Narrative That Wins All Four Judging Criteria

| Criterion | How NECRO Wins |
|-----------|----------------|
| **Technological Implementation** | 3-phase ADK pipeline · Official GitLab MCP (SSE) · NECRO as MCP server · Atlas Vector Search 768-dim · MongoDB time-series · Custom Flows · AI Catalog · Webhook real-time interception |
| **Design** | Every UI panel is populated on demo load · Score pill on every card · EKG sparkline · Group-level org view · Revival contract issue created live |
| **Potential Impact** | Not one team — the entire engineering organization. Cross-repo federation: fix one infra constraint, unlock 23 features. ROI is org-wide. |
| **Quality of Idea** | No other tool has ever intercepted feature death to write a will. No other tool federates graveyards across repos to reveal hidden org architecture. Paradigm shift, not incremental improvement. |

---

## The One-Sentence Version (For The Demo Video Opening)

> "Every day, engineers delete features that already work —
> and six months later spend twice as much rebuilding them.
> NECRO is the first system that writes a feature's will at the moment of death
> and watches autonomously until the conditions for resurrection are met."

---

## What Makes This A Category, Not A Feature

Every other "AI for DevOps" tool accelerates forward progress.
They are all competing in the same lane: build faster, test faster, deploy faster.

NECRO competes in a lane that does not exist yet:
**the recovery economy of software.**

The insight is that in software, unlike any other industry,
nothing you build ever truly disappears.
Code is preserved in git forever.
Tests might still exist.
Architecture decisions are in commit messages.
The original engineer might still be at the company.

The only thing that changes is whether anyone thinks to look.

NECRO makes looking systematic, autonomous, and economically justified.

That is not a hackathon project. That is a product category.

---

## Implementation Priority Order

1. **Feature Will Generator** — most unique, most demo-worthy, most conceptually stunning
2. **Custom Flows YAML** — 30 minutes, judges will love it, nobody else uses it
3. **AI Catalog YAML** — 30 minutes, makes NECRO discoverable org-wide
4. **Cross-Repository Group Scan** — highest business impact, clean endpoint
5. **Engineer Attribution** — half-built (git log already gives author), 2 hours
6. **Feature Vitality Time-Series** — highest MongoDB depth, pitch as next phase if time is short
