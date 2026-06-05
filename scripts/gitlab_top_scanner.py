"""
GitLab Top Repo Scanner — deep two-phase NECRO sweep.

Phase 1: Detection only (fast, ~5-15s per repo, no Gemini).
         Runs in parallel batches of --concurrency repos.
         For each hit, scores how likely the kill reason is groundable
         (does it mention a tech the constraint_grounder can verify?).
         100 repos in ~3-5 min.

Phase 2: Full pipeline (death_reason + viability + grounding + ADK).
         Only runs on top-scored Phase 1 hits.
         Sorted by groundability score so best bets run first.

Usage:
    # Fast scout — 100 repos, parallel, score groundability:
    python scripts/gitlab_top_scanner.py --phase 1 --fetch-top 80 --max-repos 100

    # Full deep search — find revive_now:
    python scripts/gitlab_top_scanner.py --phase both --fetch-top 80 --max-repos 100 --top-n-phase2 15

    # Phase 2 on specific repos:
    python scripts/gitlab_top_scanner.py --phase 2 --repos "gitlab-org/gitaly,gitlab-org/gitlab-runner"

    # Just our curated list, full pipeline:
    python scripts/gitlab_top_scanner.py --phase both --top-n-phase2 10

Results written to: outputs/necro/deep_scan_<timestamp>.json
"""

import asyncio
import json
import re
import time
import urllib.request
import urllib.error
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

# ── Groundable tech keywords (subset of constraint_grounder vocab) ──────────
# A kill mentioning any of these has a real path to a verified revive_now.
_GROUNDABLE_TECHS = {
    # JS/TS ecosystem
    "react", "react 1", "react 2", "renderToPipeableStream", "next.js", "nextjs",
    "webpack", "webpack 4", "webpack 5", "vite", "typescript", "svelte", "vue", "angular",
    "babel", "eslint", "prettier", "tailwind", "graphql", "apollo", "trpc", "zod",
    "prisma", "mongoose", "express", "fastify", "remix", "astro", "turborepo",
    # Node / runtime
    "node", "node.js", "node 12", "node 14", "node 16", "node 18", "node 20",
    # Python
    "django", "flask", "fastapi", "pydantic", "sqlalchemy", "celery",
    "requests", "aiohttp", "boto3",
    # Infra / system
    "openssl", "openssl 1", "openssl 3", "grpc", "grpc library", "protobuf",
    "kubernetes", "k8s", "docker", "terraform", "ansible",
    "redis", "postgres", "postgresql", "sqlite",
    "curl", "ffmpeg", "electron", "gtk", "qt",
    # Runtime languages
    "go 1", "golang", "ruby 3", "ruby 2", "rust 1", "python 3",
    "llvm", "clang", "openssl",
    # Payments / comms
    "stripe", "twilio", "sendgrid",
    # Cloud
    "gcs", "google cloud storage", "s3", "aws s3",
    # C++ / graphics / game engines
    "wxwidgets", "wx", "openscenegraph", "osg", "openal", "sdl", "sdl2",
    "vulkan", "wgpu", "winit", "glfw", "ogre", "ogre3d",
    "libgit2", "libssh", "libssh2", "libvirt",
    # GTK / desktop
    "gtk4", "libadwaita", "glib", "systemd", "dbus",
    # Rust ecosystem
    "tokio", "actix", "hyper", "reqwest", "serde", "clap",
    # DB / search
    "elasticsearch", "opensearch", "clickhouse", "mongodb",
    "mysql", "mariadb", "sqlite3",
    # Media / codecs
    "libav", "libavcodec", "ffmpeg", "opus", "vpx", "libvpx",
    # Node / Electron
    "electron", "socket.io", "express", "webpack", "vite",
    # Python data
    "pandas", "numpy", "scipy", "matplotlib", "pillow", "PIL",
    "celery", "redis", "dramatiq",
}


