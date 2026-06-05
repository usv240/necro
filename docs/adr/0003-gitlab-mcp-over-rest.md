# ADR-0003: GitLab MCP over direct REST API calls

**Status:** Accepted  
**Date:** 2026-05-20

---

The GitLab REST API can do everything NECRO needs. We chose the GitLab MCP server anyway, and the reasons go beyond functionality.

When an ADK agent calls a REST endpoint directly from Python, the agent does not know what it called. The tool call does not appear in the reasoning trace. The agent cannot retry it, skip it, or make decisions based on the result within the same reasoning step. You end up with a Python HTTP client masquerading as an agent. The agent is just a wrapper around our own code.

When the same operation goes through an MCP tool, the agent sees it. It can decide whether to call `get_commit_diff` at all based on what `list_commits` returned. It can call `search_blobs` with a query it derived from reading the commit message. The reasoning chain is transparent and logged. The whole system behaves like an agent rather than a deterministic script with an AI label.

The second reason is verifiability. A judge or reviewer can look at the agent's MCP tool call log and follow exactly what NECRO did: which commits it inspected, what it searched for, which blame calls it made. That is a much stronger demonstration of a GitLab integration than reading HTTP request logs.

We connect to both the official GitLab MCP server (via SSE) and the community `@zereight/mcp-gitlab` server (via stdio). They expose overlapping but not identical tool sets. The total is 19 available tools. We use the official server for write operations because it has the stricter authorization controls you want when actually creating merge requests.

The cost is latency. Each MCP tool call has a round-trip through a process boundary that a direct REST call would not. For a scan that already takes 60 to 120 seconds, the overhead is acceptable. For anything latency-sensitive it would not be.
