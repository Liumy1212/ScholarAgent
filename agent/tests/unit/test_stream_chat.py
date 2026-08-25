import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from airesearcher_agent.application.ports import ChatProviderError
from airesearcher_agent.application.stream_chat import StreamChatCommand, StreamChatUseCase
from airesearcher_agent.domain.chat import ChatPrompt, MessageDelta, ProviderEvent
from airesearcher_agent.domain.sse import SseEvent
from airesearcher_agent.providers.fake import FakeChatProvider


@dataclass(slots=True)
class SequentialIdFactory:
    next_value: int = 0

    def __call__(self, prefix: str) -> str:
        self.next_value += 1
        return f"{prefix}-{self.next_value:03d}"


def fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


async def _collect(use_case: StreamChatUseCase) -> list[SseEvent]:
    command = StreamChatCommand(
        request_id="req-unit-001",
        conversation_id="conv-unit-001",
        content="概括观点",
        paper_ids=(),
    )
    return [event async for event in use_case.execute(command)]


def test_use_case_owns_strict_sequence_and_single_completed_terminal() -> None:
    use_case = StreamChatUseCase(
        FakeChatProvider(),
        id_factory=SequentialIdFactory(),
        clock=fixed_clock,
    )

    events = asyncio.run(_collect(use_case))

    assert [event.type for event in events] == [
        "run.started",
        "message.delta",
        "message.delta",
        "citation.created",
        "run.completed",
    ]
    assert [event.sequence for event in events] == list(range(len(events)))
    assert len({event.event_id for event in events}) == len(events)
    assert len([event for event in events if event.type.startswith("run.")]) == 2
    assert len([event for event in events if event.type in {"run.completed", "run.failed"}]) == 1
    assert all(event.request_id == "req-unit-001" for event in events)
    assert all(event.conversation_id == "conv-unit-001" for event in events)
    assert len({event.run_id for event in events}) == 1
    assert len({event.assistant_message_id for event in events}) == 1


class PartialFailureProvider:
    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[ProviderEvent]:
        yield MessageDelta(f"partial: {prompt.content}")
        raise ChatProviderError(
            code="PROVIDER_FAILURE",
            message="Synthetic provider failure for contract validation.",
            retryable=True,
        )


def test_use_case_converts_provider_failure_to_only_failed_terminal() -> None:
    use_case = StreamChatUseCase(
        PartialFailureProvider(),
        id_factory=SequentialIdFactory(),
        clock=fixed_clock,
    )

    events = asyncio.run(_collect(use_case))

    assert [event.type for event in events] == ["run.started", "message.delta", "run.failed"]
    assert [event.sequence for event in events] == [0, 1, 2]
    assert events[-1].payload == {
        "code": "PROVIDER_FAILURE",
        "message": "Synthetic provider failure for contract validation.",
        "retryable": True,
    }


class UnexpectedFailureProvider:
    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[ProviderEvent]:
        if prompt.content:
            raise RuntimeError("private implementation detail")
        yield MessageDelta("unreachable")


def test_use_case_hides_unexpected_failure_and_terminates_stream() -> None:
    use_case = StreamChatUseCase(
        UnexpectedFailureProvider(),
        id_factory=SequentialIdFactory(),
        clock=fixed_clock,
    )

    events = asyncio.run(_collect(use_case))

    assert [event.type for event in events] == ["run.started", "run.failed"]
    assert events[-1].payload == {
        "code": "INTERNAL_ERROR",
        "message": "Unexpected streaming failure.",
        "retryable": False,
    }
