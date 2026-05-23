"""
Thin wrapper around the ADK agent runner.
Initialised lazily so the agent boots after the MCP client is ready.
"""

import logging
from google.adk.runners import Runner

logger = logging.getLogger(__name__)

_runner: Runner | None = None


def get_runner() -> Runner:
    global _runner
    if _runner is None:
        from agent.agent import get_runner as _build
        _runner = _build()
    return _runner
