import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tests.support import RecordingVectorStore, runtime_settings, sqlite_database

from airesearcher_agent.application.conversations import ConversationService
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.library_lifecycle import LibraryLifecycleService
from airesearcher_agent.application.library_scans import LibraryScanService
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.application.runtime import RuntimeServices
from airesearcher_agent.application.stream_chat import StreamChatUseCase
from airesearcher_agent.domain.chat import ChatPrompt
from airesearcher_agent.main import create_app
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    AgentRunRecord,
    CitationSnapshotRecord,
    ToolCallRecord,
    utc_now,
)
from airesearcher_agent.providers.fake import FakeChatProvider


def _build_app(tmp_path: Path) -> tuple[Database, FastAPI]:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    library_files = LibraryFileService(database=database, settings=settings)
    vectors = RecordingVectorStore()
    lifecycle = LibraryLifecycleService(
        database=database,
        settings=settings,
        vector_store=vectors,
        library_file_service=library_files,
    )
    provider = FakeChatProvider()
    runtime = RuntimeServices(
        settings=settings,
        database=database,
        library_file_service=library_files,
        library_lifecycle_service=lifecycle,
        library_scan_service=LibraryScanService(
            database=database,
            settings=settings,
            library_file_service=library_files,
        ),
        paper_service=PaperService(
            database=database,
            settings=settings,
            vector_store=vectors,
            library_file_service=library_files,
            library_lifecycle_service=lifecycle,
        ),
        stream_chat=StreamChatUseCase(provider),
        conversation_service=ConversationService(database),
    )
    return database, create_app(provider, runtime=runtime)


def _complete(
    store: AgentRunStore,
    index: int,
    *,
    conversation_id: str,
    scope_type: str = "ALL",
    scope_key: str = "ALL",
    paper_ids: tuple[str, ...] = (),
    request_id: str | None = None,
) -> ChatPrompt:
    prompt = ChatPrompt(
        run_id=f"run-{conversation_id}-{index:03}",
        conversation_id=conversation_id,
        assistant_message_id=f"assistant-{conversation_id}-{index:03}",
        content=f"  question   {index}  ",
        paper_ids=paper_ids,
        scope_type=scope_type,
        scope_key=scope_key,
        request_id=request_id,
    )
    store.start(prompt, model_name="fake")
    store.complete(
        prompt,
        answer=f" answer {index} [[citation:citation-{index}]] ",
        answer_mode="KNOWLEDGE_BASE",
        tool_rounds=0,
        citations=[],
    )
    return prompt


def test_list_conversations_returns_contract_page_and_echoes_request_id(tmp_path: Path) -> None:
    async def exercise() -> None:
        database, app = _build_app(tmp_path)
        store = AgentRunStore(database)
        early = _complete(store, 1, conversation_id="conversation-a")
        late = _complete(
            store,
            2,
            conversation_id="conversation-b",
            scope_type="PAPERS",
            scope_key="PAPERS:paper-1",
            paper_ids=("paper-1",),
            request_id="request-2",
        )
        with database.transaction() as session:
            early_run = session.get(AgentRunRecord, early.run_id)
            late_run = session.get(AgentRunRecord, late.run_id)
            assert early_run is not None and late_run is not None
            early_run.completed_at = utc_now() - timedelta(minutes=1)
            late_run.completed_at = utc_now()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get(
                "/agent-api/v1/conversations?offset=0&limit=50",
                headers={"X-Request-Id": "req-list-001"},
            )

        assert response.status_code == 200
        assert response.headers["X-Request-Id"] == "req-list-001"
        body = response.json()
        assert body["total"] == 2
        assert body["offset"] == 0
        assert body["limit"] == 50
        assert [item["conversationId"] for item in body["items"]] == [
            "conversation-b",
            "conversation-a",
        ]
        summary = body["items"][0]
        assert set(summary) == {
            "conversationId",
            "title",
            "preview",
            "scope",
            "turnCount",
            "createdAt",
            "updatedAt",
        }
        assert summary["title"] == "question 2"
        assert summary["preview"] == "answer 2"
        assert summary["turnCount"] == 1
        assert summary["scope"] == {
            "type": "PAPERS",
            "scopeId": None,
            "paperIds": ["paper-1"],
        }

    asyncio.run(exercise())


