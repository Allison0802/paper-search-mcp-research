"""Shared domain logic for complete journal-issue retrieval.

The MCP tools own discovery and OA resolution.  This module deliberately owns
the deterministic, filesystem-facing portion: identity, ordering, naming,
concurrent batch execution, and manifests.  Keeping it independent from MCP
also makes those guarantees inexpensive to test without network access.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .paper import Paper


MANIFEST_COLUMNS = [
    "order",
    "title",
    "authors",
    "doi",
    "journal",
    "volume",
    "issue",
    "pages",
    "publication_date",
    "status",
    "source",
    "version_type",
    "journal_doi",
    "preprint_id",
    "version_date",
    "file_name",
    "file_path",
    "error",
]

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "http://dx.doi.org/",
)
_FORBIDDEN_COMPONENT_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")
_LEADING_PAGE = re.compile(r"^\s*(\d+)")
_E_PAGE = re.compile(r"^\s*e\s*(\d+)", re.IGNORECASE)
_FIRST_INTEGER = re.compile(r"(\d+)")


def normalize_doi(doi: Any) -> str:
    """Normalize resolver URLs and case for DOI identity comparisons."""
    normalized = str(doi or "").strip().casefold()
    for prefix in _DOI_PREFIXES:
        if normalized.startswith(prefix):
            return normalized[len(prefix):].strip()
    return normalized


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _paper_metadata_identity(paper: Paper) -> str:
    """Return the normalized title-and-author identity for a paper variant."""
    authors = "\x1f".join(_normalized_text(author) for author in paper.authors)
    return f"metadata:{_normalized_text(paper.title)}\x1f{authors}"


def dedupe_issue_papers(papers: Iterable[Paper]) -> List[Paper]:
    """Coalesce DOI-less variants without merging distinct DOI-bearing papers.

    A DOI is authoritative when present.  Metadata-only records can represent
    the same paper as a DOI-bearing Crossref variant, so a later DOI record
    replaces an earlier metadata-only record in the same issue position.
    Distinct DOI-bearing records remain separate even when their normalized
    title and authors happen to match.
    """
    output: List[Paper] = []
    seen_dois: set[str] = set()
    seen_metadata: set[str] = set()
    metadata_only_positions: dict[str, int] = {}
    for paper in papers:
        doi = normalize_doi(paper.doi)
        metadata = _paper_metadata_identity(paper)

        if doi:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
            metadata_only_position = metadata_only_positions.pop(metadata, None)
            if metadata_only_position is not None:
                output[metadata_only_position] = paper
            else:
                output.append(paper)
            seen_metadata.add(metadata)
            continue

        if metadata in seen_metadata:
            continue
        seen_metadata.add(metadata)
        metadata_only_positions[metadata] = len(output)
        output.append(paper)
    return output


def _paper_pages(paper: Paper) -> str:
    extra = paper.extra if isinstance(paper.extra, dict) else {}
    return str(extra.get("page", "") or "")


def _article_number(paper: Paper) -> str:
    extra = paper.extra if isinstance(paper.extra, dict) else {}
    return str(extra.get("article_number", "") or "")


def issue_sort_key(paper: Paper) -> tuple[int, int, str]:
    """Return stable issue order: ordinary pages, e/article numbers, then title."""
    title = _normalized_text(paper.title)
    pages = _paper_pages(paper)
    leading = _LEADING_PAGE.search(pages)
    if leading:
        return (0, int(leading.group(1)), title)

    e_page = _E_PAGE.search(pages)
    if e_page:
        return (1, int(e_page.group(1)), title)

    article_number = _article_number(paper)
    article_integer = _FIRST_INTEGER.search(article_number)
    if article_integer:
        return (1, int(article_integer.group(1)), title)

    return (2, 0, title)


def safe_component(value: Any, max_length: int = 80) -> str:
    """Produce a short, single filesystem component without traversal syntax."""
    if max_length < 1:
        raise ValueError("max_length must be at least 1")
    candidate = _WHITESPACE.sub("_", str(value or ""))
    candidate = _FORBIDDEN_COMPONENT_CHARS.sub("_", candidate).strip("._")
    if not candidate:
        return "unknown"
    return candidate[:max_length].rstrip("._") or "unknown"


def issue_directory(save_path: str | os.PathLike[str], journal: str, volume: str, issue: str) -> Path:
    """Create and return the canonical issue directory below ``save_path``."""
    directory = (
        Path(save_path).expanduser()
        / safe_component(journal, max_length=80)
        / safe_component(volume, max_length=40)
        / safe_component(issue, max_length=40)
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def issue_filename(paper: Paper, order: int, reserved: set[str] | None = None) -> str:
    """Return a bounded, readable PDF filename before collision suffixing."""
    author = "UnknownAuthor"
    if paper.authors:
        tokens = str(paper.authors[0]).split()
        if tokens:
            author = tokens[-1]
    author_component = safe_component(author, max_length=36)
    title_component = safe_component(paper.title, max_length=90)
    prefix = f"{order:03d}_{author_component}_"
    max_title_length = max(1, min(90, 140 - len(prefix) - len(".pdf")))
    title_component = safe_component(title_component, max_length=max_title_length)
    filename = f"{prefix}{title_component}.pdf"
    return _reserve_filename(filename, reserved) if reserved is not None else filename


def _reserve_filename(filename: str, reserved: set[str]) -> str:
    """Reserve one deterministic, collision-free filename in the issue plan."""
    candidate = filename
    number = 2
    stem, extension = os.path.splitext(filename)
    while candidate.casefold() in reserved:
        suffix = f"_{number}"
        max_stem = 140 - len(extension) - len(suffix)
        candidate = f"{stem[:max_stem]}{suffix}{extension}"
        number += 1
    reserved.add(candidate.casefold())
    return candidate


def looks_like_pdf(path: str | os.PathLike[str]) -> bool:
    """Perform a cheap PDF guard before treating a retrieved path as success."""
    try:
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        with candidate.open("rb") as stream:
            return stream.read(4) == b"%PDF"
    except OSError:
        return False


def _publication_date(paper: Paper) -> str:
    value = paper.published_date
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value or "")


def paper_to_manifest(
    paper: Paper,
    order: int,
    journal: str,
    volume: str,
    issue: str,
    *,
    status: str = "",
    source: str = "",
    version_type: str = "",
    journal_doi: str = "",
    preprint_id: str = "",
    version_date: str = "",
    file_name: str = "",
    file_path: str = "",
    error: str = "",
) -> Dict[str, Any]:
    """Serialize one issue paper in the exact stable manifest schema."""
    return {
        "order": order,
        "title": paper.title or "",
        "authors": "; ".join(str(author) for author in paper.authors),
        "doi": paper.doi or "",
        "journal": journal,
        "volume": volume,
        "issue": issue,
        "pages": _paper_pages(paper),
        "publication_date": _publication_date(paper),
        "status": status,
        "source": source,
        "version_type": version_type,
        "journal_doi": journal_doi,
        "preprint_id": preprint_id,
        "version_date": version_date,
        "file_name": file_name,
        "file_path": file_path,
        "error": error,
    }


def write_manifests(directory: str | os.PathLike[str], summary: Dict[str, Any]) -> tuple[str, str]:
    """Write both required manifests and return their absolute paths."""
    output_directory = Path(directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / "manifest.csv"
    json_path = output_directory / "manifest.json"
    papers = summary.get("papers", [])
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for paper in papers:
            writer.writerow({column: paper.get(column, "") for column in MANIFEST_COLUMNS})
    with json_path.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return str(csv_path), str(json_path)


def _summary(
    journal: str,
    volume: str,
    issue: str,
    directory: Path,
    papers: List[Dict[str, Any]],
    *,
    discovery_status: str = "complete",
    discovery_complete: bool = True,
    error: str = "",
) -> Dict[str, Any]:
    counts = {status: 0 for status in ("downloaded", "existing", "unavailable", "error")}
    for paper in papers:
        if paper.get("status") in counts:
            counts[paper["status"]] += 1
    summary: Dict[str, Any] = {
        "journal": journal,
        "volume": volume,
        "issue": issue,
        "discovery_status": discovery_status,
        "discovery_complete": discovery_complete,
        "total_articles": len(papers),
        "downloaded": counts["downloaded"],
        "existing": counts["existing"],
        "unavailable": counts["unavailable"],
        "errors": counts["error"],
        "directory": str(directory),
        "manifest_csv": str(directory / "manifest.csv"),
        "manifest_json": str(directory / "manifest.json"),
        "papers": papers,
    }
    if error:
        summary["error"] = error
    return summary


def discovery_error_summary(
    journal: str,
    volume: str,
    issue: str,
    save_path: str | os.PathLike[str],
    error: str,
) -> Dict[str, Any]:
    """Persist an explicit discovery failure instead of feigning an empty issue."""
    directory = issue_directory(save_path, journal, volume, issue)
    summary = _summary(
        journal,
        volume,
        issue,
        directory,
        [],
        discovery_status="error",
        discovery_complete=False,
        error=error,
    )
    write_manifests(directory, summary)
    return summary


Downloader = Callable[[Paper, Path], Awaitable[Mapping[str, Any]]]


async def download_issue_batch(
    papers: Iterable[Paper],
    journal: str,
    volume: str,
    issue: str,
    save_path: str | os.PathLike[str],
    downloader: Downloader,
    *,
    max_concurrency: int = 4,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Retrieve an issue concurrently while preserving one result per paper.

    ``downloader`` must return ``path``, ``retrieval_source``, and ``error``.
    It receives an isolated temporary directory and is never asked to choose a
    final filename; that prevents concurrent collisions and partial final files.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    directory = issue_directory(save_path, journal, volume, issue)
    ordered_papers = sorted(dedupe_issue_papers(papers), key=issue_sort_key)
    reserved: set[str] = set()
    plan: List[tuple[int, Paper, str, Path]] = []
    for order, paper in enumerate(ordered_papers, start=1):
        filename = issue_filename(paper, order, reserved)
        plan.append((order, paper, filename, directory / filename))

    results: Dict[int, Dict[str, Any]] = {}
    pending: List[tuple[int, Paper, str, Path]] = []
    for order, paper, filename, target in plan:
        if not overwrite and looks_like_pdf(target):
            results[order] = paper_to_manifest(
                paper,
                order,
                journal,
                volume,
                issue,
                status="existing",
                file_name=filename,
                file_path=str(target),
            )
        else:
            pending.append((order, paper, filename, target))

    incoming_root = directory / ".incoming"
    semaphore = asyncio.Semaphore(max_concurrency)

    async def retrieve(plan_item: tuple[int, Paper, str, Path]) -> None:
        order, paper, filename, target = plan_item
        temporary_directory = incoming_root / f"{order:03d}"
        candidate_path: Path | None = None
        try:
            temporary_directory.mkdir(parents=True, exist_ok=True)
            async with semaphore:
                outcome = await downloader(paper, temporary_directory)
            if not isinstance(outcome, Mapping):
                raise TypeError("issue downloader returned a non-structured outcome")
            raw_candidate = outcome.get("path")
            if raw_candidate:
                candidate_path = Path(str(raw_candidate))
            source = str(outcome.get("retrieval_source") or "")
            version_type = str(outcome.get("version_type") or "")
            journal_doi = str(outcome.get("journal_doi") or "")
            preprint_id = str(outcome.get("preprint_id") or "")
            version_date = str(outcome.get("version_date") or "")
            failure = str(outcome.get("error") or "")
            if candidate_path and looks_like_pdf(candidate_path):
                os.replace(candidate_path, target)
                results[order] = paper_to_manifest(
                    paper,
                    order,
                    journal,
                    volume,
                    issue,
                    status="downloaded",
                    source=source,
                    version_type=version_type,
                    journal_doi=journal_doi,
                    preprint_id=preprint_id,
                    version_date=version_date,
                    file_name=filename,
                    file_path=str(target),
                )
            else:
                if candidate_path:
                    failure = failure or "retrieval produced a file that is not a valid PDF"
                results[order] = paper_to_manifest(
                    paper,
                    order,
                    journal,
                    volume,
                    issue,
                    status="unavailable",
                    source=source,
                    file_name=filename,
                    error=failure or "No lawful open-access PDF was available",
                )
        except Exception as exc:
            results[order] = paper_to_manifest(
                paper,
                order,
                journal,
                volume,
                issue,
                status="error",
                file_name=filename,
                error=str(exc),
            )
        finally:
            if candidate_path and candidate_path != target:
                try:
                    if candidate_path.exists() and not looks_like_pdf(candidate_path):
                        candidate_path.unlink()
                except OSError:
                    pass
            shutil.rmtree(temporary_directory, ignore_errors=True)

    await asyncio.gather(*(retrieve(item) for item in pending))
    try:
        incoming_root.rmdir()
    except OSError:
        pass

    manifest_papers = [results[order] for order, _, _, _ in plan]
    summary = _summary(journal, volume, issue, directory, manifest_papers)
    write_manifests(directory, summary)
    return summary
