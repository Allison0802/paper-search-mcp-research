# paper_search_mcp/academic_platforms/crossref.py
from typing import List, Optional, Dict, Any
from datetime import datetime
import requests
import time
import random
from ..paper import Paper
from ..journal_issue import dedupe_issue_papers
from ..provider_identity import contact_email, provider_user_agent
from .base import PaperSource
import logging

logger = logging.getLogger(__name__)


class CrossRefIssueDiscoveryError(RuntimeError):
    """Crossref could not finish a complete journal-issue discovery."""

    def __init__(self, reason: str, partial_count: int, truncated: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.partial_count = partial_count
        self.truncated = truncated


class CrossRefSearcher(PaperSource):
    """Searcher for CrossRef database papers"""
    
    BASE_URL = "https://api.crossref.org"
    
    # User agent for polite API usage as per CrossRef etiquette
    USER_AGENT = provider_user_agent()
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': provider_user_agent(),
            'Accept': 'application/json'
        })

    @staticmethod
    def _with_contact(params: Dict[str, Any]) -> Dict[str, Any]:
        email = contact_email()
        if email:
            params['mailto'] = email
        return params
    
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """
        Search CrossRef database for papers.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (default: 10)
            **kwargs: Additional parameters like filters, sort, etc.
            
        Returns:
            List of Paper objects
        """
        try:
            params = {
                'query': query,
                'rows': min(max_results, 1000),  # CrossRef API max is 1000
                'sort': 'relevance',
                'order': 'desc'
            }
            
            # Add any additional filters from kwargs
            if 'filter' in kwargs:
                params['filter'] = kwargs['filter']
            if 'sort' in kwargs:
                params['sort'] = kwargs['sort']
            if 'order' in kwargs:
                params['order'] = kwargs['order']
                
            # Only send a contact the local maintainer intentionally configured.
            self._with_contact(params)
            
            url = f"{self.BASE_URL}/works"
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 429:
                # Rate limited - wait and retry once
                logger.warning("Rate limited by CrossRef API, waiting 2 seconds...")
                time.sleep(2)
                response = self.session.get(url, params=params, timeout=30)
            
            response.raise_for_status()
            data = response.json()
            
            papers = []
            items = data.get('message', {}).get('items', [])
            
            for item in items:
                try:
                    paper = self._parse_crossref_item(item)
                    if paper:
                        papers.append(paper)
                except Exception as e:
                    logger.warning(f"Error parsing CrossRef item: {e}")
                    continue
                    
            return papers
            
        except requests.RequestException as e:
            logger.error(f"Error searching CrossRef: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in CrossRef search: {e}")
            return []

    @staticmethod
    def _normalize_journal_title(value: Any) -> str:
        """Normalize only harmless journal-title formatting differences."""
        if value is None:
            return ''
        normalized = ''.join(
            character if character.isalnum() or character.isspace() else ' '
            for character in str(value).casefold()
        )
        return ' '.join(normalized.split())

    def search_journal_year(self, journal: str, year: int, page_size: int = 200, volume: Optional[str] = None) -> List[Paper]:
        """Retrieve exact issue-year records, completely or with an explicit error.

        Print/issue dates take precedence over first-online dates. Query both
        date indexes because electronic-only records may lack print dates.
        """
        from datetime import date
        from ..journal_issue import normalize_doi
        today = date.today()
        year = int(year)
        if year < 1000 or year > today.year:
            raise ValueError('Journal year must be a past or current calendar year')
        journal = self._canonical_requested_journal(journal)
        normalized = self._normalize_journal_title(journal)
        end = min(date(year, 12, 31), today).isoformat()
        rows = min(1000, max(1, page_size))
        papers = {}
        for date_index in ((None,) if volume is not None else ('print-pub-date', 'pub-date')):
            cursor = '*'
            seen_pages = set()
            while True:
                date_filter = f',from-{date_index}:{year}-01-01,until-{date_index}:{end}' if date_index else ''
                params = {'filter': f'container-title:{journal},type:journal-article{date_filter}',
                          'rows': rows, 'cursor': cursor}
                response = self.session.get(f'{self.BASE_URL}/works', params=params, timeout=30)
                response.raise_for_status()
                message = response.json()['message']
                items = message['items']
                if not isinstance(items, list):
                    raise RuntimeError('Invalid Crossref items')
                signature = tuple(str(i.get('DOI')) for i in items)
                if items and signature in seen_pages:
                    raise RuntimeError('Crossref repeated a page; coverage incomplete')
                seen_pages.add(signature)
                for item in items:
                    if self._normalize_journal_title(self._extract_container_title(item)) != normalized:
                        continue
                    if volume is not None and self._normalize_issue_value(item.get('volume')) != self._normalize_issue_value(volume):
                        continue
                    issue_date = self._extract_date(item.get('journal-issue', {}), 'published-print')
                    selected = issue_date or self._extract_date(item, 'published-print') or self._extract_date(item, 'published') or self._extract_date(item, 'issued')
                    if not selected or (volume is None and selected.year != year) or selected.date() > today:
                        continue
                    paper = self._parse_crossref_item(item)
                    if paper is None:
                        raise RuntimeError('Could not parse exact journal-year record')
                    paper.doi = normalize_doi(paper.doi)
                    paper.paper_id = paper.doi
                    paper.published_date = selected
                    paper.extra['publication_dates'] = {k: item[k].get('date-parts') for k in ('published', 'published-print', 'published-online', 'issued') if k in item}
                    paper.extra['date_basis'] = 'issue/print' if issue_date or item.get('published-print') else 'published/issued (no print date)'
                    paper.extra['selection_year'] = year
                    paper.extra['year_basis'] = 'caller-validated journal volume' if volume is not None else 'Crossref issue/print or publication date'
                    papers.setdefault(paper.doi or paper.title.casefold(), paper)
                if len(items) < rows:
                    break
                cursor = message.get('next-cursor')
                if not cursor:
                    raise RuntimeError('Crossref full page without cursor; coverage incomplete')
        return sorted(papers.values(), key=lambda p: (p.published_date, p.doi))

    @classmethod
    def _canonical_requested_journal(cls, journal: str) -> str:
        """Resolve the small, explicit set of accepted query aliases."""
        normalized = cls._normalize_journal_title(journal)
        aliases = {
            'jasa': 'Journal of the American Statistical Association',
        }
        if normalized in aliases:
            return aliases[normalized]
        return ' '.join(str(journal).strip().split())

    @staticmethod
    def _normalize_issue_value(value: Any) -> str:
        """Normalize Crossref volume and issue fields without fuzzy matching."""
        if value is None:
            return ''
        return str(value).strip().casefold()

    def _is_exact_issue_item(
        self,
        item: Dict[str, Any],
        journal: str,
        volume: str,
        issue: str,
    ) -> bool:
        """Check candidate metadata locally before parsing it into a Paper."""
        return (
            self._normalize_journal_title(self._extract_container_title(item)) == journal
            and self._normalize_issue_value(item.get('volume', '')) == volume
            and self._normalize_issue_value(item.get('issue', '')) == issue
        )

    def search_issue(
        self, journal: str, volume: str, issue: str, max_results: int = 1000
    ) -> List[Paper]:
        """Discover every uniquely identified Crossref article in one exact issue.

        ``max_results`` is the Crossref page size, not a cap on the total number
        of records. Cursor pagination is required to finish every full page, so
        an upstream failure cannot be mistaken for a complete issue.
        """
        canonical_journal = self._canonical_requested_journal(journal)
        normalized_journal = self._normalize_journal_title(canonical_journal)
        canonical_volume = self._normalize_issue_value(volume)
        canonical_issue = self._normalize_issue_value(issue)
        rows = min(1000, max(1, max_results))
        cursor = '*'
        seen_cursors = {cursor}
        papers: List[Paper] = []

        while True:
            params = self._with_contact({
                'filter': f'container-title:{canonical_journal},type:journal-article',
                'rows': rows,
                'cursor': cursor,
            })
            try:
                response = self.session.get(
                    f'{self.BASE_URL}/works', params=params, timeout=30
                )
                response.raise_for_status()
                data = response.json()
                message = data.get('message')
                if not isinstance(message, dict):
                    raise ValueError('Crossref response has no message object')
                items = message.get('items')
                if not isinstance(items, list):
                    raise ValueError('Crossref response has no items list')
            except Exception as exc:
                raise CrossRefIssueDiscoveryError(
                    f'Crossref issue discovery request failed: {exc}',
                    partial_count=len(papers),
                ) from exc

            for item in items:
                if not isinstance(item, dict) or not self._is_exact_issue_item(
                    item, normalized_journal, canonical_volume, canonical_issue
                ):
                    continue
                try:
                    paper = self._parse_crossref_item(item)
                except Exception as exc:
                    raise CrossRefIssueDiscoveryError(
                        f'Exact Crossref issue record could not be parsed: {exc}',
                        partial_count=len(papers),
                    ) from exc
                if paper is None:
                    raise CrossRefIssueDiscoveryError(
                        'Exact Crossref issue record could not be parsed',
                        partial_count=len(papers),
                    )
                papers.append(paper)

            if len(items) < rows:
                return dedupe_issue_papers(papers)

            next_cursor = message.get('next-cursor')
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                raise CrossRefIssueDiscoveryError(
                    'Crossref returned a full page without a next cursor',
                    partial_count=len(papers),
                )
            next_cursor = next_cursor.strip()
            if next_cursor in seen_cursors:
                raise CrossRefIssueDiscoveryError(
                    'Crossref returned a repeated cursor after a full page',
                    partial_count=len(papers),
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
    
    def _parse_crossref_item(self, item: Dict[str, Any]) -> Optional[Paper]:
        """Parse a CrossRef API item into a Paper object."""
        try:
            # Extract basic information
            doi = item.get('DOI', '')
            title = self._extract_title(item)
            authors = self._extract_authors(item)
            abstract = item.get('abstract', '')
            
            # Extract publication date
            published_date = self._extract_date(item, 'published')
            if not published_date:
                published_date = self._extract_date(item, 'issued')
            if not published_date:
                published_date = self._extract_date(item, 'created')
            
            # Default to epoch if no date found
            if not published_date:
                published_date = datetime(1970, 1, 1)
            
            # Extract URLs
            url = item.get('URL', f"https://doi.org/{doi}" if doi else '')
            pdf_url = self._extract_pdf_url(item)
            
            # Extract additional metadata
            container_title = self._extract_container_title(item)
            publisher = item.get('publisher', '')
            categories = [item.get('type', '')]
            
            # Extract subjects/keywords if available
            subjects = item.get('subject', [])
            if isinstance(subjects, list):
                keywords = subjects
            else:
                keywords = []
            
            citations = item.get('is-referenced-by-count')
            if not isinstance(citations, int):
                citations = 0

            return Paper(
                paper_id=doi,
                title=title,
                authors=authors,
                abstract=abstract,
                doi=doi,
                published_date=published_date,
                pdf_url=pdf_url,
                url=url,
                source='crossref',
                categories=categories,
                keywords=keywords,
                citations=citations,
                extra={
                    'publisher': publisher,
                    'container_title': container_title,
                    'volume': item.get('volume', ''),
                    'issue': item.get('issue', ''),
                    'page': item.get('page', ''),
                    'article_number': item.get('article-number', ''),
                    'issn': item.get('ISSN', []),
                    'isbn': item.get('ISBN', []),
                    'crossref_type': item.get('type', ''),
                    'member': item.get('member', ''),
                    'prefix': item.get('prefix', '')
                }
            )
            
        except Exception as e:
            logger.error(f"Error parsing CrossRef item: {e}")
            return None
    
    def _extract_title(self, item: Dict[str, Any]) -> str:
        """Extract title from CrossRef item."""
        titles = item.get('title', [])
        if isinstance(titles, list) and titles:
            return titles[0]
        return str(titles) if titles else ''
    
    def _extract_authors(self, item: Dict[str, Any]) -> List[str]:
        """Extract author names from CrossRef item."""
        authors = []
        author_list = item.get('author', [])
        
        for author in author_list:
            if isinstance(author, dict):
                given = author.get('given', '')
                family = author.get('family', '')
                if given and family:
                    authors.append(f"{given} {family}")
                elif family:
                    authors.append(family)
                elif given:
                    authors.append(given)
                    
        return authors
    
    def _extract_date(self, item: Dict[str, Any], date_field: str) -> Optional[datetime]:
        """Extract date from CrossRef item."""
        date_info = item.get(date_field, {})
        if not date_info:
            return None
            
        date_parts = date_info.get('date-parts', [])
        if not date_parts or not date_parts[0]:
            return None
            
        parts = date_parts[0]
        try:
            year = parts[0] if len(parts) > 0 and parts[0] is not None else 1970
            month = parts[1] if len(parts) > 1 and parts[1] is not None else 1
            day = parts[2] if len(parts) > 2 and parts[2] is not None else 1
            return datetime(year, month, day)
        except (TypeError, ValueError, IndexError):
            return None
    
    def _extract_container_title(self, item: Dict[str, Any]) -> str:
        """Extract container title (journal/book title) from CrossRef item."""
        container_titles = item.get('container-title', [])
        if isinstance(container_titles, list) and container_titles:
            return container_titles[0]
        return str(container_titles) if container_titles else ''
    
    def _extract_pdf_url(self, item: Dict[str, Any]) -> str:
        """Extract PDF URL from CrossRef item."""
        # Check for link in the resource field
        resource = item.get('resource', {})
        if resource:
            primary = resource.get('primary', {})
            if primary and primary.get('URL', '').endswith('.pdf'):
                return primary['URL']
        
        # Check in links array
        links = item.get('link', [])
        for link in links:
            if isinstance(link, dict):
                content_type = link.get('content-type', '')
                if 'pdf' in content_type.lower():
                    return link.get('URL', '')
                    
        return ''
    
    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """
        CrossRef doesn't provide direct PDF downloads.
        
        Args:
            paper_id: DOI of the paper
            save_path: Directory to save the PDF
            
        Raises:
            NotImplementedError: Always raises this error as CrossRef doesn't provide direct PDF access
        """
        message = ("CrossRef does not provide direct PDF downloads. "
                  "CrossRef is a citation database that provides metadata about academic papers. "
                  "To access the full text, please use the paper's DOI or URL to visit the publisher's website.")
        raise NotImplementedError(message)
    
    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """
        CrossRef doesn't provide direct paper content access.
        
        Args:
            paper_id: DOI of the paper
            save_path: Directory for potential PDF storage (unused)
            
        Returns:
            str: Error message indicating PDF reading is not supported
        """
        message = ("CrossRef papers cannot be read directly through this tool. "
                  "CrossRef is a citation database that provides metadata about academic papers. "
                  "Only metadata and abstracts are available through CrossRef's API. "
                  "To access the full text, please use the paper's DOI or URL to visit the publisher's website.")
        return message

    def get_paper_by_doi(self, doi: str) -> Optional[Paper]:
        """
        Get a specific paper by DOI.
        
        Args:
            doi: Digital Object Identifier
            
        Returns:
            Paper object if found, None otherwise
        """
        try:
            url = f"{self.BASE_URL}/works/{doi}"
            params = self._with_contact({})
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 404:
                logger.warning(f"DOI not found in CrossRef: {doi}")
                return None
                
            response.raise_for_status()
            data = response.json()
            
            item = data.get('message', {})
            return self._parse_crossref_item(item)
            
        except requests.RequestException as e:
            logger.error(f"Error fetching DOI {doi} from CrossRef: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching DOI {doi}: {e}")
            return None

if __name__ == "__main__":
    # Test CrossRefSearcher functionality
    # 测试CrossRefSearcher功能
    searcher = CrossRefSearcher()
    
    # Test search functionality
    # 测试搜索功能
    print("Testing search functionality...")
    query = "machine learning"
    max_results = 5
    papers = []
    try:
        papers = searcher.search(query, max_results=max_results)
        print(f"Found {len(papers)} papers for query '{query}':")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title} (DOI: {paper.doi})")
            print(f"   Authors: {', '.join(paper.authors[:3])}{'...' if len(paper.authors) > 3 else ''}")
            print(f"   Published: {paper.published_date.year}")
            print(f"   Citations: {paper.citations}")
            publisher = paper.extra.get('publisher', 'N/A') if paper.extra else 'N/A'
            print(f"   Publisher: {publisher}")
            print()
    except Exception as e:
        print(f"Error during search: {e}")
    
    # Test DOI lookup functionality
    # 测试DOI查找功能
    if papers:
        print("Testing DOI lookup functionality...")
        test_doi = papers[0].doi
        try:
            paper = searcher.get_paper_by_doi(test_doi)
            if paper:
                print(f"Successfully retrieved paper by DOI: {paper.title}")
            else:
                print("Failed to retrieve paper by DOI")
        except Exception as e:
            print(f"Error during DOI lookup: {e}")
    
    # Test PDF download functionality (will return unsupported message)
    # 测试PDF下载功能（会返回不支持的提示）
    if papers:
        print("\nTesting PDF download functionality...")
        paper_id = papers[0].doi
        try:
            pdf_path = searcher.download_pdf(paper_id, "./downloads")
        except NotImplementedError as e:
            print(f"Expected error: {e}")
    
    # Test paper reading functionality (will return unsupported message)
    # 测试论文阅读功能（会返回不支持的提示）
    if papers:
        print("\nTesting paper reading functionality...")
        paper_id = papers[0].doi
        message = searcher.read_paper(paper_id)
        print(f"Message: {message}")
