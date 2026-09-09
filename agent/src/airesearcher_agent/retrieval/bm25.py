import re

import jieba  # type: ignore[import-untyped]
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from airesearcher_agent.retrieval.models import KeywordDocument, SearchHit

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[\u3400-\u4dbf\u4e00-\u9fff]+")


class Bm25KeywordRetriever:
    def search(
        self,
        *,
        query: str,
        documents: list[KeywordDocument],
        limit: int,
    ) -> list[SearchHit]:
        if not documents or limit < 1:
            return []
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        document_tokens = [self._tokens(document.text) for document in documents]
        matching_indexes = [
            index
            for index, tokens in enumerate(document_tokens)
            if not set(query_tokens).isdisjoint(tokens)
        ]
        if not matching_indexes:
            return []
        scores = BM25Okapi(document_tokens).get_scores(query_tokens)
        ranked_indexes = sorted(
            matching_indexes,
            key=lambda index: (-float(scores[index]), documents[index].chunk_id),
        )[:limit]
        return [
            SearchHit(
                chunk_id=documents[index].chunk_id,
                score=float(scores[index]),
            )
            for index in ranked_indexes
        ]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        tokens: list[str] = []
        for match in TOKEN_PATTERN.finditer(text):
            value = match.group(0)
            if value.isascii():
                tokens.append(value.casefold())
            else:
                tokens.extend(
                    part.strip().casefold()
                    for part in jieba.cut(value, cut_all=False)
                    if part.strip()
                )
        return tokens
