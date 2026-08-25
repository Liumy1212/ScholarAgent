from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatPrompt:
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

    def __post_init__(self) -> None:
        identifiers = (self.citation_id, self.paper_id)
        if any(not value or len(value) > 128 for value in identifiers):
            raise ValueError("citation identifiers must contain 1 to 128 characters")
        if not self.paper_title:
            raise ValueError("paper title must not be empty")
        if self.page_number < 1:
            raise ValueError("page number must be positive")
        if not self.quote:
            raise ValueError("citation quote must not be empty")


type ProviderEvent = MessageDelta | Citation
