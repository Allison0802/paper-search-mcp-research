"""Opt-in switch for tests that contact third-party services."""

import os


def live_tests_enabled() -> bool:
    """Return whether explicitly requested live-network tests may run."""
    return os.environ.get("PAPER_SEARCH_MCP_RUN_LIVE_TESTS") == "1"
