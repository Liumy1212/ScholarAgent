import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from airesearcher_agent.application.library_scans import ACTIVE_SCAN_KEY
from airesearcher_agent.config import Settings
from airesearcher_agent.domain.library import (
    LibraryFileSourceStatus,
    LibraryScanItemOutcome,
    LibraryScanStatus,
)
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.persistence.models import (
    LibraryFileRecord,
    LibraryScanItemRecord,
    LibraryScanJobRecord,
    PaperRecord,
    utc_now,
)

logger = logging.getLogger(__name__)

FILE_CHUNK_BYTES = 1024 * 1024
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
TEMPORARY_SUFFIXES = {".tmp", ".temp", ".part", ".download", ".crdownload"}


def is_unsafe_link(*, is_symlink: bool, file_attributes: int) -> bool:
    return is_symlink or bool(file_attributes & REPARSE_POINT_ATTRIBUTE)


class ScanLeaseLostError(Exception):
    pass


class ScanFileError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ClaimedScan:
    scan_id: str
    worker_id: str


@dataclass(frozen=True, slots=True)
class DiscoveredEntry:
    path: Path
    relative_path: str
    path_key: str
    kind: str
    code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    path: Path
    relative_path: str
    path_key: str
    file_name: str
    file_size_bytes: int
    sha256: str


