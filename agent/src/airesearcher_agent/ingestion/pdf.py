import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pymupdf

from airesearcher_agent.application.errors import IngestionError
from airesearcher_agent.domain.papers import ParsedChunk

YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")
NUMBERED_HEADING_PATTERN = re.compile(
    r"^(?P<number>(?:\d+(?:\.\d+)*|[IVXLC]+(?:\.[A-Z])?))[\s.：:、-]+\S",
    re.IGNORECASE,
)
KNOWN_HEADINGS = {
    "abstract",
    "acknowledgements",
    "acknowledgments",
    "conclusion",
    "conclusions",
    "discussion",
    "experiments",
    "introduction",
    "limitations",
    "methods",
    "methodology",
    "references",
    "related work",
    "results",
    "摘要",
    "引言",
    "相关工作",
    "方法",
    "实验",
    "结果",
    "讨论",
    "局限性",
    "结论",
    "参考文献",
}


@dataclass(frozen=True, slots=True)
class TextBlock:
    page: int
    text: str
    max_font_size: float
    bold: bool


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str | None
    authors: tuple[str, ...]
    publication_year: int | None
    page_count: int
    chunks: tuple[ParsedChunk, ...]

    @property
    def section_outline(self) -> tuple[str, ...]:
        seen: set[str] = set()
        outline: list[str] = []
        for chunk in self.chunks:
            label = " > ".join(chunk.section_path)
            if label and label not in seen:
                seen.add(label)
                outline.append(label)
        return tuple(outline)


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

            page_blocks: list[tuple[int, tuple[TextBlock, ...]]] = []
            all_font_sizes: list[float] = []
            total_text = 0
            for page_index in range(page_count):
                raw_page = document[page_index].get_text(  # type: ignore[no-untyped-call]
                    "dict",
                    sort=True,
                )
                blocks = self._text_blocks(page_index + 1, raw_page)
                page_blocks.append((page_index + 1, blocks))
                total_text += sum(len(block.text) for block in blocks)
                all_font_sizes.extend(
                    block.max_font_size for block in blocks if block.max_font_size > 0
                )

            body_font_size = median(all_font_sizes) if all_font_sizes else 11.0
            chunks: list[ParsedChunk] = []
            section_stack: list[str] = []
            for page, blocks in page_blocks:
                ordinal = 0
                section_texts: list[str] = []
                active_path = tuple(section_stack)

                for block in blocks:
                    heading_level = self._heading_level(block, body_font_size)
                    if heading_level is not None:
                        ordinal = self._append_chunks(
                            chunks,
                            paper_id=paper_id,
                            page=page,
                            ordinal=ordinal,
                            texts=section_texts,
                            section_path=active_path,
                        )
                        section_texts = []
                        section_stack = self._updated_section_stack(
                            section_stack,
                            heading_level,
                            block.text,
                        )
                        active_path = tuple(section_stack)
                        continue
                    current_path = tuple(section_stack)
                    if section_texts and current_path != active_path:
                        ordinal = self._append_chunks(
                            chunks,
                            paper_id=paper_id,
                            page=page,
                            ordinal=ordinal,
                            texts=section_texts,
                            section_path=active_path,
                        )
                        section_texts = []
                    active_path = current_path
                    section_texts.append(block.text)
                self._append_chunks(
                    chunks,
                    paper_id=paper_id,
                    page=page,
                    ordinal=ordinal,
                    texts=section_texts,
                    section_path=active_path,
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

    def _append_chunks(
        self,
        chunks: list[ParsedChunk],
        *,
        paper_id: str,
        page: int,
        ordinal: int,
        texts: list[str],
        section_path: tuple[str, ...],
    ) -> int:
        page_text = "\n".join(texts)
        for chunk_text in self._split_page(page_text):
            seed = f"{paper_id}:{page}:{ordinal}"
            chunks.append(
                ParsedChunk(
                    chunk_id=f"chunk-{uuid5(NAMESPACE_URL, seed).hex}",
                    vector_id=str(uuid5(NAMESPACE_URL, f"vector:{seed}")),
                    paper_id=paper_id,
                    page=page,
                    ordinal=ordinal,
                    text=chunk_text,
                    quote=chunk_text,
                    section_path=section_path,
                )
            )
            ordinal += 1
        return ordinal

    def _text_blocks(self, page: int, raw_page: dict[str, Any]) -> tuple[TextBlock, ...]:
        result: list[TextBlock] = []
        raw_blocks = raw_page.get("blocks", [])
        if not isinstance(raw_blocks, list):
            return ()
        for raw_block in raw_blocks:
            if not isinstance(raw_block, dict) or raw_block.get("type") != 0:
                continue
            lines: list[str] = []
            sizes: list[float] = []
            bold = False
            for raw_line in self._dict_items(raw_block.get("lines")):
                line_parts: list[str] = []
                for span in self._dict_items(raw_line.get("spans")):
                    value = span.get("text")
                    if isinstance(value, str) and value.strip():
                        line_parts.append(value)
                    size = span.get("size")
                    if isinstance(size, int | float):
                        sizes.append(float(size))
                    font = span.get("font")
                    flags = span.get("flags")
                    bold = bold or (isinstance(font, str) and "bold" in font.lower())
                    bold = bold or (isinstance(flags, int) and bool(flags & 16))
                normalized_line = " ".join("".join(line_parts).split())
                if normalized_line:
                    lines.append(normalized_line)
            text = self._normalize_text("\n".join(lines))
            if text:
                result.append(
                    TextBlock(
                        page=page,
                        text=text,
                        max_font_size=max(sizes, default=0.0),
                        bold=bold,
                    )
                )
        return tuple(result)

    @staticmethod
    def _dict_items(value: object) -> Iterable[dict[str, Any]]:
        if not isinstance(value, list):
            return ()
        return (item for item in value if isinstance(item, dict))

    def _heading_level(self, block: TextBlock, body_font_size: float) -> int | None:
        text = " ".join(block.text.split()).strip()
        if not text or len(text) > 180 or "\n" in block.text:
            return None
        normalized = text.casefold().rstrip(".:：")
        match = NUMBERED_HEADING_PATTERN.match(text)
        known = normalized in KNOWN_HEADINGS
        visually_distinct = block.max_font_size >= body_font_size * 1.12 or block.bold
        if not known and match is None:
            return None
        if not visually_distinct and not known:
            return None
        if match is None:
            return 1
        number = match.group("number")
        if number[0].isdigit():
            return min(number.count(".") + 1, 4)
        return 1

    @staticmethod
    def _updated_section_stack(current: list[str], level: int, heading: str) -> list[str]:
        normalized = " ".join(heading.split())[:512]
        prefix = current[: max(level - 1, 0)]
        return [*prefix, normalized]

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
