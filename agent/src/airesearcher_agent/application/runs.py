from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from airesearcher_agent.domain.chat import AnswerMode, ChatPrompt, HistoryTurn
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    AgentRunRecord,
    CitationSnapshotRecord,
    ConversationRecord,
    MessageRecord,
    ToolCallRecord,
    utc_now,
)
from airesearcher_agent.retrieval.models import Evidence


class AgentRunStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def read_history(self, session: Session, prompt: ChatPrompt) -> tuple[HistoryTurn, ...]:
        user = aliased(MessageRecord)
        assistant = aliased(MessageRecord)
        rows = session.execute(
            select(user.content, assistant.content)
            .select_from(AgentRunRecord)
            .join(user, AgentRunRecord.user_message_id == user.id)
            .join(assistant, AgentRunRecord.assistant_message_id == assistant.id)
            .where(
                AgentRunRecord.conversation_id == prompt.conversation_id,
                AgentRunRecord.status == "COMPLETED",
                AgentRunRecord.id != prompt.run_id,
                AgentRunRecord.scope_key == prompt.scope_key,
                user.conversation_id == prompt.conversation_id,
                assistant.conversation_id == prompt.conversation_id,
                user.role == "user",
                assistant.role == "assistant",
            )
            .order_by(AgentRunRecord.created_at.desc(), AgentRunRecord.id.desc())
            .limit(10)
        ).all()
        return tuple(HistoryTurn(row[0], row[1]) for row in reversed(rows))

    def start(self, prompt: ChatPrompt, *, model_name: str) -> tuple[HistoryTurn, ...]:
        now = utc_now()
        with self._database.transaction() as session:
            history = self.read_history(session, prompt)
            conversation = session.get(ConversationRecord, prompt.conversation_id)
            if conversation is None:
                session.add(ConversationRecord(id=prompt.conversation_id, created_at=now))
                session.flush()
            user_message_id = f"msg-user-{uuid4().hex}"
            session.add(
                MessageRecord(
                    id=user_message_id,
                    conversation_id=prompt.conversation_id,
                    role="user",
                    content=prompt.content,
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                AgentRunRecord(
                    id=prompt.run_id,
                    conversation_id=prompt.conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=prompt.assistant_message_id,
                    status="RUNNING",
                    answer_mode=None,
                    model_name=model_name,
                    tool_rounds=0,
                    error_code=None,
                    error_message=None,
                    scope_type=prompt.scope_type,
                    scope_key=prompt.scope_key,
                    scope_id=prompt.scope_id,
                    paper_ids_snapshot=list(prompt.paper_ids),
                    created_at=now,
                    completed_at=None,
                )
            )

        return history

    def start_tool_call(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> None:
        with self._database.transaction() as session:
            session.add(
                ToolCallRecord(
                    id=tool_call_id,
                    run_id=run_id,
                    tool_name=tool_name,
                    arguments=cast(dict[str, Any], arguments),
                    status="STARTED",
                    error_code=None,
                    created_at=utc_now(),
                    completed_at=None,
                )
            )

    def finish_tool_call(
        self,
        *,
        tool_call_id: str,
        status: str,
        error_code: str | None = None,
    ) -> None:
        with self._database.transaction() as session:
            tool_call = self._required_tool_call(session, tool_call_id)
            tool_call.status = status
            tool_call.error_code = error_code
            tool_call.completed_at = utc_now()

    def complete(
        self,
        prompt: ChatPrompt,
        *,
        answer: str,
        answer_mode: AnswerMode,
        tool_rounds: int,
        citations: list[Evidence],
    ) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            run = self._required_run(session, prompt.run_id)
            session.add(
                MessageRecord(
                    id=prompt.assistant_message_id,
                    conversation_id=prompt.conversation_id,
                    role="assistant",
                    content=answer,
                    created_at=now,
                )
            )
            session.flush()
            for citation in citations:
                session.add(
                    CitationSnapshotRecord(
                        id=citation.citation_id,
                        run_id=prompt.run_id,
                        assistant_message_id=prompt.assistant_message_id,
                        paper_id=citation.paper_id,
                        paper_title=citation.title,
                        page_number=citation.page,
                        quote=citation.quote,
                        chunk_id=citation.chunk_id,
                        created_at=now,
                    )
                )
            run.status = "COMPLETED"
            run.answer_mode = answer_mode
            run.tool_rounds = tool_rounds
            run.error_code = None
            run.error_message = None
            run.completed_at = now

    def fail(self, run_id: str, *, code: str, message: str, tool_rounds: int) -> None:
        with self._database.transaction() as session:
            run = session.get(AgentRunRecord, run_id)
            if run is None:
                return
            run.status = "FAILED"
            run.tool_rounds = tool_rounds
            run.error_code = code[:128]
            run.error_message = message[:2048]
            run.completed_at = utc_now()

    def _required_run(self, session: Session, run_id: str) -> AgentRunRecord:
        run = session.get(AgentRunRecord, run_id, with_for_update=True)
        if run is None:
            raise RuntimeError("agent run does not exist")
        return run

    def _required_tool_call(self, session: Session, tool_call_id: str) -> ToolCallRecord:
        tool_call = session.get(ToolCallRecord, tool_call_id, with_for_update=True)
        if tool_call is None:
            raise RuntimeError("tool call does not exist")
        return tool_call
