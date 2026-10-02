from datetime import UTC, timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tests.support import sqlite_database

from airesearcher_agent.application.conversations import ConversationService
from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.domain.chat import ChatPrompt
from airesearcher_agent.persistence.models import (
    AgentRunRecord,
    CitationSnapshotRecord,
    ToolCallRecord,
    utc_now,
)


def _complete(
    store: AgentRunStore,
    index: int,
    *,
    conversation_id: str = "conversation",
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


def test_lists_only_completed_runs_and_uses_latest_scope() -> None:
    database = sqlite_database()
    store = AgentRunStore(database)
    older = _complete(store, 1, scope_type="ALL", scope_key="ALL")
    latest = _complete(
        store,
        2,
        scope_type="PAPERS",
        scope_key="PAPERS:paper-1",
        paper_ids=("paper-1",),
        request_id="request-2",
    )
    failed = ChatPrompt(
        run_id="run-failed",
        conversation_id="conversation",
        assistant_message_id="assistant-failed",
        content="failed question",
        paper_ids=("paper-1",),
        scope_type="PAPERS",
        scope_key="PAPERS:paper-1",
    )
    store.start(failed, model_name="fake")
    store.fail(failed.run_id, code="RUN_CANCELLED", message="cancelled", tool_rounds=0)
    with database.transaction() as session:
        old_run = session.get(AgentRunRecord, older.run_id)
        new_run = session.get(AgentRunRecord, latest.run_id)
        assert old_run is not None and new_run is not None
        old_run.completed_at = utc_now() - timedelta(minutes=1)
        new_run.completed_at = utc_now()

    page = ConversationService(database).list_conversations(offset=0, limit=50)

    assert page.total == 1
    assert page.items[0].title == "question 1"
    assert page.items[0].preview == "answer 2"
    assert page.items[0].turn_count == 1
    assert page.items[0].scope.type == "PAPERS"
    assert page.items[0].scope.paper_ids == ("paper-1",)
    assert page.items[0].created_at.tzinfo is UTC
    assert page.items[0].updated_at.tzinfo is UTC


def test_detail_restores_latest_100_turns_tools_and_nullable_snapshots() -> None:
    database = sqlite_database()
    store = AgentRunStore(database)
    prompts = [_complete(store, index) for index in range(102)]
    latest = prompts[-1]
    with database.transaction() as session:
        session.add(
            ToolCallRecord(
                id="tool-history",
                run_id=latest.run_id,
                tool_name="knowledge_base_search",
                arguments={},
                status="COMPLETED",
                error_code=None,
            )
        )
        session.add(
            CitationSnapshotRecord(
                id="citation-history",
                run_id=latest.run_id,
                assistant_message_id=latest.assistant_message_id,
                paper_id=None,
                paper_title="deleted paper",
                page_number=7,
                quote="historical evidence",
                chunk_id="chunk-history",
            )
        )

    detail = ConversationService(database).get_conversation("conversation")

    assert detail.total_turns == 102
    assert detail.truncated is True
    assert len(detail.turns) == 100
    assert detail.turns[0].question == "  question   2  "
    assert detail.turns[-1].request_id is None
    assert detail.turns[-1].tools[0].tool_call_id == "tool-history"
    assert detail.turns[-1].citations[0].paper_id is None
    assert detail.turns[-1].citations[0].quote == "historical evidence"
    assert detail.turns[-1].created_at.tzinfo is UTC
    assert detail.turns[-1].completed_at.tzinfo is UTC


def test_list_uses_conversation_id_as_stable_completion_tie_breaker() -> None:
    database = sqlite_database()
    store = AgentRunStore(database)
    second = _complete(store, 1, conversation_id="conversation-b")
    first = _complete(store, 1, conversation_id="conversation-a")
    tied_at = utc_now()
    with database.transaction() as session:
        for run_id in (first.run_id, second.run_id):
            run = session.get(AgentRunRecord, run_id)
            assert run is not None
            run.completed_at = tied_at

    page = ConversationService(database).list_conversations(offset=0, limit=50)

    assert [item.conversation_id for item in page.items] == [
        "conversation-a",
        "conversation-b",
    ]


def test_legacy_scope_and_missing_request_id_remain_readable() -> None:
    database = sqlite_database()
    _complete(
        AgentRunStore(database),
        1,
        conversation_id="legacy-conversation",
        scope_type="LEGACY",
        scope_key="LEGACY",
    )

    detail = ConversationService(database).get_conversation("legacy-conversation")

    assert detail.conversation.scope.type == "LEGACY"
    assert detail.turns[0].request_id is None


def test_missing_conversation_and_database_failure_are_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = sqlite_database()
    service = ConversationService(database)
    with pytest.raises(AgentError) as missing:
        service.get_conversation("missing")
    assert missing.value.status_code == 404
    assert missing.value.code == "CONVERSATION_NOT_FOUND"

    def fail(*args: object, **kwargs: object) -> list[object]:
        raise SQLAlchemyError("synthetic database failure")

    monkeypatch.setattr(service, "_completed_rows", fail)
    with pytest.raises(AgentError) as unavailable:
        service.list_conversations(offset=0, limit=50)
    assert unavailable.value.status_code == 503
    assert unavailable.value.code == "DATABASE_UNAVAILABLE"
