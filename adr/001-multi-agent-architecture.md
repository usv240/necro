# ADR 001: Three separate models instead of one

**Status:** Accepted
**Date:** 2026-05-20

## What we decided

NECRO uses three distinct models with distinct jobs rather than one model handling everything.

- **Analyst** reads GitLab history and live code, extracts kill reasons, and scores viability.
- **Challenger** starts from a position of skepticism and tries to find concrete reasons a revival or deletion will fail.
- **Planner** looks at all findings, picks priorities, and writes the mission plan.

## Why we made this call

A single model playing all three roles creates a problem: it will tend to agree with itself. Once it produces a "Revive Now" verdict in the analysis step, the same model is unlikely to seriously challenge that verdict in the next step. It knows what conclusion it already reached.

By splitting the roles, we force genuine disagreement. The challenger does not see the analyst's reasoning. It only sees the proposed action and has to argue against it. If it cannot find a specific, falsifiable reason the action will fail, the proposal survives. If it can, the analyst's verdict is downgraded.

This is the same principle behind red team exercises and adversarial testing. One brain cannot reliably red-team itself.

## What we gave up

Running three separate inference calls per finding costs more time and money than a single call. A scan that would take 30 seconds with one model takes around 90 seconds with three. We decided that accuracy was worth the wait, especially because the challenger is only invoked on candidates that passed the analyst's threshold, not on every pattern detected.

## What we considered but rejected

We looked at using a single model with a chain-of-thought prompt that included an internal devil's advocate step. This works reasonably well for simple cases but reliably fails on borderline ones, which are exactly the cases that matter most. A model that is instructed to "now argue against this" will produce objections that are stylistically different but semantically weak. Having a structurally separate model produces harder, more useful objections.