# Explicit constraint language — the commit SAYS why it was killed.
# These are the only reverts Gemini will score feasibility >= 7 on, because
# Gemini can verify the constraint resolved. Without this language the
# kill reason is "unknown" → feas <= 6 → never reaches revive_now.
_CONSTRAINT_RE = re.compile(
    r"\b(blocked\s+by|disabled?\s+(?:due\s+to|because|pending|until|for)|"
    r"not\s+(?:supported|available|compatible)\s+(?:by|on|in|with)|"
    r"broken\s+(?:on|with|by|in)|incompatible\s+with|"
    r"requires?\s+\w+\s+\d|waiting\s+for|reverted?\s+(?:due\s+to|because|for)|"
    r"regression\s+in|bug\s+in\s+\w|crash\s+(?:on|with|in)|"
    r"fails?\s+(?:on|with|in)|too\s+slow\s+(?:on|with|in)|"
    r"memory\s+leak\s+in|security\s+(?:issue|vulnerability|bug)\s+in)\b",
    re.IGNORECASE,
)


def _groundability_score(candidates: list[dict]) -> int:
    """Score how likely this repo's Phase 1 hits will ground in Phase 2.
    Higher = more likely to reach revive_now.

    Scoring:
    +5 per candidate with BOTH constraint language AND a groundable tech
       (these are the genuine revive_now candidates)
    +3 per candidate with constraint language only (no known tech — could still ground)
    +2 per candidate with a groundable tech mention (but no explicit constraint)
    +1 per feature_flag_removal (explicit flag kills)
    Maintenance reverts ("version to dev", "bump version") get score=0 — they
    are dev-cycle resets, not feature kills, so Gemini correctly rates them feas<=6.
    """
    score = 0
    for c in candidates:
        msg = (c.get("kill_msg", "") or "").lower()
        name = (c.get("name", "") or "").lower()
        blob = msg + " " + name
        method = c.get("method", "")
        has_constraint = bool(_CONSTRAINT_RE.search(blob))
        has_tech = any(tech in blob for tech in _GROUNDABLE_TECHS)
        if has_constraint and has_tech:
            score += 5
            c["_signal"] = "CONSTRAINT+TECH"
        elif has_constraint:
            score += 3
            c["_signal"] = "CONSTRAINT"
        elif has_tech and method == "revert_commit":
            score += 2
            c["_signal"] = "TECH"
        elif method == "feature_flag_removal":
            score += 1
            c["_signal"] = "FLAG"
    return score


# ── Curated repo list ────────────────────────────────────────────────────────
CURATED_REPOS = [
    # GitLab core (Go/Ruby — known to have reverts + flag kills)
    "gitlab-org/gitaly", "gitlab-org/gitlab-runner", "gitlab-org/gitlab-workhorse",
    "gitlab-org/gitlab-shell", "gitlab-org/container-registry", "gitlab-org/gitlab-pages",
    "gitlab-org/release-cli", "gitlab-org/cli", "gitlab-org/gitlab",
    "gitlab-org/gitlab-foss", "gitlab-org/gitlab-development-kit",
    "gitlab-org/omnibus-gitlab", "gitlab-org/labkit", "gitlab-org/gitlab-ui",
    "gitlab-org/gitlab-svgs", "gitlab-org/charts/gitlab",
    "gitlab-org/gitlab-vscode-extension", "gitlab-org/language-tools",
    # Open source apps — C++/Rust (long histories, OS/lib/driver constraint kills)
    "inkscape/inkscape", "inkscape/inkscape-web",
    "gstreamer/gstreamer", "godotengine/godot",
    "fdroid/fdroidclient", "fdroid/fdroidserver",
    "wireshark/wireshark",        # C — massive history, many OS/SSL/lib reverts
    "qemu-project/qemu",          # C — hypervisor, tons of platform-compat reverts
    "kicad/code/kicad",           # C++ — EDA tool, wxWidgets/Python/OpenGL kills
    "OpenMW/openmw",              # C++ — OpenSceneGraph/OpenAL/SDL reverts
    "veloren/veloren",            # Rust — wgpu/winit/vulkan reverts
    "Remmina/Remmina",            # C — GTK/SSL/VNC lib kills
    "cryptsetup/cryptsetup",      # C — OpenSSL/kernel version kills
    "tortoisegit/tortoisegit",    # C++ — Windows/OpenSSL/libgit2 reverts
    "corectrl/corectrl",          # C++ — Qt/vulkan version kills
    # Python web / data
    "mayan-edms/mayan-edms",      # Django — celery/elasticsearch/PIL reverts
    "baserow/baserow",            # Django+Nuxt — node/postgres/redis kills
    "meltano/meltano",            # Python — singer/tap reverts
    # GTK apps (known lib-version constraint pattern)
    "asus-linux/asusctl",         # Rust — dbus/systemd kills
    "news-flash/news_flash_gtk",  # Rust — GTK4/libadwaita version kills
    "coolercontrol/coolercontrol", # Rust — HWMon/liqctrl kills
    # More GitLab ecosystem
    "gitlab-com/www-gitlab-com",
    "gitlab-com/runbooks",
    "gitterHQ/webapp",            # Node.js — known express/socket.io reverts
    "commento/commento",          # Go — postgres/auth lib kills
    "antora/antora",              # Node.js — asciidoc/gulp/webpack reverts
    "staltz/manyverse",           # Electron+React Native — sodium/electron kills
]


