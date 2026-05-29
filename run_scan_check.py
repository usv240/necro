"""Trigger a live scan via /api/scan/stream and summarize the final recommendation distribution."""
import json
import sys
import time
import httpx

repo = sys.argv[1]
max_commits = int(sys.argv[2])
lookback = int(sys.argv[3])

url = "http://127.0.0.1:8000/api/scan/stream"
payload = {"repo_url": repo, "max_commits": max_commits, "lookback_months": lookback}

t0 = time.time()
report = None
last_progress = []
demand_upgrades = []
synthesis_upgrades = []
search_lines = []

print(f">>> scanning {repo} (max={max_commits}, lookback={lookback}mo)", flush=True)
with httpx.stream("POST", url, json=payload, timeout=300.0) as r:
    if r.status_code != 200:
        print(f"!! HTTP {r.status_code}: {r.read()[:200]!r}")
        sys.exit(1)
    for line in r.iter_lines():
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[6:])
        except Exception:
            continue
        if evt.get("type") == "report":
            report = evt["data"]
        elif evt.get("type") == "progress":
            msg = evt.get("message", "")
            last_progress.append(msg)
            if msg.startswith("Demand override:"):
                demand_upgrades.append(msg)
            if msg.startswith("[ADK] Evidence upgrade:"):
                synthesis_upgrades.append(msg)
            if msg.startswith("[SEARCH]") or msg.startswith("[1/") or msg.startswith("[2/") or "REVIVE NOW" in msg or "INVESTIGATE" in msg or "KEEP BURIED" in msg or "SCAN COMPLETE" in msg:
                search_lines.append(msg)

elapsed = time.time() - t0
print(f">>> finished in {elapsed:.1f}s\n", flush=True)

if not report:
    print("!! no final report event received")
    print("last 20 progress lines:")
    for m in last_progress[-20:]:
        print(" ", m)
    sys.exit(1)

features = report.get("features", [])
buckets = {"revive_now": 0, "investigate_further": 0, "keep_buried": 0, "other": 0}
for f in features:
    rec = f.get("viability", {}).get("recommendation", "other")
    buckets[rec if rec in buckets else "other"] += 1

print(f"FEATURES: {len(features)}  -> revive={buckets['revive_now']}  investigate={buckets['investigate_further']}  keep_buried={buckets['keep_buried']}  other={buckets['other']}")
if demand_upgrades:
    print(f"DEMAND UPGRADES ({len(demand_upgrades)}):")
    for u in demand_upgrades: print(" ", u)
if synthesis_upgrades:
    print(f"SYNTHESIS UPGRADES ({len(synthesis_upgrades)}):")
    for u in synthesis_upgrades: print(" ", u)
print("ADK synthesis present:", report.get("adk_synthesis") is not None)

print("\nFeatures detail:")
for f in features:
    name = f.get("name", "?")[:50]
    vi = f.get("viability", {})
    rec = vi.get("recommendation", "?")
    feas = vi.get("revival_feasibility", "?")
    grounded = vi.get("grounding", {}).get("grounded", False)
    n_demand = len(f.get("open_issue_matches", []))
    ch = f.get("challenger", {}).get("challenger_verdict", "-")
    print(f"  {rec.upper():18}  feas={feas}  grounded={grounded}  demand={n_demand}  challenger={ch}  {name}")
