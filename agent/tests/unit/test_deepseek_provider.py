import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from tests.support import runtime_settings, sqlite_database

from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.domain.chat import (
    AnswerCompleted,
    ChatPrompt,
    Citation,
    MessageDelta,
    ProviderEvent,
    ToolStatus,
)
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    AgentRunRecord,
    PaperRecord,
    ToolCallRecord,
    utc_now,
)
from airesearcher_agent.providers.deepseek import DeepSeekToolCallingProvider
from airesearcher_agent.providers.deepseek_client import (
    AssistantTurn,
    ChatMessage,
    NativeToolCall,
    ToolDefinition,
)
from airesearcher_agent.retrieval.models import DocumentMatch, Evidence
from airesearcher_agent.retrieval.tools import (
    DocumentLookupArgs,
    KnowledgeBaseSearchArgs,
    RetrievalTools,
)

CITATION_ID = f"citation-{'a' * 32}"
FORGED_CITATION_ID = f"citation-{'f' * 32}"


class ScriptedGateway:
    def __init__(
        self,
        turns: list[AssistantTurn],
        final_fragments: list[str],
        *,
        repair_fragments: list[str] | None = None,
    ) -> None:
        self._turns = list(turns)
        self._final_fragments = final_fragments
        self._repair_fragments = repair_fragments
        self.complete_messages: list[list[ChatMessage]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []
        self.final_messages: list[ChatMessage] = []
        self.final_message_calls: list[list[ChatMessage]] = []

    async def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantTurn:
        self.complete_messages.append(list(messages))
        self.tool_definitions.append(list(tools))
        if not self._turns:
            return AssistantTurn()
        return self._turns.pop(0)

    async def stream_final(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        self.final_messages = list(messages)
        self.final_message_calls.append(list(messages))
        fragments = (
            self._repair_fragments
            if len(self.final_message_calls) > 1 and self._repair_fragments is not None
            else self._final_fragments
        )
        for fragment in fragments:
            yield fragment


class RecordingRetrievalTools:
    def __init__(self) -> None:
        self.search_calls: list[tuple[KnowledgeBaseSearchArgs, str]] = []
        self.lookup_calls: list[DocumentLookupArgs] = []

    def knowledge_base_search(
        self,
        arguments: KnowledgeBaseSearchArgs,
        *,
        citation_namespace: str,
    ) -> list[Evidence]:
        self.search_calls.append((arguments, citation_namespace))
        return [
            Evidence(
                citation_id=CITATION_ID,
                paper_id="paper-ready",
                title="Grounded Paper",
                page=2,
                quote="The grounded result improved by 17 percent.",
                chunk_id="chunk-ready-2",
                retrieval_score=0.8,
                rerank_score=0.95,
            )
        ]

    def document_lookup(self, arguments: DocumentLookupArgs) -> list[DocumentMatch]:
        self.lookup_calls.append(arguments)
        return [
            DocumentMatch(
                paper_id="paper-ready",
                title="Grounded Paper",
                authors=("Researcher Example",),
                publication_year=2026,
                status="READY",
            )
        ]


def _tool_call(name: str, arguments: str, *, call_id: str = "remote-call") -> NativeToolCall:
    return NativeToolCall.model_validate(
        {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }
    )


def _prompt(run_id: str = "run-deepseek-test") -> ChatPrompt:
    return ChatPrompt(
        run_id=run_id,
        conversation_id=f"conv-{run_id}",
        assistant_message_id=f"msg-{run_id}",
        content="论文中的关键实验结果是什么？",
        paper_ids=("paper-ready",),
    )


def _provider(
    tmp_path: Path,
    gateway: ScriptedGateway,
    tools: RecordingRetrievalTools,
) -> tuple[DeepSeekToolCallingProvider, Database]:
    database = sqlite_database()
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id="paper-ready",
                sha256="a" * 64,
                title="Grounded Paper",
                authors=["Researcher Example"],
                publication_year=2026,
                original_filename="grounded.pdf",
                storage_path="C:/external/grounded.pdf",
                file_size_bytes=100,
                page_count=2,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
    provider = DeepSeekToolCallingProvider(
        gateway=gateway,
        tools=cast(RetrievalTools, tools),
        run_store=AgentRunStore(database),
        settings=runtime_settings(tmp_path),
    )
    return provider, database


async def _collect(
    provider: DeepSeekToolCallingProvider,
    prompt: ChatPrompt,
) -> list[ProviderEvent]:
    return [event async for event in provider.stream(prompt)]


def test_native_knowledge_tool_call_is_scoped_persisted_and_cited(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(
                tool_calls=[
                    _tool_call(
                        "knowledge_base_search",
                        '{"query":"result","paperIds":["paper-untrusted"],"topK":5}',
                    )
                ]
            ),
            AssistantTurn(),
        ],
        [f"The result was 17 percent [[citation:{CITATION_ID}]]."],
    )
    tools = RecordingRetrievalTools()
    provider, raw_database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt()))

    statuses = [event for event in events if isinstance(event, ToolStatus)]
    assert [event.status for event in statuses] == ["started", "completed"]
    assert all(event.tool_name == "knowledge_base_search" for event in statuses)
    assert len(tools.search_calls) == 1
    assert tools.search_calls[0][0].paper_ids == ["paper-ready"]
    assert [event.citation_id for event in events if isinstance(event, Citation)] == [CITATION_ID]
    assert [event.answer_mode for event in events if isinstance(event, AnswerCompleted)] == [
        "KNOWLEDGE_BASE"
    ]
    function_definitions = [
        cast(dict[str, object], definition["function"])
        for definition in gateway.tool_definitions[0]
    ]
    assert {definition["name"] for definition in function_definitions} == {
        "knowledge_base_search",
        "document_lookup",
    }

    with raw_database.session() as session:
        run = session.get(AgentRunRecord, "run-deepseek-test")
        assert run is not None
        assert run.status == "COMPLETED"
        assert run.answer_mode == "KNOWLEDGE_BASE"
        calls = session.query(ToolCallRecord).all()
        assert len(calls) == 1
        assert calls[0].tool_name == "knowledge_base_search"
        assert calls[0].status == "COMPLETED"
        assert calls[0].id != "remote-call"


