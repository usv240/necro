# ADR-0005: NECRO exposes its own MCP endpoint

**Status:** Accepted  
**Date:** 2026-05-22

---

The minimum requirement for the GitLab partner track is that NECRO calls GitLab via MCP. We went one step further and made NECRO callable by GitLab via MCP as well.

NECRO exposes three tools at `/mcp`: `scan_repository`, `get_candidates`, and `get_health`. Any MCP-compatible client that can reach that endpoint can invoke NECRO as a tool. The `.gitlab/duo/necro-agent.yaml` file in the repository demonstrates how to register it in the GitLab Duo Agent Platform, so a developer can type `@necro check this repo for dormant features` in Duo Chat and the pipeline runs without them ever opening a separate browser tab.

The reason this matters is the difference between a tool that reads a platform and a tool that is part of a platform. A one-directional integration means NECRO is useful to people who know it exists and choose to visit it. A bidirectional integration means NECRO is available as a capability inside the workflow developers are already in. That is a qualitatively different kind of value.

It also makes the architectural story more interesting. NECRO is not just a consumer of the GitLab ecosystem. It is a participant in it. Other tools, agents, and workflows can call NECRO's analysis pipeline through the same protocol they use to call everything else.

The implementation is straightforward: FastMCP mounted at `/mcp` on the same FastAPI application that serves the rest of the backend, using Streamable HTTP transport. The maintenance cost is keeping the MCP tool schemas in sync with any changes to the underlying scan API. That is a manageable surface area.
