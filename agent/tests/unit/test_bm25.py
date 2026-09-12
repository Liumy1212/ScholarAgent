from datetime import timedelta
from typing import Any

import pytest
from tests.support import sqlite_database

from airesearcher_agent.persistence.models import ChunkRecord, PaperRecord, utc_now
from airesearcher_agent.retrieval.bm25 import Bm25Index, Bm25KeywordRetriever
from airesearcher_agent.retrieval.models import KeywordDocument


def test_bm25_retrieves_exact_english_and_chinese_terms() -> None:
    documents = [
        KeywordDocument("chunk-general", "The paper evaluates a general neural model."),
        KeywordDocument("chunk-benchmark", "Results on the QASPER benchmark improve by 7 points."),
        KeywordDocument("chunk-chinese", "该方法在低资源设置下取得更高的准确率。"),
    ]
    retriever = Bm25Index(documents)

    english = retriever.search(query="QASPER benchmark", limit=2)
    chinese = retriever.search(query="低资源设置", limit=2)

    assert english[0].chunk_id == "chunk-benchmark"
    assert chinese[0].chunk_id == "chunk-chinese"


def test_bm25_returns_no_candidates_without_token_overlap() -> None:
    hits = Bm25Index([KeywordDocument("chunk-one", "Completely unrelated evidence.")]).search(
        query="unseen terminology",
        limit=5,
    )

    assert hits == []


def test_runtime_bm25_reuses_index_until_paper_version_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = sqlite_database()
    now = utc_now()
    with database.transaction() as session:
        stored_paper = PaperRecord(
            id="paper-cache",
            sha256="a" * 64,
            title="Cached Retrieval",
            authors=[],
            publication_year=2026,
            original_filename="cached.pdf",
            storage_path="C:/external/cached.pdf",
            file_size_bytes=123,
            page_count=1,
            status="READY",
            created_at=now,
            updated_at=now,
        )
        session.add(stored_paper)
        session.flush()
        session.add(
            ChunkRecord(
                id="chunk-cache",
                vector_id="00000000-0000-0000-0000-000000000001",
                paper_id="paper-cache",
                page=1,
                ordinal=0,
                text="alpha retrieval term",
                quote="alpha retrieval term",
                created_at=now,
            )
        )

    retriever = Bm25KeywordRetriever(database)
    original_load = retriever._load_indexes
    load_calls = 0

    def recording_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal load_calls
        load_calls += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(retriever, "_load_indexes", recording_load)

    assert retriever.search(query="alpha", paper_ids=("paper-cache",), limit=5)
    assert retriever.search(query="alpha", paper_ids=("paper-cache",), limit=5)
    assert load_calls == 1

    with database.transaction() as session:
        refreshed_paper = session.get(PaperRecord, "paper-cache")
        chunk = session.get(ChunkRecord, "chunk-cache")
        assert refreshed_paper is not None
        assert chunk is not None
        refreshed_paper.updated_at = now + timedelta(seconds=1)
        chunk.text = "beta replacement term"

    assert retriever.search(query="beta", paper_ids=("paper-cache",), limit=5)
    assert load_calls == 2
