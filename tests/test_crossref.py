# tests/test_crossref.py
import unittest
import os
import requests
from unittest.mock import patch

from paper_search_mcp.academic_platforms.crossref import (
    CrossRefIssueDiscoveryError,
    CrossRefSearcher,
)
from tests.live import live_tests_enabled


class MockCrossRefResponse:
    """Minimal response double for deterministic Crossref pagination tests."""

    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": self.message}


def crossref_item(
    title,
    *,
    doi="",
    journal="Biometrika",
    volume="113",
    issue="3",
    authors=None,
):
    """Create the smallest valid Crossref journal-article record for tests."""
    return {
        "DOI": doi,
        "title": [title],
        "author": authors
        if authors is not None
        else [{"given": "Ada", "family": "Lovelace"}],
        "container-title": [journal],
        "volume": volume,
        "issue": issue,
        "type": "journal-article",
        "issued": {"date-parts": [[2026, 1, 1]]},
    }

def check_api_accessible():
    """检查 CrossRef API 是否可访问
    Check if CrossRef API is accessible"""
    if not live_tests_enabled():
        return False
    try:
        response = requests.get("https://api.crossref.org/works?sample=1", timeout=5)
        return response.status_code == 200
    except:
        return False

class TestCrossRefSearcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_accessible = check_api_accessible()
        if not cls.api_accessible:
            print("\nWarning: CrossRef API is not accessible, some tests will be skipped")

    def setUp(self):
        self.searcher = CrossRefSearcher()

    @unittest.skipUnless(live_tests_enabled(), "live network test")
    def test_search(self):
        if not self.api_accessible:
            self.skipTest("CrossRef API is not accessible")
        
        papers = self.searcher.search("machine learning", max_results=5)
        print(f"Found {len(papers)} papers for query 'machine learning':")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title} (DOI: {paper.doi})")
            print(f"   Authors: {', '.join(paper.authors[:2])}{'...' if len(paper.authors) > 2 else ''}")
            print(f"   Published: {paper.published_date.year if paper.published_date else 'N/A'}")
            print(f"   Citations: {paper.citations}")
            if paper.extra:
                print(f"   Publisher: {paper.extra.get('publisher', 'N/A')}")
                print(f"   Type: {paper.extra.get('crossref_type', 'N/A')}")
            print()
        self.assertTrue(len(papers) > 0)
        if papers:
            self.assertTrue(papers[0].title)
            self.assertTrue(papers[0].doi)

    @unittest.skipUnless(live_tests_enabled(), "live network test")
    def test_search_with_filters(self):
        if not self.api_accessible:
            self.skipTest("CrossRef API is not accessible")
            
        # Test search with date filter
        papers = self.searcher.search(
            "artificial intelligence", 
            max_results=3,
            filter="from-pub-date:2020,has-full-text:true"
        )
        print(f"Found {len(papers)} papers with filters")
        self.assertTrue(len(papers) >= 0)  # May return 0 if no papers match filters

    @unittest.skipUnless(live_tests_enabled(), "live network test")
    def test_get_paper_by_doi(self):
        if not self.api_accessible:
            self.skipTest("CrossRef API is not accessible")
            
        # Test with a known DOI
        known_doi = "10.1038/nature12373"  # A Nature paper
        paper = self.searcher.get_paper_by_doi(known_doi)
        
        if paper:  # Paper might not be found
            print(f"Retrieved paper by DOI: {paper.title}")
            self.assertEqual(paper.doi, known_doi)
            self.assertTrue(paper.title)
        else:
            print(f"Paper with DOI {known_doi} not found in CrossRef")

    @unittest.skipUnless(live_tests_enabled(), "live network test")
    def test_get_paper_by_invalid_doi(self):
        if not self.api_accessible:
            self.skipTest("CrossRef API is not accessible")
            
        # Test with an invalid DOI
        invalid_doi = "10.1234/invalid.doi.123456789"
        paper = self.searcher.get_paper_by_doi(invalid_doi)
        self.assertIsNone(paper)

    def test_download_pdf_not_supported(self):
        with self.assertRaises(NotImplementedError) as context:
            self.searcher.download_pdf("10.1038/nature12373", "./downloads")
        
        self.assertIn("CrossRef does not provide direct PDF downloads", str(context.exception))

    def test_read_paper_not_supported(self):
        message = self.searcher.read_paper("10.1038/nature12373")
        self.assertIn("CrossRef papers cannot be read directly", message)
        self.assertIn("metadata and abstracts are available", message)

    def test_search_error_handling(self):
        # Test with invalid search parameters to check error handling
        papers = self.searcher.search("", max_results=0)  # Empty query
        self.assertEqual(len(papers), 0)

    def test_user_agent_header(self):
        # Default identity names this fork and does not invent a contact email.
        user_agent = self.searcher.session.headers.get('User-Agent', '')
        self.assertIn("paper-search-mcp-research", user_agent)
        self.assertIn("github.com/Allison0802/paper-search-mcp-research", user_agent)
        self.assertNotIn("mailto:", user_agent)


