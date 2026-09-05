import asyncio
import csv
import inspect
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from paper_search_mcp.paper import Paper


def make_paper(
    title="Recurrent event models",
    authors=None,
    doi="10.1000/example",
    pages="123-145",
    article_number="",
    pdf_url="",
):
    return Paper(
        paper_id=doi or title,
        title=title,
        authors=authors if authors is not None else ["Jane Smith"],
        abstract="",
        doi=doi,
        published_date=datetime(2026, 1, 2),
        pdf_url=pdf_url,
        url="",
        source="crossref",
        extra={"page": pages, "article_number": article_number},
    )


def write_pdf(path: Path, content: bytes = b"%PDF-1.7\nbody") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_helpers_dedupe_sort_filename_and_safe_components(tmp_path):
    from paper_search_mcp.journal_issue import (
        dedupe_issue_papers,
        issue_filename,
        issue_sort_key,
        looks_like_pdf,
        normalize_doi,
        safe_component,
    )

    normal = make_paper(title="Normal", pages="123-145")
    one = make_paper(title="One", doi="10.1000/one", pages="1")
    e_page = make_paper(title="E page", doi="10.1000/e", pages="e12345")
    article = make_paper(title="Article", doi="10.1000/article", pages="", article_number="A900")
    title_only = make_paper(title="Z title", doi="10.1000/title", pages="")
    ordered = sorted([title_only, article, e_page, normal, one], key=issue_sort_key)
    assert [paper.title for paper in ordered] == ["One", "Normal", "Article", "E page", "Z title"]

    duplicate_url_doi = make_paper(doi="https://doi.org/10.1000/EXAMPLE")
    no_doi = make_paper(title="No DOI", authors=["A Writer"], doi="")
    no_doi_duplicate = make_paper(title=" no   doi ", authors=["a  writer"], doi="")
    assert normalize_doi(" http://dx.doi.org/10.1000/ABC ") == "10.1000/abc"
    assert dedupe_issue_papers([normal, duplicate_url_doi, no_doi, no_doi_duplicate]) == [normal, no_doi]

    assert issue_filename(make_paper(title='Recurrent: event / models?', authors=["Jane Smith"]), 1) == (
        "001_Smith_Recurrent__event___models.pdf"
    )
    reserved = set()
    assert issue_filename(make_paper(title="same/title"), 1, reserved).endswith(".pdf")
    assert issue_filename(make_paper(title="same:title"), 1, reserved).endswith("_2.pdf")
    assert issue_filename(make_paper(title="x" * 400), 1).endswith(".pdf")
    assert len(issue_filename(make_paper(title="x" * 400), 1)) <= 140
    assert issue_filename(make_paper(authors=[]), 1).startswith("001_UnknownAuthor_")
    assert safe_component("   ") == "unknown"
    assert safe_component(".") == "unknown"
    assert safe_component("..") == "unknown"
    assert safe_component("../../unsafe") == "unsafe"
    assert safe_component('a/b\\c:d*e?f"g<h>i|j\x00') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_component("a   b\n c") == "a_b_c"
    assert len(safe_component("j" * 200, max_length=80)) == 80
    assert len(safe_component("v" * 100, max_length=40)) == 40
    assert not looks_like_pdf(write_pdf(tmp_path / "not.pdf", b"not a PDF"))
    assert looks_like_pdf(write_pdf(tmp_path / "real.pdf"))


def test_dedupe_coalesces_doi_and_metadata_variants_without_merging_distinct_dois():
    from paper_search_mcp.journal_issue import dedupe_issue_papers

    missing_doi = make_paper(title="Same article", authors=["Ada Lovelace"], doi="")
    first_doi = make_paper(title=" same   article ", authors=["ada  lovelace"], doi="10.1000/first")
    second_doi = make_paper(title="Same article", authors=["Ada Lovelace"], doi="10.1000/second")

    assert dedupe_issue_papers([missing_doi, first_doi, second_doi]) == [first_doi, second_doi]


def test_batch_download_dedupes_doi_and_metadata_variants(tmp_path):
    from paper_search_mcp.journal_issue import download_issue_batch

    missing_doi = make_paper(title="Same article", authors=["Ada Lovelace"], doi="", pages="1")
    first_doi = make_paper(
        title=" same   article ", authors=["ada  lovelace"], doi="10.1000/first", pages="1"
    )
    second_doi = make_paper(
        title="Same article", authors=["Ada Lovelace"], doi="10.1000/second", pages="2"
    )
    downloaded_dois = []

    async def downloader(paper, incoming):
        downloaded_dois.append(paper.doi)
        return {
            "path": str(write_pdf(Path(incoming) / "candidate.pdf")),
            "retrieval_source": "direct_pdf",
            "error": "",
        }

    summary = asyncio.run(
        download_issue_batch(
            [missing_doi, first_doi, second_doi], "Biometrika", "113", "3", tmp_path, downloader
        )
    )

    assert downloaded_dois == ["10.1000/first", "10.1000/second"]
    assert summary["total_articles"] == summary["downloaded"] == 2
    assert [row["doi"] for row in summary["papers"]] == downloaded_dois


