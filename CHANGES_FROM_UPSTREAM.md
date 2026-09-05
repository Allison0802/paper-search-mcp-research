# Changes from upstream

`paper-search-mcp-research` is a research-oriented fork of
[`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp).
It retains the upstream Python import namespace, `paper_search_mcp`, and the
`paper-search-mcp` and `paper-search` console scripts for compatibility.

## Fork additions

- Exact Crossref journal-year querying, including explicit volume validation,
  complete-or-error pagination, and recorded selection/date provenance.
- Exact journal volume-and-issue discovery plus batch download manifests that
  record every discovered article and its retrieval outcome.
- Safer repository fallback matching, including normalized DOI matching and
  rejection of mismatched candidate records.
- Richer Crossref, OpenAlex, and Unpaywall metadata normalization, including
  bibliographic fields, publication-date provenance, and OA version context.
- Deterministic regression coverage and public reproducibility guidance that
  separate hermetic checks from live-provider validation.

These changes do not assert publisher-wide completeness. Provider data,
coverage, access, and metadata may change after a query is run.

## Upstream attribution

The upstream repository is
[`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp).
This fork contains substantial modifications and is independently maintained;
the upstream maintainers do not endorse it. The upstream MIT license and
`Copyright (c) 2025 OPENAGS` notice are preserved in [LICENSE](LICENSE).
Fork modifications are separately noticed there.
