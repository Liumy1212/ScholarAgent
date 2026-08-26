from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from airesearcher_agent.domain.papers import (
    IngestionFailureView,
    IngestionJobStatus,
    IngestionJobView,
    IngestionStage,
    IngestionSummaryView,
    PaperStatus,
    PaperView,
)
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    PaperRecord,
)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def latest_job_statement(paper_id: str) -> Select[tuple[IngestionJobRecord]]:
    return (
        select(IngestionJobRecord)
        .where(IngestionJobRecord.paper_id == paper_id)
        .order_by(IngestionJobRecord.created_at.desc(), IngestionJobRecord.id.desc())
        .limit(1)
    )


def latest_job(session: Session, paper_id: str) -> IngestionJobRecord:
    job = session.scalars(latest_job_statement(paper_id)).first()
    if job is None:
        raise RuntimeError(f"paper {paper_id} has no ingestion job")
    return job


def failure_view(job: IngestionJobRecord) -> IngestionFailureView | None:
    if job.failure_code is None or job.failure_message is None:
        return None
    return IngestionFailureView(
        code=job.failure_code,
        message=job.failure_message,
        retryable=job.failure_retryable,
    )


def ingestion_summary_view(job: IngestionJobRecord) -> IngestionSummaryView:
    status = IngestionJobStatus(job.status)
    return IngestionSummaryView(
        job_id=job.id,
        status=status,
        stage=IngestionStage(job.stage),
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        can_retry=(
            status is IngestionJobStatus.FAILED
            and job.failure_retryable
            and job.attempt < job.max_attempts
        ),
        failure=failure_view(job),
    )


def ingestion_job_view(job: IngestionJobRecord) -> IngestionJobView:
    summary = ingestion_summary_view(job)
    created_at = as_utc(job.created_at)
    if created_at is None:
        raise RuntimeError("ingestion job created_at must not be null")
    return IngestionJobView(
        job_id=summary.job_id,
        status=summary.status,
        stage=summary.stage,
        attempt=summary.attempt,
        max_attempts=summary.max_attempts,
        can_retry=summary.can_retry,
        failure=summary.failure,
        paper_id=job.paper_id,
        created_at=created_at,
        started_at=as_utc(job.started_at),
        completed_at=as_utc(job.completed_at),
    )


def paper_view(session: Session, paper: PaperRecord) -> PaperView:
    job = latest_job(session, paper.id)
    created_at = as_utc(paper.created_at)
    updated_at = as_utc(paper.updated_at)
    if created_at is None or updated_at is None:
        raise RuntimeError("paper timestamps must not be null")
    return PaperView(
        paper_id=paper.id,
        title=paper.title,
        authors=tuple(paper.authors),
        publication_year=paper.publication_year,
        file_name=paper.original_filename,
        file_size_bytes=paper.file_size_bytes,
        status=PaperStatus(paper.status),
        page_count=paper.page_count,
        created_at=created_at,
        updated_at=updated_at,
        current_ingestion=ingestion_summary_view(job),
    )


def list_paper_views(session: Session) -> tuple[PaperView, ...]:
    papers = session.scalars(
        select(PaperRecord).order_by(PaperRecord.created_at.desc(), PaperRecord.id.desc())
    ).all()
    return tuple(paper_view(session, paper) for paper in papers)


def ready_paper_ids(session: Session, requested: tuple[str, ...]) -> tuple[str, ...]:
    statement = select(PaperRecord.id).where(PaperRecord.status == PaperStatus.READY.value)
    if requested:
        statement = statement.where(PaperRecord.id.in_(requested))
    return tuple(session.scalars(statement).all())


def chunks_by_ids(session: Session, chunk_ids: tuple[str, ...]) -> dict[str, ChunkRecord]:
    if not chunk_ids:
        return {}
    chunks = session.scalars(select(ChunkRecord).where(ChunkRecord.id.in_(chunk_ids))).all()
    return {chunk.id: chunk for chunk in chunks}


def paper_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(PaperRecord)) or 0)