def test_missing_citation_marker_gets_one_bounded_model_repair(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(
                tool_calls=[_tool_call("knowledge_base_search", '{"query":"result","topK":1}')]
            ),
            AssistantTurn(),
        ],
        ["The grounded result improved by 17 percent."],
        repair_fragments=[f"The result was 17 percent [[citation:{CITATION_ID}]]."],
    )
    tools = RecordingRetrievalTools()
    provider, _database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-citation-repair")))

    assert len(gateway.final_message_calls) == 2
    repair_payload = cast(str, gateway.final_message_calls[1][-1]["content"])
    assert CITATION_ID in repair_payload
    assert FORGED_CITATION_ID not in repair_payload
    assert [event.citation_id for event in events if isinstance(event, Citation)] == [CITATION_ID]
    assert [event.answer_mode for event in events if isinstance(event, AnswerCompleted)] == [
        "KNOWLEDGE_BASE"
    ]


def test_document_information_question_uses_document_lookup(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(tool_calls=[_tool_call("document_lookup", '{"query":"Grounded Paper"}')]),
            AssistantTurn(),
        ],
        ["The paper was published in 2026."],
    )
    tools = RecordingRetrievalTools()
    provider, _database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-document-lookup")))

    assert len(tools.lookup_calls) == 1
    assert tools.search_calls == []
    assert [event.answer_mode for event in events if isinstance(event, AnswerCompleted)] == [
        "DOCUMENT_LOOKUP"
    ]


def test_general_question_can_complete_without_any_tool(tmp_path: Path) -> None:
    gateway = ScriptedGateway([AssistantTurn()], ["A general model-knowledge answer."])
    tools = RecordingRetrievalTools()
    provider, _database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-no-tool")))

    assert tools.search_calls == []
    assert tools.lookup_calls == []
    assert not any(isinstance(event, ToolStatus) for event in events)
    assert [event.answer_mode for event in events if isinstance(event, AnswerCompleted)] == [
        "MODEL_KNOWLEDGE"
    ]


def test_invalid_tool_arguments_emit_safe_failure_status(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(tool_calls=[_tool_call("knowledge_base_search", "{not-valid-json")]),
            AssistantTurn(),
        ],
        ["The tool arguments were invalid."],
    )
    tools = RecordingRetrievalTools()
    provider, _database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-invalid-arguments")))

    statuses = [event for event in events if isinstance(event, ToolStatus)]
    assert [event.status for event in statuses] == ["started", "failed"]
    assert tools.search_calls == []
    assert all("argument" not in event.message.lower() for event in statuses)


def test_agent_executes_at_most_three_native_tool_rounds(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(
                tool_calls=[
                    _tool_call(
                        "knowledge_base_search",
                        '{"query":"result","topK":1}',
                        call_id="reused-remote-call",
                    )
                ]
            )
            for _index in range(4)
        ],
        [f"Bounded result [[citation:{CITATION_ID}]]."],
    )
    tools = RecordingRetrievalTools()
    provider, raw_database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-round-limit")))

    assert len(gateway.complete_messages) == 3
    assert len(tools.search_calls) == 3
    assert len([event for event in events if isinstance(event, ToolStatus)]) == 6
    with raw_database.session() as session:
        run = session.get(AgentRunRecord, "run-round-limit")
        assert run is not None
        assert run.tool_rounds == 3
        assert len(session.query(ToolCallRecord).all()) == 3


def test_forged_citation_is_removed_and_answer_is_downgraded(tmp_path: Path) -> None:
    gateway = ScriptedGateway(
        [
            AssistantTurn(
                tool_calls=[_tool_call("knowledge_base_search", '{"query":"result","topK":1}')]
            ),
            AssistantTurn(),
        ],
        [f"Unsupported claim [[citation:{FORGED_CITATION_ID}]]."],
    )
    tools = RecordingRetrievalTools()
    provider, _database = _provider(tmp_path, gateway, tools)

    events = asyncio.run(_collect(provider, _prompt("run-forged-citation")))

    answer = "".join(event.delta for event in events if isinstance(event, MessageDelta))
    assert FORGED_CITATION_ID not in answer
    assert answer.startswith("未能生成可验证的论文引用")
    assert not any(isinstance(event, Citation) for event in events)
    assert [event.answer_mode for event in events if isinstance(event, AnswerCompleted)] == [
        "MODEL_KNOWLEDGE"
    ]
