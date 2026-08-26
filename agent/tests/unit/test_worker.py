import asyncio
from datetime import timedelta
from pathlib import Path

import pymupdf
from tests.support import (
    DeterministicEmbedding,
    MemoryUpload,
    RecordingVectorStore,
    runtime_settings,
    sqlite_database,
)

from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.ingestion.pdf import PdfParser
from airesearcher_agent.persistence.models import IngestionJobRecord, PaperRecord, utc_now
from airesearcher_agent.worker.service import IngestionWorker


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
    worker = IngestionWorker(
        database=database,
        parser=PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20),
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
