import asyncio
from pathlib import Path

import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope
from tests.helpers import assert_valid_lifecycle, parse_sse
from tests.unit.test_deepseek_provider import RecordingRetrievalTools, ScriptedGateway, _provider

from airesearcher_agent.api.sse import ChatStreamingResponse, encode_sse
from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.application.stream_chat import StreamChatCommand, StreamChatUseCase
from airesearcher_agent.domain.chat import ChatPrompt
from airesearcher_agent.persistence.models import AgentRunRecord
from airesearcher_agent.providers.deepseek_client import AssistantTurn, ChatMessage, ToolDefinition


class WaitingGateway(ScriptedGateway):
    def __init__(self) -> None:
        super().__init__([], [])
        self.release = asyncio.Event()
        self.cancelled = False

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolDefinition]
    ) -> AssistantTurn:
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return AssistantTurn(content="Synthetic answer")


def test_heartbeat_preserves_events_and_does_not_cancel_model(tmp_path: Path) -> None:
    async def scenario() -> None:
        gateway = WaitingGateway()
        provider, _ = _provider(tmp_path, gateway, RecordingRetrievalTools())
        command = StreamChatCommand("request", "conversation", "question", ())
        stream = encode_sse(StreamChatUseCase(provider).execute(command), heartbeat_seconds=0.01)
        blocks = [await anext(stream)]
        heartbeat = await anext(stream)
        assert heartbeat == b": heartbeat\n\n"
        assert not gateway.cancelled
        gateway.release.set()
        blocks.extend([block async for block in stream])
        assert_valid_lifecycle(parse_sse(b"".join(blocks).decode()))

    asyncio.run(scenario())


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_disconnect_cancels_model_and_excludes_run_from_history(
    tmp_path: Path, spec_version: str
) -> None:
    async def scenario() -> None:
        gateway = WaitingGateway()
        provider, database = _provider(tmp_path, gateway, RecordingRetrievalTools())
        command = StreamChatCommand("request", "conversation", "cancel me", ())
        stream = encode_sse(StreamChatUseCase(provider).execute(command), heartbeat_seconds=0.01)
        response = ChatStreamingResponse(stream, media_type="text/event-stream")
        disconnected = asyncio.Event()

        async def send(message: Message) -> None:
            if message.get("body") == b": heartbeat\n\n":
                disconnected.set()
                if spec_version == "2.4":
                    raise OSError("synthetic broken pipe")

        async def receive() -> Message:
            await disconnected.wait()
            return {"type": "http.disconnect"}

        scope: Scope = {"type": "http", "asgi": {"spec_version": spec_version}}
        if spec_version == "2.4":
            with pytest.raises(ClientDisconnect):
                await response(scope, receive, send)
        else:
            await response(scope, receive, send)
        assert gateway.cancelled
        with database.session() as session:
            run = session.query(AgentRunRecord).one()
            assert run.status == "FAILED"
            assert run.error_code == "RUN_CANCELLED"
        history = AgentRunStore(database).start(
            ChatPrompt("next-run", "conversation", "next-message", "follow up", ()),
            model_name="fake",
        )
        assert history == ()

    asyncio.run(scenario())
