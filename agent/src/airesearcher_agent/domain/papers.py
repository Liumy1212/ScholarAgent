from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PaperStatus(StrEnum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    EXCLUDED = "EXCLUDED"


class PaperSourceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    REPLACED = "REPLACED"


class IngestionJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IngestionStage(StrEnum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class IngestionFailureView:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class IngestionSummaryView:
    job_id: str
    status: IngestionJobStatus
    stage: IngestionStage
    attempt: int
    max_attempts: int
    can_retry: bool
    failure: IngestionFailureView | None


@dataclass(frozen=True, slots=True)
class PaperView:
    paper_id: str
    title: str
    authors: tuple[str, ...]
    publication_year: int | None
    file_name: str
    file_size_bytes: int
    library_relative_path: str
    source_status: PaperSourceStatus
    status: PaperStatus
    searchable: bool
    page_count: int | None
    created_at: datetime
    updated_at: datetime
    current_ingestion: IngestionSummaryView


@dataclass(frozen=True, slots=True)
class IngestionJobView(IngestionSummaryView):
    paper_id: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PaperUploadView:
    paper: PaperView
    ingestion_job: IngestionJobView
    duplicate: bool


@dataclass(frozen=True, slots=True)
class PaperListView:
    items: tuple[PaperView, ...]
    total: int


@dataclass(frozen=True, slots=True)
class DeletePaperView:
    paper_id: str
    deleted: bool = True


@dataclass(frozen=True, slots=True)
class StoredPaperFile:
    paper_id: str
    path: str
    file_name: str
    file_size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    chunk_id: str
    vector_id: str
    paper_id: str
    page: int
    ordinal: int
    text: str
    quote: str