def test_conversation_detail_returns_turns_and_echoes_request_id(tmp_path: Path) -> None:
    async def exercise() -> None:
        database, app = _build_app(tmp_path)
        store = AgentRunStore(database)
        first = _complete(store, 1, conversation_id="conversation-api")
        second = _complete(
            store,
            2,
            conversation_id="conversation-api",
            request_id="request-2",
        )
        with database.transaction() as session:
            first_run = session.get(AgentRunRecord, first.run_id)
            second_run = session.get(AgentRunRecord, second.run_id)
            assert first_run is not None and second_run is not None
            first_run.completed_at = utc_now() - timedelta(minutes=1)
            second_run.completed_at = utc_now()
            session.add(
                ToolCallRecord(
                    id="tool-api",
                    run_id=second.run_id,
                    tool_name="knowledge_base_search",
                    arguments={},
                    status="COMPLETED",
                    error_code=None,
                )
            )
            session.add(
                CitationSnapshotRecord(
                    id="citation-api",
                    run_id=second.run_id,
                    assistant_message_id=second.assistant_message_id,
                    paper_id=None,
                    paper_title="deleted paper",
                    page_number=7,
                    quote="historical evidence",
                    chunk_id="chunk-history",
                )
            )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get(
                "/agent-api/v1/conversations/conversation-api",
                headers={"X-Request-Id": "req-detail-001"},
            )

        assert response.status_code == 200
        assert response.headers["X-Request-Id"] == "req-detail-001"
        body = response.json()
        assert body["conversation"]["conversationId"] == "conversation-api"
        assert body["conversation"]["turnCount"] == 2
        assert body["totalTurns"] == 2
        assert body["truncated"] is False
        assert [turn["runId"] for turn in body["turns"]] == [first.run_id, second.run_id]
        oldest, newest = body["turns"]
        assert set(newest) == {
            "runId",
            "requestId",
            "assistantMessageId",
            "question",
            "answer",
            "answerMode",
            "tools",
            "citations",
            "createdAt",
            "completedAt",
        }
        assert oldest["requestId"] is None
        assert newest["requestId"] == "request-2"
        assert newest["assistantMessageId"] == second.assistant_message_id
        assert newest["question"] == "  question   2  "
        assert newest["answer"] == " answer 2 [[citation:citation-2]] "
        assert newest["answerMode"] == "KNOWLEDGE_BASE"
        assert newest["tools"] == [
            {
                "toolCallId": "tool-api",
                "toolName": "knowledge_base_search",
                "status": "COMPLETED",
                "errorCode": None,
            }
        ]
        assert newest["citations"] == [
            {
                "citationId": "citation-api",
                "paperId": None,
                "paperTitle": "deleted paper",
                "pageNumber": 7,
                "quote": "historical evidence",
                "chunkId": "chunk-history",
            }
        ]

    asyncio.run(exercise())


def test_missing_conversation_returns_404_contract_error(tmp_path: Path) -> None:
    async def exercise() -> None:
        _database, app = _build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get(
                "/agent-api/v1/conversations/conv-missing",
                headers={"X-Request-Id": "req-missing-001"},
            )

        assert response.status_code == 404
        assert response.headers["X-Request-Id"] == "req-missing-001"
        body = response.json()
        assert body["code"] == "CONVERSATION_NOT_FOUND"
        assert body["requestId"] == "req-missing-001"
        assert body["retryable"] is False

    asyncio.run(exercise())


@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=201"])
def test_invalid_pagination_rejected_with_400(tmp_path: Path, query: str) -> None:
    async def exercise() -> None:
        _database, app = _build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get(
                f"/agent-api/v1/conversations?{query}",
                headers={"X-Request-Id": "req-pagination-001"},
            )

        assert response.status_code == 400
        assert response.headers["X-Request-Id"] == "req-pagination-001"
        body = response.json()
        assert body["code"] == "INVALID_REQUEST"
        assert body["requestId"] == "req-pagination-001"
        assert body["details"]

    asyncio.run(exercise())


def test_missing_request_id_header_rejected_with_400(tmp_path: Path) -> None:
    async def exercise() -> None:
        _database, app = _build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get("/agent-api/v1/conversations")

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "INVALID_REQUEST"
        assert body["requestId"] == response.headers["X-Request-Id"]
        assert body["requestId"].startswith("req-")

    asyncio.run(exercise())


def test_oversized_conversation_id_rejected_with_400(tmp_path: Path) -> None:
    async def exercise() -> None:
        _database, app = _build_app(tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            response = await client.get(
                f"/agent-api/v1/conversations/{'a' * 129}",
                headers={"X-Request-Id": "req-oversized-001"},
            )

        assert response.status_code == 400
        assert response.headers["X-Request-Id"] == "req-oversized-001"
        assert response.json()["code"] == "INVALID_REQUEST"

    asyncio.run(exercise())
