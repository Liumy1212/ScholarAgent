import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    AgentRunRecord,
    CitationSnapshotRecord,
    MessageRecord,
    ToolCallRecord,
)

ConversationScopeType = Literal["ALL", "KNOWLEDGE_BASE", "PAPERS", "LEGACY"]
_KNOWN_SCOPE_TYPES = {"ALL", "KNOWLEDGE_BASE", "PAPERS", "LEGACY"}
_CITATION_MARKER = re.compile(r"\[\[citation:[^\]]+\]\]")


@dataclass(frozen=True, slots=True)
class ConversationScopeView:
    type: ConversationScopeType
    scope_id: str | None
    paper_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversationToolCallView:
    tool_call_id: str
    tool_name: str
    status: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ConversationCitationView:
    citation_id: str
    paper_id: str | None
    paper_title: str
    page_number: int
    quote: str
    chunk_id: str


@dataclass(frozen=True, slots=True)
class ConversationTurnView:
    run_id: str
    request_id: str | None
    assistant_message_id: str
    question: str
    answer: str
    answer_mode: str
    tools: tuple[ConversationToolCallView, ...]
    citations: tuple[ConversationCitationView, ...]
    created_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationSummaryView:
    conversation_id: str
    title: str
    preview: str
    scope: ConversationScopeView
    turn_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationsPageView:
    items: tuple[ConversationSummaryView, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class ConversationDetailView:
    conversation: ConversationSummaryView
    turns: tuple[ConversationTurnView, ...]
    total_turns: int
    truncated: bool


type CompletedRow = tuple[AgentRunRecord, MessageRecord, MessageRecord]


class ConversationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_conversations(self, *, offset: int, limit: int) -> ConversationsPageView:
        try:
            with self._database.session() as session:
                completed = self._completed_rows(session)
                grouped = self._group_latest_scope(completed)
                first_by_conversation = {row[0].conversation_id: row for row in completed}
                summaries = tuple(
                    self._summary(rows, first_by_conversation[conversation_id])
                    for conversation_id, rows in grouped.items()
                )
                summaries = tuple(
                    sorted(
                        summaries,
                        key=lambda summary: (
                            -summary.updated_at.timestamp(),
                            summary.conversation_id,
                        ),
                    )
                )
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error
        return ConversationsPageView(
            items=summaries[offset : offset + limit],
            total=len(summaries),
            offset=offset,
            limit=limit,
        )

    def get_conversation(self, conversation_id: str) -> ConversationDetailView:
        try:
            with self._database.session() as session:
                rows = self._completed_rows(session, conversation_id=conversation_id)
                grouped = self._group_latest_scope(rows)
                selected = grouped.get(conversation_id)
                if not selected:
                    raise AgentError(
                        status_code=404,
                        code="CONVERSATION_NOT_FOUND",
                        message="未找到包含成功问答的会话。",
                    )
                total_turns = len(selected)
                visible = selected[:100]
                run_ids = [run.id for run, _user, _assistant in visible]
                tools_by_run = self._tools_by_run(session, run_ids)
                citations_by_run = self._citations_by_run(session, run_ids)
                turns = tuple(
                    self._turn(run, user, assistant, tools_by_run, citations_by_run)
                    for run, user, assistant in reversed(visible)
                )
                return ConversationDetailView(
                    conversation=self._summary(selected, rows[-1]),
                    turns=turns,
                    total_turns=total_turns,
                    truncated=total_turns > len(visible),
                )
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    @staticmethod
    def _completed_rows(session: Session, conversation_id: str | None = None) -> list[CompletedRow]:
        user = aliased(MessageRecord)
        assistant = aliased(MessageRecord)
        statement = (
            select(AgentRunRecord, user, assistant)
            .join(user, AgentRunRecord.user_message_id == user.id)
            .join(assistant, AgentRunRecord.assistant_message_id == assistant.id)
            .where(
                AgentRunRecord.status == "COMPLETED",
                AgentRunRecord.completed_at.is_not(None),
                user.role == "user",
                assistant.role == "assistant",
            )
            .order_by(
                AgentRunRecord.completed_at.desc(),
                AgentRunRecord.id.desc(),
            )
        )
        if conversation_id is not None:
            statement = statement.where(AgentRunRecord.conversation_id == conversation_id)
        return [cast(CompletedRow, tuple(row)) for row in session.execute(statement).all()]

    @staticmethod
    def _group_latest_scope(rows: list[CompletedRow]) -> dict[str, list[CompletedRow]]:
        selected_scope: dict[str, str] = {}
        grouped: dict[str, list[CompletedRow]] = {}
        for row in rows:
            run = row[0]
            scope_key = selected_scope.setdefault(run.conversation_id, run.scope_key)
            if run.scope_key == scope_key:
                grouped.setdefault(run.conversation_id, []).append(row)
        return grouped

    def _summary(
        self,
        rows: list[CompletedRow],
        first_completed: CompletedRow,
    ) -> ConversationSummaryView:
        latest_run, _latest_user, latest_assistant = rows[0]
        first_run, first_user, _first_assistant = first_completed
        completed_at = latest_run.completed_at
        if completed_at is None:
            raise RuntimeError("completed run is missing completed_at")
        return ConversationSummaryView(
            conversation_id=latest_run.conversation_id,
            title=self._snippet(first_user.content, 80, fallback="历史会话"),
            preview=self._snippet(
                _CITATION_MARKER.sub("", latest_assistant.content),
                160,
                fallback="已完成回答",
            ),
            scope=self._scope(latest_run),
            turn_count=len(rows),
            created_at=self._as_utc(first_run.created_at),
            updated_at=self._as_utc(completed_at),
        )

    @staticmethod
    def _scope(run: AgentRunRecord) -> ConversationScopeView:
        scope_type = run.scope_type if run.scope_type in _KNOWN_SCOPE_TYPES else "LEGACY"
        return ConversationScopeView(
            type=scope_type,  # type: ignore[arg-type]
            scope_id=run.scope_id,
            paper_ids=tuple(run.paper_ids_snapshot),
        )

    @staticmethod
    def _snippet(value: str, limit: int, *, fallback: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            return fallback
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"

    @staticmethod
    def _tools_by_run(
        session: Session,
        run_ids: list[str],
    ) -> dict[str, tuple[ConversationToolCallView, ...]]:
        grouped: dict[str, list[ConversationToolCallView]] = {run_id: [] for run_id in run_ids}
        if not run_ids:
            return {}
        records = session.scalars(
            select(ToolCallRecord)
            .where(ToolCallRecord.run_id.in_(run_ids))
            .order_by(ToolCallRecord.created_at, ToolCallRecord.id)
        ).all()
        for record in records:
            grouped[record.run_id].append(
                ConversationToolCallView(
                    tool_call_id=record.id,
                    tool_name=record.tool_name,
                    status=record.status,
                    error_code=record.error_code,
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    @staticmethod
    def _citations_by_run(
        session: Session,
        run_ids: list[str],
    ) -> dict[str, tuple[ConversationCitationView, ...]]:
        grouped: dict[str, list[ConversationCitationView]] = {run_id: [] for run_id in run_ids}
        if not run_ids:
            return {}
        records = session.scalars(
            select(CitationSnapshotRecord)
            .where(CitationSnapshotRecord.run_id.in_(run_ids))
            .order_by(CitationSnapshotRecord.created_at, CitationSnapshotRecord.id)
        ).all()
        for record in records:
            grouped[record.run_id].append(
                ConversationCitationView(
                    citation_id=record.id,
                    paper_id=record.paper_id,
                    paper_title=record.paper_title,
                    page_number=record.page_number,
                    quote=record.quote,
                    chunk_id=record.chunk_id,
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    @staticmethod
    def _turn(
        run: AgentRunRecord,
        user: MessageRecord,
        assistant: MessageRecord,
        tools_by_run: dict[str, tuple[ConversationToolCallView, ...]],
        citations_by_run: dict[str, tuple[ConversationCitationView, ...]],
    ) -> ConversationTurnView:
        if run.completed_at is None or run.answer_mode is None:
            raise RuntimeError("completed run is missing completion metadata")
        return ConversationTurnView(
            run_id=run.id,
            request_id=run.request_id,
            assistant_message_id=run.assistant_message_id,
            question=user.content,
            answer=assistant.content,
            answer_mode=run.answer_mode,
            tools=tools_by_run.get(run.id, ()),
            citations=citations_by_run.get(run.id, ()),
            created_at=ConversationService._as_utc(run.created_at),
            completed_at=ConversationService._as_utc(run.completed_at),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _database_unavailable() -> AgentError:
        return AgentError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="会话数据库暂时不可用，请稍后重试。",
            retryable=True,
        )
