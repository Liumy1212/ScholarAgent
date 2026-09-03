import asyncio
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select
from tests.support import MemoryUpload, runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.domain.library import (
    LibraryFileKnowledgeStatus,
    LibraryFileSourceStatus,
    LibraryStateFilter,
)
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    IngestionJobRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)


def _counts(service_database: Database) -> tuple[int, int, int]:
    with service_database.session() as session:
        return (
            int(session.scalar(select(func.count()).select_from(LibraryFileRecord)) or 0),
            int(session.scalar(select(func.count()).select_from(PaperRecord)) or 0),
            int(session.scalar(select(func.count()).select_from(IngestionJobRecord)) or 0),
        )


def _add_state_record(
    database: Database,
    *,
    key: str,
    source_status: LibraryFileSourceStatus,
    paper_status: PaperStatus | None,
) -> str:
    now = utc_now()
    sha256 = hashlib.sha256(key.encode()).hexdigest()
    relative_path = f"states/{key}.pdf"
    paper_id = f"paper-{key}" if paper_status is not None else None
    with database.transaction() as session:
        if paper_status is not None:
            if paper_status is PaperStatus.PROCESSING:
                job_status = IngestionJobStatus.QUEUED
                job_stage = IngestionStage.QUEUED
            elif paper_status is PaperStatus.FAILED:
                job_status = IngestionJobStatus.FAILED
                job_stage = IngestionStage.FAILED
            else:
                job_status = IngestionJobStatus.SUCCEEDED
                job_stage = IngestionStage.COMPLETED
            session.add(
                PaperRecord(
                    id=paper_id,
                    sha256=sha256,
                    title=key,
                    authors=[],
                    publication_year=None,
                    original_filename=f"{key}.pdf",
                    storage_path=f"synthetic/{key}.pdf",
                    file_size_bytes=32,
                    page_count=1,
                    status=paper_status.value,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                IngestionJobRecord(
                    id=f"job-{key}",
                    paper_id=paper_id,
                    active_key=(paper_id if job_status is IngestionJobStatus.QUEUED else None),
                    status=job_status.value,
                    stage=job_stage.value,
                    attempt=1,
                    max_attempts=3,
                    failure_code=(
                        "SYNTHETIC_FAILURE" if job_status is IngestionJobStatus.FAILED else None
                    ),
                    failure_message=(
                        "Synthetic failure." if job_status is IngestionJobStatus.FAILED else None
                    ),
                    failure_retryable=job_status is IngestionJobStatus.FAILED,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    completed_at=(now if job_status is not IngestionJobStatus.QUEUED else None),
                )
            )
        record_id = f"library-file-{key}"
        session.add(
            LibraryFileRecord(
                id=record_id,
                relative_path=relative_path,
                path_key=hashlib.sha256(relative_path.encode()).hexdigest(),
                file_name=f"{key}.pdf",
                file_size_bytes=32,
                sha256=sha256,
                source_status=source_status.value,
                paper_id=paper_id,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )
    return record_id


def test_upload_registers_original_without_creating_ingestion(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = LibraryFileService(database=database, settings=settings)
    content = b"%PDF-1.7\nstandalone synthetic original"

    result = asyncio.run(service.upload(MemoryUpload(content, filename="new-paper.pdf")))

    assert result.duplicate is False
    assert result.library_file.relative_path == "uploads/new-paper.pdf"
    assert result.library_file.source_status is LibraryFileSourceStatus.AVAILABLE
    assert result.library_file.knowledge_status is LibraryFileKnowledgeStatus.NOT_INGESTED
    assert result.library_file.paper_id is None
    assert result.library_file.current_ingestion is None
    assert result.library_file.searchable is False
    assert _counts(database) == (1, 0, 0)
    stored_path = settings.paper_library_originals_dir / "uploads" / "new-paper.pdf"
    assert stored_path.read_bytes() == content
    assert list(settings.paper_library_staging_dir.iterdir()) == []


@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream", None, ""])
def test_upload_accepts_contract_pdf_content_types(
    tmp_path: Path,
    content_type: str | None,
) -> None:
    settings = runtime_settings(tmp_path)
    service = LibraryFileService(database=sqlite_database(), settings=settings)

    result = asyncio.run(
        service.upload(
            MemoryUpload(
                b"%PDF-1.7\naccepted-content-type",
                filename="accepted.pdf",
                content_type=content_type,
            )
        )
    )

    assert result.library_file.relative_path == "uploads/accepted.pdf"
    assert (settings.paper_library_originals_dir / "uploads" / "accepted.pdf").is_file()


def test_library_state_filters_share_predicate_with_total_and_pagination(
    tmp_path: Path,
) -> None:
    database = sqlite_database()
    service = LibraryFileService(database=database, settings=runtime_settings(tmp_path))
    expected = {
        "not_ingested": {
            _add_state_record(
                database,
                key="plain",
                source_status=LibraryFileSourceStatus.AVAILABLE,
                paper_status=None,
            ),
            _add_state_record(
                database,
                key="processing",
                source_status=LibraryFileSourceStatus.AVAILABLE,
                paper_status=PaperStatus.PROCESSING,
            ),
            _add_state_record(
                database,
                key="failed",
                source_status=LibraryFileSourceStatus.AVAILABLE,
                paper_status=PaperStatus.FAILED,
            ),
            _add_state_record(
                database,
                key="excluded",
                source_status=LibraryFileSourceStatus.AVAILABLE,
                paper_status=PaperStatus.EXCLUDED,
            ),
        },
        "ingested": {
            _add_state_record(
                database,
                key="ready",
                source_status=LibraryFileSourceStatus.AVAILABLE,
                paper_status=PaperStatus.READY,
            )
        },
        "original_missing": {
            _add_state_record(
                database,
                key="missing",
                source_status=LibraryFileSourceStatus.MISSING,
                paper_status=PaperStatus.READY,
            ),
            _add_state_record(
                database,
                key="replaced",
                source_status=LibraryFileSourceStatus.REPLACED,
                paper_status=PaperStatus.READY,
            ),
        },
    }

    first_not_ingested = service.list_files(
        offset=0,
        limit=2,
        library_state=LibraryStateFilter.NOT_INGESTED,
    )
    second_not_ingested = service.list_files(
        offset=2,
        limit=2,
        library_state=LibraryStateFilter.NOT_INGESTED,
    )
    ingested = service.list_files(
        offset=0,
        limit=100,
        library_state=LibraryStateFilter.INGESTED,
    )
    original_missing = service.list_files(
        offset=0,
        limit=100,
        library_state=LibraryStateFilter.ORIGINAL_MISSING,
    )
    all_files = service.list_files(offset=0, limit=100)

    assert first_not_ingested.total == second_not_ingested.total == 4
    assert len(first_not_ingested.items) == len(second_not_ingested.items) == 2
    assert {
        item.library_file_id for item in first_not_ingested.items + second_not_ingested.items
    } == expected["not_ingested"]
    assert ingested.total == 1
    assert {item.library_file_id for item in ingested.items} == expected["ingested"]
    assert original_missing.total == 2
    assert {item.library_file_id for item in original_missing.items} == expected["original_missing"]
    assert all_files.total == 7
    assert {item.library_file_id for item in all_files.items} == set().union(*expected.values())


def test_duplicate_content_is_not_stored_twice_and_list_is_paginated(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = LibraryFileService(database=database, settings=settings)
    content = b"%PDF-1.7\nduplicate synthetic original"

    first = asyncio.run(service.upload(MemoryUpload(content, filename="first.pdf")))
    duplicate = asyncio.run(service.upload(MemoryUpload(content, filename="renamed.pdf")))
    page = service.list_files(offset=0, limit=1)

    assert duplicate.duplicate is True
    assert duplicate.library_file.library_file_id == first.library_file.library_file_id
    assert page.total == 1
    assert page.offset == 0
    assert page.limit == 1
    assert page.items == (first.library_file,)
    assert [path.name for path in (settings.paper_library_originals_dir / "uploads").iterdir()] == [
        "first.pdf"
    ]


def test_same_name_with_different_content_never_overwrites(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = LibraryFileService(database=database, settings=settings)
    first_content = b"%PDF-1.7\nfirst synthetic original"
    second_content = b"%PDF-1.7\nsecond synthetic original"

    first = asyncio.run(service.upload(MemoryUpload(first_content, filename="paper.pdf")))
    second = asyncio.run(service.upload(MemoryUpload(second_content, filename="paper.pdf")))

    assert first.library_file.relative_path == "uploads/paper.pdf"
    assert second.library_file.relative_path.startswith("uploads/paper-")
    assert second.library_file.relative_path.endswith(".pdf")
    first_stored = service.get_file(first.library_file.library_file_id)
    second_stored = service.get_file(second.library_file.library_file_id)
    assert first_stored.file_size_bytes == len(first_content)
    assert second_stored.file_size_bytes == len(second_content)
    first_path = settings.paper_library_originals_dir / first.library_file.relative_path
    second_path = settings.paper_library_originals_dir / second.library_file.relative_path
    assert first_path.read_bytes() == first_content
    assert second_path.read_bytes() == second_content


@pytest.mark.parametrize(
    ("upload", "expected_code"),
    [
        (MemoryUpload(b"not a pdf"), "INVALID_PDF"),
        (MemoryUpload(b"%PDF-test", content_type="text/plain"), "UNSUPPORTED_MEDIA_TYPE"),
        (MemoryUpload(b"%PDF-test", filename="paper.txt"), "UNSUPPORTED_MEDIA_TYPE"),
        (MemoryUpload(b"%PDF-test", filename="../paper.pdf"), "INVALID_FILE_NAME"),
        (MemoryUpload(b"%PDF-test", filename="folder\\paper.pdf"), "INVALID_FILE_NAME"),
    ],
)
def test_upload_rejects_invalid_inputs(
    tmp_path: Path,
    upload: MemoryUpload,
    expected_code: str,
) -> None:
    service = LibraryFileService(
        database=sqlite_database(),
        settings=runtime_settings(tmp_path),
    )

    with pytest.raises(AgentError) as captured:
        asyncio.run(service.upload(upload))

    assert captured.value.code == expected_code


def test_upload_rejects_file_over_configured_limit(tmp_path: Path) -> None:
    service = LibraryFileService(
        database=sqlite_database(),
        settings=runtime_settings(tmp_path, upload_max_bytes=8),
    )

    with pytest.raises(AgentError) as captured:
        asyncio.run(service.upload(MemoryUpload(b"%PDF-1.7\ntoo large")))

    assert captured.value.code == "PDF_TOO_LARGE"


def test_preview_rejects_changed_original(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    service = LibraryFileService(database=sqlite_database(), settings=settings)
    uploaded = asyncio.run(service.upload(MemoryUpload(b"%PDF-1.7\noriginal")))
    path = settings.paper_library_originals_dir / uploaded.library_file.relative_path
    path.write_bytes(b"%PDF-1.7\nchanged")

    with pytest.raises(AgentError) as captured:
        service.get_file(uploaded.library_file.library_file_id)

    assert captured.value.code == "LIBRARY_FILE_CHANGED"


def test_preview_rejects_registered_path_traversal(tmp_path: Path) -> None:
    database = sqlite_database()
    settings = runtime_settings(tmp_path)
    now = utc_now()
    with database.transaction() as session:
        session.add(
            LibraryFileRecord(
                id="library-file-traversal",
                relative_path="../outside.pdf",
                path_key="0" * 64,
                file_name="outside.pdf",
                file_size_bytes=9,
                sha256="0" * 64,
                source_status="AVAILABLE",
                paper_id=None,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )

    with pytest.raises(AgentError) as captured:
        LibraryFileService(database=database, settings=settings).get_file("library-file-traversal")

    assert captured.value.code == "UNSAFE_LIBRARY_PATH"


def test_preview_rejects_symbolic_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = runtime_settings(tmp_path)
    service = LibraryFileService(database=sqlite_database(), settings=settings)
    uploaded = asyncio.run(service.upload(MemoryUpload(b"%PDF-1.7\noriginal")))
    path = settings.paper_library_originals_dir / uploaded.library_file.relative_path
    path_type = type(path)
    original_is_symlink = path_type.is_symlink
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda candidate: candidate == path or original_is_symlink(candidate),
    )

    with pytest.raises(AgentError) as captured:
        service.get_file(uploaded.library_file.library_file_id)

    assert captured.value.code == "UNSAFE_LIBRARY_PATH"
