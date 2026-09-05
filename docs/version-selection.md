# PDF version selection

`download_with_fallback` prefers the best lawfully accessible publication version when DOI metadata provides reliable version provenance.

Priority order:

1. Publisher Version of Record.
2. Repository copy explicitly identified as the published Version of Record.
3. Accepted author manuscript.
4. Source-native latest preprint (for example, the current arXiv version for an arXiv identifier).
5. Other submitted/preprint copies.
6. Unknown-version repository or OA copies only when higher-confidence routes fail.

The resolver does not infer a final version from a repository name alone. Unpaywall `version` and `host_type` metadata are used when available; an unclassified repository PDF is recorded as `repository_copy`, not as a Version of Record.

Structured retrieval results and journal-issue manifests record `retrieval_source`, `version_type`, `journal_doi`, `preprint_id`, and `version_date` when known. The public `download_with_fallback` interface remains backward compatible and still returns a path on success or an explanatory message on failure.

Sci-Hub remains explicit opt-in (`use_scihub=True`) and is not part of automatic OA/version selection. Lawful publisher and open-access routes are attempted first.
