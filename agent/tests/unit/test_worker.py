import asyncio
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep

import pymupdf
import pytest
from sqlalchemy.exc import SQLAlchemyError
from tests.support import (
    DeterministicChunkContext,
    DeterministicEmbedding,
    MemoryUpload,
    RecordingVectorStore,
    runtime_settings,
    sqlite_database,
)

import airesearcher_agent.worker.service as worker_service
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.ingestion.context import ChunkContextError, ChunkContextRequest
from airesearcher_agent.ingestion.pdf import PdfParser
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    Base,
    ChunkRecord,
    IngestionJobRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.worker.service import IngestionWorker


class MutatingPdfParser(PdfParser):
    def parse(self, *, paper_id: str, path: Path):  # type: ignore[no-untyped-def]
        parsed = super().parse(paper_id=paper_id, path=path)
        path.write_bytes(path.read_bytes() + b"\nchanged-during-ingestion")
        return parsed


class BlockingPdfParser(PdfParser):
    def __init__(self, *, started: Event, release: Event) -> None:
        super().__init__(max_pages=500, chunk_size=1200, chunk_overlap=160)
        self._started = started
        self._release = release

    def parse(self, *, paper_id: str, path: Path):  # type: ignore[no-untyped-def]
        self._started.set()
        if not self._release.wait(timeout=5):
            raise TimeoutError("test did not release PDF parser")
        return super().parse(paper_id=paper_id, path=path)


class BlockingEmbedding(DeterministicEmbedding):
    def __init__(self, *, started: Event, release: Event) -> None:
        super().__init__()
        self._started = started
        self._release = release

    def encode(self, texts: list[str]) -> list[list[float]]:
        self._started.set()
        if not self._release.wait(timeout=5):
            raise TimeoutError("test did not release embedding provider")
        return super().encode(texts)


class FailOnceOnCallChunkContext(DeterministicChunkContext):
    def __init__(self, fail_on_call: int) -> None:
        super().__init__()
        self._fail_on_call = fail_on_call
        self._failed = False

    def generate(self, request: ChunkContextRequest) -> str:
        if len(self.calls) + 1 == self._fail_on_call and not self._failed:
            self.calls.append(request)
            self._failed = True
            raise ChunkContextError("synthetic contextualization failure")
        return super().generate(request)


class ConcurrentChunkContext(DeterministicChunkContext):
    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._active = 0
        self.max_active = 0

    def generate(self, request: ChunkContextRequest) -> str:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            sleep(0.03)
            return super().generate(request)
        finally:
            with self._lock:
                self._active -= 1


class BlockingVectorStore(RecordingVectorStore):
    def __init__(self, *, operation: str, started: Event, release: Event) -> None:
        super().__init__()
        self._operation = operation
        self._started = started
        self._release = release

    def delete_paper(self, paper_id: str) -> None:
        self._block("delete")
        super().delete_paper(paper_id)

    def upsert_chunks(
        self,
        *,
        paper_id: str,
        title: str,
        chunks: list[tuple[str, str, int, str]],
        vectors: list[list[float]],
    ) -> None:
        self._block("upsert")
        super().upsert_chunks(
            paper_id=paper_id,
            title=title,
            chunks=chunks,
            vectors=vectors,
        )

    def _block(self, operation: str) -> None:
        if self._operation != operation:
            return
        self._started.set()
        if not self._release.wait(timeout=5):
            raise TimeoutError(f"test did not release Qdrant {operation}")


