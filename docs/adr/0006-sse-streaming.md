# ADR-0006: Server-Sent Events for real-time output

**Status:** Accepted  
**Date:** 2026-05-20

---

A NECRO scan takes 60 to 120 seconds. That is a long time to stare at a spinner with no feedback. The question was how to show the user what is happening as it happens.

We considered polling: the frontend asks every few seconds whether the scan is done. This is simple to implement and robust, but it means the user sees the scan in discrete jumps rather than continuously. If two GitLab API calls happen in the same polling interval, the user sees one line appear instead of two.

We chose Server-Sent Events because the communication pattern is exactly one-directional: the server pushes events, the browser listens, and there is nothing the browser needs to say back after the initial scan request. WebSockets support bidirectional communication, which is powerful but unnecessary here. SSE does what we need with a fraction of the complexity. FastAPI supports it natively via `StreamingResponse`, which meant the streaming pipeline was three lines of code, not a separate WebSocket handler with connection management logic.

The practical result is that users watch each GitLab MCP call happen in the terminal stream at the bottom of the app. They see when the Analyst finds a candidate, when the Challenger challenges it, and when the Planner opens the Draft MR. The scan becomes transparent rather than opaque, and that transparency is itself a feature: it shows the multi-agent pipeline working in real time rather than asking users to trust that something sophisticated happened.

The one meaningful limitation: SSE is one-directional, so the browser cannot cancel a running scan mid-stream. We live with this because scans are short enough that cancellation rarely matters, and dry-run mode lets users preview the plan without running the full pipeline.
