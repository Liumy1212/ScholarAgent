import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select
from tests.support import MemoryUpload, runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.domain.library import (
    LibraryFileKnowledgeStatus,
    LibraryFileSourceStatus,
)
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
