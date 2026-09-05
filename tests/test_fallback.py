import unittest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

from paper_search_mcp import server


class TestDownloadWithFallback(unittest.TestCase):
    def test_repository_fallback_before_scihub(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_pdf = Path(temporary_directory) / "repo.pdf"
            repository_pdf.write_bytes(b"%PDF-1.7\nrepository")
            with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), \
                 patch("paper_search_mcp.server._try_repository_fallback", new=AsyncMock(return_value=(str(repository_pdf), ""))), \
                 patch("paper_search_mcp.server.SciHubFetcher.download_pdf", side_effect=AssertionError("Sci-Hub should not be called")):
                result = asyncio.run(
                    server.download_with_fallback(
                        source="arxiv",
                        paper_id="1234.5678",
                        doi="10.1000/test",
                        title="test",
                        use_scihub=True,
                    )
                )
            self.assertEqual(result, str(repository_pdf))

    def test_invalid_repository_candidate_continues_to_unpaywall(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_repository_pdf = Path(temporary_directory) / "repo.pdf"
            invalid_repository_pdf.write_bytes(b"not a PDF")
            unpaywall_pdf = Path(temporary_directory) / "unpaywall.pdf"
            unpaywall_pdf.write_bytes(b"%PDF-1.7\nunpaywall")
            with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), \
                 patch("paper_search_mcp.server._try_repository_fallback", new=AsyncMock(return_value=(str(invalid_repository_pdf), ""))), \
                 patch.object(server.unpaywall_resolver, "resolve_best_pdf_url", return_value="https://example.org/oa.pdf"), \
                 patch("paper_search_mcp.server._download_from_url", new=AsyncMock(return_value=str(unpaywall_pdf))) as direct_download:
                result = asyncio.run(
                    server.download_with_fallback(
                        source="arxiv",
                        paper_id="1234.5678",
                        doi="10.1000/test",
                        title="test",
                    )
                )
            self.assertEqual(result, str(unpaywall_pdf))
            self.assertFalse(invalid_repository_pdf.exists())
            direct_download.assert_awaited_once()

    def test_unpaywall_fallback_after_repositories(self):
        with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), \
             patch("paper_search_mcp.server._try_repository_fallback", new=AsyncMock(return_value=(None, "repo failed"))), \
             patch.object(server.unpaywall_resolver, "resolve_best_pdf_url", return_value="https://example.org/oa.pdf"), \
             patch("paper_search_mcp.server._download_from_url", new=AsyncMock(return_value="/tmp/unpaywall.pdf")):
            result = asyncio.run(
                server.download_with_fallback(
                    source="arxiv",
                    paper_id="1234.5678",
                    doi="10.1000/test",
                    title="test",
                    use_scihub=True,
                )
            )
            self.assertEqual(result, "/tmp/unpaywall.pdf")

    def test_no_scihub_returns_oa_chain_error(self):
        with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), \
             patch("paper_search_mcp.server._try_repository_fallback", new=AsyncMock(return_value=(None, "repo failed"))), \
             patch.object(server.unpaywall_resolver, "resolve_best_pdf_url", return_value=None):
            result = asyncio.run(
                server.download_with_fallback(
                    source="arxiv",
                    paper_id="1234.5678",
                    doi="10.1000/test",
                    title="test",
                    use_scihub=False,
                )
            )
            self.assertIn("OA fallback chain", result)


