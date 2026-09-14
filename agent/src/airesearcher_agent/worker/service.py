import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from airesearcher_agent.application.errors import AgentError, IngestionError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.papers import (
    IngestionJobStatus,
    IngestionStage,
    PaperStatus,
    ParsedChunk,
)
from airesearcher_agent.ingestion.context import (
    ChunkContextError,
    ChunkContextProvider,
    ChunkContextRequest,
    retrieval_text,
)
from airesearcher_agent.ingestion.pdf import ParsedDocument, PdfParser
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    LibraryFileRecord,
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


@dataclass(frozen=True, slots=True)
class IngestionSource:
    path: Path
    library_file_id: str | None
    sha256: str
    file_size_bytes: int


def _heartbeat_interval_seconds(lease_seconds: int) -> float:
    return lease_seconds / 3


class _LeaseHeartbeat:
    def __init__(
        self,
        *,
        renew: Callable[[], None],
        interval_seconds: float,
        job_id: str,
    ) -> None:
        self._renew = renew
        self._interval_seconds = interval_seconds
        self._job_id = job_id
        self._stop = Event()
        self._failure_lock = Lock()
        self._failure: BaseException | None = None
        self._thread = Thread(
            target=self._run,
            name=f"ingestion-lease-{job_id[:16]}",
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def raise_if_failed(self) -> None:
        with self._failure_lock:
            failure = self._failure
        if failure is not None:
            raise LeaseLostError from failure

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._renew()
            except BaseException as error:
                logger.exception("Could not renew lease for ingestion job %s", self._job_id)
                with self._failure_lock:
                    self._failure = error
                self._stop.set()
                return


class IngestionWorker:
    def __init__(
        self,
        *,
        database: Database,
        parser: PdfParser,
        context_provider: ChunkContextProvider,
        embedding: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
        worker_id: str,
    ) -> None:
        self._database = database
        self._parser = parser
        self._context_provider = context_provider
        self._embedding = embedding
        self._vector_store = vector_store
        self._library_files = LibraryFileService(database=database, settings=settings)
        self._lease_seconds = settings.worker_lease_seconds
        self._context_concurrency = settings.chunk_context_concurrency
        self._worker_id = worker_id[:128]

    def run_once(self) -> bool:
        claimed = self.claim_next()
        if claimed is None:
            return False
        self._process(claimed)
        return True

    def close(self) -> None:
        self._context_provider.close()

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
                    job.active_key = None
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
                    job.active_key = job.paper_id
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
            job.active_key = job.paper_id
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
        heartbeat = _LeaseHeartbeat(
            renew=lambda: self._renew_claim(claimed),
            interval_seconds=_heartbeat_interval_seconds(self._lease_seconds),
            job_id=claimed.job_id,
        )
        try:
            heartbeat.start()
            try:
                source = self._paper_source(claimed)
                self._checkpoint(claimed, heartbeat)
                parsed = self._parser.parse(paper_id=claimed.paper_id, path=source.path)
                self._checkpoint(claimed, heartbeat)
                self._verify_source(source)
                self._set_stage(claimed, IngestionStage.CHUNKING)
                parsed = self._prepare_chunks(claimed, parsed)
                parsed = self._contextualize(claimed, parsed)
                self._checkpoint(claimed, heartbeat)
                self._verify_source(source)
                self._store_chunks(claimed, parsed)
                self._set_stage(claimed, IngestionStage.EMBEDDING)
                self._checkpoint(claimed, heartbeat)
                vectors = self._embedding.encode([chunk.text for chunk in parsed.chunks])
                self._checkpoint(claimed, heartbeat)
                if len(vectors) != len(parsed.chunks):
                    raise RuntimeError("embedding provider returned an unexpected vector count")
                self._set_stage(claimed, IngestionStage.INDEXING)
                self._verify_source(source)
                self._checkpoint(claimed, heartbeat)
                self._vector_store.delete_paper(claimed.paper_id)
                self._checkpoint(claimed, heartbeat)
                self._vector_store.upsert_chunks(
                    paper_id=claimed.paper_id,
                    title=parsed.title or self._paper_title(claimed.paper_id),
                    chunks=[
                        (chunk.chunk_id, chunk.vector_id, chunk.page, chunk.quote)
                        for chunk in parsed.chunks
                    ],
                    vectors=vectors,
                )
                self._checkpoint(claimed, heartbeat)
                self._verify_source(source)
            finally:
                heartbeat.stop()
            heartbeat.raise_if_failed()
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

    def _paper_source(self, claimed: ClaimedJob) -> IngestionSource:
        with self._database.session() as session:
            paper = session.get(PaperRecord, claimed.paper_id)
            if paper is None:
                raise RuntimeError("claimed job references a missing paper")
            linked_sources = session.scalars(
                select(LibraryFileRecord)
                .where(LibraryFileRecord.paper_id == paper.id)
                .order_by(LibraryFileRecord.last_seen_at.desc(), LibraryFileRecord.id)
            ).all()
            available = next(
                (source for source in linked_sources if source.source_status == "AVAILABLE"),
                None,
            )
            legacy_path = Path(paper.storage_path)
            legacy_sha256 = paper.sha256
            legacy_size = paper.file_size_bytes
        if available is not None:
            try:
                stored = self._library_files.get_file(available.id)
            except AgentError as error:
                raise self._source_error(error) from error
            return IngestionSource(
                path=Path(stored.path),
                library_file_id=stored.library_file_id,
                sha256=stored.sha256,
                file_size_bytes=stored.file_size_bytes,
            )
        if linked_sources:
            raise IngestionError(
                code="LIBRARY_FILE_UNAVAILABLE",
                message="论文没有可用原件，请重新扫描原件库。",
                retryable=False,
            )
        if not legacy_path.is_file():
            raise IngestionError(
                code="PAPER_FILE_MISSING",
                message="论文文件不存在，无法入库。",
                retryable=False,
            )
        return IngestionSource(
            path=legacy_path,
            library_file_id=None,
            sha256=legacy_sha256,
            file_size_bytes=legacy_size,
        )

    def _verify_source(self, source: IngestionSource) -> None:
        if source.library_file_id is None:
            if not source.path.is_file() or source.path.stat().st_size != source.file_size_bytes:
                raise IngestionError(
                    code="PAPER_FILE_MISSING",
                    message="论文文件在入库期间变得不可用。",
                    retryable=False,
                )
            return
        try:
            current = self._library_files.get_file(source.library_file_id)
        except AgentError as error:
            raise self._source_error(error) from error
        if (
            Path(current.path) != source.path
            or current.sha256 != source.sha256
            or current.file_size_bytes != source.file_size_bytes
        ):
            raise IngestionError(
                code="LIBRARY_FILE_CHANGED",
                message="原件在入库期间发生变化，请重新扫描后重试。",
                retryable=False,
            )

    @staticmethod
    def _source_error(error: AgentError) -> IngestionError:
        code = (
            error.code
            if error.code in {"LIBRARY_FILE_CHANGED", "LIBRARY_FILE_UNAVAILABLE"}
            else "LIBRARY_FILE_UNAVAILABLE"
        )
        return IngestionError(code=code, message=error.message, retryable=False)

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

    def _prepare_chunks(self, claimed: ClaimedJob, parsed: ParsedDocument) -> ParsedDocument:
        """Persist raw chunks and restore completed context from an earlier attempt."""
        now = utc_now()
        paper_title = parsed.title or self._paper_title(claimed.paper_id)
        with self._database.transaction() as session:
            job, _paper = self._locked_records(session, claimed)
            existing = {
                row.id: row
                for row in session.execute(
                    select(
                        ChunkRecord.id,
                        ChunkRecord.vector_id,
                        ChunkRecord.page,
                        ChunkRecord.ordinal,
                        ChunkRecord.quote,
                        ChunkRecord.section_path,
                        ChunkRecord.context_text,
                    ).where(ChunkRecord.paper_id == claimed.paper_id)
                )
            }
            prepared: list[ParsedChunk] = []
            session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == claimed.paper_id))
            for chunk in parsed.chunks:
                cached = existing.get(chunk.chunk_id)
                context_text = (
                    cached.context_text
                    if cached is not None
                    and cached.vector_id == chunk.vector_id
                    and cached.page == chunk.page
                    and cached.ordinal == chunk.ordinal
                    and cached.quote == chunk.quote
                    and cached.section_path == " > ".join(chunk.section_path)
                    and cached.context_text
                    else ""
                )
                prepared_chunk = replace(
                    chunk,
                    text=(
                        retrieval_text(
                            paper_title=paper_title,
                            section_path=chunk.section_path,
                            context_text=context_text,
                            quote=chunk.quote,
                        )
                        if context_text
                        else chunk.quote
                    ),
                    context_text=context_text,
                )
                prepared.append(prepared_chunk)
                session.add(self._chunk_record(prepared_chunk, now))
            self._renew(job, now)
        return replace(parsed, chunks=tuple(prepared))

    def _contextualize(self, claimed: ClaimedJob, parsed: ParsedDocument) -> ParsedDocument:
        paper_title = parsed.title or self._paper_title(claimed.paper_id)
        contextualized = list(parsed.chunks)
        try:
            pending = [index for index, chunk in enumerate(parsed.chunks) if not chunk.context_text]
            with ThreadPoolExecutor(
                max_workers=self._context_concurrency,
                thread_name_prefix="chunk-context",
            ) as executor:
                for start in range(0, len(pending), self._context_concurrency):
                    batch = pending[start : start + self._context_concurrency]
                    futures = {
                        index: executor.submit(
                            self._context_provider.generate,
                            self._context_request(parsed, paper_title, index),
                        )
                        for index in batch
                    }
                    first_error: ChunkContextError | None = None
                    for index, future in futures.items():
                        try:
                            context_text = future.result()
                        except ChunkContextError as error:
                            first_error = first_error or error
                            continue
                        chunk = parsed.chunks[index]
                        contextualized_chunk = replace(
                            chunk,
                            text=retrieval_text(
                                paper_title=paper_title,
                                section_path=chunk.section_path,
                                context_text=context_text,
                                quote=chunk.quote,
                            ),
                            context_text=context_text,
                        )
                        self._store_chunk_context(claimed, contextualized_chunk)
                        contextualized[index] = contextualized_chunk
                    if first_error is not None:
                        raise first_error
        except ChunkContextError as error:
            raise IngestionError(
                code="CONTEXTUALIZATION_FAILED",
                message="论文上下文生成失败，入库可以重试。",
                retryable=True,
            ) from error
        return replace(parsed, chunks=tuple(contextualized))

    @staticmethod
    def _context_request(
        parsed: ParsedDocument,
        paper_title: str,
        index: int,
    ) -> ChunkContextRequest:
        chunk = parsed.chunks[index]
        return ChunkContextRequest(
            paper_title=paper_title,
            section_path=chunk.section_path,
            section_outline=parsed.section_outline,
            previous_text=parsed.chunks[index - 1].quote if index > 0 else None,
            current_text=chunk.quote,
            next_text=(parsed.chunks[index + 1].quote if index + 1 < len(parsed.chunks) else None),
        )

    def _store_chunk_context(self, claimed: ClaimedJob, chunk: ParsedChunk) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job = self._locked_job(session, claimed, now)
            record = session.get(ChunkRecord, chunk.chunk_id, with_for_update=True)
            if record is None or record.paper_id != claimed.paper_id or record.quote != chunk.quote:
                raise RuntimeError("prepared chunk disappeared during contextualization")
            record.text = chunk.text
            record.context_text = chunk.context_text
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
            section_path=" > ".join(chunk.section_path),
            context_text=chunk.context_text,
            created_at=now,
        )

    def _set_stage(self, claimed: ClaimedJob, stage: IngestionStage) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job, _paper = self._locked_records(session, claimed)
            job.stage = stage.value
            self._renew(job, now)

    def _checkpoint(self, claimed: ClaimedJob, heartbeat: _LeaseHeartbeat) -> None:
        heartbeat.raise_if_failed()
        with self._database.transaction() as session:
            self._locked_job(session, claimed, utc_now())
        heartbeat.raise_if_failed()

    def _renew_claim(self, claimed: ClaimedJob) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job = self._locked_job(session, claimed, now)
            self._renew(job, now)

    def _complete(self, claimed: ClaimedJob) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            job, paper = self._locked_records(session, claimed)
            job.status = IngestionJobStatus.SUCCEEDED.value
            job.active_key = None
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
                job = self._find_locked_job(session, claimed, now)
                if job is None:
                    return
                paper = session.get(PaperRecord, claimed.paper_id)
                if paper is None:
                    return
                job.status = IngestionJobStatus.FAILED.value
                job.active_key = None
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
        job = self._locked_job(session, claimed, utc_now())
        paper = session.get(PaperRecord, claimed.paper_id)
        if paper is None:
            raise RuntimeError("claimed job references a missing paper")
        return job, paper

    def _locked_job(
        self,
        session: Session,
        claimed: ClaimedJob,
        now: datetime,
    ) -> IngestionJobRecord:
        job = self._find_locked_job(session, claimed, now)
        if job is None:
            raise LeaseLostError
        return job

    @staticmethod
    def _find_locked_job(
        session: Session,
        claimed: ClaimedJob,
        now: datetime,
    ) -> IngestionJobRecord | None:
        return session.scalars(
            select(IngestionJobRecord)
            .where(
                IngestionJobRecord.id == claimed.job_id,
                IngestionJobRecord.paper_id == claimed.paper_id,
                IngestionJobRecord.status == IngestionJobStatus.RUNNING.value,
                IngestionJobRecord.lease_owner == claimed.worker_id,
                IngestionJobRecord.lease_expires_at.is_not(None),
                IngestionJobRecord.lease_expires_at > now,
            )
            .with_for_update()
            .limit(1)
        ).first()

    def _renew(self, job: IngestionJobRecord, now: datetime) -> None:
        job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        job.updated_at = now
