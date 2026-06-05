"""
Necrosis Registry audit harness.

Drives every necrosis entry point the frontend exposes — exactly as the buttons do —
and captures the raw output to JSON files for accuracy review.

Frontend wiring being exercised:
  Instant demo chips  -> loadNecrosisDemo(path)  -> POST /api/necrosis/demo?project_path=
  Live scan chips     -> quickNecrosis(path,..)  -> POST /api/necrosis/scan  (SSE)
  Manual scan + sad/edge paths -> POST /api/necrosis/scan

Outputs: necrosis_audit/<label>.json  (+ _summary.json)
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
OUT = Path(__file__).parent

# (label, project_path) — instant demo chips
DEMOS = [
    ("demo_gitlab-runner", "gitlab-org/gitlab-runner"),
    ("demo_gitlab",        "gitlab-org/gitlab"),
    ("demo_gitaly",        "gitlab-org/gitaly"),
    ("demo_gitlab-shell",  "gitlab-org/gitlab-shell"),
]

# (label, repo_url, max_findings, min_age_days) — live scan chips + manual + sad/edge
LIVE = [
    ("live_gitlab-runner", "gitlab-org/gitlab-runner", 30, 90),
    ("live_gitlab",        "gitlab-org/gitlab",        30, 180),
    ("live_gitaly",        "gitlab-org/gitaly",        30, 90),
    ("live_gitlab-shell",  "gitlab-org/gitlab-shell",  30, 90),
]

# Sad / edge paths
EDGE = [
    ("edge_nonexistent",   "gitlab-org/this-repo-does-not-exist-necro", 20, 90),
    ("edge_tiny-private",  "gitlab-org/nonexistent-private-xyz",        10, 90),
]


async def run_demo(client, label, path):
    t0 = time.time()
    try:
        r = await client.post(f"/api/necrosis/demo", params={"project_path": path}, timeout=30)
        data = r.json()
        data["_audit"] = {"label": label, "status_code": r.status_code, "elapsed_s": round(time.time() - t0, 1)}
        (OUT / f"{label}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        n = len(data.get("findings", []))
        print(f"[OK]   {label}: {n} findings, source={data.get('source')}, {data['_audit']['elapsed_s']}s")
    except Exception as e:
        (OUT / f"{label}.json").write_text(json.dumps({"_error": str(e), "label": label}, indent=2), encoding="utf-8")
        print(f"[FAIL] {label}: {e}")


async def run_live(client, label, repo_url, max_findings, min_age):
    t0 = time.time()
    progress = []
    report = None
    try:
        async with client.stream(
            "POST", "/api/necrosis/scan",
            json={"repo_url": repo_url, "max_findings": max_findings, "min_age_days": min_age},
            timeout=300,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue
                if evt.get("type") == "progress":
                    progress.append(evt["message"])
                elif evt.get("type") == "report":
                    report = evt["data"]
        out = {
            "_audit": {"label": label, "repo_url": repo_url, "max_findings": max_findings,
                       "min_age_days": min_age, "elapsed_s": round(time.time() - t0, 1),
                       "progress_lines": len(progress)},
            "progress": progress,
            "report": report,
        }
        (OUT / f"{label}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        if report:
            s = report.get("summary", {})
            print(f"[OK]   {label}: {s.get('total',0)} findings "
                  f"(excise={s.get('excise_now',0)} biopsy={s.get('needs_biopsy',0)} intact={s.get('leave_intact',0)}) "
                  f"{out['_audit']['elapsed_s']}s")
        else:
            print(f"[WARN] {label}: stream ended with no report ({len(progress)} progress lines), {out['_audit']['elapsed_s']}s")
    except Exception as e:
        (OUT / f"{label}.json").write_text(
            json.dumps({"_error": str(e), "label": label, "progress": progress}, indent=2), encoding="utf-8")
        print(f"[FAIL] {label}: {e}")


async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    async with httpx.AsyncClient(base_url=BASE) as client:
        if which in ("all", "demos"):
            print("=== INSTANT DEMOS (cached MongoDB data) ===")
            for label, path in DEMOS:
                await run_demo(client, label, path)
        if which in ("all", "live"):
            print("=== LIVE SCANS (fresh — runs fixed pipeline code) ===")
            for label, url, mx, age in LIVE:
                await run_live(client, label, url, mx, age)
        if which in ("all", "edge"):
            print("=== EDGE / SAD PATHS ===")
            for label, url, mx, age in EDGE:
                await run_live(client, label, url, mx, age)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
