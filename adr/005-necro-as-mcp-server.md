# ADR 005: NECRO exposes its own MCP endpoint

**Status:** Accepted
**Date:** 2026-05-22

## What we decided

In addition to consuming GitLab's MCP server, NECRO exposes itself as an MCP server at `/mcp`. It offers three tools: `scan_repository`, `get_candidates`, and `get_health`.

## Why we made this call

This turns the integration from one-directional to bidirectional.

In the one-directional version, NECRO calls GitLab. That is the minimum required for the track. In the bidirectional version, GitLab Duo agents can also call NECRO. A developer working in GitLab Duo Chat could say "check this repo for dormant features" and, if NECRO is registered as an MCP tool in their Duo workspace, Duo would call NECRO's `/mcp` endpoint to get the answer.

This is a qualitatively different integration. NECRO stops being a standalone tool that happens to read GitLab and becomes a first-class participant in the GitLab AI ecosystem. The `.gitlab/duo/necro-agent.yaml` file in this repository demonstrates the registration format.

## How it works

NECRO's MCP server is built with FastMCP and mounted at `/mcp` on the same FastAPI application that serves the rest of the backend. It uses Streamable HTTP transport. Any MCP-compatible client that can reach the `/mcp` endpoint can discover and call NECRO's tools without any additional setup.

## What we gave up

Maintaining an MCP server adds surface area that needs to stay in sync with the rest of the API. If the scan response format changes, both the REST API and the MCP tool schema need to be updated. This is a manageable cost given the scope of the project.

## Why this matters for the judging criteria

The "Technological Implementation" criterion asks whether the interaction with the partner service demonstrates quality software development. A bidirectional MCP integration is a substantially deeper demonstration of that integration than a one-way integration.
