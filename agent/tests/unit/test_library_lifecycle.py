import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from tests.support import MemoryUpload, RecordingVectorStore, runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.library_lifecycle import LibraryLifecycleService
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)


def _services(
    tmp_path: Path,
) -> tuple[
    Database,
    LibraryFileService,
    LibraryLifecycleService,
    RecordingVectorStore,
]:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    files = LibraryFileService(database=database, settings=settings)
    vectors = RecordingVectorStore()
    lifecycle = LibraryLifecycleService(
        database=database,
        settings=settings,
        vector_store=vectors,
        library_file_service=files,
    )
    return database, files, lifecycle, vectors


def test_manual_ingestion_is_idempotent_and_links_all_available_same_sha_sources(
    tmp_path: Path,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    files = LibraryFileService(database=database, settings=settings)
    lifecycle = LibraryLifecycleService(
        database=database,
        settings=settings,
        vector_store=RecordingVectorStore(),
        library_file_service=files,
    )
    content = b"%PDF-1.7\nmanual-ingestion"
    uploaded = asyncio.run(files.upload(MemoryUpload(content, filename="primary.pdf")))
    copy_path = settings.paper_library_originals_dir / "manual" / "copy.pdf"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(content)
    now = utc_now()
    duplicate_id = f"library-file-{uuid4().hex}"
    relative_path = "manual/copy.pdf"
    with database.transaction() as session:
        session.add(
            LibraryFileRecord(
                id=duplicate_id,
                relative_path=relative_path,
                path_key=hashlib.sha256(relative_path.encode()).hexdigest(),
                file_name="copy.pdf",
                file_size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                source_status="AVAILABLE",
                paper_id=None,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )

    first = lifecycle.ingest_file(uploaded.library_file.library_file_id)
    second = lifecycle.ingest_file(duplicate_id)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.paper.paper_id == first.paper.paper_id
    assert second.ingestion_job.job_id == first.ingestion_job.job_id
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(PaperRecord)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionJobRecord)) == 1
        linked = session.scalars(
            select(LibraryFileRecord).where(LibraryFileRecord.paper_id == first.paper.paper_id)
        ).all()
        assert {item.id for item in linked} == {
            uploaded.library_file.library_file_id,
            duplicate_id,
        }


def test_manual_ingestion_rejects_changed_or_unavailable_original(tmp_path: Path) -> None:
    database, files, lifecycle, _vectors = _services(tmp_path)
    uploaded = asyncio.run(files.upload(MemoryUpload(b"%PDF-1.7\nstable", filename="stable.pdf")))
    stored = files.get_file(uploaded.library_file.library_file_id)
    Path(stored.path).write_bytes(b"%PDF-1.7\nchanged")

    with pytest.raises(AgentError) as changed:
        lifecycle.ingest_file(uploaded.library_file.library_file_id)
    assert changed.value.code == "LIBRARY_FILE_CHANGED"

    with database.transaction() as session:
        record = session.get(LibraryFileRecord, uploaded.library_file.library_file_id)
        assert record is not None
        record.source_status = "MISSING"
    with pytest.raises(AgentError) as missing:
        lifecycle.ingest_file(uploaded.library_file.library_file_id)
    assert missing.value.code == "LIBRARY_FILE_UNAVAILABLE"


def test_active_job_constraint_and_exclusion_restore_lifecycle(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    files = LibraryFileService(database=database, settings=settings)
    vectors = RecordingVectorStore()
    lifecycle = LibraryLifecycleService(
        database=database,
        settings=settings,
        vector_store=vectors,
        library_file_service=files,
    )
    uploaded = asyncio.run(
        files.upload(MemoryUpload(b"%PDF-1.7\nlifecycle", filename="lifecycle.pdf"))
    )
    ingestion = lifecycle.ingest_file(uploaded.library_file.library_file_id)

    with pytest.raises(AgentError) as busy:
        lifecycle.exclude_paper(ingestion.paper.paper_id)
    assert busy.value.code == "PAPER_BUSY"

    now = utc_now()
    with database.transaction() as session:
        job = session.get(IngestionJobRecord, ingestion.ingestion_job.job_id)
        paper = session.get(PaperRecord, ingestion.paper.paper_id)
        assert job is not None
        assert paper is not None
        job.status = IngestionJobStatus.SUCCEEDED.value
        job.active_key = None
        job.stage = IngestionStage.COMPLETED.value
        job.completed_at = now
        paper.status = PaperStatus.READY.value
        session.add(
            ChunkRecord(
                id="chunk-lifecycle",
                vector_id=str(uuid4()),
                paper_id=paper.id,
                page=1,
                ordinal=0,
                text="residual evidence",
                quote="residual evidence",
                created_at=now,
            )
        )

    excluded = lifecycle.exclude_paper(ingestion.paper.paper_id)
    assert excluded.status is PaperStatus.EXCLUDED
    assert excluded.searchable is False
    assert files.get_file(uploaded.library_file.library_file_id).path
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ChunkRecord)) == 0
    assert vectors.deleted_papers == [ingestion.paper.paper_id]

    restored = lifecycle.restore_paper(ingestion.paper.paper_id)
    assert restored.status is PaperStatus.PROCESSING
    assert restored.current_ingestion.status is IngestionJobStatus.QUEUED
    assert restored.current_ingestion.job_id != ingestion.ingestion_job.job_id
    assert vectors.deleted_papers == [ingestion.paper.paper_id, ingestion.paper.paper_id]
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(IngestionJobRecord)) == 2

        conflicting = IngestionJobRecord(
            id=f"job-{uuid4().hex}",
            paper_id=ingestion.paper.paper_id,
            active_key=ingestion.paper.paper_id,
            status=IngestionJobStatus.QUEUED.value,
            stage=IngestionStage.QUEUED.value,
            attempt=0,
            max_attempts=3,
            failure_code=None,
            failure_message=None,
            failure_retryable=False,
            available_at=now,
            lease_owner=None,
            lease_expires_at=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        session.add(conflicting)
        with pytest.raises(IntegrityError):
            session.flush()


def test_restore_requires_an_available_original(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    files = LibraryFileService(database=database, settings=settings)
    lifecycle = LibraryLifecycleService(
        database=database,
        settings=settings,
        vector_store=RecordingVectorStore(),
        library_file_service=files,
    )
    uploaded = asyncio.run(files.upload(MemoryUpload(b"%PDF-1.7\nmissing", filename="missing.pdf")))
    ingestion = lifecycle.ingest_file(uploaded.library_file.library_file_id)
    with database.transaction() as session:
        job = session.get(IngestionJobRecord, ingestion.ingestion_job.job_id)
        paper = session.get(PaperRecord, ingestion.paper.paper_id)
        source = session.get(LibraryFileRecord, uploaded.library_file.library_file_id)
        assert job is not None and paper is not None and source is not None
        job.status = IngestionJobStatus.SUCCEEDED.value
        job.active_key = None
        job.stage = IngestionStage.COMPLETED.value
        paper.status = PaperStatus.EXCLUDED.value
        source.source_status = "MISSING"

    with pytest.raises(AgentError) as captured:
        lifecycle.restore_paper(ingestion.paper.paper_id)
    assert captured.value.code == "LIBRARY_FILE_UNAVAILABLE"
