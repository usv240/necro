"""
pytest conftest — automatically skips all integration tests when
the NECRO backend is not reachable on localhost:8080.

All tests in this suite are live integration tests; they require a
running server.  In CI (no credentials → no server) they should
show as SKIPPED rather than FAILED so the pipeline stays green.
"""

import httpx
import pytest

_BASE = "http://localhost:8080"


def pytest_collection_modifyitems(config, items):
    """Mark every collected test as skip if the backend is unreachable."""
    try:
        r = httpx.get(f"{_BASE}/api/health", timeout=3.0)
        server_up = r.status_code == 200
    except Exception:
        server_up = False

    if not server_up:
        skip = pytest.mark.skip(
            reason="NECRO backend not running on localhost:8080 — integration tests skipped in CI"
        )
        for item in items:
            item.add_marker(skip)
