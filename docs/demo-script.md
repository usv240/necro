# NECRO Demo Script — 3 Minutes

**Format:** Each block has a navigation instruction and exact words to say.
**Prep:** Browser fullscreen, no bookmarks bar, light mode, zoom 90%, terminal footer visible but collapsed.
**Live URL:** `https://necro-agent-38381883054.us-central1.run.app`
**Start on:** The landing page (`/`).

---

## [0:00 to 0:12] The Hook — Hero Section

**NAVIGATE:** Land on the hero. Do not scroll yet. Let the headline and the three sample cards sit on screen — the three verdict types are all visible right there: **Revive Now**, **Candidate**, and **Safe to Delete**.

**SAY:**
> "Every software team has a graveyard. Features they killed for reasons that stopped being true. Dead code nobody cleaned up because nobody was sure it was safe to remove. Teams spend months rebuilding things they already built once. NECRO handles both of those."

**NAVIGATE:** Point at the three sample cards in the hero.

**SAY:**
> "Three verdicts, one scan. Code that should be deleted, code that might be worth reviving, and code that needs a human decision. Every verdict is backed by live evidence — not a guess."

---

## [0:12 to 0:25] The Scale — ROI Calculator

**NAVIGATE:** Scroll down past **The Problem** section and **How it works**. Keep scrolling until you reach the **Why It Matters** section with the **Opportunity Cost Calculator** slider. Drag it from 25 to 50 engineers.

**SAY:**
> "Fifty engineers. Three hundred and fifty thousand dollars a year in dead code overhead and wasted rebuilds. That is the problem. Let me show you what solving it looks like."

**NAVIGATE:** Click **Launch App** in the top nav (or the CTA at the bottom of the hero). App opens at `/app.html`.

---

## [0:25 to 0:48] Dormant Feature Registry — The Live Scan

**NAVIGATE:** You are on the **Dormant Feature Registry** tab. The URL field already has `ujwal240/necro-demo-graveyard`. Leave Max Commits at 200, Lookback at 12. Click **Run Forensic Scan**.

**SAY:**
> "This is a real GitLab repository. Watch the bottom of the screen — those are live API calls going to GitLab's MCP server right now. `list_commits`, `get_commit_diff`, `search_blobs`. Not simulated. Happening as we speak."

**NAVIGATE:** Expand the terminal footer. Point at the scrolling MCP lines. Let it run about 10 seconds.

---

## [0:48 to 1:08] The Pipeline Running

**NAVIGATE:** When a `[SEARCH]` line appears in the terminal, point at it.

**SAY:**
> "And now it is calling Google Search — verifying whether the thing that killed each feature is still true today. Every verdict NECRO gives you has a live URL behind it. Not a training-data guess."

**SAY:** (while the scan runs — ~60 to 90 seconds total)
> "The adversarial agent is running right now — a second model on completely separate Vertex AI infrastructure, arguing against every revival it sees. If it finds a real objection, the verdict gets downgraded. If it cannot, the candidate survives."

---

## [1:08 to 1:28] Reading the Results

**NAVIGATE:** Results appear: 1 Revive Now, 2 Revival Candidates, 2 Keep Buried. Point at each verdict type.

**SAY:**
> "Three different verdicts. **Revive Now** — Streaming SSR, blocked by React 17. React is now at 19.2.7. That constraint is gone. Feasibility 90 percent. **Revival Candidate** — Post-quantum TLS, blocked by OpenSSL 1.x not supporting Kyber. OpenSSL 4.0 shipped in April 2026, that blocker is also gone — but the challenger flagged migration complexity, so it stays in investigate. **Keep Buried** — Adobe Flash. Verified permanent deprecation. That one should stay dead."

**NAVIGATE:** Click the **Streaming SSR** card to expand it. Scroll to the evidence section.

**SAY:**
> "Live URL. Release date. The exact constraint that was resolved. React v19.2.7, June 1st 2026. Not an AI inference — verified against the public record."

---

## [1:28 to 1:40] Second Repo — Instant Demo

**NAVIGATE:** Scroll up to the scanner. Click the **gitlab-pages** instant demo chip. Loads in about 1 second from MongoDB cache.

**SAY:**
> "Different repo, same pipeline. Pre-analysed and loaded instantly from our MongoDB cache. Same output you would get from a live run."

---

## [1:40 to 1:58] Necrosis Registry — The Other Direction

**NAVIGATE:** Click **Necrosis Registry** in the sidebar. Click the **gitlab-runner** instant demo chip. Loads in about 1 second.

**SAY:**
> "Same engine, opposite question. Not should this come back — is it finally safe to delete this. gitlab-runner is a mature Go codebase. Forty-two and a half years of cumulative dead code age across eleven findings."

**NAVIGATE:** Click **logDeprecationWarning** in the left list. The detail panel opens on the right.

**SAY:**
> "This function has been marked deprecated for over six years — 2,221 days. NECRO called `search_blobs` on the live codebase. Zero callers. Risk score one out of ten. Safe to delete — and that button opens a real GitLab Draft MR with the removal plan already written."

**NAVIGATE:** Point at a **Needs Biopsy** finding below it.

**SAY:**
> "This one has active callers. NECRO will never tell you to delete code that is still being used. That is a hard guarantee — caller count is verified before any deletion is ever suggested."

