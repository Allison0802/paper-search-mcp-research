# Public validation guidance

This directory intentionally contains no captured provider responses, machine
paths, personal configuration, or execution-state artifacts. Such captures can
be large, stale, and unsuitable as public test fixtures.

## Deterministic checks

From a source checkout, install the locked development environment and run the
hermetic suite:

```bash
uv sync --all-extras --locked
uv run pytest -q --tb=short
uv build
```

The test configuration blocks outbound network connections unless a maintainer
explicitly enables live validation. The GitHub Actions workflow also builds the
wheel and source distribution, installs the wheel in a fresh virtual
environment, and checks the installed package, CLI, and MCP entry point.

## Live-provider validation

Provider behavior is intentionally not a CI claim. Run live checks only with
explicit authorization, lawful provider use, and a controlled environment:

```bash
PAPER_SEARCH_MCP_RUN_LIVE_TESTS=1 uv run pytest -q
```

Record the command, date, provider scope, and limitations in a separate local
maintenance record. Do not commit raw API payloads, credentials, personal
paths, or large response archives to this directory.
