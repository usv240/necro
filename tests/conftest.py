"""
pytest conftest — automatically skips INTEGRATION tests when the NECRO backend
is not reachable on localhost:8080.

Tests marked @pytest.mark.unit are pure-Python and run in CI without a server.
Integration tests (everything else) require a running server.

In CI (no credentials → no server) integration tests show as SKIPPED so the
pipeline stays green while unit tests still run and provide signal.
"""

import httpx
import pytest


_BASE = "http://localhost:8080"


def pytest_collection_modifyitems(config, items):
    """Mark every non-unit test as skip if the backend is unreachable."""
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
            # Unit-marked tests run regardless of server availability
            if item.get_closest_marker("unit") is None:
                item.add_marker(skip)
