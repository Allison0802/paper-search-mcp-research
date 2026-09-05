# paper-search-mcp-research

[![CI](https://github.com/Allison0802/paper-search-mcp-research/actions/workflows/ci.yml/badge.svg)](https://github.com/Allison0802/paper-search-mcp-research/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

A research-oriented fork of
[`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp),
focused on reproducible academic-literature retrieval, exact journal/volume/
issue discovery, transparent bibliographic provenance, and open-access-first
full-text resolution.

The distribution name is `paper-search-mcp-research`; the Python import
namespace remains `paper_search_mcp`. This project is not published to PyPI or
Smithery. Install it from this repository until a separately announced
distribution release exists.

## Highlights

- Search across academic metadata and open repositories with normalized paper
  records.
- Retrieve exact Crossref journal-year or journal-volume scopes without
  silently treating incomplete pagination as a complete result.
- List a complete journal issue before requesting downloads, then retain CSV
  and JSON manifests for every discovered article and retrieval outcome.
- Prefer source-native public copies, open repositories, and Unpaywall-backed
  open-access locations for full-text resolution.
- Preserve date, volume, issue, and source provenance so nominal journal-year
  selection is not confused with a provider's recorded publication date.

## Open-access and compliance posture

Default retrieval is open-access-first. The standard fallback chain does not
use Sci-Hub unless a caller explicitly enables its legacy optional connector.
It is not a recommended retrieval route, and this project does not provide
guidance for bypassing publisher access controls. Use only sources and copies
you are authorized to access.

## Install from this fork

Clone the fork and use its locked environment:

```bash
git clone https://github.com/Allison0802/paper-search-mcp-research.git
cd paper-search-mcp-research
uv sync --all-extras
```

Alternatively, install directly from the Git repository:

```bash
python -m pip install "paper-search-mcp-research @ git+https://github.com/Allison0802/paper-search-mcp-research.git"
```

The compatibility console scripts remain:

```bash
paper-search --help
paper-search-mcp
```

`paper-search-mcp` starts a standard-input/output MCP server, so invoke it
through an MCP client rather than an interactive terminal.

## MCP registration

For a source checkout, configure an MCP client with an absolute path in place
of `<absolute-path-to-checkout>`:

```json
{
  "mcpServers": {
    "paper-search-mcp-research": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "<absolute-path-to-checkout>",
        "-m",
        "paper_search_mcp.server"
      ]
    }
  }
}
```

This preserves the existing `paper_search_mcp.server` registration behavior
while giving the installed project a distinct public identity.

## Journal and issue workflows

Use exact journal, volume, and issue identifiers when requesting an issue:

```bash
paper-search issue-list "Biometrika" 113 3
paper-search issue-download "Biometrika" 113 3 -o ./papers
```

The issue download command writes a dedicated directory plus `manifest.csv`
and `manifest.json`. A record is retained for every discovered article, whether
it was downloaded, already existed, was unavailable, or produced an error.

For exact journal-year searches, see
[docs/journal-year-search.md](docs/journal-year-search.md). When a volume is
used to select a journal's nominal year, verify that journal's own volume/year
relationship first; the server preserves source publication dates rather than
rewriting them.

## Provider configuration

`PAPER_SEARCH_MCP_CONTACT_EMAIL` is an optional contact address for provider
requests that benefit from one. If it is unset, this fork does not fabricate a
contact address. `PAPER_SEARCH_MCP_UNPAYWALL_EMAIL` remains the separate
optional address used to enable Unpaywall resolution. Other optional provider
keys are described in [.env.example](.env.example); do not commit credentials.

## Testing

The default suite is deterministic and blocks outbound network access:

```bash
uv sync --all-extras --locked
uv run pytest -q --tb=short
uv build
```

Live-provider tests are deliberately outside normal CI. They require explicit
opt-in and do not establish provider-wide completeness or continuing access.
See [docs/testing/README.md](docs/testing/README.md) for the public validation
contract.

## Relationship to upstream

This is a substantially modified, independently maintained fork of
[`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp).
The original package metadata identifies P.S Zhang as an upstream author. The
upstream MIT license and its `Copyright (c) 2025 OPENAGS` notice remain intact;
this fork adds a separate modification notice. The upstream maintainers do not
endorse this fork.

Use the `paper-search-mcp-research` distribution name and the
`Allison0802/paper-search-mcp-research` repository URL to distinguish this
project from upstream. See [CHANGES_FROM_UPSTREAM.md](CHANGES_FROM_UPSTREAM.md)
for source-supported fork additions.

## Contributing and license

Report fork-specific issues at
<https://github.com/Allison0802/paper-search-mcp-research/issues>. Contributions
remain subject to the MIT license in [LICENSE](LICENSE), including the preserved
upstream attribution.
