from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from tests.support import (
    DeterministicEmbedding,
    FixedReranker,
    RecordingVectorStore,
    runtime_settings,
    sqlite_database,
)

from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.retrieval.models import SearchHit
from airesearcher_agent.retrieval.tools import (
    DocumentLookupArgs,
    KnowledgeBaseSearchArgs,
    RetrievalTools,
)


def _seed_paper(
    database: Database,
    *,
    paper_id: str,
    title: str,
    status: str,
    source_status: str = "AVAILABLE",
    chunks: list[tuple[str, int, str]],
) -> None:
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id=paper_id,
                sha256=(paper_id.removeprefix("paper-") * 64)[:64],
                title=title,
                authors=["Researcher Example"],
                publication_year=2026,
                original_filename=f"{paper_id}.pdf",
                storage_path=f"C:/external/{paper_id}.pdf",
                file_size_bytes=123,
                page_count=2,
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            LibraryFileRecord(
                id=f"library-file-{paper_id}",
                relative_path=f"seed/{paper_id}.pdf",
                path_key=(f"path-{paper_id}" * 64)[:64],
                file_name=f"{paper_id}.pdf",
                file_size_bytes=123,
                sha256=(paper_id.removeprefix("paper-") * 64)[:64],
                source_status=source_status,
                paper_id=paper_id,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )
        for ordinal, (chunk_id, page, quote) in enumerate(chunks):
            session.add(
                ChunkRecord(
                    id=chunk_id,
                    vector_id=str(uuid5(NAMESPACE_URL, f"{paper_id}:{ordinal}")),
                    paper_id=paper_id,
                    page=page,
                    ordinal=ordinal,
                    text=quote,
                    quote=quote,
                    created_at=now,
                )
            )


def test_knowledge_search_scopes_to_ready_papers_and_reranks_page_evidence(
    tmp_path: Path,
) -> None:
    database = sqlite_database()
    _seed_paper(
        database,
        paper_id="paper-ready",
        title="Grounded Retrieval",
        status="READY",
        chunks=[
            ("chunk-ready-1", 1, "Page one has lower reranker relevance."),
            ("chunk-ready-2", 2, "Page two contains the decisive 17 percent result."),
        ],
    )
    _seed_paper(
        database,
        paper_id="paper-processing",
        title="Not Yet Searchable",
        status="PROCESSING",
        chunks=[("chunk-processing", 1, "This must never become evidence.")],
    )
    vectors = RecordingVectorStore()
    vectors.search_hits = [
        SearchHit(chunk_id="chunk-ready-1", score=0.95),
        SearchHit(chunk_id="chunk-processing", score=0.99),
        SearchHit(chunk_id="chunk-ready-2", score=0.80),
    ]
    reranker = FixedReranker([0.1, 0.9])
    tools = RetrievalTools(
        database=database,
        embedding=DeterministicEmbedding(),
        reranker=reranker,
        vector_store=vectors,
        settings=runtime_settings(tmp_path),
    )

    evidence = tools.knowledge_base_search(
        KnowledgeBaseSearchArgs.model_validate(
            {
                "query": "What was the result?",
                "paperIds": ["paper-ready", "paper-processing"],
                "topK": 2,
            }
        ),
        citation_namespace="run-retrieval-test",
    )

    assert [item.chunk_id for item in evidence] == ["chunk-ready-2", "chunk-ready-1"]
    assert [item.page for item in evidence] == [2, 1]
    assert evidence[0].quote == "Page two contains the decisive 17 percent result."
    assert all(item.paper_id == "paper-ready" for item in evidence)
    assert all(item.citation_id.startswith("citation-") for item in evidence)
    assert vectors.search_scopes == [("paper-ready",)]
    assert vectors.search_limits == [20]
    assert reranker.calls[0][1] == [
        "Page one has lower reranker relevance.",
        "Page two contains the decisive 17 percent result.",
    ]


def test_document_lookup_returns_matching_metadata_without_vector_search(tmp_path: Path) -> None:
    database = sqlite_database()
    _seed_paper(
        database,
        paper_id="paper-metadata",
        title="Metadata Lookup Study",
        status="READY",
        chunks=[],
    )
    vectors = RecordingVectorStore()
    tools = RetrievalTools(
        database=database,
        embedding=DeterministicEmbedding(),
        reranker=FixedReranker([]),
        vector_store=vectors,
        settings=runtime_settings(tmp_path),
    )

    matches = tools.document_lookup(DocumentLookupArgs(query="Metadata"))

    assert [item.paper_id for item in matches] == ["paper-metadata"]
    assert matches[0].title == "Metadata Lookup Study"
    assert vectors.search_scopes == []


@pytest.mark.parametrize(
    ("paper_status", "source_status"),
    [
        ("READY", "MISSING"),
        ("READY", "REPLACED"),
        ("EXCLUDED", "AVAILABLE"),
    ],
)
def test_residual_vectors_never_bypass_paper_and_original_status_filters(
    tmp_path: Path,
    paper_status: str,
    source_status: str,
) -> None:
    database = sqlite_database()
    _seed_paper(
        database,
        paper_id="paper-hidden",
        title="Residual Vector Must Stay Hidden",
        status=paper_status,
        source_status=source_status,
        chunks=[("chunk-residual", 1, "This stale vector must not be returned.")],
    )
    vectors = RecordingVectorStore()
    vectors.search_hits = [SearchHit(chunk_id="chunk-residual", score=0.99)]
    tools = RetrievalTools(
        database=database,
        embedding=DeterministicEmbedding(),
        reranker=FixedReranker([1.0]),
        vector_store=vectors,
        settings=runtime_settings(tmp_path),
    )

    evidence = tools.knowledge_base_search(
        KnowledgeBaseSearchArgs.model_validate({"query": "residual", "paperIds": ["paper-hidden"]}),
        citation_namespace="hidden-paper",
    )
    matches = tools.document_lookup(DocumentLookupArgs(query="Residual"))

    assert evidence == []
    assert matches == []
    assert vectors.search_scopes == []
