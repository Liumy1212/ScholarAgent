import pytest
from sqlalchemy import func, select
from tests.support import sqlite_database

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.knowledge_bases import KnowledgeBaseService
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    KnowledgeBasePaperRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)


def _paper(database: Database, paper_id: str, *, available: bool = True) -> None:
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id=paper_id,
                sha256=paper_id.removeprefix("paper-").ljust(64, "0")[:64],
                title=paper_id,
                authors=[],
                publication_year=None,
                original_filename=f"{paper_id}.pdf",
                storage_path=f"/synthetic/{paper_id}.pdf",
                file_size_bytes=128,
                page_count=1,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            LibraryFileRecord(
                id=f"file-{paper_id}",
                relative_path=f"collection/{paper_id}.pdf",
                path_key=paper_id.ljust(64, "f")[:64],
                file_name=f"{paper_id}.pdf",
                file_size_bytes=128,
                sha256=paper_id.removeprefix("paper-").ljust(64, "0")[:64],
                source_status="AVAILABLE" if available else "MISSING",
                paper_id=paper_id,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )


def test_name_normalization_conflict_membership_and_scope_snapshot() -> None:
    database = sqlite_database()
    service = KnowledgeBaseService(database)
    _paper(database, "paper-a")
    _paper(database, "paper-b", available=False)

    first = service.create("  Ａ研究  ")
    second = service.create("第二库")
    assert first.name == "Ａ研究"

    with pytest.raises(AgentError) as conflict:
        service.create("ａ研究")
    assert conflict.value.code == "KNOWLEDGE_BASE_NAME_CONFLICT"

    updated = service.update_members(first.knowledge_base_id, ("paper-a", "paper-b"), ())
    service.update_members(second.knowledge_base_id, ("paper-a",), ())
    idempotent = service.update_members(second.knowledge_base_id, ("paper-a",), ("paper-b",))
    assert updated.knowledge_base.paper_count == 2
    assert updated.knowledge_base.searchable_paper_count == 1
    assert idempotent.added_paper_ids == ()
    assert idempotent.removed_paper_ids == ()

    scope = service.resolve_chat_scope(
        knowledge_base_id=first.knowledge_base_id,
        paper_ids=(),
    )
    assert scope.scope_key == f"KNOWLEDGE_BASE:{first.knowledge_base_id}"
    assert scope.paper_ids == ("paper-a",)

    service.delete(first.knowledge_base_id)
    assert scope.paper_ids == ("paper-a",)
    with database.session() as session:
        assert session.get(PaperRecord, "paper-a") is not None
        remaining = session.scalar(select(func.count()).select_from(KnowledgeBasePaperRecord))
    assert remaining == 1


def test_empty_knowledge_base_is_valid_but_not_searchable() -> None:
    service = KnowledgeBaseService(sqlite_database())
    knowledge_base = service.create("空库")

    with pytest.raises(AgentError) as error:
        service.resolve_chat_scope(
            knowledge_base_id=knowledge_base.knowledge_base_id,
            paper_ids=(),
        )
    assert error.value.code == "KNOWLEDGE_BASE_NOT_SEARCHABLE"
