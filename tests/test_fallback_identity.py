import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from paper_search_mcp import server


def test_repository_fallback_rejects_wrong_paper(monkeypatch):
    wrong = SimpleNamespace(doi='10.1234/wrong',title='Unrelated paper',pdf_url='https://example.org/wrong.pdf',paper_id='wrong')
    for name in ('openaire_searcher','core_searcher','europepmc_searcher','pmc_searcher'):
        monkeypatch.setattr(getattr(server,name),'search',Mock(return_value=[wrong]))
    download = AsyncMock(return_value='/tmp/wrong.pdf')
    monkeypatch.setattr(server,'_download_from_url',download)
    result = asyncio.run(server._try_repository_fallback('10.1234/intended','Intended paper','/tmp'))
    assert result[0] is None
    download.assert_not_called()


def test_repository_fallback_accepts_normalized_doi(monkeypatch):
    paper = SimpleNamespace(doi='HTTPS://DOI.ORG/10.1234/RIGHT',title='A paper',pdf_url='https://example.org/right.pdf',paper_id=17)
    monkeypatch.setattr(server.openaire_searcher,'search',Mock(return_value=[paper]))
    monkeypatch.setattr(server,'_download_from_url',AsyncMock(return_value='/tmp/right.pdf'))
    assert asyncio.run(server._try_repository_fallback('10.1234/right','','/tmp'))[0] == '/tmp/right.pdf'