def _file_database(path: Path) -> Database:
    database = Database(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(database.engine)
    return database


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _pdf_bytes(path: Path) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Runtime worker evidence about retrieval, ranking, and grounded citations. " * 8,
        fontsize=11,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return path.read_bytes()


def _multi_chunk_pdf_bytes(path: Path) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    for line_number in range(6):
        page.insert_text(
            (72, 72 + line_number * 24),
            f"Evidence segment {line_number} about retrieval and grounded citations. " * 5,
            fontsize=11,
        )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return path.read_bytes()


def test_worker_retries_transient_failure_then_marks_paper_ready(tmp_path: Path) -> None:
    settings = runtime_settings(
        tmp_path,
        AIRESEARCHER_CHUNK_SIZE=200,
        AIRESEARCHER_CHUNK_OVERLAP=20,
    )
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(_pdf_bytes(tmp_path / "worker.pdf"), filename="worker.pdf"))
    )
    embedding = DeterministicEmbedding(fail_calls=1)
    context_provider = DeterministicChunkContext()
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20),
        context_provider=context_provider,
        embedding=embedding,
        vector_store=vectors,
        settings=settings,
        worker_id="worker-test",
    )

    assert worker.run_once() is True
    failed = service.get_job(uploaded.ingestion_job.job_id)
    assert failed.status is IngestionJobStatus.FAILED
    assert failed.stage is IngestionStage.FAILED
    assert failed.can_retry is True
    assert service.get_paper(uploaded.paper.paper_id).status is PaperStatus.FAILED

    queued = service.retry_job(failed.job_id)
    assert queued.status is IngestionJobStatus.QUEUED
    assert worker.run_once() is True

    completed = service.get_job(failed.job_id)
    paper = service.get_paper(uploaded.paper.paper_id)
    assert completed.status is IngestionJobStatus.SUCCEEDED
    assert completed.stage is IngestionStage.COMPLETED
    assert completed.attempt == 2
    assert paper.status is PaperStatus.READY
    assert paper.page_count == 1
    assert len(vectors.upserts) == 1
    assert vectors.upserts[0][0] == paper.paper_id
    assert vectors.deleted_papers == [paper.paper_id]
    assert context_provider.calls
    assert embedding.calls[-1][0].startswith("论文标题：")
    with database.session() as session:
        chunk = session.query(ChunkRecord).first()
        assert chunk is not None
        assert chunk.quote not in chunk.context_text
        assert "上下文：" in chunk.text
        assert chunk.quote in chunk.text
    worker.close()
    assert context_provider.close_calls == 1


def test_worker_recovers_an_expired_database_lease(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(_pdf_bytes(tmp_path / "lease.pdf"), filename="lease.pdf"))
    )
    with database.transaction() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        paper = session.get(PaperRecord, uploaded.paper.paper_id)
        assert job is not None
        assert paper is not None
        job.status = IngestionJobStatus.RUNNING.value
        job.stage = IngestionStage.EMBEDDING.value
        job.attempt = 1
        job.lease_owner = "dead-worker"
        job.lease_expires_at = utc_now() - timedelta(minutes=1)
        paper.status = PaperStatus.PROCESSING.value

    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160),
        context_provider=DeterministicChunkContext(),
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="recovery-worker",
    )

    assert worker.recover_expired_leases() == 1
    recovered = service.get_job(uploaded.ingestion_job.job_id)
    assert recovered.status is IngestionJobStatus.QUEUED
    assert recovered.stage is IngestionStage.QUEUED
    assert recovered.attempt == 1
    assert recovered.failure is None


def test_worker_cannot_renew_an_expired_lease(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(_pdf_bytes(tmp_path / "expired.pdf"), filename="expired.pdf"))
    )
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160),
        context_provider=DeterministicChunkContext(),
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="expired-worker",
    )
    claimed = worker.claim_next()
    assert claimed is not None
    expired_at = utc_now() - timedelta(seconds=1)
    with database.transaction() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        assert job is not None
        job.lease_expires_at = expired_at

    with pytest.raises(worker_service.LeaseLostError):
        worker._renew_claim(claimed)

    with database.session() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        assert job is not None
        assert job.lease_expires_at == expired_at.replace(tzinfo=None)


def test_worker_rejects_an_original_changed_after_parsing_without_publishing(
    tmp_path: Path,
) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(MemoryUpload(_pdf_bytes(tmp_path / "changing.pdf"), filename="changing.pdf"))
    )
    worker = IngestionWorker(
        database=database,
        parser=MutatingPdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160),
        context_provider=DeterministicChunkContext(),
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="source-stability-worker",
    )

    assert worker.run_once() is True

    failed = service.get_job(uploaded.ingestion_job.job_id)
    assert failed.status is IngestionJobStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "LIBRARY_FILE_CHANGED"
    assert failed.can_retry is False
    assert service.get_paper(uploaded.paper.paper_id).status is PaperStatus.FAILED
    assert vectors.upserts == []
    with database.session() as session:
        assert session.query(ChunkRecord).count() == 0


