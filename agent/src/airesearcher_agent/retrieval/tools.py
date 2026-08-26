from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import String, cast, or_, select
from sqlalchemy.sql.elements import ColumnElement

from airesearcher_agent.config import Settings
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import ChunkRecord, PaperRecord
from airesearcher_agent.persistence.repositories import chunks_by_ids, ready_paper_ids
from airesearcher_agent.retrieval.models import DocumentMatch, Evidence
from airesearcher_agent.retrieval.ports import EmbeddingProvider, Reranker, VectorStore

Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class KnowledgeBaseSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: Query
    paper_ids: list[Identifier] | None = Field(default=None, alias="paperIds", max_length=100)
    top_k: int = Field(default=5, alias="topK", ge=1, le=10)

    @field_validator("paper_ids")
    @classmethod
    def unique_paper_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("paperIds must contain unique items")
        return value


class DocumentLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Query


class RetrievalTools:
    def __init__(
        self,
        *,
        database: Database,
        embedding: EmbeddingProvider,
        reranker: Reranker,
        vector_store: VectorStore,
        settings: Settings,
    ) -> None:
        self._database = database
        self._embedding = embedding
        self._reranker = reranker
        self._vector_store = vector_store
        self._candidate_count = settings.retrieval_candidate_count
        self._default_top_k = settings.rerank_default_top_k

    def knowledge_base_search(
        self,
        arguments: KnowledgeBaseSearchArgs,
        *,
        citation_namespace: str,
    ) -> list[Evidence]:
        requested = tuple(arguments.paper_ids or ())
        with self._database.session() as session:
            allowed_ids = ready_paper_ids(session, requested)
        if not allowed_ids:
            return []

        query_vector = self._embedding.encode([arguments.query])[0]
        hits = self._vector_store.search(
            vector=query_vector,
            ready_paper_ids=allowed_ids,
            limit=self._candidate_count,
        )
        ordered_chunk_ids = tuple(hit.chunk_id for hit in hits)
        with self._database.session() as session:
            chunks = chunks_by_ids(session, ordered_chunk_ids)
            papers = {
                paper.id: paper
                for paper in session.scalars(
                    select(PaperRecord).where(PaperRecord.id.in_(allowed_ids))
                ).all()
            }

        candidates: list[tuple[ChunkRecord, PaperRecord, float]] = []
        for hit in hits:
            chunk = chunks.get(hit.chunk_id)
            if chunk is None or chunk.paper_id not in papers:
                continue
            candidates.append((chunk, papers[chunk.paper_id], hit.score))
        if not candidates:
            return []

        rerank_scores = self._reranker.score(
            arguments.query,
            [candidate[0].text for candidate in candidates],
        )
        if len(rerank_scores) != len(candidates):
            raise RuntimeError("reranker returned an unexpected score count")
        ranked = sorted(
            zip(candidates, rerank_scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        top_k = arguments.top_k or self._default_top_k
        evidence: list[Evidence] = []
        for (chunk, paper, retrieval_score), rerank_score in ranked[:top_k]:
            citation_id = f"citation-{uuid5(NAMESPACE_URL, f'{citation_namespace}:{chunk.id}').hex}"
            evidence.append(
                Evidence(
                    citation_id=citation_id,
                    paper_id=paper.id,
                    title=paper.title,
                    page=chunk.page,
                    quote=chunk.quote,
                    chunk_id=chunk.id,
                    retrieval_score=retrieval_score,
                    rerank_score=rerank_score,
                )
            )
        return evidence

    def document_lookup(self, arguments: DocumentLookupArgs) -> list[DocumentMatch]:
        term = arguments.query.strip()
        like = f"%{term}%"
        conditions: list[ColumnElement[bool]] = [
            PaperRecord.id.ilike(like),
            PaperRecord.title.ilike(like),
            cast(PaperRecord.authors, String).ilike(like),
        ]
        if term.isdigit() and len(term) == 4:
            conditions.append(PaperRecord.publication_year == int(term))
        with self._database.session() as session:
            papers = session.scalars(
                select(PaperRecord)
                .where(or_(*conditions))
                .order_by(PaperRecord.created_at.desc())
                .limit(10)
            ).all()
        return [
            DocumentMatch(
                paper_id=paper.id,
                title=paper.title,
                authors=tuple(paper.authors),
                publication_year=paper.publication_year,
                status=paper.status,
            )
            for paper in papers
        ]
