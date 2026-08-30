from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.library import (
    LibraryInfoView,
    LibraryScanFailureView,
    LibraryScanItemOutcome,
    LibraryScanItemsPageView,
    LibraryScanItemView,
    LibraryScanStatus,
    LibraryScanView,
)
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    LibraryScanItemRecord,
    LibraryScanJobRecord,
    utc_now,
)
from airesearcher_agent.persistence.repositories import as_utc

ACTIVE_SCAN_KEY = "ACTIVE"


class LibraryScanService:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        library_file_service: LibraryFileService,
    ) -> None:
        self._database = database
        self._settings = settings
        self._library_files = library_file_service

    def get_library_info(self) -> LibraryInfoView:
        try:
            with self._database.session() as session:
                latest = session.scalars(
                    select(LibraryScanJobRecord)
                    .order_by(
                        LibraryScanJobRecord.created_at.desc(),
                        LibraryScanJobRecord.id.desc(),
                    )
                    .limit(1)
                ).first()
                active = session.scalar(
                    select(func.count())
                    .select_from(LibraryScanJobRecord)
                    .where(LibraryScanJobRecord.active_key == ACTIVE_SCAN_KEY)
                )
                return LibraryInfoView(
                    root_path=str(self._settings.paper_library_dir),
                    supported_extensions=(".pdf",),
                    scan_in_progress=bool(active),
                    latest_scan=self._scan_view(latest) if latest is not None else None,
                )
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def create_scan(self) -> LibraryScanView:
        self._library_files.ensure_directories()
        now = utc_now()
        record = LibraryScanJobRecord(
            id=f"scan-{uuid4().hex}",
            status=LibraryScanStatus.QUEUED.value,
            active_key=ACTIVE_SCAN_KEY,
            discovered_count=0,
            registered_count=0,
            unchanged_count=0,
            duplicate_count=0,
            excluded_count=0,
            skipped_count=0,
            failed_count=0,
            failure_code=None,
            failure_message=None,
            lease_owner=None,
            lease_expires_at=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        try:
            with self._database.transaction() as session:
                active = session.scalar(
                    select(LibraryScanJobRecord)
                    .where(LibraryScanJobRecord.active_key == ACTIVE_SCAN_KEY)
                    .with_for_update()
                )
                if active is not None:
                    raise self._active_scan()
                session.add(record)
                session.flush()
            return self.get_scan(record.id)
        except AgentError:
            raise
        except IntegrityError as error:
            raise self._active_scan() from error
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def get_scan(self, scan_id: str) -> LibraryScanView:
        try:
            with self._database.session() as session:
                scan = session.get(LibraryScanJobRecord, scan_id)
                if scan is None:
                    raise self._not_found()
                return self._scan_view(scan)
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    def list_items(
        self,
        scan_id: str,
        *,
        offset: int,
        limit: int,
        outcome: LibraryScanItemOutcome | None,
    ) -> LibraryScanItemsPageView:
        try:
            with self._database.session() as session:
                if session.get(LibraryScanJobRecord, scan_id) is None:
                    raise self._not_found()
                filters = [LibraryScanItemRecord.scan_id == scan_id]
                if outcome is not None:
                    filters.append(LibraryScanItemRecord.outcome == outcome.value)
                total = int(
                    session.scalar(
                        select(func.count()).select_from(LibraryScanItemRecord).where(*filters)
                    )
                    or 0
                )
                items = session.scalars(
                    select(LibraryScanItemRecord)
                    .where(*filters)
                    .order_by(LibraryScanItemRecord.id)
                    .offset(offset)
                    .limit(limit)
                ).all()
                return LibraryScanItemsPageView(
                    items=tuple(self._item_view(item) for item in items),
                    total=total,
                    offset=offset,
                    limit=limit,
                )
        except AgentError:
            raise
        except SQLAlchemyError as error:
            raise self._database_unavailable() from error

    @staticmethod
    def _scan_view(scan: LibraryScanJobRecord) -> LibraryScanView:
        created_at = as_utc(scan.created_at)
        if created_at is None:
            raise RuntimeError("library scan created_at must not be null")
        failure = (
            LibraryScanFailureView(code=scan.failure_code, message=scan.failure_message)
            if scan.failure_code is not None and scan.failure_message is not None
            else None
        )
        return LibraryScanView(
            scan_id=scan.id,
            status=LibraryScanStatus(scan.status),
            discovered_count=scan.discovered_count,
            registered_count=scan.registered_count,
            unchanged_count=scan.unchanged_count,
            duplicate_count=scan.duplicate_count,
            excluded_count=scan.excluded_count,
            skipped_count=scan.skipped_count,
            failed_count=scan.failed_count,
            created_at=created_at,
            started_at=as_utc(scan.started_at),
            completed_at=as_utc(scan.completed_at),
            failure=failure,
        )

    @staticmethod
    def _item_view(item: LibraryScanItemRecord) -> LibraryScanItemView:
        return LibraryScanItemView(
            relative_path=item.relative_path,
            outcome=LibraryScanItemOutcome(item.outcome),
            library_file_id=item.library_file_id,
            paper_id=item.paper_id,
            code=item.code,
            message=item.message,
        )

    @staticmethod
    def _active_scan() -> AgentError:
        return AgentError(
            status_code=409,
            code="LIBRARY_SCAN_ACTIVE",
            message="原件库扫描正在进行。",
            retryable=True,
        )

    @staticmethod
    def _not_found() -> AgentError:
        return AgentError(
            status_code=404,
            code="LIBRARY_SCAN_NOT_FOUND",
            message="未找到指定原件库扫描任务。",
        )

    @staticmethod
    def _database_unavailable() -> AgentError:
        return AgentError(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="原件库数据库暂时不可用。",
            retryable=True,
        )
