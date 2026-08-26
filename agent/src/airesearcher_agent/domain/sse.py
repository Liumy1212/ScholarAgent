from dataclasses import dataclass
from datetime import datetime
from typing import Literal

type EventType = Literal[
    "run.started",
    "message.delta",
    "citation.created",
    "tool.status",
    "run.completed",
    "run.failed",
]
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


@dataclass(frozen=True, slots=True)
class SseEvent:
    type: EventType
    event_id: str
    request_id: str
    run_id: str
    conversation_id: str
    assistant_message_id: str
    sequence: int
    timestamp: datetime
    payload: dict[str, JsonValue]

    def __post_init__(self) -> None:
        identifiers = (
            self.event_id,
            self.request_id,
            self.run_id,
            self.conversation_id,
            self.assistant_message_id,
        )
        if any(not value or len(value) > 128 for value in identifiers):
            raise ValueError("SSE identifiers must contain 1 to 128 characters")
        if self.sequence < 0:
            raise ValueError("SSE sequence must not be negative")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("SSE timestamp must include a timezone")

    def to_wire(self) -> dict[str, JsonValue]:
        timestamp = self.timestamp.isoformat().replace("+00:00", "Z")
        return {
            "schemaVersion": "1.0",
            "type": self.type,
            "eventId": self.event_id,
            "requestId": self.request_id,
            "runId": self.run_id,
            "conversationId": self.conversation_id,
            "assistantMessageId": self.assistant_message_id,
            "sequence": self.sequence,
            "timestamp": timestamp,
            "payload": self.payload,
        }
