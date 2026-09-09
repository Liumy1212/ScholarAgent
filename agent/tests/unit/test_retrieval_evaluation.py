from pathlib import Path

from tests.support import sqlite_database

from airesearcher_agent.evaluation.retrieval import (
    RetrievalCase,
    RetrievalDataset,
    RetrievalEvaluator,
    load_dataset,
)
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import LibraryFileRecord, PaperRecord, utc_now
from airesearcher_agent.retrieval.models import RankedChunk
from airesearcher_agent.retrieval.tools import RetrievalMode


class FixedChunkRanker:
    def rank_chunks(
        self,
        *,
        query: str,
        paper_ids: tuple[str, ...],
        mode: RetrievalMode,
    ) -> list[RankedChunk]:
        paper_id = paper_ids[0]
        if mode == "dense" and query == "second question":
            return []
        relevant_page = 1 if query == "first question" else 2
        relevant = _ranked(paper_id, relevant_page, f"chunk-relevant-{relevant_page}")
        if mode == "dense":
            return [_ranked(paper_id, 2, "chunk-distractor"), relevant]
        return [relevant]


def _ranked(paper_id: str, page: int, chunk_id: str) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        title="Synthetic Evaluation Paper",
        page=page,
        quote=f"Synthetic evidence on page {page}.",
        retrieval_score=0.5,
        rerank_score=0.5,
    )


def _seed_ready_paper() -> Database:
    database = sqlite_database()
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id="paper-evaluation",
                sha256="e" * 64,
                title="Synthetic Evaluation Paper",
                authors=["Synthetic Author"],
                publication_year=2026,
                original_filename="evaluation.pdf",
                storage_path="C:/external/evaluation.pdf",
                file_size_bytes=100,
                page_count=2,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            LibraryFileRecord(
                id="library-file-evaluation",
                relative_path="evaluation.pdf",
                path_key="p" * 64,
                file_name="evaluation.pdf",
                file_size_bytes=100,
                sha256="e" * 64,
                source_status="AVAILABLE",
                paper_id="paper-evaluation",
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )
    return database


def test_retrieval_evaluator_compares_recall_mrr_and_traceability() -> None:
    dataset = RetrievalDataset(
        name="synthetic-comparison",
        cases=[
            RetrievalCase(
                case_id="case-1",
                category="term",
                paper_title="Synthetic Evaluation Paper",
                query="first question",
                relevant_pages=[1],
            ),
            RetrievalCase(
                case_id="case-2",
                category="context",
                paper_title="Synthetic Evaluation Paper",
                query="second question",
                relevant_pages=[2],
            ),
        ],
    )

    report = RetrievalEvaluator(
        database=_seed_ready_paper(),
        ranker=FixedChunkRanker(),
    ).compare(dataset)

    assert report.dense.recall_at_20 == 0.5
    assert report.hybrid.recall_at_20 == 1.0
    assert report.dense.mrr == 0.25
    assert report.hybrid.mrr == 1.0
    assert report.recall_delta == 0.5
    assert report.mrr_delta == 0.75
    assert report.dense.traceable_result_rate == 1.0
    assert report.hybrid.traceable_result_rate == 1.0


def test_committed_retrieval_dataset_is_valid() -> None:
    dataset_path = Path(__file__).resolve().parents[2] / "evals" / "retrieval_cases.json"
    dataset = load_dataset(dataset_path)

    assert dataset.name == "aurora-bamboo-retrieval-v1"
    assert len(dataset.cases) == 5
    assert {case.category for case in dataset.cases} == {
        "exact-term",
        "bilingual-term",
        "document-context",
        "method",
        "traceability",
    }
