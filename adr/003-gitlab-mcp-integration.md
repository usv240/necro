# ADR 003: GitLab MCP over the REST API

**Status:** Accepted
**Date:** 2026-05-20

## What we decided

NECRO uses GitLab's official MCP server (plus the community `@zereight/mcp-gitlab` server as a secondary) rather than calling the GitLab REST API directly.

## Why we made this call

The GitLab REST API is a great API. We chose MCP for reasons that go beyond functionality.

**It fits the ADK agent model.** Google Cloud Agent Builder expects tools to be declared as MCP tools. If we called the GitLab REST API directly from Python, the agent would have no visibility into what was happening. With MCP tools, each GitLab call flows through the agent's tool-use loop, shows up in the reasoning trace, and can be retried or skipped by the agent itself. The agent becomes genuinely agentic rather than a thin wrapper around our Python HTTP calls.

**It makes the integration verifiable.** Judges and reviewers can look at the agent's tool call log and see exactly which GitLab operations NECRO performed, in what order, with what arguments. This is much clearer than reading raw HTTP request logs.

**It matches the track requirement.** We are in the GitLab partner track. Using the official GitLab MCP server is the most direct demonstration of the integration the judges are looking for.

## Two MCP servers, not one

We connect to both the official GitLab MCP server (via SSE) and the community `@zereight/mcp-gitlab` server (via stdio). They expose overlapping but not identical tool sets. The total is 19 available tools. We use the official server for write operations (creating issues and merge requests) because it has stricter authorization, and either for reads.

## What we gave up

MCP adds a round-trip and a process boundary compared to a direct HTTP call. Each tool call is slower than the equivalent REST call would be. For an interactive scan that already takes 60 to 120 seconds, this overhead is acceptable. For a sub-second use case it would not be.
