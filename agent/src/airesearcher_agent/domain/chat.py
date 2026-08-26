from dataclasses import dataclass
from typing import Literal

type AnswerMode = Literal["KNOWLEDGE_BASE", "DOCUMENT_LOOKUP", "MODEL_KNOWLEDGE"]


@dataclass(frozen=True, slots=True)
class ChatPrompt:
    run_id: str
    conversation_id: str
    assistant_message_id: str
    content: str
    paper_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageDelta:
    delta: str

    def __post_init__(self) -> None:
        if not self.delta:
            raise ValueError("message delta must not be empty")


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    paper_id: str
    paper_title: str
    page_number: int
    quote: str
    chunk_id: str

    def __post_init__(self) -> None:
        identifiers = (self.citation_id, self.paper_id, self.chunk_id)
        if any(not value or len(value) > 128 for value in identifiers):
            raise ValueError("citation identifiers must contain 1 to 128 characters")
        if not self.paper_title:
            raise ValueError("paper title must not be empty")
        if self.page_number < 1:
            raise ValueError("page number must be positive")
        if not self.quote:
            raise ValueError("citation quote must not be empty")


@dataclass(frozen=True, slots=True)
class ToolStatus:
    tool_call_id: str
    tool_name: Literal["knowledge_base_search", "document_lookup"]
    status: Literal["started", "completed", "failed"]
    message: str

    def __post_init__(self) -> None:
        if not self.tool_call_id or len(self.tool_call_id) > 128:
            raise ValueError("tool call ID must contain 1 to 128 characters")
        if not self.message or len(self.message) > 512:
            raise ValueError("tool status message must contain 1 to 512 characters")


@dataclass(frozen=True, slots=True)
class AnswerCompleted:
    answer_mode: AnswerMode


type ProviderEvent = MessageDelta | Citation | ToolStatus | AnswerCompleted
