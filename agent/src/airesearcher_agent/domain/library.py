from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from airesearcher_agent.domain.papers import (
    IngestionJobView,
    IngestionSummaryView,
    PaperView,
)


class LibraryFileSourceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    REPLACED = "REPLACED"


class LibraryFileKnowledgeStatus(StrEnum):
    NOT_INGESTED = "NOT_INGESTED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    EXCLUDED = "EXCLUDED"


class LibraryScanStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class LibraryScanItemOutcome(StrEnum):
    REGISTERED = "REGISTERED"
    UNCHANGED = "UNCHANGED"
    MOVED = "MOVED"
    DUPLICATE = "DUPLICATE"
    EXCLUDED = "EXCLUDED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class LibraryFileView:
    library_file_id: str
    relative_path: str
    file_name: str
    file_size_bytes: int
    sha256: str
    source_status: LibraryFileSourceStatus
    knowledge_status: LibraryFileKnowledgeStatus
    paper_id: str | None
    paper_title: str | None
    searchable: bool
    current_ingestion: IngestionSummaryView | None
    discovered_at: datetime
    last_seen_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryFilesPageView:
    items: tuple[LibraryFileView, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class LibraryFileUploadView:
    library_file: LibraryFileView
    duplicate: bool


@dataclass(frozen=True, slots=True)
class LibraryFileIngestionView:
    library_file: LibraryFileView
    paper: PaperView
    ingestion_job: IngestionJobView
    duplicate: bool


@dataclass(frozen=True, slots=True)
class StoredLibraryFile:
    library_file_id: str
    path: str
    file_name: str
    file_size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LibraryScanFailureView:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class LibraryScanView:
    scan_id: str
    status: LibraryScanStatus
    discovered_count: int
    registered_count: int
    unchanged_count: int
    duplicate_count: int
    excluded_count: int
    skipped_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure: LibraryScanFailureView | None


@dataclass(frozen=True, slots=True)
class LibraryInfoView:
    root_path: str
    supported_extensions: tuple[str, ...]
    scan_in_progress: bool
    latest_scan: LibraryScanView | None


@dataclass(frozen=True, slots=True)
class LibraryScanItemView:
    relative_path: str
    outcome: LibraryScanItemOutcome
    library_file_id: str | None
    paper_id: str | None
    code: str | None
    message: str | None


@dataclass(frozen=True, slots=True)
class LibraryScanItemsPageView:
    items: tuple[LibraryScanItemView, ...]
    total: int
    offset: int
    limit: int
