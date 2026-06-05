# ADR-0001: Three separate models instead of one

**Status:** Accepted  
**Date:** 2026-05-20

---

The first version of NECRO used a single Gemini call that did everything: found the candidate, reasoned about the kill reason, assessed revival viability, and returned a verdict. It worked well enough for clear-cut cases. When a feature was killed because a dependency went end-of-life and the dependency was still end-of-life, the single model got it right. The problem showed up on borderline candidates.

A model that produces a "Revive Now" verdict in the analysis step will not seriously challenge that verdict in the next step. It has already committed to a framing. The adversarial pass becomes a box-ticking exercise where the model generates polite objections that do not change the conclusion. We ran this and it was exactly as useless as it sounds.

The fix was structural, not prompt-based. NECRO now uses three models with distinct, non-overlapping jobs. The Analyst reads GitLab history and live code, extracts kill reasons, and scores viability. It has no knowledge of what the Challenger will do. The Challenger receives only the proposed action and must find specific, falsifiable reasons it will fail. It does not see the Analyst's reasoning. If it cannot find a real objection, the proposal survives. If it can, the Analyst's verdict is downgraded. The Planner then looks at everything that survived and decides what to actually do.

This is the same principle behind red team exercises. One person cannot reliably red-team their own proposal. The architecture makes genuine disagreement structurally inevitable rather than something we hope the prompt will produce.

The cost is real. Running three separate inference calls per candidate takes longer than one. A scan that takes 30 seconds with a single model takes 90 seconds with three. We decided accuracy on borderline cases was worth the wait, especially because the Challenger only runs on candidates that passed the Analyst's confidence threshold, not on every pattern detected.