def test_issue_directory_component_limits(tmp_path):
    from paper_search_mcp.journal_issue import issue_directory

    directory = issue_directory(tmp_path, "J" * 200, "V" * 100, "I" * 100)
    assert directory.parent.name == "V" * 40
    assert directory.name == "I" * 40
    assert directory.parent.parent.name == "J" * 80


def test_batch_download_manifest_existing_collision_and_overwrite(tmp_path):
    from paper_search_mcp.journal_issue import download_issue_batch

    papers = [
        make_paper(title="Same / title", doi="10.1000/one", pages="1"),
        make_paper(title="Same: title", doi="10.1000/two", pages="2"),
    ]
    calls = []

    async def downloader(paper, incoming):
        calls.append(paper.doi)
        return {"path": str(write_pdf(Path(incoming) / "candidate.pdf")), "retrieval_source": "direct_pdf", "error": ""}

    summary = asyncio.run(download_issue_batch(papers, "Biometrika", "113", "3", tmp_path, downloader))
    assert summary["downloaded"] == 2
    filenames = [row["file_name"] for row in summary["papers"]]
    assert len(set(filenames)) == 2
    assert all(name.endswith(".pdf") for name in filenames)
    assert not (tmp_path / ".incoming").exists()

    second_calls = []

    async def second_downloader(paper, incoming):
        second_calls.append(paper.doi)
        return {"path": str(write_pdf(Path(incoming) / "candidate.pdf")), "retrieval_source": "direct_pdf", "error": ""}

    second = asyncio.run(download_issue_batch(papers, "Biometrika", "113", "3", tmp_path, second_downloader))
    assert second["existing"] == 2
    assert second_calls == []
    assert [row["file_name"] for row in second["papers"]] == filenames

    overwritten = asyncio.run(download_issue_batch(papers, "Biometrika", "113", "3", tmp_path, second_downloader, overwrite=True))
    assert overwritten["downloaded"] == 2
    assert second_calls == ["10.1000/one", "10.1000/two"]


def test_batch_replaces_invalid_existing_only_with_valid_candidate(tmp_path):
    from paper_search_mcp.journal_issue import download_issue_batch

    paper = make_paper(pages="1")
    first = asyncio.run(download_issue_batch([], "Biometrika", "113", "3", tmp_path, AsyncMock()))
    target = Path(first["directory"]) / "001_Smith_Recurrent_event_models.pdf"
    write_pdf(target, b"invalid")

    async def invalid_downloader(paper, incoming):
        return {"path": str(write_pdf(Path(incoming) / "candidate.pdf", b"invalid")), "retrieval_source": "direct_pdf", "error": "no PDF"}

    unavailable = asyncio.run(download_issue_batch([paper], "Biometrika", "113", "3", tmp_path, invalid_downloader))
    assert unavailable["unavailable"] == 1
    assert target.read_bytes() == b"invalid"

    async def valid_downloader(paper, incoming):
        return {"path": str(write_pdf(Path(incoming) / "candidate.pdf")), "retrieval_source": "direct_pdf", "error": ""}

    downloaded = asyncio.run(download_issue_batch([paper], "Biometrika", "113", "3", tmp_path, valid_downloader))
    assert downloaded["downloaded"] == 1
    assert target.read_bytes().startswith(b"%PDF")


def test_batch_manifest_preserves_version_provenance(tmp_path):
    from paper_search_mcp.journal_issue import download_issue_batch

    paper = make_paper(doi="10.1000/example", pages="1")

    async def downloader(paper, incoming):
        return {
            "path": str(write_pdf(Path(incoming) / "candidate.pdf")),
            "retrieval_source": "unpaywall_publisher",
            "version_type": "version_of_record",
            "journal_doi": "10.1000/example",
            "preprint_id": "2306.04177",
            "version_date": "",
            "error": "",
        }

    summary = asyncio.run(
        download_issue_batch([paper], "Biometrika", "113", "3", tmp_path, downloader)
    )
    row = summary["papers"][0]
    assert row["source"] == "unpaywall_publisher"
    assert row["version_type"] == "version_of_record"
    assert row["journal_doi"] == "10.1000/example"
    assert row["preprint_id"] == "2306.04177"
    assert row["version_date"] == ""

    with open(summary["manifest_csv"], newline="") as stream:
        csv_row = next(csv.DictReader(stream))
    assert csv_row["version_type"] == "version_of_record"
    assert csv_row["journal_doi"] == "10.1000/example"
    assert csv_row["preprint_id"] == "2306.04177"