def _fetch_top_gitlab_projects(token: str, base_url: str, n: int) -> list[str]:
    """Fetch top N public projects by star count + recent activity.
    NOTE: do NOT add min_access_level param — causes HTTP 400 on gitlab.com."""
    headers = {"Authorization": "Bearer " + token}
    paths = []
    for order in ("star_count", "last_activity_at"):
        page = 1
        while len(paths) < n:
            url = (base_url.rstrip("/") + "/api/v4/projects"
                   + f"?visibility=public&order_by={order}&sort=desc"
                   + f"&per_page=20&page={page}")
            try:
                req = urllib.request.Request(url, headers=headers)
                data = json.loads(urllib.request.urlopen(req, timeout=15).read())
                if not data:
                    break
                for p in data:
                    ns = p.get("path_with_namespace", "")
                    if ns and ns not in paths:
                        paths.append(ns)
                page += 1
                if len(data) < 20:
                    break
            except Exception as e:
                print(f"  [fetch-top {order}] page {page} err: {e}", flush=True)
                break
        if len(paths) >= n:
            break
    return paths[:n]


# ── Phase 1 ──────────────────────────────────────────────────────────────────

async def phase1_detect(repo: str, lookback: int, max_commits: int) -> dict:
    from backend.services.git_forensics import detect_dead_features
    msgs = []
    async def _emit(m): msgs.append(str(m))
    t0 = time.time()
    try:
        feats = await asyncio.wait_for(
            detect_dead_features(repo, max_commits, lookback,
                                 progress_cb=_emit, mcp_calls=[]),
            timeout=180,  # large repos (Wireshark/QEMU/OpenRGB) need >90s
        )
    except Exception as e:
        return {"repo": repo, "phase": 1, "error": repr(e)[:80],
                "secs": round(time.time() - t0), "candidate_count": 0,
                "groundability_score": 0}

    from collections import Counter
    candidates = [
        {"name": f.name[:50], "method": f.detection_method,
         "conf": f.detection_confidence,
         "kill_msg": (f.kill_commit_message or "")[:80],
         "kill_date": f.kill_date}
        for f in feats[:8]
    ]
    g_score = _groundability_score(candidates)
    return {
        "repo": repo, "phase": 1,
        "candidate_count": len(feats),
        "detection_methods": dict(Counter(f.detection_method for f in feats)),
        "groundability_score": g_score,
        "candidates": candidates,
        "secs": round(time.time() - t0),
    }


async def phase1_batch(repos: list[str], lookback: int, max_commits: int,
                       concurrency: int, results: list, out_path: Path,
                       sem: asyncio.Semaphore) -> None:
    """Run Phase 1 with bounded concurrency."""
    async def _run_one(repo):
        async with sem:
            r = await phase1_detect(repo, lookback, max_commits)
            _print_phase1(r)
            results.append(r)
            json.dump(results, open(out_path, "w", encoding="utf-8"), indent=2)
    await asyncio.gather(*[_run_one(r) for r in repos])


# ── Phase 2 ──────────────────────────────────────────────────────────────────