class TestVersionPreference(unittest.TestCase):
    def test_publisher_version_of_record_beats_arxiv_primary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            publisher_pdf = Path(temporary_directory) / "publisher.pdf"
            publisher_pdf.write_bytes(b"%PDF-1.7\npublisher")
            with patch.object(
                server.unpaywall_resolver,
                "resolve_ranked_pdf_candidates",
                return_value=[{
                    "url": "https://publisher.example/final.pdf",
                    "version_type": "version_of_record",
                    "host_type": "publisher",
                }],
            ), patch(
                "paper_search_mcp.server._download_from_url",
                new=AsyncMock(return_value=str(publisher_pdf)),
            ), patch.object(
                server.arxiv_searcher,
                "download_pdf",
                side_effect=AssertionError("arXiv must not win over a publisher version of record"),
            ):
                result = asyncio.run(
                    server._download_with_oa_fallback_structured(
                        source="arxiv",
                        paper_id="2306.04177",
                        doi="10.1000/test",
                        title="Test paper",
                        save_path=temporary_directory,
                    )
                )

            self.assertEqual(result["path"], str(publisher_pdf))
            self.assertEqual(result["retrieval_source"], "unpaywall_publisher")
            self.assertEqual(result["version_type"], "version_of_record")
            self.assertEqual(result["journal_doi"], "10.1000/test")
            self.assertEqual(result["preprint_id"], "2306.04177")

    def test_accepted_manuscript_beats_arxiv_preprint(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            accepted_pdf = Path(temporary_directory) / "accepted.pdf"
            accepted_pdf.write_bytes(b"%PDF-1.7\naccepted")
            with patch.object(
                server.unpaywall_resolver,
                "resolve_ranked_pdf_candidates",
                return_value=[{
                    "url": "https://repository.example/accepted.pdf",
                    "version_type": "accepted_manuscript",
                    "host_type": "repository",
                }],
            ), patch(
                "paper_search_mcp.server._download_from_url",
                new=AsyncMock(return_value=str(accepted_pdf)),
            ), patch.object(
                server.arxiv_searcher,
                "download_pdf",
                side_effect=AssertionError("arXiv must not win over an accepted manuscript"),
            ):
                result = asyncio.run(
                    server._download_with_oa_fallback_structured(
                        source="arxiv",
                        paper_id="2306.04177",
                        doi="10.1000/test",
                        title="Test paper",
                        save_path=temporary_directory,
                    )
                )

            self.assertEqual(result["version_type"], "accepted_manuscript")
            self.assertEqual(result["retrieval_source"], "unpaywall_repository")

    def test_latest_source_preprint_beats_unpaywall_submitted_copy(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            latest_preprint = Path(temporary_directory) / "2306.04177.pdf"
            latest_preprint.write_bytes(b"%PDF-1.7\nlatest arxiv")
            with patch.object(
                server.unpaywall_resolver,
                "resolve_ranked_pdf_candidates",
                return_value=[{
                    "url": "https://repository.example/submitted.pdf",
                    "version_type": "preprint",
                    "host_type": "repository",
                }],
            ), patch(
                "paper_search_mcp.server._try_repository_fallback",
                new=AsyncMock(return_value=(None, "no classified repository copy", "")),
            ), patch.object(
                server.arxiv_searcher,
                "download_pdf",
                return_value=str(latest_preprint),
            ), patch(
                "paper_search_mcp.server._download_from_url",
                new=AsyncMock(side_effect=AssertionError("older submitted copy should not be tried before source-latest arXiv")),
            ):
                result = asyncio.run(
                    server._download_with_oa_fallback_structured(
                        source="arxiv",
                        paper_id="2306.04177",
                        doi="10.1000/test",
                        title="Test paper",
                        save_path=temporary_directory,
                    )
                )

            self.assertEqual(result["path"], str(latest_preprint))
            self.assertEqual(result["version_type"], "preprint")
            self.assertEqual(result["retrieval_source"], "arxiv")
            self.assertEqual(result["preprint_id"], "2306.04177")


class TestRepositoryFallbackNumericPaperId(unittest.TestCase):
    """Regression test for issue #57: _try_repository_fallback crashed when a
    repository connector returned a Paper whose paper_id was a non-string
    (int) value, because the code called .strip() on it directly."""

    def test_numeric_paper_id_does_not_crash(self):
        class FakePaper:
            doi = "10.1000/test"
            pdf_url = "https://example.org/oa.pdf"
            paper_id = 12345  # int, not str — caused 'int' object has no attribute 'strip'

        fake_searcher = type(
            "S", (), {"search": staticmethod(lambda q, max_results=3: [FakePaper()])}
        )

        # Patch one of the repository searchers to return our FakePaper.
        with patch.object(server, "openaire_searcher", fake_searcher), \
             patch("paper_search_mcp.server._download_from_url", new=AsyncMock(return_value="/tmp/ok.pdf")):
            result, err = asyncio.run(
                server._try_repository_fallback(
                    doi="10.1000/test",
                    title="some title",
                    save_path="/tmp",
                )
            )
            self.assertEqual(result, "/tmp/ok.pdf")
            self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
