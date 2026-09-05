import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from paper_search_mcp import server
from paper_search_mcp.academic_platforms.acm import ACMSearcher
from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
from paper_search_mcp.academic_platforms.ieee import IEEESearcher
from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher


def test_provider_user_agents_identify_this_fork_without_false_contact(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_MCP_CONTACT_EMAIL", raising=False)

    user_agents = [
        ArxivSearcher().session.headers["User-Agent"],
        CrossRefSearcher().session.headers["User-Agent"],
        OpenAlexSearcher().session.headers["User-Agent"],
    ]

    for user_agent in user_agents:
        assert "paper-search-mcp-research" in user_agent
        assert "https://github.com/Allison0802/paper-search-mcp-research" in user_agent
        assert "openags" not in user_agent.casefold()
        assert "dragonatorul" not in user_agent.casefold()
        assert "mailto:" not in user_agent.casefold()


def test_crossref_uses_configured_contact_email_without_impersonating_upstream(monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_MCP_CONTACT_EMAIL", "maintainer@example.org")
    searcher = CrossRefSearcher()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"message": {"items": []}}
    response.raise_for_status.return_value = None
    searcher.session.get = Mock(return_value=response)

    assert searcher.search("reproducible literature", max_results=1) == []

    _, kwargs = searcher.session.get.call_args
    assert kwargs["params"]["mailto"] == "maintainer@example.org"
    assert "mailto:maintainer@example.org" in searcher.session.headers["User-Agent"]
    assert "paper-search-mcp-research" in searcher.session.headers["User-Agent"]


@pytest.mark.parametrize(
    ("searcher_class", "environment_name"),
    [
        (ACMSearcher, "PAPER_SEARCH_MCP_ACM_API_KEY"),
        (IEEESearcher, "PAPER_SEARCH_MCP_IEEE_API_KEY"),
    ],
)
def test_optional_connector_messages_identify_this_fork(
    monkeypatch, searcher_class, environment_name
):
    monkeypatch.setenv(environment_name, "configured-for-test")

    with pytest.raises(NotImplementedError) as error:
        searcher_class().search("reproducible literature")

    assert "https://github.com/Allison0802/paper-search-mcp-research" in str(error.value)
    assert "your-repo" not in str(error.value)


def test_public_mcp_tools_do_not_register_scihub():
    assert "download_scihub" not in server.mcp._tool_manager._tools


def test_scihub_fallback_is_disabled_without_explicit_environment_gate(monkeypatch):
    monkeypatch.delenv("PAPER_SEARCH_MCP_ENABLE_SCIHUB", raising=False)
    with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), patch(
        "paper_search_mcp.server._try_repository_fallback",
        new=AsyncMock(return_value=(None, "repository failed")),
    ), patch.object(
        server.unpaywall_resolver,
        "resolve_ranked_pdf_candidates",
        return_value=[],
    ), patch.object(
        server.unpaywall_resolver,
        "resolve_best_pdf_url",
        return_value=None,
    ), patch(
        "paper_search_mcp.server.SciHubFetcher.download_pdf",
        return_value=None,
    ) as download_scihub:
        result = asyncio.run(
            server.download_with_fallback(
                source="arxiv",
                paper_id="1234.5678",
                doi="10.1000/test",
                title="Test paper",
                use_scihub=True,
            )
        )

    download_scihub.assert_not_called()
    assert "scihub:" not in result.casefold()


def test_scihub_local_compatibility_requires_the_explicit_environment_gate(monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_MCP_ENABLE_SCIHUB", "1")
    with patch.object(server.arxiv_searcher, "download_pdf", side_effect=Exception("primary failed")), patch(
        "paper_search_mcp.server._try_repository_fallback",
        new=AsyncMock(return_value=(None, "repository failed")),
    ), patch.object(
        server.unpaywall_resolver,
        "resolve_ranked_pdf_candidates",
        return_value=[],
    ), patch.object(
        server.unpaywall_resolver,
        "resolve_best_pdf_url",
        return_value=None,
    ), patch(
        "paper_search_mcp.server.SciHubFetcher.download_pdf",
        return_value=None,
    ) as download_scihub:
        asyncio.run(
            server.download_with_fallback(
                source="arxiv",
                paper_id="1234.5678",
                doi="10.1000/test",
                title="Test paper",
                use_scihub=True,
            )
        )

    download_scihub.assert_called_once_with("10.1000/test")