async def phase2_full(repo: str, lookback: int, max_commits: int) -> dict:
    from backend.routes.stream import _stream_live
    holder = {}
    async def emit(m):
        s = str(m)
        if s.startswith("__REPORT__:"):
            try: holder["r"] = json.loads(s[len("__REPORT__:"):])
            except Exception: pass
    t0 = time.time()
    try:
        await asyncio.wait_for(_stream_live(emit, repo, max_commits, lookback), timeout=420)
    except Exception as e:
        return {"repo": repo, "phase": 2, "error": repr(e)[:80],
                "secs": round(time.time() - t0)}
    rep = holder.get("r", {}); feats = rep.get("features", [])
    from collections import Counter
    recs = Counter((f.get("viability", {}) or {}).get("recommendation") for f in feats)
    detail = []
    for f in feats:
        vi = f.get("viability", {}) or {}; gr = vi.get("grounding", {}) or {}
        detail.append({
            "name": f.get("name", "")[:50],
            "method": f.get("detection_method"),
            "recommendation": vi.get("recommendation"),
            "feasibility": vi.get("revival_feasibility"),
            "grounded": gr.get("grounded"),
            "technology": gr.get("technology", ""),
            "evidence_url": str(gr.get("evidence_url", ""))[:80],
            "kill_date": f.get("kill_date", ""),
        })
    return {
        "repo": repo, "phase": 2,
        "feature_count": len(feats),
        "recommendations": dict(recs),
        "has_revive_now": recs.get("revive_now", 0) > 0,
        "detail": detail,
        "secs": round(time.time() - t0),
    }


# ── Printers ─────────────────────────────────────────────────────────────────

