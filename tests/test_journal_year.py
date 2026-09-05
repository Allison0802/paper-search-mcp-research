from unittest.mock import Mock
import pytest
from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher


def item(doi='10.1234/A', journal='Example Journal', year=2025):
    return {'DOI': doi, 'title': ['A paper'], 'container-title': [journal],
            'type': 'journal-article', 'volume': '9', 'issue': '1',
            'published': {'date-parts': [[2024, 6, 1]]},
            'published-print': {'date-parts': [[year, 2, 1]]}}


def test_issue_year_exact_identity_pagination_and_doi():
    s = CrossRefSearcher()
    pages = [
        {'items': [item(), item('10.1234/wrong', 'Other Journal')], 'next-cursor': 'next'},
        {'items': [item('https://doi.org/10.1234/a'), item('10.1234/B')], 'next-cursor': 'last'},
        {'items': []},
        {'items': []},
    ]
    s.session.get = Mock(side_effect=[Mock(status_code=200, json=Mock(return_value={'message': p})) for p in pages])
    assert hasattr(s, 'search_journal_year'), 'No exact journal-year retrieval exists'
    papers = s.search_journal_year('Example Journal', 2025, page_size=2)
    assert [p.doi for p in papers] == ['10.1234/a', '10.1234/b']
    assert all(p.published_date.year == 2025 for p in papers)
    assert papers[0].extra['publication_dates']['published'] == [[2024, 6, 1]]
    assert s.session.get.call_count == 4


def test_unified_journal_query_routes_explicitly(monkeypatch):
    import asyncio
    from paper_search_mcp import server
    s = CrossRefSearcher()
    paper = s._parse_crossref_item(item())
    search = Mock(return_value=[paper])
    monkeypatch.setattr(server.crossref_searcher, 'search_journal_year', search, raising=False)
    result = asyncio.run(server.search_papers('journal:"Example Journal"', year='2025', sources='crossref'))
    assert search.called, 'Unified search ignores exact journal intent'
    assert result['coverage']['crossref']['complete'] is True


def test_future_print_issue_is_not_ytd():
    s = CrossRefSearcher()
    s.session.get = Mock(return_value=Mock(status_code=200, json=Mock(return_value={'message': {'items': [item(year=2099)]}})))
    assert hasattr(s, 'search_journal_year'), 'No YTD-aware journal retrieval exists'
    with pytest.raises(ValueError):
        s.search_journal_year('Example Journal', 2099)


def test_full_page_without_cursor_is_error():
    s = CrossRefSearcher()
    s.session.get = Mock(return_value=Mock(status_code=200, json=Mock(return_value={'message': {'items': [item()]}})))
    assert hasattr(s, 'search_journal_year'), 'No complete-or-error journal retrieval exists'
    with pytest.raises(RuntimeError):
        s.search_journal_year('Example Journal', 2025, page_size=1)


def test_publisher_validated_volume_keeps_conflicting_dates():
    s=CrossRefSearcher()
    record=item(year=2024)
    s.session.get=Mock(return_value=Mock(status_code=200,json=Mock(return_value={'message':{'items':[record,item('10.1234/other',year=2024)|{'volume':'10'}]}})))
    import inspect
    assert 'volume' in inspect.signature(s.search_journal_year).parameters, 'No explicit volume-year reconciliation exists'
    papers=s.search_journal_year('Example Journal',2025,volume='9')
    assert len(papers)==1
    assert papers[0].published_date.year==2024  # Never manufacture a publisher date.
    assert papers[0].extra['selection_year']==2025
    assert papers[0].extra['year_basis']=='caller-validated journal volume'


def test_unified_volume_query(monkeypatch):
    import asyncio
    from paper_search_mcp import server
    search=Mock(return_value=[])
    monkeypatch.setattr(server.crossref_searcher,'search_journal_year',search)
    asyncio.run(server.search_papers('journal:"Example Journal" volume:"9"',year='2025',sources='crossref'))
    search.assert_called_once_with('Example Journal',2025,volume='9')
