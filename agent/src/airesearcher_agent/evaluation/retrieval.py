import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from airesearcher_agent.domain.papers import PaperSourceStatus, PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import LibraryFileRecord, PaperRecord
from airesearcher_agent.retrieval.models import RankedChunk
from airesearcher_agent.retrieval.tools import RetrievalMode


class EvaluationError(Exception):
    pass


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    case_id: str = Field(alias="id", min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    paper_title: str = Field(alias="paperTitle", min_length=1, max_length=1024)
    query: str = Field(min_length=1, max_length=2000)
    relevant_pages: list[int] = Field(alias="relevantPages", min_length=1)

    @field_validator("relevant_pages")
    @classmethod
    def valid_relevant_pages(cls, value: list[int]) -> list[int]:
        if any(page < 1 for page in value) or len(value) != len(set(value)):
            raise ValueError("relevantPages must contain unique positive page numbers")
        return value


class RetrievalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=128)
    cases: list[RetrievalCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def unique_case_ids(cls, value: list[RetrievalCase]) -> list[RetrievalCase]:
        case_ids = [case.case_id for case in value]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case ids must be unique")
        return value


class CaseResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(alias="id")
    category: str
    recall_at_20: float = Field(alias="recallAt20")
    reciprocal_rank: float = Field(alias="reciprocalRank")
    retrieved_pages: list[int] = Field(alias="retrievedPages")


class StrategyReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recall_at_20: float = Field(alias="recallAt20")
    mrr: float
    traceable_result_rate: float = Field(alias="traceableResultRate")
    cases: list[CaseResult]


class ComparisonReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dataset: str
    dense: StrategyReport
    hybrid: StrategyReport
    recall_delta: float = Field(alias="recallDelta")
    mrr_delta: float = Field(alias="mrrDelta")


class ChunkRanker(Protocol):
    def rank_chunks(
        self,
        *,
        query: str,
        paper_ids: tuple[str, ...],
        mode: RetrievalMode,
    ) -> list[RankedChunk]: ...


def load_dataset(path: Path) -> RetrievalDataset:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RetrievalDataset.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError(f"无法读取评测集：{path}") from error


class RetrievalEvaluator:
    def __init__(self, *, database: Database, ranker: ChunkRanker) -> None:
        self._database = database
        self._ranker = ranker

    def compare(self, dataset: RetrievalDataset) -> ComparisonReport:
        dense = self._evaluate(dataset, "dense")
        hybrid = self._evaluate(dataset, "hybrid")
        return ComparisonReport(
            dataset=dataset.name,
            dense=dense,
            hybrid=hybrid,
            recall_delta=hybrid.recall_at_20 - dense.recall_at_20,
            mrr_delta=hybrid.mrr - dense.mrr,
        )

    def _evaluate(self, dataset: RetrievalDataset, mode: RetrievalMode) -> StrategyReport:
        results: list[CaseResult] = []
        traceable = 0
        returned = 0
        for case in dataset.cases:
            paper_id = self._paper_id(case.paper_title)
            ranked = self._ranker.rank_chunks(
                query=case.query,
                paper_ids=(paper_id,),
                mode=mode,
            )[:20]
            relevant = set(case.relevant_pages)
            retrieved_relevant = {chunk.page for chunk in ranked if chunk.page in relevant}
            first_rank = next(
                (index for index, chunk in enumerate(ranked, start=1) if chunk.page in relevant),
                None,
            )
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    recall_at_20=len(retrieved_relevant) / len(relevant),
                    reciprocal_rank=0.0 if first_rank is None else 1.0 / first_rank,
                    retrieved_pages=[chunk.page for chunk in ranked],
                )
            )
            returned += len(ranked)
            traceable += sum(
                1
                for chunk in ranked
                if chunk.paper_id == paper_id
                and chunk.page >= 1
                and bool(chunk.chunk_id)
                and bool(chunk.quote.strip())
            )
        count = len(results)
        return StrategyReport(
            recall_at_20=sum(result.recall_at_20 for result in results) / count,
            mrr=sum(result.reciprocal_rank for result in results) / count,
            traceable_result_rate=0.0 if returned == 0 else traceable / returned,
            cases=results,
        )

    def _paper_id(self, title: str) -> str:
        with self._database.session() as session:
            paper_ids = tuple(
                session.scalars(
                    select(PaperRecord.id)
                    .join(LibraryFileRecord, LibraryFileRecord.paper_id == PaperRecord.id)
                    .where(
                        PaperRecord.title == title,
                        PaperRecord.status == PaperStatus.READY.value,
                        LibraryFileRecord.source_status == PaperSourceStatus.AVAILABLE.value,
                    )
                    .distinct()
                ).all()
            )
        if len(paper_ids) != 1:
            raise EvaluationError(
                f"评测论文必须存在且标题唯一、可检索：{title}[匹配 {len(paper_ids)} 篇]"
            )
        return paper_ids[0]
