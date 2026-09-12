import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

import jieba  # type: ignore[import-untyped]
from sqlalchemy import select

from airesearcher_agent.domain.papers import IngestionJobStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import ChunkRecord, IngestionJobRecord, PaperRecord
from airesearcher_agent.retrieval.models import KeywordDocument, SearchHit

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[\u3400-\u4dbf\u4e00-\u9fff]+")
BM25_K1 = 1.5
BM25_B = 0.75


@dataclass(frozen=True, slots=True)
class _Posting:
    chunk_id: str
    term_frequency: int
    document_length: int


@dataclass(frozen=True, slots=True)
class _PaperIndex:
    version: str
    document_count: int
    total_document_length: int
    document_frequencies: Counter[str]
    postings: dict[str, tuple[_Posting, ...]]


class Bm25Index:
    """Immutable BM25 index used by tests and by the per-paper runtime cache."""

    def __init__(self, documents: list[KeywordDocument]) -> None:
        self._index = _build_index(version="standalone", documents=documents)

    def search(self, *, query: str, limit: int) -> list[SearchHit]:
        return _search_indexes(query=query, indexes=(self._index,), limit=limit)


class Bm25KeywordRetriever:
    """Cache immutable per-paper indexes and refresh them after successful ingestion."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._indexes: dict[str, _PaperIndex] = {}
        self._lock = RLock()

    def search(
        self,
        *,
        query: str,
        paper_ids: tuple[str, ...],
        limit: int,
    ) -> list[SearchHit]:
        if not paper_ids or limit < 1:
            return []
        versions = self._paper_versions(paper_ids)
        with self._lock:
            previous_versions = {
                paper_id: cached.version if (cached := self._indexes.get(paper_id)) else None
                for paper_id in versions
            }
            stale_ids = tuple(
                paper_id
                for paper_id, version in versions.items()
                if (cached := self._indexes.get(paper_id)) is None or cached.version != version
            )
        if stale_ids:
            refreshed = self._load_indexes(stale_ids, versions)
            with self._lock:
                for paper_id, index in refreshed.items():
                    current = self._indexes.get(paper_id)
                    current_version = current.version if current else None
                    if current_version == previous_versions[paper_id]:
                        self._indexes[paper_id] = index
        with self._lock:
            selected = tuple(
                self._indexes[paper_id]
                for paper_id in paper_ids
                if paper_id in versions and paper_id in self._indexes
            )
        return _search_indexes(query=query, indexes=selected, limit=limit)

    def _paper_versions(self, paper_ids: tuple[str, ...]) -> dict[str, str]:
        latest_successful_job = (
            select(IngestionJobRecord.id)
            .where(
                IngestionJobRecord.paper_id == PaperRecord.id,
                IngestionJobRecord.status == IngestionJobStatus.SUCCEEDED.value,
            )
            .order_by(IngestionJobRecord.created_at.desc(), IngestionJobRecord.id.desc())
            .limit(1)
            .correlate(PaperRecord)
            .scalar_subquery()
        )
        with self._database.session() as session:
            rows = session.execute(
                select(PaperRecord.id, PaperRecord.updated_at, latest_successful_job).where(
                    PaperRecord.id.in_(paper_ids)
                )
            ).all()
        return {
            paper_id: successful_job_id or f"legacy:{_timestamp_key(updated_at)}"
            for paper_id, updated_at, successful_job_id in rows
        }

    def _load_indexes(
        self,
        paper_ids: tuple[str, ...],
        versions: dict[str, str],
    ) -> dict[str, _PaperIndex]:
        with self._database.session() as session:
            rows = session.execute(
                select(ChunkRecord.paper_id, ChunkRecord.id, ChunkRecord.text)
                .where(ChunkRecord.paper_id.in_(paper_ids))
                .order_by(ChunkRecord.paper_id, ChunkRecord.page, ChunkRecord.ordinal)
            ).all()
        documents_by_paper: dict[str, list[KeywordDocument]] = defaultdict(list)
        for paper_id, chunk_id, text in rows:
            documents_by_paper[paper_id].append(KeywordDocument(chunk_id=chunk_id, text=text))
        return {
            paper_id: _build_index(
                version=versions[paper_id],
                documents=documents_by_paper[paper_id],
            )
            for paper_id in paper_ids
        }


def _build_index(*, version: str, documents: list[KeywordDocument]) -> _PaperIndex:
    document_frequencies: Counter[str] = Counter()
    postings: dict[str, list[_Posting]] = defaultdict(list)
    total_document_length = 0
    for document in documents:
        frequencies = Counter(_tokens(document.text))
        document_length = frequencies.total()
        total_document_length += document_length
        document_frequencies.update(frequencies.keys())
        for term, frequency in frequencies.items():
            postings[term].append(
                _Posting(
                    chunk_id=document.chunk_id,
                    term_frequency=frequency,
                    document_length=document_length,
                )
            )
    return _PaperIndex(
        version=version,
        document_count=len(documents),
        total_document_length=total_document_length,
        document_frequencies=document_frequencies,
        postings={term: tuple(values) for term, values in postings.items()},
    )


def _search_indexes(
    *,
    query: str,
    indexes: tuple[_PaperIndex, ...],
    limit: int,
) -> list[SearchHit]:
    if not indexes or limit < 1:
        return []
    query_frequencies = Counter(_tokens(query))
    if not query_frequencies:
        return []
    document_count = sum(index.document_count for index in indexes)
    if document_count == 0:
        return []
    average_document_length = sum(index.total_document_length for index in indexes) / document_count
    scores: dict[str, float] = defaultdict(float)
    for term, query_frequency in query_frequencies.items():
        document_frequency = sum(index.document_frequencies[term] for index in indexes)
        if document_frequency == 0:
            continue
        inverse_document_frequency = math.log1p(
            (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        for index in indexes:
            for posting in index.postings.get(term, ()):
                length_normalization = BM25_K1 * (
                    1 - BM25_B + BM25_B * posting.document_length / average_document_length
                )
                scores[posting.chunk_id] += (
                    query_frequency
                    * inverse_document_frequency
                    * posting.term_frequency
                    * (BM25_K1 + 1)
                    / (posting.term_frequency + length_normalization)
                )
    return [
        SearchHit(chunk_id=chunk_id, score=score)
        for chunk_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        value = match.group(0)
        if value.isascii():
            tokens.append(value.casefold())
        else:
            tokens.extend(
                part.strip().casefold() for part in jieba.cut(value, cut_all=False) if part.strip()
            )
    return tokens


def _timestamp_key(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")