class LibraryScanWorker:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        worker_id: str,
    ) -> None:
        self._database = database
        self._settings = settings
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
            scans = session.scalars(
                select(LibraryScanJobRecord)
                .where(
                    LibraryScanJobRecord.status == LibraryScanStatus.RUNNING.value,
                    LibraryScanJobRecord.lease_expires_at.is_not(None),
                    LibraryScanJobRecord.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for scan in scans:
                session.execute(
                    delete(LibraryScanItemRecord).where(LibraryScanItemRecord.scan_id == scan.id)
                )
                scan.status = LibraryScanStatus.QUEUED.value
                scan.active_key = ACTIVE_SCAN_KEY
                scan.discovered_count = 0
                scan.registered_count = 0
                scan.unchanged_count = 0
                scan.duplicate_count = 0
                scan.excluded_count = 0
                scan.skipped_count = 0
                scan.failed_count = 0
                scan.lease_owner = None
                scan.lease_expires_at = None
                scan.failure_code = None
                scan.failure_message = None
                scan.completed_at = None
                scan.updated_at = now
                recovered += 1
        return recovered

    def claim_next(self) -> ClaimedScan | None:
        self.recover_expired_leases()
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        with self._database.transaction() as session:
            scan = session.scalars(
                select(LibraryScanJobRecord)
                .where(LibraryScanJobRecord.status == LibraryScanStatus.QUEUED.value)
                .order_by(LibraryScanJobRecord.created_at, LibraryScanJobRecord.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).first()
            if scan is None:
                return None
            session.execute(
                delete(LibraryScanItemRecord).where(LibraryScanItemRecord.scan_id == scan.id)
            )
            scan.status = LibraryScanStatus.RUNNING.value
            scan.active_key = ACTIVE_SCAN_KEY
            scan.discovered_count = 0
            scan.registered_count = 0
            scan.unchanged_count = 0
            scan.duplicate_count = 0
            scan.excluded_count = 0
            scan.skipped_count = 0
            scan.failed_count = 0
            scan.failure_code = None
            scan.failure_message = None
            scan.lease_owner = self._worker_id
            scan.lease_expires_at = lease_expires_at
            scan.started_at = scan.started_at or now
            scan.completed_at = None
            scan.updated_at = now
            return ClaimedScan(scan_id=scan.id, worker_id=self._worker_id)

    def _process(self, claimed: ClaimedScan) -> None:
        try:
            entries, fatal_traversal = self._discover(claimed)
            discovered_pdf_keys = {entry.path_key for entry in entries if entry.kind == "PDF"}
            matched_ids: set[str] = set()
            protected_keys: set[str] = set()
            for entry in entries:
                if entry.kind == "SKIPPED":
                    self._record_item(
                        claimed,
                        entry=entry,
                        outcome=LibraryScanItemOutcome.SKIPPED,
                        code=entry.code,
                        message=entry.message,
                    )
                    continue
                if entry.kind == "TRAVERSAL_FAILED":
                    self._record_item(
                        claimed,
                        entry=entry,
                        outcome=LibraryScanItemOutcome.FAILED,
                        code=entry.code,
                        message=entry.message,
                    )
                    continue
                protected_keys.add(entry.path_key)
                try:
                    fingerprint = self._fingerprint(entry)
                    self._reconcile_file(
                        claimed,
                        fingerprint,
                        discovered_pdf_keys=discovered_pdf_keys,
                        matched_ids=matched_ids,
                    )
                except ScanFileError as error:
                    self._record_item(
                        claimed,
                        entry=entry,
                        outcome=LibraryScanItemOutcome.FAILED,
                        code=error.code,
                        message=error.message,
                    )
            if fatal_traversal:
                self._fail(
                    claimed,
                    code="LIBRARY_TRAVERSAL_FAILED",
                    message="原件库目录未能完整遍历，未执行缺失原件对账。",
                )
                return
            self._mark_missing(claimed, protected_keys)
            self._complete(claimed)
        except ScanLeaseLostError:
            logger.warning("Worker lease was lost for library scan %s", claimed.scan_id)
        except SQLAlchemyError:
            logger.exception("Database failed for library scan %s", claimed.scan_id)
            self._fail(
                claimed,
                code="DATABASE_UNAVAILABLE",
                message="原件库数据库暂时不可用，扫描未完成。",
            )
        except Exception:
            logger.exception("Library scan %s failed unexpectedly", claimed.scan_id)
            self._fail(
                claimed,
                code="LIBRARY_SCAN_RUNTIME_FAILED",
                message="原件库扫描执行失败。",
            )

    def _discover(self, claimed: ClaimedScan) -> tuple[list[DiscoveredEntry], bool]:
        originals = self._settings.paper_library_originals_dir
        try:
            if originals.is_symlink():
                raise OSError("originals directory is a symbolic link")
            originals.mkdir(parents=True, exist_ok=True)
            originals_stat = originals.lstat()
            if is_unsafe_link(
                is_symlink=originals.is_symlink(),
                file_attributes=getattr(originals_stat, "st_file_attributes", 0),
            ):
                raise OSError("originals directory is a reparse point")
        except OSError as error:
            return [self._traversal_failure(".", originals, error)], True

        entries: list[DiscoveredEntry] = []
        fatal_traversal = False
        pending = [originals]
        while pending:
            directory = pending.pop()
            self._renew_claim(claimed)
            try:
                with os.scandir(directory) as directory_entries:
                    children = sorted(
                        directory_entries,
                        key=lambda item: item.name.casefold(),
                    )
            except OSError as error:
                relative_path = self._relative_path(originals, directory)
                entries.append(self._traversal_failure(relative_path, directory, error))
                fatal_traversal = True
                continue
            for child in children:
                path = Path(child.path)
                relative_path = self._relative_path(originals, path)
                path_key = self._path_key(relative_path)
                try:
                    file_stat = child.stat(follow_symlinks=False)
                except OSError as error:
                    entries.append(self._traversal_failure(relative_path, path, error))
                    fatal_traversal = True
                    continue
                if is_unsafe_link(
                    is_symlink=child.is_symlink(),
                    file_attributes=getattr(file_stat, "st_file_attributes", 0),
                ):
                    entries.append(
                        DiscoveredEntry(
                            path=path,
                            relative_path=relative_path,
                            path_key=path_key,
                            kind="SKIPPED",
                            code="UNSAFE_LIBRARY_PATH",
                            message="已跳过符号链接或 reparse point。",
                        )
                    )
                    continue
                if stat.S_ISDIR(file_stat.st_mode):
                    if child.name.startswith(".") or child.name == ".staging":
                        continue
                    pending.append(path)
                    continue
                if not stat.S_ISREG(file_stat.st_mode):
                    entries.append(
                        DiscoveredEntry(
                            path=path,
                            relative_path=relative_path,
                            path_key=path_key,
                            kind="SKIPPED",
                            code="UNSUPPORTED_FILE_TYPE",
                            message="已跳过非普通文件。",
                        )
                    )
                    continue
                skip = self._skip_reason(path.name)
                if skip is not None:
                    entries.append(
                        DiscoveredEntry(
                            path=path,
                            relative_path=relative_path,
                            path_key=path_key,
                            kind="SKIPPED",
                            code=skip[0],
                            message=skip[1],
                        )
                    )
                    continue
                entries.append(
                    DiscoveredEntry(
                        path=path,
                        relative_path=relative_path,
                        path_key=path_key,
                        kind="PDF",
                    )
                )
        entries.sort(key=lambda entry: entry.relative_path.casefold())
        return entries, fatal_traversal

    def _fingerprint(self, entry: DiscoveredEntry) -> FileFingerprint:
        if len(entry.relative_path) > 2048:
            raise ScanFileError(
                code="LIBRARY_PATH_TOO_LONG",
                message="原件相对路径超过 2048 个字符。",
            )
        try:
            self._assert_safe_path(entry.path)
            before = entry.path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise ScanFileError(
                    code="UNSUPPORTED_FILE_TYPE",
                    message="扫描项不是普通文件。",
                )
            if before.st_size <= 0:
                raise ScanFileError(code="INVALID_PDF", message="PDF 文件为空。")
            if before.st_size > self._settings.upload_max_bytes:
                raise ScanFileError(code="PDF_TOO_LARGE", message="PDF 不能超过 50 MB。")
            digest = hashlib.sha256()
            prefix = bytearray()
            size = 0
            with entry.path.open("rb") as source:
                while block := source.read(FILE_CHUNK_BYTES):
                    size += len(block)
                    if len(prefix) < 5:
                        prefix.extend(block[: 5 - len(prefix)])
                    digest.update(block)
            after = entry.path.stat()
            self._assert_safe_path(entry.path)
        except ScanFileError:
            raise
        except OSError as error:
            raise ScanFileError(
                code="LIBRARY_FILE_READ_FAILED",
                message="无法读取 PDF 原件。",
            ) from error
        if bytes(prefix) != b"%PDF-":
            raise ScanFileError(code="INVALID_PDF", message="文件缺少 PDF 签名。")
        if (
            before.st_size != size
            or after.st_size != size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
        ):
            raise ScanFileError(
                code="LIBRARY_FILE_CHANGED",
                message="PDF 在扫描过程中发生变化。",
            )
        return FileFingerprint(
            path=entry.path,
            relative_path=entry.relative_path,
            path_key=entry.path_key,
            file_name=entry.path.name[:512],
            file_size_bytes=size,
            sha256=digest.hexdigest(),
        )

    def _reconcile_file(
        self,
        claimed: ClaimedScan,
        fingerprint: FileFingerprint,
        *,
        discovered_pdf_keys: set[str],
        matched_ids: set[str],
    ) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            scan = self._locked_scan(session, claimed)
            exact_records = session.scalars(
                select(LibraryFileRecord)
                .where(
                    LibraryFileRecord.path_key == fingerprint.path_key,
                    LibraryFileRecord.relative_path == fingerprint.relative_path,
                )
                .order_by(LibraryFileRecord.discovered_at.desc(), LibraryFileRecord.id.desc())
            ).all()
            exact_same = next(
                (record for record in exact_records if record.sha256 == fingerprint.sha256),
                None,
            )
            if exact_same is not None:
                for record in exact_records:
                    if (
                        record.id != exact_same.id
                        and record.source_status == LibraryFileSourceStatus.AVAILABLE.value
                    ):
                        record.source_status = LibraryFileSourceStatus.REPLACED.value
                        record.updated_at = now
                self._refresh_record(exact_same, fingerprint, now)
                self._link_existing_paper(session, exact_same)
                matched_ids.add(exact_same.id)
                outcome = self._unchanged_outcome(session, exact_same)
                self._add_item(session, scan, fingerprint, outcome, exact_same)
                self._increment(scan, outcome, registered=False)
                self._renew(scan, now)
                return

            current_at_path = next(
                (
                    record
                    for record in exact_records
                    if record.source_status == LibraryFileSourceStatus.AVAILABLE.value
                ),
                None,
            )
            if current_at_path is not None:
                for record in exact_records:
                    if record.source_status == LibraryFileSourceStatus.AVAILABLE.value:
                        record.source_status = LibraryFileSourceStatus.REPLACED.value
                        record.updated_at = now
                created = self._new_record(session, fingerprint, now)
                session.add(created)
                session.flush()
                matched_ids.add(created.id)
                self._add_item(
                    session,
                    scan,
                    fingerprint,
                    LibraryScanItemOutcome.REGISTERED,
                    created,
                )
                self._increment(scan, LibraryScanItemOutcome.REGISTERED, registered=True)
                self._renew(scan, now)
                return

            move_statement = select(LibraryFileRecord).where(
                LibraryFileRecord.sha256 == fingerprint.sha256,
                LibraryFileRecord.source_status.in_(
                    (
                        LibraryFileSourceStatus.AVAILABLE.value,
                        LibraryFileSourceStatus.MISSING.value,
                    )
                ),
                LibraryFileRecord.path_key.not_in(discovered_pdf_keys),
            )
            if matched_ids:
                move_statement = move_statement.where(LibraryFileRecord.id.not_in(matched_ids))
            move_candidate = session.scalars(
                move_statement.order_by(
                    LibraryFileRecord.last_seen_at.desc(),
                    LibraryFileRecord.id,
                ).limit(1)
            ).first()
            if move_candidate is not None:
                self._refresh_record(move_candidate, fingerprint, now)
                self._link_existing_paper(session, move_candidate)
                matched_ids.add(move_candidate.id)
                self._add_item(
                    session,
                    scan,
                    fingerprint,
                    LibraryScanItemOutcome.MOVED,
                    move_candidate,
                )
                self._increment(scan, LibraryScanItemOutcome.MOVED, registered=False)
                self._renew(scan, now)
                return

            duplicate_exists = session.scalar(
                select(LibraryFileRecord.id)
                .where(LibraryFileRecord.sha256 == fingerprint.sha256)
                .limit(1)
            )
            created = self._new_record(session, fingerprint, now)
            session.add(created)
            session.flush()
            matched_ids.add(created.id)
            outcome = (
                LibraryScanItemOutcome.DUPLICATE
                if duplicate_exists is not None
                else LibraryScanItemOutcome.REGISTERED
            )
            self._add_item(session, scan, fingerprint, outcome, created)
            self._increment(scan, outcome, registered=True)
            self._renew(scan, now)

    def _record_item(
        self,
        claimed: ClaimedScan,
        *,
        entry: DiscoveredEntry,
        outcome: LibraryScanItemOutcome,
        code: str | None,
        message: str | None,
    ) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            scan = self._locked_scan(session, claimed)
            session.add(
                LibraryScanItemRecord(
                    scan_id=scan.id,
                    relative_path=entry.relative_path,
                    path_key=entry.path_key,
                    outcome=outcome.value,
                    library_file_id=None,
                    paper_id=None,
                    code=code[:128] if code is not None else None,
                    message=message[:2048] if message is not None else None,
                    created_at=now,
                )
            )
            self._increment(scan, outcome, registered=False)
            self._renew(scan, now)

    def _mark_missing(self, claimed: ClaimedScan, protected_keys: set[str]) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            scan = self._locked_scan(session, claimed)
            statement = select(LibraryFileRecord).where(
                LibraryFileRecord.source_status == LibraryFileSourceStatus.AVAILABLE.value
            )
            if protected_keys:
                statement = statement.where(LibraryFileRecord.path_key.not_in(protected_keys))
            for record in session.scalars(statement).all():
                record.source_status = LibraryFileSourceStatus.MISSING.value
                record.updated_at = now
            self._renew(scan, now)

    def _complete(self, claimed: ClaimedScan) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            scan = self._locked_scan(session, claimed)
            scan.status = LibraryScanStatus.SUCCEEDED.value
            scan.active_key = None
            scan.failure_code = None
            scan.failure_message = None
            scan.lease_owner = None
            scan.lease_expires_at = None
            scan.completed_at = now
            scan.updated_at = now

    def _fail(self, claimed: ClaimedScan, *, code: str, message: str) -> None:
        now = utc_now()
        try:
            with self._database.transaction() as session:
                scan = session.get(LibraryScanJobRecord, claimed.scan_id, with_for_update=True)
                if (
                    scan is None
                    or scan.status != LibraryScanStatus.RUNNING.value
                    or scan.lease_owner != claimed.worker_id
                ):
                    return
                scan.status = LibraryScanStatus.FAILED.value
                scan.active_key = None
                scan.failure_code = code[:128]
                scan.failure_message = message[:2048]
                scan.lease_owner = None
                scan.lease_expires_at = None
                scan.completed_at = now
                scan.updated_at = now
        except SQLAlchemyError:
            logger.exception("Could not persist failure for library scan %s", claimed.scan_id)

    def _renew_claim(self, claimed: ClaimedScan) -> None:
        now = utc_now()
        with self._database.transaction() as session:
            scan = self._locked_scan(session, claimed)
            self._renew(scan, now)

    def _locked_scan(
        self,
        session: Session,
        claimed: ClaimedScan,
    ) -> LibraryScanJobRecord:
        scan = session.get(LibraryScanJobRecord, claimed.scan_id, with_for_update=True)
        if (
            scan is None
            or scan.status != LibraryScanStatus.RUNNING.value
            or scan.lease_owner != claimed.worker_id
        ):
            raise ScanLeaseLostError
        return scan

    def _renew(self, scan: LibraryScanJobRecord, now: datetime) -> None:
        scan.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
        scan.updated_at = now

    def _add_item(
        self,
        session: Session,
        scan: LibraryScanJobRecord,
        fingerprint: FileFingerprint,
        outcome: LibraryScanItemOutcome,
        library_file: LibraryFileRecord,
    ) -> None:
        session.add(
            LibraryScanItemRecord(
                scan_id=scan.id,
                relative_path=fingerprint.relative_path,
                path_key=fingerprint.path_key,
                outcome=outcome.value,
                library_file_id=library_file.id,
                paper_id=library_file.paper_id,
                code=None,
                message=None,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _increment(
        scan: LibraryScanJobRecord,
        outcome: LibraryScanItemOutcome,
        *,
        registered: bool,
    ) -> None:
        scan.discovered_count += 1
        if registered:
            scan.registered_count += 1
        if outcome in {LibraryScanItemOutcome.UNCHANGED, LibraryScanItemOutcome.MOVED}:
            scan.unchanged_count += 1
        elif outcome is LibraryScanItemOutcome.DUPLICATE:
            scan.duplicate_count += 1
        elif outcome is LibraryScanItemOutcome.EXCLUDED:
            scan.excluded_count += 1
        elif outcome is LibraryScanItemOutcome.SKIPPED:
            scan.skipped_count += 1
        elif outcome is LibraryScanItemOutcome.FAILED:
            scan.failed_count += 1

    @staticmethod
    def _refresh_record(
        record: LibraryFileRecord,
        fingerprint: FileFingerprint,
        now: datetime,
    ) -> None:
        record.relative_path = fingerprint.relative_path
        record.path_key = fingerprint.path_key
        record.file_name = fingerprint.file_name
        record.file_size_bytes = fingerprint.file_size_bytes
        record.sha256 = fingerprint.sha256
        record.source_status = LibraryFileSourceStatus.AVAILABLE.value
        record.last_seen_at = now
        record.updated_at = now

    @staticmethod
    def _new_record(
        session: Session,
        fingerprint: FileFingerprint,
        now: datetime,
    ) -> LibraryFileRecord:
        paper_id = session.scalar(
            select(PaperRecord.id).where(PaperRecord.sha256 == fingerprint.sha256).limit(1)
        )
        return LibraryFileRecord(
            id=f"library-file-{uuid4().hex}",
            relative_path=fingerprint.relative_path,
            path_key=fingerprint.path_key,
            file_name=fingerprint.file_name,
            file_size_bytes=fingerprint.file_size_bytes,
            sha256=fingerprint.sha256,
            source_status=LibraryFileSourceStatus.AVAILABLE.value,
            paper_id=paper_id,
            discovered_at=now,
            last_seen_at=now,
            updated_at=now,
        )

    @staticmethod
    def _link_existing_paper(session: Session, record: LibraryFileRecord) -> None:
        if record.paper_id is not None:
            return
        record.paper_id = session.scalar(
            select(PaperRecord.id).where(PaperRecord.sha256 == record.sha256).limit(1)
        )

    @staticmethod
    def _unchanged_outcome(
        session: Session,
        record: LibraryFileRecord,
    ) -> LibraryScanItemOutcome:
        if record.paper_id is None:
            return LibraryScanItemOutcome.UNCHANGED
        paper = session.get(PaperRecord, record.paper_id)
        if paper is not None and paper.status == "EXCLUDED":
            return LibraryScanItemOutcome.EXCLUDED
        return LibraryScanItemOutcome.UNCHANGED

    @staticmethod
    def _skip_reason(file_name: str) -> tuple[str, str] | None:
        lowered = file_name.casefold()
        if file_name.startswith("."):
            return "HIDDEN_FILE", "已跳过隐藏文件。"
        if (
            file_name.startswith("~")
            or file_name.endswith("~")
            or Path(lowered).suffix in TEMPORARY_SUFFIXES
        ):
            return "TEMPORARY_FILE", "已跳过临时文件。"
        if not lowered.endswith(".pdf"):
            return "UNSUPPORTED_FILE_TYPE", "当前扫描只登记 PDF 原件。"
        return None

    def _assert_safe_path(self, path: Path) -> None:
        originals = self._settings.paper_library_originals_dir
        try:
            relative = path.relative_to(originals)
            current = originals
            for part in relative.parts:
                current = current / part
                path_stat = current.lstat()
                if is_unsafe_link(
                    is_symlink=current.is_symlink(),
                    file_attributes=getattr(path_stat, "st_file_attributes", 0),
                ):
                    raise ScanFileError(
                        code="UNSAFE_LIBRARY_PATH",
                        message="扫描过程中检测到符号链接或 reparse point。",
                    )
            if not path.resolve().is_relative_to(originals.resolve()):
                raise ScanFileError(
                    code="UNSAFE_LIBRARY_PATH",
                    message="原件路径超出 originals 目录。",
                )
        except ScanFileError:
            raise
        except (OSError, ValueError) as error:
            raise ScanFileError(
                code="UNSAFE_LIBRARY_PATH",
                message="无法安全解析原件路径。",
            ) from error

    @staticmethod
    def _relative_path(originals: Path, path: Path) -> str:
        if path == originals:
            return "."
        return path.relative_to(originals).as_posix()

    @staticmethod
    def _path_key(relative_path: str) -> str:
        return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()

    def _traversal_failure(
        self,
        relative_path: str,
        path: Path,
        error: OSError,
    ) -> DiscoveredEntry:
        return DiscoveredEntry(
            path=path,
            relative_path=relative_path,
            path_key=self._path_key(relative_path),
            kind="TRAVERSAL_FAILED",
            code="LIBRARY_TRAVERSAL_FAILED",
            message=f"无法遍历原件库路径：{error}"[:2048],
        )
