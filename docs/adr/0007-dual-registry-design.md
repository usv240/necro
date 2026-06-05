# ADR-0007: Two registries, one shared engine

**Status:** Accepted  
**Date:** 2026-05-23

---

NECRO started as a revival tool. The Dormant Feature Registry was the whole product: find features that were killed, check whether the kill reason still applies, and surface the ones worth shipping again. During development it became clear that mature repos scanned for revival often returned zero "Revive Now" results. Most things that were killed were killed for good reasons. The pipeline was technically sound but the output was often empty.

The same repos were full of deprecated functions that nobody had cleaned up. `@deprecated` annotations from 2020, `TODO: remove` comments that outlived the sprint they were written in, feature flags marked `Deprecated: true` three years ago with a dozen open callers nobody had checked. This was a different problem from revival but it lived in the same codebase and it was solvable with the same infrastructure.

We built the Necrosis Registry as a direct response to what we were seeing in real scans. Dead code cleanup is a reliable result on virtually every mature repo. Revival is valuable when it happens but rare because most things that were killed were killed permanently. Having both in the same tool means a scan always produces something useful regardless of whether revival candidates exist.

The two registries share the GitLab MCP toolset, the Gemini analysis pipeline, the Challenger architecture, and the MongoDB persistence layer. The difference is the detection step: the Dormant Registry reads commit history for disablement patterns, and the Necrosis Registry reads the live codebase for deprecation markers and then confirms zero active callers before suggesting anything is safe to remove. The verdict labels differ (Revive Now vs. Excise Now, Revival Candidate vs. Needs Biopsy, Keep Buried vs. Leave Intact) but the underlying confidence tiers are identical. One codebase, two surfaces, mirror-imaged missions.

The naming is intentional. Necrosis is what happens to tissue that is dead but still attached to a living body. That is exactly what deprecated-but-unreplaced code does to a codebase.
