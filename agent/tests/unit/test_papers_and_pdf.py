import asyncio
import hashlib
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from tests.support import MemoryUpload, RecordingVectorStore, runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError, IngestionError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.domain.library import LibraryStateFilter
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.ingestion.pdf import PdfParser
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    LibraryFileRecord,
    PaperRecord,
    utc_now,
)


class FailOnceVectorStore(RecordingVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self._remaining_failures = 1

    def delete_paper(self, paper_id: str) -> None:
        self.deleted_papers.append(paper_id)
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("synthetic qdrant failure")


def _complete_ingestion(database: Database, paper_id: str, *, add_chunk: bool = True) -> None:
    now = utc_now()
    with database.transaction() as session:
        paper = session.get(PaperRecord, paper_id)
        job = session.scalar(
            select(IngestionJobRecord).where(IngestionJobRecord.paper_id == paper_id)
        )
        assert paper is not None and job is not None
        paper.status = PaperStatus.READY.value
        paper.updated_at = now
        job.active_key = None
        job.status = IngestionJobStatus.SUCCEEDED.value
        job.stage = IngestionStage.COMPLETED.value
        job.completed_at = now
        job.updated_at = now
        if add_chunk:
            session.add(
                ChunkRecord(
                    id=f"chunk-{paper_id}",
                    vector_id="00000000-0000-0000-0000-000000000001",
                    paper_id=paper_id,
                    page=1,
                    ordinal=0,
                    text="Synthetic deletion evidence.",
                    quote="Synthetic deletion evidence.",
                    created_at=now,
                )
            )


def _write_text_pdf(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    first = document.new_page()
    first.insert_text(
        (72, 72),
        "Page one: bilingual retrieval evidence. 第一页包含检索证据。" * 4,
        fontname="china-s",
        fontsize=11,
    )
    second = document.new_page()
    second.insert_text(
        (72, 72),
        "Page two: the control group improved by 17 percent. 第二页是实验结论。" * 4,
        fontname="china-s",
        fontsize=11,
    )
    document.set_metadata(
        {
            "title": "Synthetic bilingual paper",
            "author": "Ada Example; 李明",
            "creationDate": "D:20260825000000+08'00'",
        }
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def _write_blank_pdf(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def test_compatibility_upload_reuses_original_library_and_sha256_deduplicates(
    tmp_path: Path,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    content = b"%PDF-1.7\nsynthetic redistributable test bytes"

    first = asyncio.run(service.upload(MemoryUpload(content, filename="research.pdf")))
    second = asyncio.run(service.upload(MemoryUpload(content, filename="copy.pdf")))

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.paper.paper_id == first.paper.paper_id
    assert first.paper.library_relative_path == "uploads/research.pdf"
    assert first.paper.source_status.value == "AVAILABLE"
    assert first.paper.searchable is False
    stored = service.get_file(first.paper.paper_id)
    assert Path(stored.path).is_relative_to(settings.paper_library_originals_dir / "uploads")
    assert Path(stored.path).read_bytes() == content
    assert len(list((settings.paper_library_originals_dir / "uploads").glob("*.pdf"))) == 1
    assert not (settings.storage_dir / "papers").exists()


def test_compatibility_delete_preserves_registered_original(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(b"%PDF-1.7\npreserved original", filename="keep.pdf"))
    )
    stored_path = Path(service.get_file(uploaded.paper.paper_id).path)
    _complete_ingestion(database, uploaded.paper.paper_id)

    deleted = service.delete_paper(uploaded.paper.paper_id)

    assert deleted.deleted is True
    assert stored_path.read_bytes() == b"%PDF-1.7\npreserved original"
    assert vectors.deleted_papers == [uploaded.paper.paper_id]
    with database.session() as session:
        source = session.scalar(select(LibraryFileRecord))
        assert source is not None
        assert source.paper_id is None
        assert session.scalar(select(func.count()).select_from(PaperRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ChunkRecord)) == 0

    not_ingested = LibraryFileService(database=database, settings=settings).list_files(
        offset=0,
        limit=100,
        library_state=LibraryStateFilter.NOT_INGESTED,
    )
    assert not_ingested.total == 1
    assert not_ingested.items[0].paper_id is None


@pytest.mark.parametrize("active_status", [IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING])
def test_delete_rejects_active_ingestion_without_touching_original(
    tmp_path: Path,
    active_status: IngestionJobStatus,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(b"%PDF-1.7\nbusy deletion", filename="busy.pdf"))
    )
    stored_path = Path(service.get_file(uploaded.paper.paper_id).path)
    with database.transaction() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        assert job is not None
        job.status = active_status.value

    with pytest.raises(AgentError) as captured:
        service.delete_paper(uploaded.paper.paper_id)

    assert captured.value.code == "PAPER_BUSY"
    assert captured.value.status_code == 409
    assert captured.value.retryable is True
    assert stored_path.is_file()
    assert vectors.deleted_papers == []
    with database.session() as session:
        assert session.get(PaperRecord, uploaded.paper.paper_id) is not None


def test_delete_cleans_missing_registration_with_knowledge(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = PaperService(
        database=database,
        settings=settings,
        vector_store=RecordingVectorStore(),
    )
    uploaded = asyncio.run(
        service.upload(MemoryUpload(b"%PDF-1.7\nmissing deletion", filename="missing.pdf"))
    )
    _complete_ingestion(database, uploaded.paper.paper_id)
    stored_path = Path(service.get_file(uploaded.paper.paper_id).path)
    stored_path.unlink()
    with database.transaction() as session:
        source = session.scalar(
            select(LibraryFileRecord).where(LibraryFileRecord.paper_id == uploaded.paper.paper_id)
        )
        assert source is not None
        source.source_status = "MISSING"

    service.delete_paper(uploaded.paper.paper_id)

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(LibraryFileRecord)) == 0
        assert session.scalar(select(func.count()).select_from(PaperRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ChunkRecord)) == 0


def test_delete_preserves_all_available_same_content_originals(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = PaperService(
        database=database,
        settings=settings,
        vector_store=RecordingVectorStore(),
    )
    content = b"%PDF-1.7\nmultiple originals"
    uploaded = asyncio.run(service.upload(MemoryUpload(content, filename="primary.pdf")))
    paper_id = uploaded.paper.paper_id
    primary_path = Path(service.get_file(paper_id).path)
    copy_path = settings.paper_library_originals_dir / "copies" / "copy.pdf"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(content)
    relative_path = "copies/copy.pdf"
    now = utc_now()
    with database.transaction() as session:
        session.add(
            LibraryFileRecord(
                id="library-file-copy",
                relative_path=relative_path,
                path_key=hashlib.sha256(relative_path.encode()).hexdigest(),
                file_name="copy.pdf",
                file_size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                source_status="AVAILABLE",
                paper_id=paper_id,
                discovered_at=now,
                last_seen_at=now,
                updated_at=now,
            )
        )
    _complete_ingestion(database, paper_id)

    service.delete_paper(paper_id)

    assert primary_path.read_bytes() == content
    assert copy_path.read_bytes() == content
    with database.session() as session:
        sources = session.scalars(select(LibraryFileRecord)).all()
        assert len(sources) == 2
        assert all(source.paper_id is None for source in sources)


def test_qdrant_failure_keeps_paper_unsearchable_and_delete_is_retryable(
    tmp_path: Path,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = FailOnceVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(b"%PDF-1.7\nqdrant retry", filename="retry.pdf"))
    )
    paper_id = uploaded.paper.paper_id
    stored_path = Path(service.get_file(paper_id).path)
    _complete_ingestion(database, paper_id)

    with pytest.raises(AgentError) as captured:
        service.delete_paper(paper_id)

    assert captured.value.code == "QDRANT_UNAVAILABLE"
    assert captured.value.retryable is True
    assert stored_path.is_file()
    assert service.get_paper(paper_id).status is PaperStatus.EXCLUDED
    assert service.get_paper(paper_id).searchable is False
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ChunkRecord)) == 1

    assert service.delete_paper(paper_id).deleted is True
    assert stored_path.is_file()
    assert vectors.deleted_papers == [paper_id, paper_id]


def test_database_failure_after_vector_cleanup_can_retry_without_losing_original(
    tmp_path: Path,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(b"%PDF-1.7\ndatabase retry", filename="db-retry.pdf"))
    )
    paper_id = uploaded.paper.paper_id
    stored_path = Path(service.get_file(paper_id).path)
    _complete_ingestion(database, paper_id)

    def fail_ingestion_job_delete(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.startswith("DELETE FROM ingestion_jobs"):
            raise OperationalError(statement, {}, RuntimeError("synthetic database failure"))

    event.listen(database.engine, "before_cursor_execute", fail_ingestion_job_delete)
    try:
        with pytest.raises(AgentError) as captured:
            service.delete_paper(paper_id)
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_ingestion_job_delete)

    assert captured.value.code == "DATABASE_UNAVAILABLE"
    assert captured.value.retryable is True
    assert stored_path.is_file()
    assert service.get_paper(paper_id).status is PaperStatus.EXCLUDED

    assert service.delete_paper(paper_id).deleted is True
    assert stored_path.is_file()
    assert vectors.deleted_papers == [paper_id, paper_id]


