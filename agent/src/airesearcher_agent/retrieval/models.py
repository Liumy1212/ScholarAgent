from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    score: float


@dataclass(frozen=True, slots=True)
class Evidence:
    citation_id: str
    paper_id: str
    title: str
    page: int
    quote: str
    chunk_id: str
    retrieval_score: float
    rerank_score: float

    def to_tool_dict(self) -> dict[str, str | int | float]:
        return {
            "citationId": self.citation_id,
            "paperId": self.paper_id,
            "title": self.title,
            "page": self.page,
            "quote": self.quote,
            "chunkId": self.chunk_id,
            "retrievalScore": self.retrieval_score,
            "rerankScore": self.rerank_score,
        }


@dataclass(frozen=True, slots=True)
class DocumentMatch:
    paper_id: str
    title: str
    authors: tuple[str, ...]
    publication_year: int | None
    status: str

    def to_tool_dict(self) -> dict[str, object]:
        return {
            "paperId": self.paper_id,
            "title": self.title,
            "authors": list(self.authors),
            "publicationYear": self.publication_year,
            "status": self.status,
        }
