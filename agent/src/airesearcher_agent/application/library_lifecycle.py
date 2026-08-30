from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.library import (
    LibraryFileIngestionView,
    LibraryFileSourceStatus,
)
from airesearcher_agent.domain.papers import (
    IngestionJobStatus,
    IngestionStage,
    PaperStatus,
    PaperView,
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
    paper_view,
)
from airesearcher_agent.retrieval.ports import VectorStore


class LibraryLifecycleService:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        vector_store: VectorStore,
        library_file_service: LibraryFileService,
    ) -> None:
        self._database = database
        self._settings = settings
        self._vector_store = vector_store
        self._library_files = library_file_service

    def ingest_file(self, library_file_id: str) -> LibraryFileIngestionView:
        stored = self._library_files.get_file(library_file_id)
        try:
            paper_id, job_id, duplicate = self._create_or_reuse_ingestion(
                library_file_id=library_file_id,
                expected_sha256=stored.sha256,
                expected_size=stored.file_size_bytes,
                storage_path=stored.path,
                file_name=stored.file_name,
            )
        except IntegrityError:
            paper_id, job_id = self._reuse_after_race(
                library_file_id=library_file_id,
                sha256=stored.sha256,
            )
            duplicate = True
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error
        return self._ingestion_view(
            library_file_id=library_file_id,
            paper_id=paper_id,
            job_id=job_id,
            duplicate=duplicate,
        )

    def exclude_paper(self, paper_id: str) -> PaperView:
        now = utc_now()
        try:
            with self._database.transaction() as session:
                paper = session.get(PaperRecord, paper_id, with_for_update=True)
                if paper is None:
                    raise self._paper_not_found()
                if self._active_job(session, paper.id) is not None:
                    raise self._paper_busy()
                paper.status = PaperStatus.EXCLUDED.value
                paper.updated_at = now
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

        try:
            self._vector_store.delete_paper(paper_id)
        except Exception as error:
            raise AgentError(
                status_code=503,
                code="QDRANT_UNAVAILABLE",
                message="向量服务暂时不可用；论文已停止检索，但清理尚未完成。",
                retryable=True,
            ) from error

        try:
            with self._database.transaction() as session:
                paper = session.get(PaperRecord, paper_id, with_for_update=True)
                if paper is None:
                    raise self._paper_not_found()
                if paper.status != PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_STATE_CHANGED",
                        message="论文状态已经变化，请刷新后重试。",
                        retryable=True,
                    )
                session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == paper_id))
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error
        return self._paper_view(paper_id)

    def restore_paper(self, paper_id: str) -> PaperView:
        try:
            with self._database.session() as session:
                paper = session.get(PaperRecord, paper_id)
                if paper is None:
                    raise self._paper_not_found()
                if paper.status != PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_NOT_EXCLUDED",
                        message="只有已移出知识库的论文可以恢复。",
                    )
                source = self._available_source(session, paper.id)
                if source is None:
                    raise self._source_unavailable()
                source_id = source.id
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

        stored = self._library_files.get_file(source_id)
        now = utc_now()
        job_id = f"job-{uuid4().hex}"
        try:
            with self._database.transaction() as session:
                paper = session.get(PaperRecord, paper_id, with_for_update=True)
                if paper is None:
                    raise self._paper_not_found()
                if paper.status != PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_STATE_CHANGED",
                        message="论文状态已经变化，请刷新后重试。",
                        retryable=True,
                    )
                if self._active_job(session, paper.id) is not None:
                    raise self._paper_busy()
                source = session.get(LibraryFileRecord, source_id, with_for_update=True)
                self._verify_source_record(
                    source,
                    expected_sha256=stored.sha256,
                    expected_size=stored.file_size_bytes,
                )
                try:
                    self._vector_store.delete_paper(paper_id)
                except Exception as error:
                    raise AgentError(
                        status_code=503,
                        code="QDRANT_UNAVAILABLE",
                        message="向量服务暂时不可用，论文尚未恢复。",
                        retryable=True,
                    ) from error
                self._link_available_sources(session, paper)
                session.execute(delete(ChunkRecord).where(ChunkRecord.paper_id == paper.id))
                session.add(self._new_job(job_id=job_id, paper_id=paper.id, now=now))
                paper.storage_path = stored.path
                paper.status = PaperStatus.PROCESSING.value
                paper.updated_at = now
        except AgentError:
            raise
        except IntegrityError as error:
            raise self._paper_busy() from error
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error
        return self._paper_view(paper_id)

    def _create_or_reuse_ingestion(
        self,
        *,
        library_file_id: str,
        expected_sha256: str,
        expected_size: int,
        storage_path: str,
        file_name: str,
    ) -> tuple[str, str, bool]:
        now = utc_now()
        with self._database.transaction() as session:
            source = session.get(LibraryFileRecord, library_file_id, with_for_update=True)
            self._verify_source_record(
                source,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
            )
            paper = session.scalar(
                select(PaperRecord).where(PaperRecord.sha256 == expected_sha256).with_for_update()
            )
            if paper is not None:
                if paper.status == PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_EXCLUDED",
                        message="该论文已移出知识库，请使用恢复操作重新入库。",
                    )
                self._link_available_sources(session, paper)
                job = latest_job(session, paper.id)
                return paper.id, job.id, True

            paper_id = f"paper-{uuid4().hex}"
            job_id = f"job-{uuid4().hex}"
            paper = PaperRecord(
                id=paper_id,
                sha256=expected_sha256,
                title=self._default_title(file_name),
                authors=[],
                publication_year=None,
                original_filename=file_name,
                storage_path=storage_path,
                file_size_bytes=expected_size,
                page_count=None,
                status=PaperStatus.PROCESSING.value,
                created_at=now,
                updated_at=now,
            )
            session.add(paper)
            session.flush()
            self._link_available_sources(session, paper)
            session.add(self._new_job(job_id=job_id, paper_id=paper_id, now=now))
            return paper_id, job_id, False

    def _reuse_after_race(self, *, library_file_id: str, sha256: str) -> tuple[str, str]:
        try:
            with self._database.transaction() as session:
                source = session.get(LibraryFileRecord, library_file_id, with_for_update=True)
                self._verify_source_record(source, expected_sha256=sha256, expected_size=None)
                paper = session.scalar(
                    select(PaperRecord).where(PaperRecord.sha256 == sha256).with_for_update()
                )
                if paper is None:
                    raise self._database_unavailable()
                if paper.status == PaperStatus.EXCLUDED.value:
                    raise AgentError(
                        status_code=409,
                        code="PAPER_EXCLUDED",
                        message="该论文已移出知识库，请使用恢复操作重新入库。",
                    )
                self._link_available_sources(session, paper)
                return paper.id, latest_job(session, paper.id).id
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def _ingestion_view(
        self,
        *,
        library_file_id: str,
        paper_id: str,
        job_id: str,
        duplicate: bool,
    ) -> LibraryFileIngestionView:
        library_file = self._library_files.get_library_file(library_file_id)
        try:
            with self._database.session() as session:
                paper = session.get(PaperRecord, paper_id)
                job = session.get(IngestionJobRecord, job_id)
                if paper is None or job is None:
                    raise RuntimeError("committed ingestion records could not be reloaded")
                return LibraryFileIngestionView(
                    library_file=library_file,
                    paper=paper_view(session, paper),
                    ingestion_job=ingestion_job_view(job),
                    duplicate=duplicate,
                )
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def _paper_view(self, paper_id: str) -> PaperView:
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

    def _link_available_sources(self, session: Session, paper: PaperRecord) -> None:
        sources = session.scalars(
            select(LibraryFileRecord)
            .where(
                LibraryFileRecord.sha256 == paper.sha256,
                LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value,
            )
            .with_for_update()
        ).all()
        if not sources:
            raise self._source_unavailable()
        now = utc_now()
        for source in sources:
            if source.paper_id is not None and source.paper_id != paper.id:
                raise AgentError(
                    status_code=409,
                    code="LIBRARY_FILE_ALREADY_LINKED",
                    message="相同原件已经关联到另一篇论文。",
                )
            source.paper_id = paper.id
            source.updated_at = now

    def _available_source(self, session: Session, paper_id: str) -> LibraryFileRecord | None:
        return session.scalars(
            select(LibraryFileRecord)
            .where(
                LibraryFileRecord.paper_id == paper_id,
                LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value,
            )
            .order_by(LibraryFileRecord.last_seen_at.desc(), LibraryFileRecord.id)
            .limit(1)
        ).first()

    @staticmethod
    def _active_job(session: Session, paper_id: str) -> IngestionJobRecord | None:
        return session.scalar(
            select(IngestionJobRecord).where(IngestionJobRecord.active_key == paper_id).limit(1)
        )

    def _new_job(self, *, job_id: str, paper_id: str, now: datetime) -> IngestionJobRecord:
        return IngestionJobRecord(
            id=job_id,
            paper_id=paper_id,
            active_key=paper_id,
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

    @staticmethod
    def _verify_source_record(
        source: LibraryFileRecord | None,
        *,
        expected_sha256: str,
        expected_size: int | None,
    ) -> None:
        if source is None:
            raise AgentError(
                status_code=404,
                code="LIBRARY_FILE_NOT_FOUND",
                message="未找到指定原件。",
            )
        if source.source_status != LibraryFileSourceStatus.AVAILABLE.value:
            raise LibraryLifecycleService._source_unavailable()
        if source.sha256 != expected_sha256 or (
            expected_size is not None and source.file_size_bytes != expected_size
        ):
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_CHANGED",
                message="原件在创建入库任务前发生变化，请重新扫描。",
            )

    @staticmethod
    def _default_title(file_name: str) -> str:
        stem = Path(file_name).stem.strip()
        return (stem or "Untitled paper")[:1024]

    @staticmethod
    def _paper_not_found() -> AgentError:
        return AgentError(status_code=404, code="PAPER_NOT_FOUND", message="未找到指定论文。")

    @staticmethod
    def _paper_busy() -> AgentError:
        return AgentError(
            status_code=409,
            code="PAPER_BUSY",
            message="论文正在入库，请稍后再操作。",
            retryable=True,
        )

    @staticmethod
    def _source_unavailable() -> AgentError:
        return AgentError(
            status_code=409,
            code="LIBRARY_FILE_UNAVAILABLE",
            message="论文没有可用原件，请重新扫描原件库。",
        )

    @staticmethod
    def _database_unavailable() -> AgentError:
        return AgentError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="论文数据库暂时不可用。",
            retryable=True,
        )
