import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from tests.support import runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.library_scans import LibraryScanService
from airesearcher_agent.domain.library import (
    LibraryFileSourceStatus,
    LibraryScanItemOutcome,
    LibraryScanStatus,
)
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    LibraryFileRecord,
    LibraryScanJobRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.persistence.repositories import ready_paper_ids
from airesearcher_agent.worker.library_scan import (
    REPARSE_POINT_ATTRIBUTE,
    LibraryScanWorker,
    is_unsafe_link,
)
from airesearcher_agent.worker.main import CompositeWorker
from airesearcher_agent.worker.service import IngestionWorker


def _write_pdf(path: Path, marker: str) -> bytes:
    content = f"%PDF-1.7\nsynthetic-{marker}".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _services(
    tmp_path: Path,
) -> tuple[Database, LibraryFileService, LibraryScanService, LibraryScanWorker]:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    library_files = LibraryFileService(database=database, settings=settings)
    scans = LibraryScanService(
        database=database,
        settings=settings,
        library_file_service=library_files,
    )
    worker = LibraryScanWorker(
        database=database,
        settings=settings,
        worker_id="scan-worker-test",
    )
    return database, library_files, scans, worker


def _run_scan(scans: LibraryScanService, worker: LibraryScanWorker) -> str:
    queued = scans.create_scan()
    assert queued.status is LibraryScanStatus.QUEUED
    assert worker.run_once() is True
    return queued.scan_id


def _domain_counts(database: Database) -> tuple[int, int, int]:
    with database.session() as session:
        return (
            int(session.scalar(select(func.count()).select_from(PaperRecord)) or 0),
            int(session.scalar(select(func.count()).select_from(IngestionJobRecord)) or 0),
            int(session.scalar(select(func.count()).select_from(ChunkRecord)) or 0),
        )


