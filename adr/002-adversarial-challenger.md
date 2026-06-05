# ADR 002: The challenger runs on separate infrastructure

**Status:** Accepted
**Date:** 2026-05-20

## What we decided

The adversarial challenger model runs on Vertex AI rather than the same Google AI Studio endpoint used by the analyst. This is intentional. They are literally different serving infrastructure, not just different prompts on the same backend.

## Why we made this call

For the adversarial pattern to mean anything, the challenger has to be genuinely independent. If both models share the same underlying weights, the same fine-tuning, and the same serving infrastructure, any disagreement between them is statistical noise rather than a real second opinion.

By routing the analyst through Google AI Studio and the challenger through Vertex AI, we get:

1. Different model versions in some cases, since the two platforms do not always serve identical checkpoints.
2. Different serving paths, which means different temperature sampling, different batching behavior, and in practice different output distributions on borderline inputs.
3. An architectural guarantee that we can communicate to users: the challenger is not just a re-run of the same prompt.

## The practical constraint

Vertex AI does not currently serve the `gemini-3-flash-preview` model that the analyst uses. The challenger runs on `gemini-2.5-flash` via Vertex. This is actually a feature rather than a bug: the model version difference reinforces the independence guarantee.

## What we gave up

Managing two separate clients and two sets of credentials adds complexity to the codebase and the deployment configuration. A simpler system would use one API key. We decided the independence guarantee was worth the overhead.
