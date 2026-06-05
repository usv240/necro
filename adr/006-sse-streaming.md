# ADR 006: Server-Sent Events for real-time scan output

**Status:** Accepted
**Date:** 2026-05-20

## What we decided

Scan progress is streamed to the browser using Server-Sent Events (SSE) rather than polling or WebSockets.

## Why we made this call

A typical NECRO scan takes 60 to 120 seconds from URL to final report. Without streaming, the user stares at a spinner with no feedback. With streaming, they can watch each GitLab MCP call as it happens, see when Gemini finishes analyzing a candidate, and watch the adversarial challenge play out in real time. The scan becomes transparent rather than opaque.

We chose SSE over WebSockets for three reasons.

**Simplicity.** SSE is one-directional by design. The server pushes events and the browser listens. That is exactly the communication pattern we need: the user submits a form, the server runs the scan, and the server reports progress. There is no need for the browser to push data back after the initial request.

**FastAPI support.** FastAPI has first-class SSE support via `StreamingResponse`. Adding a WebSocket endpoint would require a different route type and separate connection management logic. SSE slots in with three lines of code.

**Firewall and proxy compatibility.** SSE works over plain HTTP/1.1 and is handled correctly by most reverse proxies and corporate firewalls. WebSockets require protocol upgrades that some environments block.

## What we gave up

SSE is one-directional, so we cannot use it to cancel a running scan from the browser. We handle this by keeping scans short enough that cancellation is rarely needed, and by offering a dry-run mode that previews the plan without running the full pipeline.
