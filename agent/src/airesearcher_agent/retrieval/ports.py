from typing import Protocol

from airesearcher_agent.retrieval.models import SearchHit


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert_chunks(
        self,
        *,
        paper_id: str,
        title: str,
        chunks: list[tuple[str, str, int, str]],
        vectors: list[list[float]],
    ) -> None: ...

    def delete_paper(self, paper_id: str) -> None: ...

    def search(
        self,
        *,
        vector: list[float],
        ready_paper_ids: tuple[str, ...],
        limit: int,
    ) -> list[SearchHit]: ...
