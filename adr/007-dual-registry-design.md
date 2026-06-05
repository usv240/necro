# ADR 007: Two registries, one shared engine

**Status:** Accepted
**Date:** 2026-05-23

## What we decided

NECRO has two separate registries with distinct UIs and separate scan endpoints:

- **Dormant Feature Registry** asks "should this come back?" It reads commit history, feature flags, and merge requests to find features that were intentionally disabled.
- **Necrosis Registry** asks "is it finally safe to delete this?" It reads the live codebase for deprecation markers and confirms zero active callers before suggesting removal.

Both registries are powered by the same underlying Gemini-based analysis pipeline and the same GitLab MCP toolset.

## Why we made this call

We started with revival as the primary use case. During testing we noticed that Dormant Feature Registry scans on mature repos often returned zero "Revive Now" results. The features were gone, and the kill reasons were still valid. But those same repos were full of deprecated functions, dead feature flags, and tombstoned handlers that had never been cleaned up.

That was a real and immediate problem we could solve. We built the Necrosis Registry as a direct response.

The two registries solve complementary problems. Revival is valuable when it succeeds but rare because most things that were killed were killed for good reasons. Dead code cleanup succeeds on virtually every mature codebase scan because dead code accumulates universally. Having both in the same tool means every scan produces something useful regardless of whether revival candidates exist.

## Why they share one engine

The core analysis loop is the same for both:

1. Find a candidate (history scan for revival, blob scan for necrosis).
2. Determine context (kill reason vs. deprecation age and caller count).
3. Run through Gemini analysis.
4. Challenge the verdict.
5. Return a verdict with evidence.

Implementing them as completely separate pipelines would have duplicated most of the codebase. We kept the shared infrastructure (Gemini client, MCP connection, MongoDB schema) and parameterized the detection step and the verdict labels.

## The naming convention

Revival verdicts: Revive Now, Revival Candidate, Keep Buried.
Necrosis verdicts: Excise Now, Needs Biopsy, Leave Intact.

Different labels, same underlying confidence tiers. This made it easy to build a unified reporting format that works for both registries.
