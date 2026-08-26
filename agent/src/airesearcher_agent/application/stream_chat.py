from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from airesearcher_agent.application.ports import ChatProvider, ChatProviderError
from airesearcher_agent.domain.chat import (
    AnswerCompleted,
    AnswerMode,
    ChatPrompt,
    Citation,
    MessageDelta,
    ToolStatus,
)
from airesearcher_agent.domain.sse import EventType, JsonValue, SseEvent

type IdFactory = Callable[[str], str]
type Clock = Callable[[], datetime]


def uuid_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def utc_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StreamChatCommand:
    request_id: str
    conversation_id: str
    content: str
    paper_ids: tuple[str, ...]


class _EventFactory:
    def __init__(
        self,
        command: StreamChatCommand,
        *,
        id_factory: IdFactory,
        clock: Clock,
    ) -> None:
        self._command = command
        self._id_factory = id_factory
        self._clock = clock
        self._run_id = id_factory("run")
        self._assistant_message_id = id_factory("msg-assistant")
        self._event_id_namespace = uuid5(NAMESPACE_URL, self._run_id).hex
        self._next_sequence = 0

    def create(self, event_type: EventType, payload: dict[str, JsonValue]) -> SseEvent:
        event = SseEvent(
            type=event_type,
            event_id=f"evt-{self._event_id_namespace}-{self._next_sequence}",
            request_id=self._command.request_id,
            run_id=self._run_id,
            conversation_id=self._command.conversation_id,
            assistant_message_id=self._assistant_message_id,
            sequence=self._next_sequence,
            timestamp=self._clock(),
            payload=payload,
        )
        self._next_sequence += 1
        return event

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def assistant_message_id(self) -> str:
        return self._assistant_message_id


class StreamChatUseCase:
    def __init__(
        self,
        provider: ChatProvider,
        *,
        id_factory: IdFactory = uuid_id_factory,
        clock: Clock = utc_clock,
    ) -> None:
        self._provider = provider
        self._id_factory = id_factory
        self._clock = clock

    async def execute(self, command: StreamChatCommand) -> AsyncIterator[SseEvent]:
        events = _EventFactory(command, id_factory=self._id_factory, clock=self._clock)
        yield events.create("run.started", {})

        prompt = ChatPrompt(
            run_id=events.run_id,
            conversation_id=command.conversation_id,
            assistant_message_id=events.assistant_message_id,
            content=command.content,
            paper_ids=command.paper_ids,
        )
        answer_mode: AnswerMode | None = None
        try:
            async for provider_event in self._provider.stream(prompt):
                if isinstance(provider_event, MessageDelta):
                    yield events.create("message.delta", {"delta": provider_event.delta})
                elif isinstance(provider_event, Citation):
                    yield events.create(
                        "citation.created",
                        {
                            "citationId": provider_event.citation_id,
                            "paperId": provider_event.paper_id,
                            "paperTitle": provider_event.paper_title,
                            "pageNumber": provider_event.page_number,
                            "quote": provider_event.quote,
                            "chunkId": provider_event.chunk_id,
                        },
                    )
                elif isinstance(provider_event, ToolStatus):
                    yield events.create(
                        "tool.status",
                        {
                            "toolCallId": provider_event.tool_call_id,
                            "toolName": provider_event.tool_name,
                            "status": provider_event.status,
                            "message": provider_event.message,
                        },
                    )
                elif isinstance(provider_event, AnswerCompleted):
                    if answer_mode is not None:
                        raise TypeError("chat provider returned multiple completion markers")
                    answer_mode = provider_event.answer_mode
                else:
                    raise TypeError("chat provider returned an unsupported event")
        except ChatProviderError as error:
            yield events.create(
                "run.failed",
                {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                },
            )
        except Exception:
            yield events.create(
                "run.failed",
                {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected streaming failure.",
                    "retryable": False,
                },
            )
        else:
            if answer_mode is None:
                yield events.create(
                    "run.failed",
                    {
                        "code": "INTERNAL_ERROR",
                        "message": "Provider did not report an answer mode.",
                        "retryable": False,
                    },
                )
            else:
                yield events.create("run.completed", {"answerMode": answer_mode})