class TestCrossRefIssueDiscovery(unittest.TestCase):
    def setUp(self):
        self.searcher = CrossRefSearcher()

    def _search_with_pages(self, pages, **kwargs):
        """Run discovery with mocked sequential API pages and capture requests."""
        with patch.object(self.searcher.session, "get", side_effect=pages) as get:
            papers = self.searcher.search_issue("Biometrika", "113", "3", **kwargs)
        return papers, get

    def test_search_issue_filters_exact_metadata_deduplicates_and_paginates(self):
        pages = [
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item("Unique DOI", doi="https://doi.org/10.1000/ONE"),
                        crossref_item("Wrong volume", volume="112"),
                    ],
                    "next-cursor": "cursor-1",
                }
            ),
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item("Duplicate DOI", doi="http://dx.doi.org/10.1000/one"),
                        crossref_item("No DOI", authors=[{"family": "Noether"}]),
                    ],
                    "next-cursor": "cursor-2",
                }
            ),
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item("No DOI", authors=[{"family": "Noether"}]),
                        crossref_item("Wrong issue", issue="2"),
                    ],
                    "next-cursor": "cursor-3",
                }
            ),
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item(
                            "Wrong journal",
                            journal="Journal of the American Statistical Association",
                        )
                    ]
                }
            ),
        ]

        papers, get = self._search_with_pages(pages, max_results=2)

        self.assertEqual([paper.title for paper in papers], ["Unique DOI", "No DOI"])
        self.assertEqual([call.kwargs["params"]["cursor"] for call in get.call_args_list], [
            "*",
            "cursor-1",
            "cursor-2",
            "cursor-3",
        ])
        for call in get.call_args_list:
            params = call.kwargs["params"]
            self.assertEqual(params["filter"], "container-title:Biometrika,type:journal-article")
            self.assertEqual(params["rows"], 2)
            self.assertNotIn("mailto", params)

    def test_search_issue_coalesces_doi_and_metadata_variants(self):
        page = MockCrossRefResponse(
            {
                "items": [
                    crossref_item("Same article", doi="10.1000/first"),
                    crossref_item(" same   article ", doi=""),
                    crossref_item("Same article", doi="10.1000/second"),
                ]
            }
        )

        with patch.object(self.searcher.session, "get", return_value=page):
            papers = self.searcher.search_issue("Biometrika", "113", "3")

        self.assertEqual([paper.doi for paper in papers], ["10.1000/first", "10.1000/second"])

    def test_search_issue_maps_only_requested_jasa_alias(self):
        pages = [
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item(
                            "Accepted JASA article",
                            journal="Journal of the American Statistical Association",
                        ),
                        crossref_item("Abbreviation is not a container title match", journal="JASA"),
                    ]
                }
            )
        ]

        with patch.object(self.searcher.session, "get", side_effect=pages) as get:
            papers = self.searcher.search_issue("JASA", "113", "3", max_results=10)

        self.assertEqual([paper.title for paper in papers], ["Accepted JASA article"])
        self.assertEqual(
            get.call_args.kwargs["params"]["filter"],
            "container-title:Journal of the American Statistical Association,type:journal-article",
        )

    def test_search_issue_accepts_punctuation_adjacent_journal_title(self):
        page = MockCrossRefResponse(
            {
                "items": [
                    crossref_item(
                        "Punctuation-normalized journal article",
                        journal="Journal-of-the-American Statistical Association",
                    )
                ]
            }
        )

        with patch.object(self.searcher.session, "get", return_value=page):
            papers = self.searcher.search_issue(
                "Journal of the American Statistical Association", "113", "3"
            )

        self.assertEqual(
            [paper.title for paper in papers],
            ["Punctuation-normalized journal article"],
        )

    def test_search_issue_max_results_is_page_size_not_total_limit(self):
        pages = [
            MockCrossRefResponse(
                {
                    "items": [
                        crossref_item("First"),
                        crossref_item("Second"),
                    ],
                    "next-cursor": "cursor-1",
                }
            ),
            MockCrossRefResponse({"items": [crossref_item("Third")]}),
        ]

        papers, get = self._search_with_pages(pages, max_results=2)

        self.assertEqual([paper.title for paper in papers], ["First", "Second", "Third"])
        self.assertTrue(all(call.kwargs["params"]["rows"] == 2 for call in get.call_args_list))

    def test_search_issue_page_one_failure_raises_incomplete_discovery_error(self):
        with patch.object(
            self.searcher.session,
            "get",
            side_effect=requests.RequestException("page one failed"),
        ):
            with self.assertRaises(CrossRefIssueDiscoveryError) as context:
                self.searcher.search_issue("Biometrika", "113", "3")

        self.assertEqual(context.exception.partial_count, 0)
        self.assertTrue(context.exception.truncated)
        self.assertIn("page one failed", context.exception.reason)

    def test_search_issue_page_two_failure_raises_incomplete_discovery_error(self):
        pages = [
            MockCrossRefResponse(
                {
                    "items": [crossref_item("First")],
                    "next-cursor": "cursor-1",
                }
            ),
            requests.RequestException("page two failed"),
        ]

        with patch.object(self.searcher.session, "get", side_effect=pages):
            with self.assertRaises(CrossRefIssueDiscoveryError) as context:
                self.searcher.search_issue("Biometrika", "113", "3", max_results=1)

        self.assertEqual(context.exception.partial_count, 1)
        self.assertTrue(context.exception.truncated)
        self.assertIn("page two failed", context.exception.reason)

    def test_search_issue_repeated_cursor_raises_incomplete_discovery_error(self):
        pages = [
            MockCrossRefResponse(
                {
                    "items": [crossref_item("First")],
                    "next-cursor": "*",
                }
            )
        ]

        with patch.object(self.searcher.session, "get", side_effect=pages):
            with self.assertRaises(CrossRefIssueDiscoveryError) as context:
                self.searcher.search_issue("Biometrika", "113", "3", max_results=1)

        self.assertEqual(context.exception.partial_count, 1)
        self.assertTrue(context.exception.truncated)
        self.assertIn("repeated cursor", context.exception.reason)

    def test_search_issue_unparsable_exact_record_raises_incomplete_discovery_error(self):
        page = MockCrossRefResponse({"items": [crossref_item("Cannot parse")]})

        with patch.object(self.searcher.session, "get", return_value=page):
            with patch.object(self.searcher, "_parse_crossref_item", return_value=None):
                with self.assertRaises(CrossRefIssueDiscoveryError) as context:
                    self.searcher.search_issue("Biometrika", "113", "3")

        self.assertEqual(context.exception.partial_count, 0)
        self.assertTrue(context.exception.truncated)
        self.assertIn("could not be parsed", context.exception.reason)

if __name__ == '__main__':
    unittest.main()