def test_batch_partial_failure_concurrency_and_manifest(tmp_path):
    from paper_search_mcp.journal_issue import MANIFEST_COLUMNS, download_issue_batch

    papers = [make_paper(title=f"Paper {index}", doi=f"10.1000/{index}", pages=str(index)) for index in range(1, 5)]
    active = 0
    peak = 0

    async def downloader(paper, incoming):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            if paper.doi == "10.1000/2":
                return {"path": "", "retrieval_source": "", "error": "not open access"}
            if paper.doi == "10.1000/3":
                raise RuntimeError("network exploded")
            return {"path": str(write_pdf(Path(incoming) / "candidate.pdf")), "retrieval_source": "direct_pdf", "error": ""}
        finally:
            active -= 1

    summary = asyncio.run(download_issue_batch(papers, "Biometrika", "113", "3", tmp_path, downloader, max_concurrency=2))
    assert peak <= 2
    assert summary["downloaded"] == 2
    assert summary["unavailable"] == 1
    assert summary["errors"] == 1
    assert len(summary["papers"]) == 4
    assert not (tmp_path / ".incoming").exists()
    with open(summary["manifest_csv"], newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    assert list(rows[0]) == MANIFEST_COLUMNS
    on_disk = json.loads(Path(summary["manifest_json"]).read_text())
    assert on_disk["total_articles"] == 4
    assert len(on_disk["papers"]) == 4


@pytest.mark.parametrize("max_concurrency", [0, -1])
def test_batch_rejects_invalid_concurrency(tmp_path, max_concurrency):
    from paper_search_mcp.journal_issue import download_issue_batch

    with pytest.raises(ValueError, match="max_concurrency"):
        asyncio.run(download_issue_batch([], "Biometrika", "113", "3", tmp_path, AsyncMock(), max_concurrency=max_concurrency))


def test_zero_complete_issue_writes_truthful_manifests(tmp_path):
    from paper_search_mcp.journal_issue import download_issue_batch

    summary = asyncio.run(download_issue_batch([], "Biometrika", "113", "3", tmp_path, AsyncMock()))
    assert summary["discovery_status"] == "complete"
    assert summary["discovery_complete"] is True
    assert summary["total_articles"] == 0
    assert summary["downloaded"] == summary["existing"] == summary["unavailable"] == summary["errors"] == 0
    assert Path(summary["manifest_csv"]).exists()
    assert Path(summary["manifest_json"]).exists()


def test_server_issue_tools_and_discovery_error_manifest(tmp_path):
    from paper_search_mcp import server
    from paper_search_mcp.academic_platforms.crossref import CrossRefIssueDiscoveryError

    direct = make_paper(pdf_url="https://example.test/paper.pdf")
    with patch.object(server.crossref_searcher, "search_issue", return_value=[direct]), patch(
        "paper_search_mcp.server._download_with_oa_fallback_structured",
        new=AsyncMock(return_value={"path": "", "retrieval_source": "", "error": "not open"}),
    ) as fallback:
        listed = asyncio.run(server.list_journal_issue("Biometrika", "113", "3"))
        assert listed == {
            "journal": "Biometrika", "volume": "113", "issue": "3", "total": 1,
            "papers": [{"order": 1, "title": direct.title, "authors": direct.authors, "doi": direct.doi,
                        "pages": "123-145", "publication_date": "2026-01-02T00:00:00"}],
        }
        summary = asyncio.run(server.download_journal_issue("Biometrika", "113", "3", str(tmp_path)))
        assert summary["unavailable"] == 1
        assert fallback.call_args.kwargs["direct_pdf_url"] == "https://example.test/paper.pdf"
        assert fallback.call_args.kwargs["use_scihub"] is False

    discovery_error = CrossRefIssueDiscoveryError("page failed", partial_count=2)
    with patch.object(server.crossref_searcher, "search_issue", side_effect=discovery_error):
        assert asyncio.run(server.list_journal_issue("Biometrika", "113", "3")) == {
            "discovery_status": "error", "error": "page failed"
        }
        summary = asyncio.run(server.download_journal_issue("Biometrika", "113", "3", str(tmp_path)))
    assert summary["discovery_status"] == "error"
    assert summary["discovery_complete"] is False
    assert summary["total_articles"] == 0
    assert Path(summary["manifest_csv"]).exists()
    assert Path(summary["manifest_json"]).exists()


def test_structured_fallback_prefers_direct_pdf_and_public_default_is_oa_only(tmp_path):
    from paper_search_mcp import server

    direct_path = write_pdf(tmp_path / "direct.pdf")
    with patch("paper_search_mcp.server._download_from_url", new=AsyncMock(return_value=str(direct_path))) as direct_url, patch.object(
        server.crossref_searcher, "download_pdf", side_effect=AssertionError("primary should not run")
    ):
        result = asyncio.run(
            server._download_with_oa_fallback_structured(
                source="crossref",
                paper_id="10.1000/example",
                doi="10.1000/example",
                title="Example",
                save_path=str(tmp_path),
                direct_pdf_url="https://example.test/direct.pdf",
            )
        )
    assert result["path"] == str(direct_path)
    assert result["retrieval_source"] == "direct_pdf"
    assert result["version_type"] == "version_of_record"
    assert result["journal_doi"] == "10.1000/example"
    assert result["preprint_id"] == ""
    assert result["error"] == ""
    assert direct_url.call_args.args[0] == "https://example.test/direct.pdf"
    assert inspect.signature(server.download_with_fallback).parameters["use_scihub"].default is False
