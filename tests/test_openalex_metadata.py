from unittest.mock import Mock
from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher


def test_preserves_journal_bibliography_and_normalizes_doi():
    s=OpenAlexSearcher()
    s.session.get=Mock(return_value=Mock(status_code=200,json=Mock(return_value={'results':[{
        'id':'https://openalex.org/W1','title':'A paper','doi':'HTTPS://DOI.ORG/10.1234/ABC',
        'publication_date':'2025-01-02','primary_location':{'source':{'display_name':'Example Journal','issn':['1234-5678']}},
        'biblio':{'volume':'9','issue':'2','first_page':'11','last_page':'20'}}]})))
    p=s.search('A paper')[0]
    assert p.extra.get('container_title')=='Example Journal'
    assert p.extra['volume']=='9' and p.extra['issue']=='2'
    assert p.doi=='10.1234/abc'
