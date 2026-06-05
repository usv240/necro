"""Quick local test of necrosis_detector against a live GitLab repo (no server)."""
import asyncio
import sys
from dotenv import load_dotenv

# Force UTF-8 so Windows console can print signal glyphs
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

load_dotenv()

from backend.services.necrosis_detector import detect_necrosis  # noqa: E402
from backend.services.deletion_scorer import score_deletion_safety  # noqa: E402

repo = sys.argv[1] if len(sys.argv) > 1 else "gitlab-org/gitlab-runner"
score = "--score" in sys.argv


async def main():
    async def emit(msg):
        print("  ", msg, flush=True)

    calls: list = []
    print(f">>> necrosis scan: {repo}\n", flush=True)
    results = await detect_necrosis(repo, progress_cb=emit, mcp_calls=calls, age_top_n=8)
    print(f"\n=== {len(results)} NECROSIS CANDIDATES ===")

    # Score the top few for deletion safety (Phase 2)
    to_score = results[:5] if score else []
    for c in results:
        print(f"\n  [{c.detection_method}] conf={c.detection_confidence} age={c.age_days}d  {c.name}")
        print(f"    file: {c.file_path}")
        print(f"    annotation: {c.annotation[:100]}")
        if c.replacement:
            print(f"    replacement: {c.replacement}")
        if c.removal_target:
            print(f"    removal_target: {c.removal_target}")
        print(f"    signals: {c.detection_signals}")

    if to_score:
        print(f"\n\n=== DELETION SCORING (top {len(to_score)}) ===")
        for c in to_score:
            safety = await score_deletion_safety(c, repo)
            print(f"\n  {c.name} ({c.file_path})")
            print(f"    -> {safety['recommendation'].upper()}  risk={safety.get('deletion_risk')}  callers={safety.get('callers_found')}")
            print(f"    blast_radius: {safety.get('blast_radius','')[:100]}")
            print(f"    reasoning: {safety.get('reasoning','')[:160]}")

    print(f"\n=== {len(calls)} MCP calls ===")


asyncio.run(main())