def test_worker_fails_retryably_when_chunk_context_generation_fails(tmp_path: Path) -> None:
    settings = runtime_settings(
        tmp_path,
        AIRESEARCHER_CHUNK_SIZE=200,
        AIRESEARCHER_CHUNK_OVERLAP=20,
        AIRESEARCHER_CHUNK_CONTEXT_CONCURRENCY=1,
    )
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(
            MemoryUpload(
                _multi_chunk_pdf_bytes(tmp_path / "context.pdf"),
                filename="context.pdf",
            )
        )
    )
    context_provider = FailOnceOnCallChunkContext(fail_on_call=2)
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20),
        context_provider=context_provider,
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="context-worker",
    )

    assert worker.run_once() is True

    failed = service.get_job(uploaded.ingestion_job.job_id)
    assert failed.status is IngestionJobStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "CONTEXTUALIZATION_FAILED"
    assert failed.can_retry is True
    assert vectors.upserts == []
    with database.session() as session:
        chunks = session.query(ChunkRecord).order_by(ChunkRecord.ordinal).all()
        assert len(chunks) > 2
        assert chunks[0].context_text
        assert all(not chunk.context_text for chunk in chunks[1:])

    service.retry_job(failed.job_id)
    assert worker.run_once() is True
    assert service.get_job(failed.job_id).status is IngestionJobStatus.SUCCEEDED
    assert [request.current_text for request in context_provider.calls].count(chunks[0].quote) == 1


def test_worker_contextualizes_chunks_with_bounded_concurrency(tmp_path: Path) -> None:
    settings = runtime_settings(
        tmp_path,
        AIRESEARCHER_CHUNK_SIZE=200,
        AIRESEARCHER_CHUNK_OVERLAP=20,
        AIRESEARCHER_CHUNK_CONTEXT_CONCURRENCY=3,
    )
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    asyncio.run(
        service.upload(
            MemoryUpload(
                _multi_chunk_pdf_bytes(tmp_path / "concurrent-context.pdf"),
                filename="concurrent-context.pdf",
            )
        )
    )
    context_provider = ConcurrentChunkContext()
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20),
        context_provider=context_provider,
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="concurrent-context-worker",
    )

    assert worker.run_once() is True
    assert context_provider.max_active == 3


@pytest.mark.parametrize("blocked_operation", ["parse", "embedding", "delete", "upsert"])
def test_worker_renews_lease_during_long_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_operation: str,
) -> None:
    monkeypatch.setattr(worker_service, "_heartbeat_interval_seconds", lambda _seconds: 0.02)
    settings = runtime_settings(tmp_path)
    database = _file_database(tmp_path / f"heartbeat-{blocked_operation}.db")
    started = Event()
    release = Event()
    parser = (
        BlockingPdfParser(started=started, release=release)
        if blocked_operation == "parse"
        else PdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160)
    )
    embedding = (
        BlockingEmbedding(started=started, release=release)
        if blocked_operation == "embedding"
        else DeterministicEmbedding()
    )
    vectors = BlockingVectorStore(
        operation=blocked_operation,
        started=started,
        release=release,
    )
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(
            MemoryUpload(
                _pdf_bytes(tmp_path / f"heartbeat-{blocked_operation}.pdf"),
                filename=f"heartbeat-{blocked_operation}.pdf",
            )
        )
    )
    worker = IngestionWorker(
        database=database,
        parser=parser,
        context_provider=DeterministicChunkContext(),
        embedding=embedding,
        vector_store=vectors,
        settings=settings,
        worker_id=f"heartbeat-{blocked_operation}-worker",
    )
    worker_thread = Thread(target=worker.run_once)

    worker_thread.start()
    try:
        assert started.wait(timeout=2)
        shortened_expiry = utc_now() + timedelta(milliseconds=100)
        with database.transaction() as session:
            job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
            assert job is not None
            job.lease_expires_at = shortened_expiry
        with database.session() as session:
            job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
            assert job is not None
            assert job.lease_expires_at is not None
            stored_shortened_expiry = job.lease_expires_at

        def lease_was_renewed() -> bool:
            with database.session() as session:
                job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
                assert job is not None
                return (
                    job.lease_expires_at is not None
                    and job.lease_expires_at > stored_shortened_expiry
                )

        _wait_until(lease_was_renewed)
        sleep(0.12)
        competing_worker = IngestionWorker(
            database=database,
            parser=PdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160),
            context_provider=DeterministicChunkContext(),
            embedding=DeterministicEmbedding(),
            vector_store=RecordingVectorStore(),
            settings=settings,
            worker_id="competing-worker",
        )
        assert competing_worker.recover_expired_leases() == 0
    finally:
        release.set()
        worker_thread.join(timeout=5)
        worker.close()

    assert not worker_thread.is_alive()
    assert service.get_job(uploaded.ingestion_job.job_id).status is IngestionJobStatus.SUCCEEDED


