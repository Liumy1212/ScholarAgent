from airesearcher_agent.retrieval.bm25 import Bm25KeywordRetriever
from airesearcher_agent.retrieval.models import KeywordDocument


def test_bm25_retrieves_exact_english_and_chinese_terms() -> None:
    documents = [
        KeywordDocument("chunk-general", "The paper evaluates a general neural model."),
        KeywordDocument("chunk-benchmark", "Results on the QASPER benchmark improve by 7 points."),
        KeywordDocument("chunk-chinese", "该方法在低资源设置下取得更高的准确率。"),
    ]
    retriever = Bm25KeywordRetriever()

    english = retriever.search(query="QASPER benchmark", documents=documents, limit=2)
    chinese = retriever.search(query="低资源设置", documents=documents, limit=2)

    assert english[0].chunk_id == "chunk-benchmark"
    assert chinese[0].chunk_id == "chunk-chinese"


def test_bm25_returns_no_candidates_without_token_overlap() -> None:
    hits = Bm25KeywordRetriever().search(
        query="unseen terminology",
        documents=[KeywordDocument("chunk-one", "Completely unrelated evidence.")],
        limit=5,
    )

    assert hits == []
