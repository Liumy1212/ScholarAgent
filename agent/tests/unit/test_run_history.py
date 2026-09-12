import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tests.support import sqlite_database

from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.domain.chat import ChatPrompt
from airesearcher_agent.persistence.models import AgentRunRecord, utc_now


def prompt(index: int, conversation: str = "conversation") -> ChatPrompt:
    return ChatPrompt(
        run_id=f"run-{index:03}",
        conversation_id=conversation,
        assistant_message_id=f"assistant-{index}",
        content=f"question-{index}",
        paper_ids=(),
    )


def test_history_is_successful_complete_pairs_in_stable_order() -> None:
    database = sqlite_database()
    store = AgentRunStore(database)
    now = utc_now()
    for index in range(15):
        current = prompt(index)
        store.start(current, model_name="fake")
        store.complete(
            current,
            answer=f"answer-{index}",
            answer_mode="MODEL_KNOWLEDGE",
            tool_rounds=0,
            citations=[],
        )
        with database.transaction() as session:
            run = session.get(AgentRunRecord, current.run_id)
            assert run is not None
            run.created_at = now
    store.start(prompt(20), model_name="fake")
    store.fail("run-020", code="RUN_CANCELLED", message="cancelled", tool_rounds=0)
    store.start(prompt(21), model_name="fake")
    isolated = prompt(22, "other")
    store.start(isolated, model_name="fake")
    store.complete(
        isolated, answer="unrelated", answer_mode="MODEL_KNOWLEDGE", tool_rounds=0, citations=[]
    )
    history = store.start(prompt(23), model_name="fake")
    assert [(turn.user_content, turn.assistant_content) for turn in history] == [
        (f"question-{index}", f"answer-{index}") for index in range(5, 15)
    ]
    with database.session() as session:
        assert len(store.read_history(session, prompt(14))) == 10
        assert "question-14" not in [
            turn.user_content for turn in store.read_history(session, prompt(14))
        ]


def test_history_serialized_budget_preserves_contiguous_complete_turns(tmp_path: Path) -> None:
    from tests.unit.test_deepseek_provider import (
        RecordingRetrievalTools,
        ScriptedGateway,
        _provider,
    )

    from airesearcher_agent.domain.chat import HistoryTurn

    provider, _ = _provider(tmp_path, ScriptedGateway([], []), RecordingRetrievalTools())
    current = prompt(50)
    small = HistoryTurn('question with "escapes"', "answer")
    pair = provider._history_messages((small,), current)
    serialized = json.dumps(pair, ensure_ascii=False, separators=(",", ":"))
    exact = replace(small, assistant_content="answer" + "x" * (24_000 - len(serialized)))
    assert len(provider._history_messages((exact,), current)) == 2
    oversized = replace(exact, assistant_content=exact.assistant_content + "x")
    assert provider._history_messages((small, oversized), current) == []
    assert provider._history_messages((small, oversized, small), current) == pair


def test_history_failure_rolls_back_start(monkeypatch: pytest.MonkeyPatch) -> None:
    database = sqlite_database()
    store = AgentRunStore(database)

    def fail_read(*args: object) -> None:
        raise SQLAlchemyError("synthetic database failure")

    monkeypatch.setattr(store, "read_history", fail_read)
    with pytest.raises(SQLAlchemyError):
        store.start(prompt(1), model_name="fake")
    with database.session() as session:
        assert session.get(AgentRunRecord, "run-001") is None
