# Exact journal-year metadata retrieval

Use the unified tool with explicit journal intent:

```python
search_papers(query='journal:"Biometrika"', year='2025', sources='crossref')
search_papers(query='journal:"JASA"', year='2025', sources='crossref')
```

`JASA` and the full journal title are equivalent. Journal matching normalizes punctuation, capitalization and whitespace but does not accept approximate titles. The explicit journal mode enumerates all matching Crossref journal-article records, using cursor pagination; `max_results_per_source` does not truncate this mode. Retrieval errors are reported in `errors`, with incomplete coverage. A zero count is not evidence that a publisher published nothing.

Ordinary keyword queries retain their existing behavior. Their `year` argument applies only to Semantic Scholar. Crossref is the supported source for exact journal-year enumeration; selecting other sources in journal mode returns an explicit unsupported-scope error. OpenAlex keyword results preserve journal/volume/issue metadata, but their publication date may be first-online.

## Dates and nominal issue years

Default selection uses Crossref's issue/print date, falling back to published/issued when print metadata is absent. Current-year results are bounded by today's date. Online-first records without print dates can therefore be included; inspect `extra.date_basis` and volume/issue before treating a result as issue-assigned. Crossref's `journal-article` category also includes some editorials, corrections and book reviews.

Publisher nominal issue years can disagree with Crossref dates. Independently establish the volume from the publisher archive, then explicitly constrain it:

```python
# Only after independently verifying the publisher's nominal year for this volume:
search_papers(query='journal:"Exact Journal Title" volume:"validated volume"',
              year='2025', sources='crossref')
```

The volume form selects the exact journal and volume, excluding future-dated records. It records `selection_year` and `year_basis='caller-validated journal volume'` in `extra`. It retains the original publication dates; the supplied year does not rewrite them. This form depends on the caller's independent volume-year validation, not an internal journal-specific mapping. `extra.publication_dates` preserves online, print and general date parts; the legacy serialized `extra` field remains a string for compatibility.

Coverage means the matching Crossref-indexed records were enumerated, not that Crossref is a complete publisher archive. For date discrepancies or suspected missing papers, consult an official issue page. See the [public testing guidance](testing/README.md) for reproducible commands and the limits of deterministic versus live-provider validation.

## PDFs and running servers

Journal searches are metadata-only. For representative public PDFs, explicitly pass an absolute `save_path`, check existing files by DOI/title first, and verify both PDF integrity and extracted text. Fallback repository candidates must match DOI, or exact normalized title where DOI comparison is unavailable. Public preprints may differ from the publisher version. OA resolution can fail when providers are unavailable or required configuration is absent; this is separate from search coverage.

Restart/reconnect a running MCP process after updating the source. Existing Python processes retain imported code. A successful fresh-process test does not prove that an already-connected client loaded the update.