def test_worker_stops_after_lease_is_transferred_during_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(worker_service, "_heartbeat_interval_seconds", lambda _seconds: 0.02)
    settings = runtime_settings(tmp_path)
    database = _file_database(tmp_path / "lease-transferred.db")
    started = Event()
    release = Event()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(
            MemoryUpload(_pdf_bytes(tmp_path / "lease-transferred.pdf"), filename="lease.pdf")
        )
    )
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=1200, chunk_overlap=160),
        context_provider=DeterministicChunkContext(),
        embedding=BlockingEmbedding(started=started, release=release),
        vector_store=vectors,
        settings=settings,
        worker_id="old-worker",
    )
    worker_thread = Thread(target=worker.run_once)

    worker_thread.start()
    try:
        assert started.wait(timeout=2)
        with database.transaction() as session:
            job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
            assert job is not None
            job.lease_owner = "replacement-worker"
            job.lease_expires_at = utc_now() + timedelta(seconds=30)
        _wait_until(
            lambda: any("Could not renew lease" in record.getMessage() for record in caplog.records)
        )
    finally:
        release.set()
        worker_thread.join(timeout=5)
        worker.close()

    assert not worker_thread.is_alive()
    assert vectors.deleted_papers == []
    assert vectors.upserts == []
    with database.session() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        paper = session.get(PaperRecord, uploaded.paper.paper_id)
        assert job is not None
        assert paper is not None
        assert job.status == IngestionJobStatus.RUNNING.value
        assert job.lease_owner == "replacement-worker"
        assert paper.status == PaperStatus.PROCESSING.value


def test_worker_stops_after_heartbeat_database_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(worker_service, "_heartbeat_interval_seconds", lambda _seconds: 0.02)
    settings = runtime_settings(tmp_path)
    database = _file_database(tmp_path / "heartbeat-database-failure.db")
    started = Event()
    release = Event()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    uploaded = asyncio.run(
        service.upload(
            MemoryUpload(
                _pdf_bytes(tmp_path / "heartbeat-database-failure.pdf"),
                filename="lease.pdf",
            )
        )
    )
    worker = IngestionWorker(
        database=database,
        parser=BlockingPdfParser(started=started, release=release),
        context_provider=DeterministicChunkContext(),
        embedding=DeterministicEmbedding(),
        vector_store=vectors,
        settings=settings,
        worker_id="database-failure-worker",
    )
    renewal_attempted = Event()

    def fail_renewal(_claimed: worker_service.ClaimedJob) -> None:
        renewal_attempted.set()
        raise SQLAlchemyError("synthetic heartbeat database failure")

    monkeypatch.setattr(worker, "_renew_claim", fail_renewal)
    worker_thread = Thread(target=worker.run_once)

    worker_thread.start()
    try:
        assert started.wait(timeout=2)
        assert renewal_attempted.wait(timeout=2)
        _wait_until(
            lambda: any("Could not renew lease" in record.getMessage() for record in caplog.records)
        )
    finally:
        release.set()
        worker_thread.join(timeout=5)
        worker.close()

    assert not worker_thread.is_alive()
    assert vectors.deleted_papers == []
    assert vectors.upserts == []
    with database.session() as session:
        job = session.get(IngestionJobRecord, uploaded.ingestion_job.job_id)
        paper = session.get(PaperRecord, uploaded.paper.paper_id)
        assert job is not None
        assert paper is not None
        assert job.status == IngestionJobStatus.RUNNING.value
        assert job.lease_owner == "database-failure-worker"
        assert paper.status == PaperStatus.PROCESSING.value
