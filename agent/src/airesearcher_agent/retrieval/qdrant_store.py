from dataclasses import dataclass
from math import ceil

from qdrant_client import QdrantClient, models

from airesearcher_agent.config import Settings
from airesearcher_agent.retrieval.models import SearchHit


class VectorStoreError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class QdrantVectorStore:
    client: QdrantClient
    collection_name: str
    vector_size: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "QdrantVectorStore":
        return cls(
            client=QdrantClient(
                url=settings.qdrant_url,
                timeout=ceil(settings.qdrant_timeout_seconds),
                check_compatibility=True,
            ),
            collection_name=settings.qdrant_collection,
            vector_size=settings.vector_size,
        )

    def ensure_collection(self) -> None:
        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="paperId",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="chunkId",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
                return

            info = self.client.get_collection(self.collection_name)
            vectors = info.config.params.vectors
            if not isinstance(vectors, models.VectorParams):
                raise VectorStoreError("configured collection must use one unnamed dense vector")
            if vectors.size != self.vector_size or vectors.distance != models.Distance.COSINE:
                raise VectorStoreError(
                    "configured Qdrant collection has an incompatible vector size or distance"
                )
        except VectorStoreError:
            raise
        except Exception as error:
            raise VectorStoreError("Qdrant collection is unavailable") from error

    def upsert_chunks(
        self,
        *,
        paper_id: str,
        title: str,
        chunks: list[tuple[str, str, int, str]],
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        self.ensure_collection()
        points = [
            models.PointStruct(
                id=vector_id,
                vector=vector,
                payload={
                    "paperId": paper_id,
                    "chunkId": chunk_id,
                    "page": page,
                    "quote": quote,
                    "title": title,
                },
            )
            for (chunk_id, vector_id, page, quote), vector in zip(chunks, vectors, strict=True)
        ]
        try:
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
        except Exception as error:
            raise VectorStoreError("Qdrant indexing failed") from error

    def delete_paper(self, paper_id: str) -> None:
        try:
            if not self.client.collection_exists(self.collection_name):
                return
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="paperId",
                                match=models.MatchValue(value=paper_id),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as error:
            raise VectorStoreError("Qdrant cleanup failed") from error

    def search(
        self,
        *,
        vector: list[float],
        ready_paper_ids: tuple[str, ...],
        limit: int,
    ) -> list[SearchHit]:
        if not ready_paper_ids:
            return []
        try:
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="paperId",
                            match=models.MatchAny(any=list(ready_paper_ids)),
                        )
                    ]
                ),
                with_payload=["chunkId"],
                with_vectors=False,
                limit=limit,
            )
        except Exception as error:
            raise VectorStoreError("Qdrant retrieval failed") from error
        hits: list[SearchHit] = []
        for point in result.points:
            payload = point.payload or {}
            chunk_id = payload.get("chunkId")
            if isinstance(chunk_id, str) and chunk_id:
                hits.append(SearchHit(chunk_id=chunk_id, score=float(point.score)))
        return hits