def test_delete_never_removes_legacy_pdf_outside_originals(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    service = PaperService(
        database=database,
        settings=settings,
        vector_store=RecordingVectorStore(),
    )
    legacy_path = settings.storage_dir / "papers" / "legacy.pdf"
    legacy_path.parent.mkdir(parents=True)
    content = b"%PDF-1.7\nlegacy preserved"
    legacy_path.write_bytes(content)
    now = utc_now()
    with database.transaction() as session:
        session.add(
            PaperRecord(
                id="paper-legacy-delete",
                sha256=hashlib.sha256(content).hexdigest(),
                title="Legacy preserved",
                authors=[],
                publication_year=None,
                original_filename="legacy.pdf",
                storage_path=str(legacy_path),
                file_size_bytes=len(content),
                page_count=1,
                status=PaperStatus.READY.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            IngestionJobRecord(
                id="job-legacy-delete",
                paper_id="paper-legacy-delete",
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

    service.delete_paper("paper-legacy-delete")

    assert legacy_path.read_bytes() == content


@pytest.mark.parametrize(
    ("upload", "expected_code"),
    [
        (MemoryUpload(b"not a pdf"), "INVALID_PDF"),
        (MemoryUpload(b"%PDF-test", content_type="text/plain"), "UNSUPPORTED_MEDIA_TYPE"),
        (MemoryUpload(b"%PDF-test", filename="paper.txt"), "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
def test_upload_rejects_invalid_pdf_inputs(
    tmp_path: Path,
    upload: MemoryUpload,
    expected_code: str,
) -> None:
    service = PaperService(
        database=sqlite_database(),
        settings=runtime_settings(tmp_path),
        vector_store=RecordingVectorStore(),
    )

    with pytest.raises(AgentError) as captured:
        asyncio.run(service.upload(upload))

    assert captured.value.code == expected_code


def test_parser_keeps_chunks_on_their_source_page_and_extracts_metadata(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two-pages.pdf"
    _write_text_pdf(pdf_path)
    parser = PdfParser(max_pages=500, chunk_size=200, chunk_overlap=30)

    parsed = parser.parse(paper_id="paper-test", path=pdf_path)

    assert parsed.page_count == 2
    assert parsed.title == "Synthetic bilingual paper"
    assert parsed.publication_year == 2026
    assert set(chunk.page for chunk in parsed.chunks) == {1, 2}
    assert all(chunk.paper_id == "paper-test" for chunk in parsed.chunks)
    assert all(chunk.quote == chunk.text for chunk in parsed.chunks)
    assert len({chunk.chunk_id for chunk in parsed.chunks}) == len(parsed.chunks)
    assert parser.parse(paper_id="paper-test", path=pdf_path).chunks == parsed.chunks


def test_parser_rejects_pdf_without_extractable_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    _write_blank_pdf(pdf_path)

    with pytest.raises(IngestionError) as captured:
        PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20).parse(
            paper_id="paper-blank",
            path=pdf_path,
        )

    assert captured.value.code == "PDF_HAS_NO_TEXT"