---

## [1:58 to 2:15] Mission Control — What It Does

**NAVIGATE:** Click **Mission Control** in the sidebar. Do not click Launch yet. Let the panel sit.

**SAY:**
> "Everything I just showed you — the forensic scan, the adversarial challenge, the verdict, the artifact creation — Mission Control runs all of that in one click. No further input. Here is what it is about to do."

**NAVIGATE:** Point at the six phase indicators in the right panel: Recon → Plan → Challenge → Act → Verify → Report.

**SAY:**
> "Phase one: it scans both the dormant feature registry and the dead code registry simultaneously. Phase two: Google Cloud Agent Builder reasons over all findings and writes a prioritised plan. Phase three: a challenger model on Vertex AI red-teams the plan — anything without verified evidence gets rejected. Phase four: it acts. Real GitLab Draft MRs and issues for whatever survives. Autonomously."

---

## [2:15 to 2:30] Mission Control — Launch

**NAVIGATE:** Scan repo is `gitlab-org/gitlab-runner`, action repo is `ujwal240-group/ujwal240-project`. Check **Dry run**. Click **Launch Autonomous Mission**.

**SAY:**
> "Watch the terminal."

**NAVIGATE:** Point at the phase banners as they appear: `RECON complete` → `PHASE 2 / PLAN` → `PHASE 3 / CHALLENGE`.

**SAY:**
> "The challenger just rejected the revival. No verified evidence that the original API constraint was fixed. So NECRO downgrades it to a discussion issue instead of a Draft MR. It is honest about what it does not know."

**NAVIGATE:** When results appear, point at the **Prepared Artifacts** section — two items.

**SAY:**
> "Two artifacts, autonomously prepared. No black box — every decision is logged."

---

## [2:30 to 2:45] Quick Tour — Three Tabs

**NAVIGATE:** Click **Timeline Forensics** in the sidebar.

**SAY:**
> "All your scans over time — when features were killed, how revivable they are, easiest wins across your entire history."

**NAVIGATE:** Click **Active Watchlist**.

**SAY:**
> "Add a repo and NECRO rescans it every 24 hours. Slack alert the moment new dormant features appear."

**NAVIGATE:** Click **Revival Logs**.

**SAY:**
> "Every GitLab issue and Draft MR NECRO created, with direct links. Full audit trail."

---

## [2:45 to 3:00] The Close

**NAVIGATE:** Click the NECRO logo to return to the landing page. Let the hero sit.

**SAY:**
> "476 scans. 524 findings. Zero load-bearing code ever flagged for deletion. Dead code is universal — NECRO finds it on every mature repo. Revival candidates are rarer, but worth real money when they exist. Both in under two minutes, on any public GitLab repo."

**NAVIGATE:** Stop. Two seconds of silence.

**[End recording]**

---

## Landing page section map

For reference — what is visible at each scroll depth:

| Scroll position | Section | What to point at |
|---|---|---|
| Top | **Hero** | Headline + 3 sample verdict cards + 476/524/5.7k stats |
| ~20% | **The Problem** | Three pain point columns (dead code / killed features / manual archaeology) |
| ~35% | **How it works** | Four pipeline stages: Forensic Scan → Verify → AI Verdict → Auto GitLab Action |
| ~50% | **Features** | Six module cards (Necrosis, Dormant, Mission Control, Timeline, Watchlist, Logs) |
| ~65% | **Under the hood** | Live pipeline execution log with `→ callers found: 0`, `→ MR !4421 created` |
| ~75% | **Numbers** | 476+ / 524 / 5.7k / 0 false flags — dark section, high contrast |
| ~80% | **Why It Matters** (id: `#impact`) | ROI calculator slider — drag from 25 to 50 engineers |
| ~90% | **Integrations** | Google Gemini · GitLab MCP · ADK · MongoDB · Slack logos |

---

## Preparation checklist

- [ ] Browser fullscreen, no bookmarks bar, no notifications
- [ ] Zoom at 90% (Ctrl+- once from default)
- [ ] Light mode on — click the `◑` toggle in the app header
- [ ] Terminal footer visible but collapsed — `_` button
- [ ] Green dot visible in app header (MongoDB + backend healthy)
- [ ] Dormant Feature tab pre-loaded with `ujwal240/necro-demo-graveyard` in the URL field
- [ ] Mission Control repos set: scan = `gitlab-org/gitlab-runner`, action = `ujwal240-group/ujwal240-project`
- [ ] **Dry run** checkbox checked on Mission Control
- [ ] One full dry run of all 3 minutes before recording

---

## Backup: if live scan is slow

If `ujwal240/necro-demo-graveyard` takes more than 90 seconds at [0:25], click the **necro-demo** instant demo chip:

> "This is a pre-analysed result from our cache — the live pipeline produces the same output, just takes about 90 seconds to run."

Then use **gitlab-pages** at [1:28] as planned. You lose the live API calls moment but keep pacing tight.

---

## Three lines that must land

Say these clearly. Do not rush them.

1. *"Those are live API calls going to GitLab's MCP server right now — not simulated, happening as we speak."*
2. *"A second model on completely separate Vertex AI infrastructure, arguing against every revival it sees."*
3. *"476 scans. 524 findings. Zero load-bearing code ever flagged for deletion."*
