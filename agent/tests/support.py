from pathlib import Path
from typing import Any

from airesearcher_agent.config import Settings
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import Base
from airesearcher_agent.retrieval.models import SearchHit


def runtime_settings(runtime_root: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "AIRESEARCHER_STORAGE_DIR": runtime_root / "storage",
        "AIRESEARCHER_MODEL_CACHE_DIR": runtime_root / "models",
        "DEEPSEEK_API_KEY": "test-only-key",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def sqlite_database() -> Database:
    database = Database("sqlite://")
    with database.engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(database.engine)
    return database


class MemoryUpload:
    def __init__(
        self,
        content: bytes,
        *,
        filename: str = "paper.pdf",
        content_type: str = "application/pdf",
    ) -> None:
        self._content = content
        self._offset = 0
        self._filename = filename
        self._content_type = content_type

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def content_type(self) -> str:
        return self._content_type

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            result = self._content[self._offset :]
            self._offset = len(self._content)
            return result
        result = self._content[self._offset : self._offset + size]
        self._offset += len(result)
        return result


class RecordingVectorStore:
    def __init__(self) -> None:
        self.deleted_papers: list[str] = []
        self.upserts: list[tuple[str, list[tuple[str, str, int, str]], list[list[float]]]] = []
        self.search_hits: list[SearchHit] = []
        self.search_scopes: list[tuple[str, ...]] = []
        self.search_limits: list[int] = []

    def ensure_collection(self) -> None:
        return

    def upsert_chunks(
        self,
        *,
        paper_id: str,
        title: str,
        chunks: list[tuple[str, str, int, str]],
        vectors: list[list[float]],
    ) -> None:
        del title
        self.upserts.append((paper_id, chunks, vectors))

    def delete_paper(self, paper_id: str) -> None:
        self.deleted_papers.append(paper_id)

    def search(
        self,
        *,
        vector: list[float],
        ready_paper_ids: tuple[str, ...],
        limit: int,
    ) -> list[SearchHit]:
        del vector
        self.search_scopes.append(ready_paper_ids)
        self.search_limits.append(limit)
        return list(self.search_hits)


class DeterministicEmbedding:
    def __init__(self, *, fail_calls: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._fail_calls = fail_calls

    @property
    def dimension(self) -> int:
        return 3

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._fail_calls > 0:
            self._fail_calls -= 1
            raise RuntimeError("synthetic transient model failure")
        return [[float(index + 1), 0.5, 0.25] for index, _text in enumerate(texts)]


class FixedReranker:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        return self._scores[: len(passages)]
