from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import AsyncUpload, LibraryFileService
from airesearcher_agent.application.library_lifecycle import LibraryLifecycleService
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
    LibraryFileRecord,
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


class PaperService:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        vector_store: VectorStore,
        library_file_service: LibraryFileService | None = None,
        library_lifecycle_service: LibraryLifecycleService | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._vector_store = vector_store
        self._library_files = library_file_service or LibraryFileService(
            database=database,
            settings=settings,
        )
        self._library_lifecycle = library_lifecycle_service or LibraryLifecycleService(
            database=database,
            settings=settings,
            vector_store=vector_store,
            library_file_service=self._library_files,
        )

    async def upload(self, upload: AsyncUpload) -> PaperUploadView:
        registered = await self._library_files.upload(upload)
        ingested = self._library_lifecycle.ingest_file(registered.library_file.library_file_id)
        return PaperUploadView(
            paper=ingested.paper,
            ingestion_job=ingested.ingestion_job,
            duplicate=ingested.duplicate,
        )

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
                linked_sources = session.scalars(
                    select(LibraryFileRecord)
                    .where(LibraryFileRecord.paper_id == paper.id)
                    .order_by(LibraryFileRecord.discovered_at, LibraryFileRecord.id)
                ).all()
                available_source_id = next(
                    (source.id for source in linked_sources if source.source_status == "AVAILABLE"),
                    None,
                )
                legacy_storage_path = paper.storage_path
                legacy_file_name = paper.original_filename
                legacy_file_size = paper.file_size_bytes
                legacy_sha256 = paper.sha256
            if available_source_id is not None:
                stored = self._library_files.get_file(available_source_id)
                return StoredPaperFile(
                    paper_id=paper_id,
                    path=stored.path,
                    file_name=stored.file_name,
                    file_size_bytes=stored.file_size_bytes,
                    sha256=stored.sha256,
                )
            if linked_sources:
                raise AgentError(
                    status_code=409,
                    code="LIBRARY_FILE_UNAVAILABLE",
                    message="论文没有可用原件，请重新扫描原件库。",
                )
            path = Path(legacy_storage_path).resolve()
            storage_root = (self._settings.storage_dir / "papers").resolve()
            if not path.is_relative_to(storage_root) or not path.is_file():
                raise AgentError(
                    status_code=500,
                    code="PAPER_FILE_MISSING",
                    message="论文文件不可用。",
                    retryable=False,
                )
            return StoredPaperFile(
                paper_id=paper_id,
                path=str(path),
                file_name=legacy_file_name,
                file_size_bytes=legacy_file_size,
                sha256=legacy_sha256,
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
                if paper.status == PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_EXCLUDED",
                        message="该论文已移出知识库，请使用恢复操作重新入库。",
                    )
                if latest_job(session, paper.id).id != job.id:
                    raise AgentError(
                        status_code=409,
                        code="INGESTION_NOT_RETRYABLE",
                        message="该任务已不是论文的最新入库任务。",
                    )
                job.status = IngestionJobStatus.QUEUED.value
                job.active_key = paper.id
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
        except IntegrityError as error:
            raise AgentError(
                status_code=409,
                code="PAPER_BUSY",
                message="论文正在入库，请稍后再操作。",
                retryable=True,
            ) from error
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def delete_paper(self, paper_id: str) -> DeletePaperView:
        now = utc_now()
        try:
            with self._database.transaction() as session:
                paper = session.get(PaperRecord, paper_id, with_for_update=True)
                if paper is None:
                    raise self._paper_not_found()
                active_job = session.scalar(
                    select(IngestionJobRecord)
                    .where(
                        IngestionJobRecord.paper_id == paper.id,
                        IngestionJobRecord.status.in_(
                            (
                                IngestionJobStatus.QUEUED.value,
                                IngestionJobStatus.RUNNING.value,
                            )
                        ),
                    )
                    .with_for_update()
                )
                if active_job is not None:
                    raise self._paper_busy()
                paper.status = PaperStatus.EXCLUDED.value
                paper.updated_at = now

            try:
                self._vector_store.delete_paper(paper_id)
            except Exception as error:
                raise AgentError(
                    status_code=503,
                    code="QDRANT_UNAVAILABLE",
                    message="向量服务暂时不可用；论文已停止检索，但清理尚未完成。",
                    retryable=True,
                ) from error

            with self._database.transaction() as session:
                paper = session.get(PaperRecord, paper_id, with_for_update=True)
                if paper is None:
                    raise self._paper_not_found()
                sources = session.scalars(
                    select(LibraryFileRecord)
                    .where(LibraryFileRecord.paper_id == paper_id)
                    .with_for_update()
                ).all()
                for source in sources:
                    if source.source_status == "AVAILABLE":
                        source.paper_id = None
                        source.updated_at = now
                    else:
                        session.delete(source)
                session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == paper_id))
                session.execute(
                    delete(IngestionJobRecord).where(IngestionJobRecord.paper_id == paper_id)
                )
                session.delete(paper)
            return DeletePaperView(paper_id=paper_id)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    @staticmethod
    def _paper_busy() -> AgentError:
        return AgentError(
            status_code=409,
            code="PAPER_BUSY",
            message="论文正在入库，请稍后再删除。",
            retryable=True,
        )

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
