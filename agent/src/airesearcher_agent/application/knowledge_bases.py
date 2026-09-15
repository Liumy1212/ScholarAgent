import unicodedata
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from airesearcher_agent.application.errors import AgentError, ErrorDetail
from airesearcher_agent.domain.knowledge_bases import (
    DeleteKnowledgeBaseView,
    KnowledgeBaseMembersUpdateView,
    KnowledgeBasePapersPageView,
    KnowledgeBasesPageView,
    KnowledgeBaseView,
    ResolvedChatScope,
)
from airesearcher_agent.domain.papers import PaperSourceStatus, PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    KnowledgeBasePaperRecord,
    KnowledgeBaseRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.persistence.repositories import as_utc, paper_view, ready_paper_ids


class KnowledgeBaseService:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def normalize_name(value: str) -> tuple[str, str]:
        name = unicodedata.normalize("NFC", value.strip())
        if not 1 <= len(name) <= 100 or any(unicodedata.category(char) == "Cc" for char in name):
            raise AgentError(
                status_code=400,
                code="INVALID_REQUEST",
                message="知识库名称必须包含 1 到 100 个非控制字符。",
                details=(ErrorDetail(field="name", reason="invalid knowledge base name"),),
            )
        return name, name.casefold()

    def list(self, offset: int, limit: int) -> KnowledgeBasesPageView:
        with self._database.session() as session:
            total = int(session.scalar(select(func.count()).select_from(KnowledgeBaseRecord)) or 0)
            records = session.scalars(
                select(KnowledgeBaseRecord)
                .order_by(KnowledgeBaseRecord.created_at.desc(), KnowledgeBaseRecord.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            items = tuple(self._view(session, item) for item in records)
        return KnowledgeBasesPageView(items=items, total=total, offset=offset, limit=limit)

    def get(self, knowledge_base_id: str) -> KnowledgeBaseView:
        with self._database.session() as session:
            return self._view(session, self._required(session, knowledge_base_id))

    def create(self, raw_name: str) -> KnowledgeBaseView:
        name, name_key = self.normalize_name(raw_name)
        now = utc_now()
        try:
            with self._database.transaction() as session:
                record = KnowledgeBaseRecord(
                    id=f"kb-{uuid4().hex}",
                    name=name,
                    name_key=name_key,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                session.flush()
                return self._view(session, record)
        except IntegrityError as error:
            raise self._name_conflict() from error

    def rename(self, knowledge_base_id: str, raw_name: str) -> KnowledgeBaseView:
        name, name_key = self.normalize_name(raw_name)
        try:
            with self._database.transaction() as session:
                record = self._required(session, knowledge_base_id, lock=True)
                record.name = name
                record.name_key = name_key
                record.updated_at = utc_now()
                session.flush()
                return self._view(session, record)
        except IntegrityError as error:
            raise self._name_conflict() from error

    def delete(self, knowledge_base_id: str) -> DeleteKnowledgeBaseView:
        with self._database.transaction() as session:
            record = self._required(session, knowledge_base_id, lock=True)
            session.delete(record)
        return DeleteKnowledgeBaseView(knowledge_base_id=knowledge_base_id)

    def list_papers(
        self, knowledge_base_id: str, offset: int, limit: int
    ) -> KnowledgeBasePapersPageView:
        with self._database.session() as session:
            self._required(session, knowledge_base_id)
            predicate = KnowledgeBasePaperRecord.knowledge_base_id == knowledge_base_id
            total = int(
                session.scalar(
                    select(func.count()).select_from(KnowledgeBasePaperRecord).where(predicate)
                )
                or 0
            )
            papers = session.scalars(
                select(PaperRecord)
                .join(KnowledgeBasePaperRecord, KnowledgeBasePaperRecord.paper_id == PaperRecord.id)
                .where(predicate)
                .order_by(PaperRecord.created_at.desc(), PaperRecord.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            items = tuple(paper_view(session, paper) for paper in papers)
        return KnowledgeBasePapersPageView(items=items, total=total, offset=offset, limit=limit)

    def update_members(
        self, knowledge_base_id: str, add_ids: tuple[str, ...], remove_ids: tuple[str, ...]
    ) -> KnowledgeBaseMembersUpdateView:
        with self._database.transaction() as session:
            knowledge_base = self._required(session, knowledge_base_id, lock=True)
            requested = set(add_ids) | set(remove_ids)
            existing_papers = (
                set(
                    session.scalars(
                        select(PaperRecord.id).where(PaperRecord.id.in_(requested))
                    ).all()
                )
                if requested
                else set()
            )
            missing = sorted(requested - existing_papers)
            if missing:
                raise AgentError(
                    status_code=404,
                    code="PAPER_NOT_FOUND",
                    message="未找到指定论文。",
                )
            existing_members = (
                set(
                    session.scalars(
                        select(KnowledgeBasePaperRecord.paper_id).where(
                            KnowledgeBasePaperRecord.knowledge_base_id == knowledge_base_id,
                            KnowledgeBasePaperRecord.paper_id.in_(add_ids),
                        )
                    ).all()
                )
                if add_ids
                else set()
            )
            added = tuple(item for item in add_ids if item not in existing_members)
            for paper_id in added:
                session.add(
                    KnowledgeBasePaperRecord(
                        knowledge_base_id=knowledge_base_id,
                        paper_id=paper_id,
                    )
                )
            if remove_ids:
                removed = tuple(
                    session.scalars(
                        select(KnowledgeBasePaperRecord.paper_id).where(
                            KnowledgeBasePaperRecord.knowledge_base_id == knowledge_base_id,
                            KnowledgeBasePaperRecord.paper_id.in_(remove_ids),
                        )
                    ).all()
                )
                session.execute(
                    delete(KnowledgeBasePaperRecord).where(
                        KnowledgeBasePaperRecord.knowledge_base_id == knowledge_base_id,
                        KnowledgeBasePaperRecord.paper_id.in_(remove_ids),
                    )
                )
            else:
                removed = ()
            knowledge_base.updated_at = utc_now()
            session.flush()
            view = self._view(session, knowledge_base)
        return KnowledgeBaseMembersUpdateView(view, added, removed)

    def resolve_chat_scope(
        self, *, knowledge_base_id: str | None, paper_ids: tuple[str, ...]
    ) -> ResolvedChatScope:
        if knowledge_base_id is not None and paper_ids:
            raise AgentError(
                status_code=400,
                code="INVALID_REQUEST",
                message="knowledgeBaseId 与 paperIds 不能同时指定。",
            )
        with self._database.session() as session:
            if knowledge_base_id is not None:
                self._required(session, knowledge_base_id)
                member_ids = tuple(
                    session.scalars(
                        select(KnowledgeBasePaperRecord.paper_id).where(
                            KnowledgeBasePaperRecord.knowledge_base_id == knowledge_base_id
                        )
                    ).all()
                )
                resolved = ready_paper_ids(session, member_ids, allow_all=False)
                if not resolved:
                    raise AgentError(
                        status_code=409,
                        code="KNOWLEDGE_BASE_NOT_SEARCHABLE",
                        message="该知识库当前没有可检索论文。",
                    )
                return ResolvedChatScope(
                    "KNOWLEDGE_BASE",
                    f"KNOWLEDGE_BASE:{knowledge_base_id}",
                    knowledge_base_id,
                    resolved,
                )
            if paper_ids:
                resolved = ready_paper_ids(session, paper_ids, allow_all=False)
                return ResolvedChatScope(
                    "PAPERS",
                    "PAPERS:" + ",".join(sorted(paper_ids)),
                    None,
                    resolved,
                )
            return ResolvedChatScope(
                "ALL", "ALL", None, ready_paper_ids(session, (), allow_all=True)
            )

    def _view(self, session: Session, record: KnowledgeBaseRecord) -> KnowledgeBaseView:
        membership = KnowledgeBasePaperRecord.knowledge_base_id == record.id
        paper_count = int(
            session.scalar(
                select(func.count()).select_from(KnowledgeBasePaperRecord).where(membership)
            )
            or 0
        )
        searchable_count = int(
            session.scalar(
                select(func.count(func.distinct(PaperRecord.id)))
                .select_from(KnowledgeBasePaperRecord)
                .join(PaperRecord, PaperRecord.id == KnowledgeBasePaperRecord.paper_id)
                .join(LibraryFileRecord, LibraryFileRecord.paper_id == PaperRecord.id)
                .where(
                    membership,
                    PaperRecord.status == PaperStatus.READY.value,
                    LibraryFileRecord.source_status == PaperSourceStatus.AVAILABLE.value,
                )
            )
            or 0
        )
        created_at, updated_at = as_utc(record.created_at), as_utc(record.updated_at)
        if created_at is None or updated_at is None:
            raise RuntimeError("knowledge base timestamps must not be null")
        return KnowledgeBaseView(
            record.id,
            record.name,
            paper_count,
            searchable_count,
            created_at,
            updated_at,
        )

    def _required(
        self, session: Session, knowledge_base_id: str, *, lock: bool = False
    ) -> KnowledgeBaseRecord:
        record = session.get(KnowledgeBaseRecord, knowledge_base_id, with_for_update=lock)
        if record is None:
            raise AgentError(
                status_code=404,
                code="KNOWLEDGE_BASE_NOT_FOUND",
                message="未找到指定知识库。",
            )
        return record

    @staticmethod
    def _name_conflict() -> AgentError:
        return AgentError(
            status_code=409,
            code="KNOWLEDGE_BASE_NAME_CONFLICT",
            message="知识库名称已存在。",
        )
