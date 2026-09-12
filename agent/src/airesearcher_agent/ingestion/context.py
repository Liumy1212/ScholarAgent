from dataclasses import dataclass
from typing import Protocol


class ChunkContextError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ChunkContextRequest:
    paper_title: str
    section_path: tuple[str, ...]
    section_outline: tuple[str, ...]
    previous_text: str | None
    current_text: str
    next_text: str | None


class ChunkContextProvider(Protocol):
    def generate(self, request: ChunkContextRequest) -> str: ...

    def close(self) -> None: ...


def retrieval_text(
    *,
    paper_title: str,
    section_path: tuple[str, ...],
    context_text: str,
    quote: str,
) -> str:
    parts = [f"论文标题：{paper_title}"]
    if section_path:
        parts.append(f"章节：{' > '.join(section_path)}")
    parts.append(f"上下文：{context_text}")
    parts.append(f"原文：{quote}")
    return "\n".join(parts)
