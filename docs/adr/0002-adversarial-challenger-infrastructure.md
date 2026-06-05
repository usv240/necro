# ADR-0002: The Challenger runs on separate infrastructure

**Status:** Accepted  
**Date:** 2026-05-20

---

Splitting the Analyst and Challenger into two separate roles (ADR-0001) is only half of the independence guarantee. If both models run on identical infrastructure with identical weights and identical temperature sampling, any disagreement between them is statistical noise, not a real second opinion. We needed the Challenger to be genuinely independent, not just a re-prompt of the same model.

The Analyst runs on Google AI Studio using `gemini-3-flash-preview`. The Challenger runs on Vertex AI. They are literally different serving backends. Vertex AI does not currently serve `gemini-3-flash-preview`, so the Challenger runs on the model that is available there. This means the two agents can diverge not just in their outputs but in the underlying model weights and serving behaviour.

The practical benefit is that we can make a structural claim to users: the Challenger is not a re-run of the same prompt on the same backend. Its disagreements come from a genuinely different model processing the same candidate independently. When OptimistAgent and PessimistAgent both land near the same verdict, that convergence means something. When they disagree sharply, the system surfaces that tension explicitly rather than silently averaging it away.

Two API clients, two credential paths, and two points of failure is more complex than one. There is also an ongoing maintenance concern: if Vertex AI eventually serves the same model checkpoint as AI Studio, the independence guarantee weakens. We think the accuracy benefit justifies the complexity for now, and the architecture makes it easy to swap either backend independently if better options emerge.