def _link_ready_paper(database: Database, library_file_id: str, storage_path: Path) -> str:
    now = utc_now()
    paper_id = f"paper-{library_file_id.removeprefix('library-file-')}"
    with database.transaction() as session:
        source = session.get(LibraryFileRecord, library_file_id)
        assert source is not None
        session.add(
            PaperRecord(
                id=paper_id,
                sha256=source.sha256,
                title="Synthetic linked paper",
                authors=[],
                publication_year=None,
                original_filename=source.file_name,
                storage_path=str(storage_path),
                file_size_bytes=source.file_size_bytes,
                page_count=1,
                status=PaperStatus.READY.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        source.paper_id = paper_id
        session.add(
            IngestionJobRecord(
                id=f"job-{library_file_id.removeprefix('library-file-')}",
                paper_id=paper_id,
                active_key=None,
                status=IngestionJobStatus.SUCCEEDED.value,
                stage=IngestionStage.COMPLETED.value,
                attempt=1,
                max_attempts=3,
                failure_code=None,
                failure_message=None,
                failure_retryable=False,
                available_at=now,
                lease_owner=None,
                lease_expires_at=None,
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            ChunkRecord(
                id=f"chunk-{library_file_id.removeprefix('library-file-')}",
                vector_id="00000000-0000-0000-0000-000000000001",
                paper_id=paper_id,
                page=1,
                ordinal=0,
                text="Synthetic evidence.",
                quote="Synthetic evidence.",
                created_at=now,
            )
        )
    return paper_id


def test_scan_registers_new_file_then_reports_unchanged_without_ingestion(
    tmp_path: Path,
) -> None:
    database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    _write_pdf(settings.paper_library_originals_dir / "topic" / "paper.pdf", "new")

    first_id = _run_scan(scans, worker)
    first = scans.get_scan(first_id)
    first_item = scans.list_items(first_id, offset=0, limit=100, outcome=None).items[0]
    registered = library_files.list_files(offset=0, limit=100).items[0]
    second_id = _run_scan(scans, worker)
    second = scans.get_scan(second_id)
    second_item = scans.list_items(second_id, offset=0, limit=100, outcome=None).items[0]

    assert first.status is LibraryScanStatus.SUCCEEDED
    assert first.discovered_count == 1
    assert first.registered_count == 1
    assert first_item.outcome is LibraryScanItemOutcome.REGISTERED
    assert registered.relative_path == "topic/paper.pdf"
    assert registered.paper_id is None
    assert second.unchanged_count == 1
    assert second.registered_count == 0
    assert second_item.outcome is LibraryScanItemOutcome.UNCHANGED
    assert second_item.library_file_id == registered.library_file_id
    assert _domain_counts(database) == (0, 0, 0)


def test_scan_links_copied_legacy_original_to_existing_paper_by_sha256(
    tmp_path: Path,
) -> None:
    database, _library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    content = _write_pdf(settings.paper_library_originals_dir / "legacy.pdf", "legacy")
    sha256 = hashlib.sha256(content).hexdigest()
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id="paper-legacy",
                sha256=sha256,
                title="Legacy paper",
                authors=[],
                publication_year=None,
                original_filename="legacy.pdf",
                storage_path=str(settings.storage_dir / "papers" / "legacy.pdf"),
                file_size_bytes=len(content),
                page_count=1,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )

    scan_id = _run_scan(scans, worker)
    item = scans.list_items(scan_id, offset=0, limit=100, outcome=None).items[0]
    with database.session() as session:
        registered = session.scalar(select(LibraryFileRecord))

    assert registered is not None
    assert registered.paper_id == "paper-legacy"
    assert item.paper_id == "paper-legacy"
    assert _domain_counts(database) == (1, 0, 0)


def test_scan_preserves_id_when_file_moves(tmp_path: Path) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    original = settings.paper_library_originals_dir / "old" / "paper.pdf"
    moved = settings.paper_library_originals_dir / "new" / "renamed.pdf"
    _write_pdf(original, "move")
    _run_scan(scans, worker)
    original_id = library_files.list_files(offset=0, limit=100).items[0].library_file_id
    moved.parent.mkdir(parents=True)
    original.rename(moved)

    scan_id = _run_scan(scans, worker)
    item = scans.list_items(scan_id, offset=0, limit=100, outcome=None).items[0]
    current = library_files.list_files(offset=0, limit=100).items

    assert item.outcome is LibraryScanItemOutcome.MOVED
    assert item.library_file_id == original_id
    assert len(current) == 1
    assert current[0].library_file_id == original_id
    assert current[0].relative_path == "new/renamed.pdf"


def test_scan_registers_same_content_at_multiple_paths_as_duplicate(tmp_path: Path) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    content = _write_pdf(settings.paper_library_originals_dir / "a.pdf", "duplicate")
    _run_scan(scans, worker)
    (settings.paper_library_originals_dir / "b.pdf").write_bytes(content)

    scan_id = _run_scan(scans, worker)
    scan = scans.get_scan(scan_id)
    items = scans.list_items(scan_id, offset=0, limit=100, outcome=None).items
    originals = library_files.list_files(offset=0, limit=100).items

    assert {item.outcome for item in items} == {
        LibraryScanItemOutcome.UNCHANGED,
        LibraryScanItemOutcome.DUPLICATE,
    }
    assert scan.registered_count == 1
    assert scan.duplicate_count == 1
    assert len(originals) == 2
    assert len({item.library_file_id for item in originals}) == 2
    assert len({item.sha256 for item in originals}) == 1


def test_scan_replaces_changed_content_at_same_path(tmp_path: Path) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    path = settings.paper_library_originals_dir / "paper.pdf"
    _write_pdf(path, "version-one")
    _run_scan(scans, worker)
    old_id = library_files.list_files(offset=0, limit=100).items[0].library_file_id
    _write_pdf(path, "version-two")

    scan_id = _run_scan(scans, worker)
    items = library_files.list_files(offset=0, limit=100).items
    available = items[0]

    assert scans.get_scan(scan_id).registered_count == 1
    assert available.library_file_id != old_id
    assert available.source_status is LibraryFileSourceStatus.AVAILABLE
    assert available.relative_path == "paper.pdf"
    assert len(items) == 1


def test_scan_preserves_replaced_record_when_it_still_has_knowledge(tmp_path: Path) -> None:
    database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    path = settings.paper_library_originals_dir / "paper.pdf"
    _write_pdf(path, "linked-version-one")
    _run_scan(scans, worker)
    old_id = library_files.list_files(offset=0, limit=100).items[0].library_file_id
    paper_id = _link_ready_paper(database, old_id, path)
    _write_pdf(path, "linked-version-two")

    _run_scan(scans, worker)
    items = library_files.list_files(offset=0, limit=100).items
    available = next(
        item for item in items if item.source_status is LibraryFileSourceStatus.AVAILABLE
    )
    replaced = next(
        item for item in items if item.source_status is LibraryFileSourceStatus.REPLACED
    )

    assert available.paper_id is None
    assert replaced.library_file_id == old_id
    assert replaced.paper_id == paper_id
    assert available.relative_path == replaced.relative_path == "paper.pdf"
    assert _domain_counts(database) == (1, 1, 1)


def test_scan_removes_disappeared_original_without_knowledge(tmp_path: Path) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    path = settings.paper_library_originals_dir / "paper.pdf"
    _write_pdf(path, "missing")
    _run_scan(scans, worker)
    path.unlink()

    scan_id = _run_scan(scans, worker)

    assert scans.get_scan(scan_id).status is LibraryScanStatus.SUCCEEDED
    assert library_files.list_files(offset=0, limit=100).total == 0


def test_scan_marks_linked_original_missing_without_deleting_knowledge(tmp_path: Path) -> None:
    database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    path = settings.paper_library_originals_dir / "paper.pdf"
    _write_pdf(path, "linked-missing")
    _run_scan(scans, worker)
    original_id = library_files.list_files(offset=0, limit=100).items[0].library_file_id
    paper_id = _link_ready_paper(database, original_id, path)
    path.unlink()

    _run_scan(scans, worker)
    original = library_files.list_files(offset=0, limit=100).items[0]

    assert original.source_status is LibraryFileSourceStatus.MISSING
    assert original.paper_id == paper_id
    assert original.searchable is False
    assert _domain_counts(database) == (1, 1, 1)
    with database.session() as session:
        assert ready_paper_ids(session, (paper_id,)) == ()


def test_single_file_failure_is_reported_without_failing_scan(tmp_path: Path) -> None:
    database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    _write_pdf(settings.paper_library_originals_dir / "valid.pdf", "valid")
    invalid = settings.paper_library_originals_dir / "invalid.pdf"
    invalid.parent.mkdir(parents=True, exist_ok=True)
    invalid.write_bytes(b"not-a-pdf")

    scan_id = _run_scan(scans, worker)
    scan = scans.get_scan(scan_id)
    failed = scans.list_items(
        scan_id,
        offset=0,
        limit=100,
        outcome=LibraryScanItemOutcome.FAILED,
    )

    assert scan.status is LibraryScanStatus.SUCCEEDED
    assert scan.registered_count == 1
    assert scan.failed_count == 1
    assert failed.total == 1
    assert failed.items[0].relative_path == "invalid.pdf"
    assert failed.items[0].code == "INVALID_PDF"
    assert len(library_files.list_files(offset=0, limit=100).items) == 1
    assert _domain_counts(database) == (0, 0, 0)


def test_fatal_traversal_failure_does_not_mark_original_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    path = settings.paper_library_originals_dir / "paper.pdf"
    _write_pdf(path, "protected")
    _run_scan(scans, worker)
    path.unlink()

    def fail_scandir(_path: Path) -> None:
        raise PermissionError("synthetic traversal failure")

    monkeypatch.setattr("airesearcher_agent.worker.library_scan.os.scandir", fail_scandir)
    scan_id = _run_scan(scans, worker)
    scan = scans.get_scan(scan_id)
    original = library_files.list_files(offset=0, limit=100).items[0]

    assert scan.status is LibraryScanStatus.FAILED
    assert scan.failure is not None
    assert scan.failure.code == "LIBRARY_TRAVERSAL_FAILED"
    assert original.source_status is LibraryFileSourceStatus.AVAILABLE


def test_scan_skips_hidden_temporary_and_unsupported_files(tmp_path: Path) -> None:
    _database, library_files, scans, worker = _services(tmp_path)
    settings = runtime_settings(tmp_path)
    originals = settings.paper_library_originals_dir
    _write_pdf(originals / ".hidden-dir" / "hidden.pdf", "hidden-directory")
    _write_pdf(originals / ".hidden.pdf", "hidden-file")
    _write_pdf(originals / "~draft.pdf", "temporary")
    (originals / "notes.txt").write_text("synthetic", encoding="utf-8")

    scan_id = _run_scan(scans, worker)
    scan = scans.get_scan(scan_id)
    items = scans.list_items(scan_id, offset=0, limit=100, outcome=None).items

    assert scan.status is LibraryScanStatus.SUCCEEDED
    assert scan.skipped_count == 3
    assert {item.relative_path for item in items} == {
        ".hidden.pdf",
        "notes.txt",
        "~draft.pdf",
    }
    assert library_files.list_files(offset=0, limit=100).total == 0


def test_symlink_and_reparse_detection_is_explicit() -> None:
    assert is_unsafe_link(is_symlink=True, file_attributes=0)
    assert is_unsafe_link(is_symlink=False, file_attributes=REPARSE_POINT_ATTRIBUTE)
    assert not is_unsafe_link(is_symlink=False, file_attributes=0)


def test_only_one_scan_can_be_active(tmp_path: Path) -> None:
    _database, _library_files, scans, _worker = _services(tmp_path)
    scans.create_scan()

    with pytest.raises(AgentError) as captured:
        scans.create_scan()

    assert captured.value.code == "LIBRARY_SCAN_ACTIVE"


def test_worker_recovers_expired_scan_lease(tmp_path: Path) -> None:
    database, _library_files, scans, worker = _services(tmp_path)
    queued = scans.create_scan()
    with database.transaction() as session:
        scan = session.get(LibraryScanJobRecord, queued.scan_id)
        assert scan is not None
        scan.status = LibraryScanStatus.RUNNING.value
        scan.lease_owner = "dead-worker"
        scan.lease_expires_at = utc_now() - timedelta(minutes=1)

    assert worker.recover_expired_leases() == 1
    assert scans.get_scan(queued.scan_id).status is LibraryScanStatus.QUEUED
    assert worker.run_once() is True
    assert scans.get_scan(queued.scan_id).status is LibraryScanStatus.SUCCEEDED


def test_composite_worker_does_not_build_ingestion_models_for_scan(tmp_path: Path) -> None:
    _database, _library_files, scans, scan_worker = _services(tmp_path)
    scans.create_scan()
    ingestion_built = False

    def build_ingestion() -> IngestionWorker:
        nonlocal ingestion_built
        ingestion_built = True
        raise AssertionError("ingestion worker must remain lazy while a scan is available")

    composite = CompositeWorker(
        scan_worker=scan_worker,
        ingestion_factory=build_ingestion,
    )

    assert composite.run_once() is True
    assert ingestion_built is False