def _print_phase1(r: dict):
    n = r.get("candidate_count", 0); g = r.get("groundability_score", 0)
    err = r.get("error", "")
    if err:
        print(f"  ❌ {r['repo']}: {err} ({r.get('secs')}s)", flush=True)
    elif n == 0:
        print(f"  ○  {r['repo']}: 0 candidates ({r.get('secs')}s)", flush=True)
    else:
        methods = r.get("detection_methods", {})
        stars = "★" * min(g // 3, 5) if g > 0 else ""
        print(f"  ✦  {r['repo']}: {n} candidates score={g}{stars} {methods} ({r.get('secs')}s)", flush=True)
        for c in r.get("candidates", [])[:4]:
            sig = c.get("_signal", "")
            sig_tag = f" [{sig}]" if sig else ""
            print(f"       · [{c['method']}]{sig_tag} {c['name'][:44]}  {c['kill_date']}", flush=True)


def _print_phase2(r: dict):
    err = r.get("error", ""); recs = r.get("recommendations", {})
    if err:
        print(f"  ❌ {r['repo']}: {err} ({r.get('secs')}s)", flush=True)
        return
    flag = "🟢" if r.get("has_revive_now") else ("🟡" if recs.get("investigate_further") else "⚫")
    print(f"  {flag} {r['repo']}: {recs} ({r.get('secs')}s)", flush=True)
    for d in r.get("detail", []):
        sym = {"revive_now": "🟢", "investigate_further": "🟡", "keep_buried": "⚫"}.get(d["recommendation"], "?")
        grd = f"[{d['technology']}✓]" if d.get("grounded") else ""
        print(f"       {sym} feas={d['feasibility']} {grd} {d['name'][:40]}", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args):
    env = {}
    try:
        for line in open(".env", encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    import backend.config  # pydantic-settings .env load

    # ── build repo list ──────────────────────────────────────────────────────
    if args.repos:
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    else:
        repos = list(dict.fromkeys(CURATED_REPOS))
        if args.fetch_top > 0:
            token = env.get("GITLAB_TOKEN", "")
            base = env.get("GITLAB_URL", "https://gitlab.com")
            print(f"\n[fetch-top] Fetching top {args.fetch_top} public projects…", flush=True)
            extra = _fetch_top_gitlab_projects(token, base, args.fetch_top)
            added = [r for r in extra if r not in repos]
            repos.extend(added)
            print(f"[fetch-top] +{len(added)} new repos → {len(repos)} total", flush=True)
    repos = list(dict.fromkeys(repos))[:args.max_repos]  # dedup + cap

    out_dir = Path("outputs/necro")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = out_dir / f"deep_scan_{ts}.json"
    results: list[dict] = []

    # ── Phase 1 (parallel) ───────────────────────────────────────────────────
    if args.phase in ("1", "both"):
        print(f"\n{'='*65}", flush=True)
        print(f"Phase 1: parallel detection across {len(repos)} repos  "
              f"(concurrency={args.concurrency})", flush=True)
        print(f"  lookback={args.lookback}mo  max_commits={args.max_commits}", flush=True)
        print("=" * 65, flush=True)
        t0 = time.time()
        sem = asyncio.Semaphore(args.concurrency)
        await phase1_batch(repos, args.lookback, args.max_commits,
                           args.concurrency, results, out_path, sem)
        hits = [r for r in results if r.get("candidate_count", 0) >= args.min_candidates]
        print(f"\nPhase 1 done in {round(time.time()-t0)}s — "
              f"{len(hits)}/{len(repos)} repos have candidates", flush=True)

        # rank hits by groundability score (highest first = most likely revive_now)
        hits.sort(key=lambda r: r.get("groundability_score", 0), reverse=True)
        print(f"\nTop hits by groundability score:", flush=True)
        for r in hits[:15]:
            g = r.get("groundability_score", 0)
            print(f"  score={g:2d}  {r['repo']}", flush=True)
    else:
        hits = [{"repo": rp, "candidate_count": 1} for rp in repos]

    # ── Phase 2 (full pipeline on top-scored hits) ────────────────────────────
    phase2_repos = [r["repo"] for r in hits[:args.top_n_phase2]]
    if args.phase == "2":
        phase2_repos = repos  # use provided list directly

    if phase2_repos and args.phase in ("2", "both"):
        print(f"\n{'='*65}", flush=True)
        print(f"Phase 2: full pipeline on top {len(phase2_repos)} repos", flush=True)
        print("  (highest groundability score first — most likely revive_now)", flush=True)
        print("=" * 65, flush=True)
        for repo in phase2_repos:
            r = await phase2_full(repo, args.lookback, args.max_commits)
            _print_phase2(r)
            results = [x for x in results if x.get("repo") != repo]
            results.append(r)
            json.dump(results, open(out_path, "w", encoding="utf-8"), indent=2)

        revive = [r["repo"] for r in results
                  if r.get("phase") == 2 and r.get("has_revive_now")]
        print(f"\n{'='*65}", flush=True)
        if revive:
            print(f"★  REVIVE NOW found in {len(revive)} repo(s):", flush=True)
            for repo in revive:
                r2 = next(x for x in results if x.get("repo") == repo and x.get("phase") == 2)
                for d in r2.get("detail", []):
                    if d.get("recommendation") == "revive_now":
                        print(f"   🟢 {repo}  →  {d['name'][:50]}  "
                              f"feas={d['feasibility']}  [{d.get('technology','')}✓]", flush=True)
        else:
            print("REVIVE NOW: 0 found in public repos (expected — external-constraint"
                  " kills with verified evidence are rare by design)", flush=True)
            # show best near-misses
            near = []
            for r in results:
                if r.get("phase") != 2: continue
                for d in r.get("detail", []):
                    if d.get("recommendation") == "investigate_further" and (d.get("feasibility") or 0) >= 5:
                        near.append((r["repo"], d))
            near.sort(key=lambda x: x[1].get("feasibility", 0) or 0, reverse=True)
            if near:
                print(f"\nBest near-misses (Investigate, feas≥5):", flush=True)
                for repo, d in near[:8]:
                    grd = f"[{d['technology']}✓]" if d.get("grounded") else "[ungrounded]"
                    print(f"   🟡 {repo}  →  {d['name'][:44]}  feas={d['feasibility']}  {grd}", flush=True)

    print(f"\nFull results: {out_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NECRO deep GitLab scanner")
    parser.add_argument("--phase", default="1", choices=["1", "2", "both"])
    parser.add_argument("--repos", default="",
                        help="Comma-separated override list")
    parser.add_argument("--max-repos",   type=int, default=30)
    parser.add_argument("--fetch-top",   type=int, default=0,
                        help="Fetch this many top public projects from GitLab API")
    parser.add_argument("--lookback",    type=int, default=36)
    parser.add_argument("--max-commits", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=8,
                        help="Parallel repos for Phase 1 (default 8)")
    parser.add_argument("--min-candidates", type=int, default=1)
    parser.add_argument("--top-n-phase2",   type=int, default=10,
                        help="Run Phase 2 on this many top-scored Phase 1 hits (default 10)")
    args = parser.parse_args()
    asyncio.run(main(args))
