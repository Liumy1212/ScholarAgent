import re
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pymupdf

from airesearcher_agent.application.errors import IngestionError
from airesearcher_agent.domain.papers import ParsedChunk

YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str | None
    authors: tuple[str, ...]
    publication_year: int | None
    page_count: int
    chunks: tuple[ParsedChunk, ...]


class PdfParser:
    def __init__(self, *, max_pages: int, chunk_size: int, chunk_overlap: int) -> None:
        self._max_pages = max_pages
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def parse(self, *, paper_id: str, path: Path) -> ParsedDocument:
        try:
            document = pymupdf.open(path)  # type: ignore[no-untyped-call]
        except Exception as error:
            raise IngestionError(
                code="INVALID_PDF",
                message="PDF 文件已损坏或无法解析。",
                retryable=False,
            ) from error

        with document:
            if document.needs_pass:
                raise IngestionError(
                    code="ENCRYPTED_PDF",
                    message="暂不支持加密 PDF。",
                    retryable=False,
                )
            page_count = document.page_count
            if page_count < 1:
                raise IngestionError(
                    code="INVALID_PDF",
                    message="PDF 不包含页面。",
                    retryable=False,
                )
            if page_count > self._max_pages:
                raise IngestionError(
                    code="PDF_TOO_MANY_PAGES",
                    message="PDF 不能超过 500 页。",
                    retryable=False,
                )

            chunks: list[ParsedChunk] = []
            total_text = 0
            for page_index in range(page_count):
                raw_text = document[page_index].get_text(  # type: ignore[no-untyped-call]
                    "text",
                    sort=True,
                )
                page_text = self._normalize_text(raw_text)
                total_text += len(page_text)
                for ordinal, chunk_text in enumerate(self._split_page(page_text)):
                    seed = f"{paper_id}:{page_index + 1}:{ordinal}"
                    chunk_id = f"chunk-{uuid5(NAMESPACE_URL, seed).hex}"
                    vector_id = str(uuid5(NAMESPACE_URL, f"vector:{seed}"))
                    chunks.append(
                        ParsedChunk(
                            chunk_id=chunk_id,
                            vector_id=vector_id,
                            paper_id=paper_id,
                            page=page_index + 1,
                            ordinal=ordinal,
                            text=chunk_text,
                            quote=chunk_text,
                        )
                    )
            if total_text < 20 or not chunks:
                raise IngestionError(
                    code="PDF_HAS_NO_TEXT",
                    message="PDF 没有足够的可提取文本；暂不支持扫描版 PDF。",
                    retryable=False,
                )

            metadata = document.metadata or {}
            title = self._clean_metadata(metadata.get("title"))
            author_value = self._clean_metadata(metadata.get("author"))
            authors = self._authors(author_value)
            publication_year = self._year(metadata)
            return ParsedDocument(
                title=title,
                authors=authors,
                publication_year=publication_year,
                page_count=page_count,
                chunks=tuple(chunks),
            )

    def _normalize_text(self, value: str) -> str:
        lines = [" ".join(line.replace("\x00", "").split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()

    def _split_page(self, text: str) -> tuple[str, ...]:
        if not text:
            return ()
        chunks: list[str] = []
        start = 0
        while start < len(text):
            target_end = min(start + self._chunk_size, len(text))
            end = self._boundary(text, start, target_end)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            next_start = max(end - self._chunk_overlap, start + 1)
            start = next_start
        return tuple(chunks)

    def _boundary(self, text: str, start: int, target_end: int) -> int:
        if target_end >= len(text):
            return len(text)
        floor = start + self._chunk_size // 2
        candidates = [
            text.rfind(separator, floor, target_end)
            for separator in ("\n", "。", "！", "？", ". ", "! ", "? ")
        ]
        boundary = max(candidates, default=-1)
        return boundary + 1 if boundary >= floor else target_end

    def _clean_metadata(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.replace("\x00", "").split()).strip()
        return cleaned[:1024] or None

    def _authors(self, value: str | None) -> tuple[str, ...]:
        if value is None:
            return ()
        values = [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
        return tuple(values[:32])

    def _year(self, metadata: dict[str, str]) -> int | None:
        for key in ("creationDate", "modDate", "subject"):
            value = metadata.get(key, "")
            match = YEAR_PATTERN.search(value)
            if match is not None:
                return int(match.group(0))
        return None
