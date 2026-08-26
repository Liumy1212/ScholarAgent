import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from airesearcher_agent.application.errors import IngestionError
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.papers import (
    IngestionJobStatus,
    IngestionStage,
    PaperStatus,
    ParsedChunk,
)
from airesearcher_agent.ingestion.pdf import ParsedDocument, PdfParser
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.retrieval.ports import EmbeddingProvider, VectorStore
from airesearcher_agent.retrieval.qdrant_store import VectorStoreError

logger = logging.getLogger(__name__)


class LeaseLostError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: str
    paper_id: str
    worker_id: str


class IngestionWorker:
    def __init__(
        self,
        *,
        database: Database,
        parser: PdfParser,
        embedding: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
        worker_id: str,
    ) -> None:
        self._database = database
        self._parser = parser
        self._embedding = embedding
        self._vector_store = vector_store
        self._lease_seconds = settings.worker_lease_seconds
        self._worker_id = worker_id[:128]

    def run_once(self) -> bool:
        claimed = self.claim_next()
        if claimed is None:
            return False
        self._process(claimed)
        return True

    def recover_expired_leases(self) -> int:
        now = utc_now()
        recovered = 0
        with self._database.transaction() as session:
            jobs = session.scalars(
                select(IngestionJobRecord)
                .where(
                    IngestionJobRecord.status == IngestionJobStatus.RUNNING.value,
                    IngestionJobRecord.lease_expires_at.is_not(None),
                    IngestionJobRecord.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                if job.attempt >= job.max_attempts:
                    job.status = IngestionJobStatus.FAILED.value
                    job.stage = IngestionStage.FAILED.value
                    job.failure_code = "WORKER_LEASE_EXPIRED"
                    job.failure_message = "入库 Worker 中断次数已达到上限。"
                    job.failure_retryable = False
                    job.completed_at = now
                    paper = session.get(PaperRecord, job.paper_id)
                    if paper is not None:
                        paper.status = PaperStatus.FAILED.value
                        paper.updated_at = now
                else:
                    job.status = IngestionJobStatus.QUEUED.value
                    job.stage = IngestionStage.QUEUED.value
                    job.available_at = now
                    job.failure_code = None
                    job.failure_message = None
                    job.failure_retryable = False
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = now
                recovered += 1
        return recovered

    def claim_next(self) -> ClaimedJob | None:
        self.recover_expired_leases()
        now = utc_now()
        lease_expires = now + timedelta(seconds=self._lease_seconds)
        with self._database.transaction() as session:
            job = session.scalars(
                select(IngestionJobRecord)
                .where(
                    IngestionJobRecord.status == IngestionJobStatus.QUEUED.value,
                    IngestionJobRecord.available_at <= now,
                    IngestionJobRecord.attempt < IngestionJobRecord.max_attempts,
                )
                .order_by(IngestionJobRecord.available_at, IngestionJobRecord.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).first()
            if job is None:
                return None
            paper = session.get(PaperRecord, job.paper_id)
            if paper is None:
                raise RuntimeError("queued ingestion job references a missing paper")
            job.status = IngestionJobStatus.RUNNING.value
            job.stage = IngestionStage.PARSING.value
            job.attempt += 1
            job.lease_owner = self._worker_id
            job.lease_expires_at = lease_expires
            job.started_at = job.started_at or now
            job.completed_at = None
            job.updated_at = now
            paper.status = PaperStatus.PROCESSING.value
            paper.updated_at = now
            return ClaimedJob(job_id=job.id, paper_id=job.paper_id, worker_id=self._worker_id)

    def _process(self, claimed: ClaimedJob) -> None:
        try:
            paper_path = self._paper_path(claimed)
            parsed = self._parser.parse(paper_id=claimed.paper_id, path=paper_path)
            self._set_stage(claimed, IngestionStage.CHUNKING)
            self._store_chunks(claimed, parsed)
            self._set_stage(claimed, IngestionStage.EMBEDDING)
            vectors = self._embedding.encode([chunk.text for chunk in parsed.chunks])
            if len(vectors) != len(parsed.chunks):
                raise RuntimeError("embedding provider returned an unexpected vector count")
            self._set_stage(claimed, IngestionStage.INDEXING)
            self._vector_store.delete_paper(claimed.paper_id)
            self._vector_store.upsert_chunks(
                paper_id=claimed.paper_id,
                title=parsed.title or self._paper_title(claimed.paper_id),
                chunks=[
                    (chunk.chunk_id, chunk.vector_id, chunk.page, chunk.quote)
                    for chunk in parsed.chunks
                ],
                vectors=vectors,
            )
            self._complete(claimed)
        except LeaseLostError:
            logger.warning("Worker lease was lost for ingestion job %s", claimed.job_id)
        except IngestionError as error:
            self._fail(claimed, code=error.code, message=error.message, retryable=error.retryable)
        except VectorStoreError:
            logger.exception("Qdrant failed for ingestion job %s", claimed.job_id)
            self._fail(
                claimed,
                code="QDRANT_UNAVAILABLE",
                message="向量服务暂时不可用，入库可以重试。",
                retryable=True,
            )
        except SQLAlchemyError:
            logger.exception("Database failed for ingestion job %s", claimed.job_id)
            self._fail(
                claimed,
                code="DATABASE_UNAVAILABLE",
                message="论文数据库暂时不可用，入库可以重试。",
                retryable=True,
            )
        except Exception:
            logger.exception("Model or worker failed for ingestion job %s", claimed.job_id)
            self._fail(
                claimed,
                code="INGESTION_RUNTIME_FAILED",
                message="解析或本地模型执行失败，入库可以重试。",
                retryable=True,
            )

    def _paper_path(self, claimed: ClaimedJob) -> Path:
        with self._database.session() as session:
            paper = session.get(PaperRecord, claimed.paper_id)
            if paper is None:
                raise RuntimeError("claimed job references a missing paper")
            path = Path(paper.storage_path)
        if not path.is_file():
            raise IngestionError(
                code="PAPER_FILE_MISSING",
                message="论文文件不存在，无法入库。",
                retryable=False,
            )
        return path

    def _paper_title(self, paper_id: str) -> str:
        with self._database.session() as session:
            paper = session.get(PaperRecord, paper_id)
            if paper is None:
                raise RuntimeError("paper disappeared while indexing")
            return paper.title

    def _store_chunks(self, claimed: ClaimedJob, parsed: ParsedDocument) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job, paper = self._locked_records(session, claimed)
            session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == claimed.paper_id))
            for chunk in parsed.chunks:
                session.add(self._chunk_record(chunk, now))
            if parsed.title:
                paper.title = parsed.title[:1024]
            paper.authors = list(parsed.authors)
            paper.publication_year = parsed.publication_year
            paper.page_count = parsed.page_count
            paper.updated_at = now
            self._renew(job, now)

    def _chunk_record(self, chunk: ParsedChunk, now: datetime) -> ChunkRecord:
        return ChunkRecord(
            id=chunk.chunk_id,
            vector_id=chunk.vector_id,
            paper_id=chunk.paper_id,
            page=chunk.page,
            ordinal=chunk.ordinal,
            text=chunk.text,
            quote=chunk.quote,
            created_at=now,
        )

    def _set_stage(self, claimed: ClaimedJob, stage: IngestionStage) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job, _paper = self._locked_records(session, claimed)
            job.stage = stage.value
            self._renew(job, now)

    def _complete(self, claimed: ClaimedJob) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job, paper = self._locked_records(session, claimed)
            job.status = IngestionJobStatus.SUCCEEDED.value
            job.stage = IngestionStage.COMPLETED.value
            job.lease_owner = None
            job.lease_expires_at = None
            job.failure_code = None
            job.failure_message = None
            job.failure_retryable = False
            job.completed_at = now
            job.updated_at = now
            paper.status = PaperStatus.READY.value
            paper.updated_at = now

    def _fail(self, claimed: ClaimedJob, *, code: str, message: str, retryable: bool) -> None:
        now = utc_now()
        try:
            with self._database.transaction() as session:
                job = session.get(IngestionJobRecord, claimed.job_id, with_for_update=True)
                if job is None or job.status != IngestionJobStatus.RUNNING.value:
                    return
                if job.lease_owner != claimed.worker_id:
                    return
                paper = session.get(PaperRecord, claimed.paper_id)
                if paper is None:
                    return
                job.status = IngestionJobStatus.FAILED.value
                job.stage = IngestionStage.FAILED.value
                job.failure_code = code[:128]
                job.failure_message = message[:2048]
                job.failure_retryable = retryable and job.attempt < job.max_attempts
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = now
                job.updated_at = now
                paper.status = PaperStatus.FAILED.value
                paper.updated_at = now
        except SQLAlchemyError:
            logger.exception("Could not persist failure for ingestion job %s", claimed.job_id)

    def _locked_records(
        self,
        session: Session,
        claimed: ClaimedJob,
    ) -> tuple[IngestionJobRecord, PaperRecord]:
        job = session.get(IngestionJobRecord, claimed.job_id, with_for_update=True)
        if (
            job is None
            or job.status != IngestionJobStatus.RUNNING.value
            or job.lease_owner != claimed.worker_id
        ):
            raise LeaseLostError
        paper = session.get(PaperRecord, claimed.paper_id)
        if paper is None:
            raise RuntimeError("claimed job references a missing paper")
        return job, paper

    def _renew(self, job: IngestionJobRecord, now: datetime) -> None:
        job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        job.updated_at = now
