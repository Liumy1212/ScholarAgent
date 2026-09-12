import argparse
from pathlib import Path

from airesearcher_agent.config import Settings
from airesearcher_agent.evaluation.retrieval import RetrievalEvaluator, load_dataset
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.retrieval.bm25 import Bm25KeywordRetriever
from airesearcher_agent.retrieval.local_models import BgeM3EmbeddingProvider, BgeReranker
from airesearcher_agent.retrieval.qdrant_store import QdrantVectorStore
from airesearcher_agent.retrieval.tools import RetrievalTools

AGENT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = AGENT_ROOT / "evals" / "retrieval_cases.json"
DEFAULT_ENV_FILE = AGENT_ROOT.parent / ".env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对比 Dense 与 Hybrid 论文检索质量")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--require-hybrid-improvement",
        action="store_true",
        help="Hybrid 两项指标均未提升或任一指标退化时返回非零退出码",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    settings = Settings(_env_file=arguments.env_file)
    database = Database(settings.database_url)
    try:
        tools = RetrievalTools(
            database=database,
            embedding=BgeM3EmbeddingProvider(settings),
            keyword_retriever=Bm25KeywordRetriever(database),
            reranker=BgeReranker(settings),
            vector_store=QdrantVectorStore.from_settings(settings),
            settings=settings,
        )
        report = RetrievalEvaluator(database=database, ranker=tools).compare(
            load_dataset(arguments.dataset.resolve())
        )
        print(report.model_dump_json(by_alias=True, indent=2))
        if report.dense.traceable_result_rate < 1 or report.hybrid.traceable_result_rate < 1:
            raise SystemExit("评测结果未全部绑定到有效原文、页码和 Chunk。")
        improved = report.recall_delta > 0 or report.mrr_delta > 0
        regressed = report.recall_delta < 0 or report.mrr_delta < 0
        if arguments.require_hybrid_improvement and (not improved or regressed):
            raise SystemExit("Hybrid 未在无退化条件下提升 Recall@20 或 MRR。")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
