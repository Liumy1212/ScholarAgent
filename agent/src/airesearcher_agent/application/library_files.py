import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from airesearcher_agent.application.errors import AgentError, ErrorDetail
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.library import (
    LibraryFileKnowledgeStatus,
    LibraryFileSourceStatus,
    LibraryFilesPageView,
    LibraryFileUploadView,
    LibraryFileView,
    LibraryStateFilter,
    StoredLibraryFile,
)
from airesearcher_agent.domain.papers import PaperStatus
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import LibraryFileRecord, PaperRecord, utc_now
from airesearcher_agent.persistence.repositories import as_utc, ingestion_summary_view, latest_job

UPLOAD_CHUNK_BYTES = 1024 * 1024
INVALID_WINDOWS_FILE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AsyncUpload(Protocol):
    @property
    def filename(self) -> str | None: ...

    @property
    def content_type(self) -> str | None: ...

    async def read(self, size: int = -1) -> bytes: ...


class LibraryFileService:
    def __init__(self, *, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings
        self._registration_lock = Lock()

    def ensure_directories(self) -> None:
        self._ensure_safe_directories()

    async def upload(self, upload: AsyncUpload) -> LibraryFileUploadView:
        file_name = self._validated_file_name(upload.filename)
        if upload.content_type not in {None, "", "application/pdf", "application/octet-stream"}:
            raise AgentError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="只支持 PDF 文件。",
                details=(
                    ErrorDetail(
                        field="file",
                        reason=(
                            "content type must be application/pdf, "
                            "application/octet-stream, or omitted"
                        ),
                    ),
                ),
            )

        self._ensure_safe_directories()
        staging_path = self._settings.paper_library_staging_dir / f"upload-{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            with staging_path.open("xb") as destination:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_BYTES)
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
                destination.flush()
                os.fsync(destination.fileno())
            if size == 0 or bytes(prefix) != b"%PDF-":
                raise AgentError(
                    status_code=422,
                    code="INVALID_PDF",
                    message="上传文件不是有效的 PDF。",
                    details=(ErrorDetail(field="file", reason="missing PDF signature"),),
                )
            sha256 = digest.hexdigest()
            self._verify_staged_file(staging_path, expected_size=size, expected_sha256=sha256)
            with self._registration_lock:
                return self._register_staged_file(
                    staging_path=staging_path,
                    file_name=file_name,
                    file_size_bytes=size,
                    sha256=sha256,
                )
        except AgentError:
            raise
        except OSError as error:
            raise AgentError(
                status_code=500,
                code="LIBRARY_FILE_STORE_FAILED",
                message="无法写入 PDF 原件库。",
            ) from error
        finally:
            staging_path.unlink(missing_ok=True)

    def list_files(
        self,
        *,
        offset: int,
        limit: int,
        library_state: LibraryStateFilter | None = None,
    ) -> LibraryFilesPageView:
        conditions = self._library_state_conditions(library_state)
        try:
            with self._database.session() as session:
                total = int(
                    session.scalar(
                        select(func.count())
                        .select_from(LibraryFileRecord)
                        .outerjoin(PaperRecord, PaperRecord.id == LibraryFileRecord.paper_id)
                        .where(*conditions)
                    )
                    or 0
                )
                records = session.scalars(
                    select(LibraryFileRecord)
                    .outerjoin(PaperRecord, PaperRecord.id == LibraryFileRecord.paper_id)
                    .where(*conditions)
                    .order_by(
                        LibraryFileRecord.discovered_at.desc(),
                        LibraryFileRecord.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                ).all()
                items = tuple(self._view(session, record) for record in records)
            return LibraryFilesPageView(items=items, total=total, offset=offset, limit=limit)
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    @staticmethod
    def _library_state_conditions(
        library_state: LibraryStateFilter | None,
    ) -> tuple[ColumnElement[bool], ...]:
        if library_state is LibraryStateFilter.ORIGINAL_MISSING:
            return (
                PaperRecord.id.is_not(None),
                LibraryFileRecord.source_status.in_(
                    (
                        LibraryFileSourceStatus.MISSING.value,
                        LibraryFileSourceStatus.REPLACED.value,
                    )
                ),
            )
        if library_state is LibraryStateFilter.NOT_INGESTED:
            return (
                LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value,
                or_(PaperRecord.id.is_(None), PaperRecord.status != PaperStatus.READY.value),
            )
        if library_state is LibraryStateFilter.INGESTED:
            return (
                LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value,
                PaperRecord.status == PaperStatus.READY.value,
            )
        return ()

    def get_file(self, library_file_id: str) -> StoredLibraryFile:
        try:
            with self._database.session() as session:
                record = session.get(LibraryFileRecord, library_file_id)
                if record is None:
                    raise self._not_found()
                if record.source_status != LibraryFileSourceStatus.AVAILABLE.value:
                    raise AgentError(
                        status_code=409,
                        code="LIBRARY_FILE_UNAVAILABLE",
                        message="原件当前不可用，请重新扫描原件库。",
                    )
                path = self._resolve_available_path(record.relative_path)
                self._verify_registered_file(path, record)
                return StoredLibraryFile(
                    library_file_id=record.id,
                    path=str(path),
                    file_name=record.file_name,
                    file_size_bytes=record.file_size_bytes,
                    sha256=record.sha256,
                )
        except AgentError:
            raise
        except OSError as error:
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_UNAVAILABLE",
                message="原件文件不存在或不可用，请重新扫描原件库。",
            ) from error
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_library_file(self, library_file_id: str) -> LibraryFileView:
        try:
            with self._database.session() as session:
                record = session.get(LibraryFileRecord, library_file_id)
                if record is None:
                    raise self._not_found()
                return self._view(session, record)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_record(self, library_file_id: str) -> LibraryFileRecord:
        try:
            with self._database.session() as session:
                record = session.get(LibraryFileRecord, library_file_id)
                if record is None:
                    raise self._not_found()
                session.expunge(record)
                return record
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def _register_staged_file(
        self,
        *,
        staging_path: Path,
        file_name: str,
        file_size_bytes: int,
        sha256: str,
    ) -> LibraryFileUploadView:
        try:
            with self._database.session() as session:
                existing = session.scalar(
                    select(LibraryFileRecord)
                    .where(
                        LibraryFileRecord.sha256 == sha256,
                        LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value,
                    )
                    .order_by(LibraryFileRecord.discovered_at, LibraryFileRecord.id)
                )
                if existing is not None:
                    return LibraryFileUploadView(
                        library_file=self._view(session, existing),
                        duplicate=True,
                    )
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

        destination = self._unused_upload_path(file_name, sha256)
        try:
            os.link(staging_path, destination)
        except FileExistsError:
            destination = self._unused_upload_path(file_name, sha256, force_unique=True)
            os.link(staging_path, destination)
        except OSError as error:
            raise AgentError(
                status_code=500,
                code="LIBRARY_FILE_STORE_FAILED",
                message="无法将 PDF 原子写入原件库。",
            ) from error

        relative_path = destination.relative_to(
            self._settings.paper_library_originals_dir
        ).as_posix()
        now = utc_now()
        record = LibraryFileRecord(
            id=f"library-file-{uuid4().hex}",
            relative_path=relative_path,
            path_key=hashlib.sha256(relative_path.encode("utf-8")).hexdigest(),
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            sha256=sha256,
            source_status=LibraryFileSourceStatus.AVAILABLE.value,
            paper_id=None,
            discovered_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        try:
            with self._database.transaction() as session:
                session.add(record)
                session.flush()
            with self._database.session() as session:
                stored = session.get(LibraryFileRecord, record.id)
                if stored is None:
                    raise RuntimeError("newly committed library file could not be reloaded")
                return LibraryFileUploadView(
                    library_file=self._view(session, stored),
                    duplicate=False,
                )
        except SQLAlchemyError as error:
            destination.unlink(missing_ok=True)
            raise self._database_unavailable() from error

    def _view(self, session: Session, record: LibraryFileRecord) -> LibraryFileView:
        paper = session.get(PaperRecord, record.paper_id) if record.paper_id is not None else None
        current_ingestion = latest_job(session, paper.id) if paper is not None else None
        knowledge_status = (
            LibraryFileKnowledgeStatus.NOT_INGESTED
            if paper is None
            else LibraryFileKnowledgeStatus(paper.status)
        )
        discovered_at = as_utc(record.discovered_at)
        last_seen_at = as_utc(record.last_seen_at)
        updated_at = as_utc(record.updated_at)
        if discovered_at is None or last_seen_at is None or updated_at is None:
            raise RuntimeError("library file timestamps must not be null")
        source_status = LibraryFileSourceStatus(record.source_status)
        return LibraryFileView(
            library_file_id=record.id,
            relative_path=record.relative_path,
            file_name=record.file_name,
            file_size_bytes=record.file_size_bytes,
            sha256=record.sha256,
            source_status=source_status,
            knowledge_status=knowledge_status,
            paper_id=paper.id if paper is not None else None,
            paper_title=paper.title if paper is not None else None,
            searchable=(
                source_status is LibraryFileSourceStatus.AVAILABLE
                and paper is not None
                and paper.status == PaperStatus.READY.value
            ),
            current_ingestion=(
                ingestion_summary_view(current_ingestion) if current_ingestion is not None else None
            ),
            discovered_at=discovered_at,
            last_seen_at=last_seen_at,
            updated_at=updated_at,
        )

    def _validated_file_name(self, value: str | None) -> str:
        if value is None or not value.strip():
            raise AgentError(
                status_code=400,
                code="INVALID_REQUEST",
                message="PDF 文件名不能为空。",
                details=(ErrorDetail(field="file", reason="filename is required"),),
            )
        raw_name = value.strip()
        if raw_name != Path(raw_name).name or "/" in raw_name or "\\" in raw_name:
            raise AgentError(
                status_code=400,
                code="INVALID_FILE_NAME",
                message="PDF 文件名不能包含路径。",
                details=(ErrorDetail(field="file", reason="path components are not allowed"),),
            )
        if not raw_name.lower().endswith(".pdf"):
            raise AgentError(
                status_code=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="只支持 PDF 文件。",
                details=(ErrorDetail(field="file", reason="filename must end with .pdf"),),
            )
        safe_name = INVALID_WINDOWS_FILE_NAME.sub("_", raw_name).rstrip(" .")
        if not safe_name or safe_name in {".", ".."}:
            raise AgentError(
                status_code=400,
                code="INVALID_FILE_NAME",
                message="PDF 文件名无效。",
            )
        if len(safe_name) > 512:
            safe_name = f"{safe_name[:508]}.pdf"
        return safe_name

    def _ensure_safe_directories(self) -> None:
        for path in (
            self._settings.paper_library_dir,
            self._settings.paper_library_originals_dir,
            self._settings.paper_library_originals_dir / "uploads",
            self._settings.paper_library_staging_dir,
        ):
            if path.is_symlink():
                raise AgentError(
                    status_code=409,
                    code="UNSAFE_LIBRARY_PATH",
                    message="原件库目录不能使用符号链接。",
                )
        try:
            self._settings.ensure_paper_library_directories()
        except OSError as error:
            raise AgentError(
                status_code=409,
                code="UNSAFE_LIBRARY_PATH",
                message="原件库目录不可用。",
            ) from error
        for path in (
            self._settings.paper_library_originals_dir / "uploads",
            self._settings.paper_library_staging_dir,
        ):
            if path.is_symlink() or not path.is_dir():
                raise AgentError(
                    status_code=409,
                    code="UNSAFE_LIBRARY_PATH",
                    message="原件库目录不可用。",
                )

    def _verify_staged_file(
        self,
        path: Path,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        if path.is_symlink() or not path.is_file():
            raise AgentError(
                status_code=409,
                code="UNSAFE_LIBRARY_PATH",
                message="暂存文件不可用。",
            )
        first = path.stat()
        actual_sha256 = self._sha256(path)
        second = path.stat()
        if (
            first.st_size != expected_size
            or second.st_size != expected_size
            or first.st_mtime_ns != second.st_mtime_ns
            or actual_sha256 != expected_sha256
        ):
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_CHANGED",
                message="PDF 在登记过程中发生变化，请重新上传。",
            )

    def _verify_registered_file(self, path: Path, record: LibraryFileRecord) -> None:
        first = path.stat()
        if first.st_size != record.file_size_bytes or self._sha256(path) != record.sha256:
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_CHANGED",
                message="原件内容与登记信息不一致，请重新扫描原件库。",
            )
        second = path.stat()
        if first.st_mtime_ns != second.st_mtime_ns or first.st_size != second.st_size:
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_CHANGED",
                message="原件正在变化，请稍后重试。",
            )

    def _resolve_available_path(self, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise self._unsafe_registered_path()
        originals = self._settings.paper_library_originals_dir.resolve()
        candidate = originals.joinpath(*relative.parts)
        current = originals
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise self._unsafe_registered_path()
        resolved = candidate.resolve()
        if not resolved.is_relative_to(originals) or not resolved.is_file():
            raise AgentError(
                status_code=409,
                code="LIBRARY_FILE_UNAVAILABLE",
                message="原件文件不存在或不可用，请重新扫描原件库。",
            )
        return resolved

    def _unused_upload_path(
        self,
        file_name: str,
        sha256: str,
        *,
        force_unique: bool = False,
    ) -> Path:
        uploads = self._settings.paper_library_originals_dir / "uploads"
        requested = uploads / file_name
        if not force_unique and not requested.exists() and not requested.is_symlink():
            return requested
        stem = Path(file_name).stem[:440]
        candidate = uploads / f"{stem}-{sha256[:12]}.pdf"
        if not force_unique and not candidate.exists() and not candidate.is_symlink():
            return candidate
        return uploads / f"{stem}-{sha256[:12]}-{uuid4().hex[:8]}.pdf"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(UPLOAD_CHUNK_BYTES):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _not_found() -> AgentError:
        return AgentError(
            status_code=404,
            code="LIBRARY_FILE_NOT_FOUND",
            message="未找到指定原件。",
        )

    @staticmethod
    def _unsafe_registered_path() -> AgentError:
        return AgentError(
            status_code=409,
            code="UNSAFE_LIBRARY_PATH",
            message="原件登记路径不安全。",
        )

    @staticmethod
    def _database_unavailable() -> AgentError:
        return AgentError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="原件库数据库暂时不可用。",
            retryable=True,
        )
