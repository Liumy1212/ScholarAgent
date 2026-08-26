import hashlib
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from airesearcher_agent.application.errors import AgentError, ErrorDetail
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.papers import (
    DeletePaperView,
    IngestionJobStatus,
    IngestionJobView,
    IngestionStage,
    PaperListView,
    PaperStatus,
    PaperUploadView,
    PaperView,
    StoredPaperFile,
)
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    ChunkRecord,
    IngestionJobRecord,
    PaperRecord,
    utc_now,
)
from airesearcher_agent.persistence.repositories import (
    ingestion_job_view,
    latest_job,
    list_paper_views,
    paper_view,
)
from airesearcher_agent.retrieval.ports import VectorStore


class AsyncUpload(Protocol):
    @property
    def filename(self) -> str | None: ...

    @property
    def content_type(self) -> str | None: ...

    async def read(self, size: int = -1) -> bytes: ...


class PaperService:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        vector_store: VectorStore,
    ) -> None:
        self._database = database
        self._settings = settings
        self._vector_store = vector_store

    async def upload(self, upload: AsyncUpload) -> PaperUploadView:
        file_name = self._validated_file_name(upload.filename)
        if upload.content_type != "application/pdf":
            raise AgentError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="只支持 application/pdf 文本型 PDF。",
                details=(ErrorDetail(field="file", reason="content type must be application/pdf"),),
            )

        self._settings.ensure_runtime_directories()
        temporary_path = self._settings.storage_dir / "uploads" / f"upload-{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            with temporary_path.open("xb") as destination:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self._settings.upload_max_bytes:
                        raise AgentError(
                            status_code=413,
                            code="PDF_TOO_LARGE",
                            message="PDF 不能超过 50 MB。",
                            details=(ErrorDetail(field="file", reason="maximum size is 50 MB"),),
                        )
                    if len(prefix) < 5:
                        prefix.extend(chunk[: 5 - len(prefix)])
                    digest.update(chunk)
                    destination.write(chunk)
            if size == 0 or bytes(prefix) != b"%PDF-":
                raise AgentError(
                    status_code=422,
                    code="INVALID_PDF",
                    message="上传文件不是有效的 PDF。",
                    details=(ErrorDetail(field="file", reason="missing PDF signature"),),
                )
            return self._persist_upload(
                temporary_path=temporary_path,
                file_name=file_name,
                file_size=size,
                sha256=digest.hexdigest(),
            )
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def list_papers(self) -> PaperListView:
        try:
            with self._database.session() as session:
                items = list_paper_views(session)
            return PaperListView(items=items, total=len(items))
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_paper(self, paper_id: str) -> PaperView:
        try:
            with self._database.session() as session:
                paper = session.get(PaperRecord, paper_id)
                if paper is None:
                    raise self._paper_not_found()
                return paper_view(session, paper)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_file(self, paper_id: str) -> StoredPaperFile:
        try:
            with self._database.session() as session:
                paper = session.get(PaperRecord, paper_id)
                if paper is None:
                    raise self._paper_not_found()
                path = Path(paper.storage_path).resolve()
                storage_root = (self._settings.storage_dir / "papers").resolve()
                if not path.is_relative_to(storage_root) or not path.is_file():
                    raise AgentError(
                        status_code=500,
                        code="PAPER_FILE_MISSING",
                        message="论文文件不可用。",
                        retryable=False,
                    )
                return StoredPaperFile(
                    paper_id=paper.id,
                    path=str(path),
                    file_name=paper.original_filename,
                    file_size_bytes=paper.file_size_bytes,
                    sha256=paper.sha256,
                )
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_job(self, job_id: str) -> IngestionJobView:
        try:
            with self._database.session() as session:
                job = session.get(IngestionJobRecord, job_id)
                if job is None:
                    raise AgentError(
                        status_code=404,
                        code="INGESTION_JOB_NOT_FOUND",
                        message="未找到指定入库任务。",
                    )
                return ingestion_job_view(job)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def retry_job(self, job_id: str) -> IngestionJobView:
        now = utc_now()
        try:
            with self._database.transaction() as session:
                job = session.get(IngestionJobRecord, job_id, with_for_update=True)
                if job is None:
                    raise AgentError(
                        status_code=404,
                        code="INGESTION_JOB_NOT_FOUND",
                        message="未找到指定入库任务。",
                    )
                can_retry = (
                    job.status == IngestionJobStatus.FAILED.value
                    and job.failure_retryable
                    and job.attempt < job.max_attempts
                )
                if not can_retry:
                    raise AgentError(
                        status_code=409,
                        code="INGESTION_NOT_RETRYABLE",
                        message="当前入库任务不能重试。",
                    )
                paper = session.get(PaperRecord, job.paper_id)
                if paper is None:
                    raise RuntimeError("ingestion job references a missing paper")
                job.status = IngestionJobStatus.QUEUED.value
                job.stage = IngestionStage.QUEUED.value
                job.failure_code = None
                job.failure_message = None
                job.failure_retryable = False
                job.available_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = None
                job.updated_at = now
                paper.status = PaperStatus.PROCESSING.value
                paper.updated_at = now
            return self.get_job(job_id)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def delete_paper(self, paper_id: str) -> DeletePaperView:
        tombstone: Path | None = None
        source_path: Path | None = None
        try:
            with self._database.session() as session:
                paper = session.get(PaperRecord, paper_id)
                if paper is None:
                    raise self._paper_not_found()
                job = latest_job(session, paper.id)
                if job.status == IngestionJobStatus.RUNNING.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_BUSY",
                        message="论文正在入库，请稍后再删除。",
                        retryable=True,
                    )
                source_path = Path(paper.storage_path).resolve()
            try:
                self._vector_store.delete_paper(paper_id)
            except Exception as error:
                raise AgentError(
                    status_code=503,
                    code="QDRANT_UNAVAILABLE",
                    message="向量服务暂时不可用，论文尚未删除。",
                    retryable=True,
                ) from error

            if source_path.is_file():
                tombstone = source_path.with_name(f".{source_path.name}.{uuid4().hex}.deleting")
                source_path.replace(tombstone)
            try:
                with self._database.transaction() as session:
                    paper = session.get(PaperRecord, paper_id, with_for_update=True)
                    if paper is None:
                        raise self._paper_not_found()
                    session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == paper_id))
                    session.delete(paper)
            except BaseException:
                if tombstone is not None and tombstone.exists() and source_path is not None:
                    tombstone.replace(source_path)
                raise
            if tombstone is not None:
                tombstone.unlink(missing_ok=True)
            return DeletePaperView(paper_id=paper_id)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def _persist_upload(
        self,
        *,
        temporary_path: Path,
        file_name: str,
        file_size: int,
        sha256: str,
    ) -> PaperUploadView:
        try:
            with self._database.session() as session:
                existing = session.scalar(select(PaperRecord).where(PaperRecord.sha256 == sha256))
                if existing is not None:
                    job = latest_job(session, existing.id)
                    return PaperUploadView(
                        paper=paper_view(session, existing),
                        ingestion_job=ingestion_job_view(job),
                        duplicate=True,
                    )
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

        paper_id = f"paper-{uuid4().hex}"
        job_id = f"job-{uuid4().hex}"
        destination = self._settings.storage_dir / "papers" / f"{paper_id}.pdf"
        temporary_path.replace(destination)
        now = utc_now()
        paper = PaperRecord(
            id=paper_id,
            sha256=sha256,
            title=self._default_title(file_name),
            authors=[],
            publication_year=None,
            original_filename=file_name,
            storage_path=str(destination.resolve()),
            file_size_bytes=file_size,
            page_count=None,
            status=PaperStatus.PROCESSING.value,
            created_at=now,
            updated_at=now,
        )
        job = IngestionJobRecord(
            id=job_id,
            paper_id=paper_id,
            status=IngestionJobStatus.QUEUED.value,
            stage=IngestionStage.QUEUED.value,
            attempt=0,
            max_attempts=self._settings.ingestion_max_attempts,
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
        try:
            with self._database.transaction() as session:
                session.add(paper)
                session.flush()
                session.add(job)
        except IntegrityError as error:
            destination.unlink(missing_ok=True)
            try:
                with self._database.session() as session:
                    existing = session.scalar(
                        select(PaperRecord).where(PaperRecord.sha256 == sha256)
                    )
                    if existing is None:
                        raise self._database_unavailable() from error
                    existing_job = latest_job(session, existing.id)
                    return PaperUploadView(
                        paper=paper_view(session, existing),
                        ingestion_job=ingestion_job_view(existing_job),
                        duplicate=True,
                    )
            except SQLAlchemyError as lookup_error:
                raise self._database_unavailable() from lookup_error
        except SQLAlchemyError as error:
            destination.unlink(missing_ok=True)
            raise self._database_unavailable() from error

        with self._database.session() as session:
            stored_paper = session.get(PaperRecord, paper_id)
            stored_job = session.get(IngestionJobRecord, job_id)
            if stored_paper is None or stored_job is None:
                raise RuntimeError("newly committed upload could not be reloaded")
            return PaperUploadView(
                paper=paper_view(session, stored_paper),
                ingestion_job=ingestion_job_view(stored_job),
                duplicate=False,
            )

    def _validated_file_name(self, value: str | None) -> str:
        if value is None or not value.strip():
            raise AgentError(
                status_code=400,
                code="INVALID_REQUEST",
                message="PDF 文件名不能为空。",
                details=(ErrorDetail(field="file", reason="filename is required"),),
            )
        file_name = Path(value.strip()).name
        if not file_name.lower().endswith(".pdf"):
            raise AgentError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="只支持 PDF 文件。",
                details=(ErrorDetail(field="file", reason="filename must end with .pdf"),),
            )
        return file_name[:512]

    def _default_title(self, file_name: str) -> str:
        stem = Path(file_name).stem.strip()
        return (stem or "Untitled paper")[:1024]

    def _paper_not_found(self) -> AgentError:
        return AgentError(
            status_code=404,
            code="PAPER_NOT_FOUND",
            message="未找到指定论文。",
        )

    def _database_unavailable(self) -> AgentError:
        return AgentError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="论文数据库暂时不可用。",
            retryable=True,
        )
