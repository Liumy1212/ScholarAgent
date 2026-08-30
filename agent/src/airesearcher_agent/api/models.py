from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from airesearcher_agent.domain.library import (
    LibraryFileKnowledgeStatus,
    LibraryFileSourceStatus,
    LibraryScanItemOutcome,
    LibraryScanStatus,
)
from airesearcher_agent.domain.papers import (
    IngestionJobStatus,
    IngestionStage,
    PaperSourceStatus,
    PaperStatus,
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content: Annotated[str, StringConstraints(min_length=1, max_length=16000)]
    paper_ids: list[Identifier] = Field(alias="paperIds", max_length=100)

    @field_validator("paper_ids")
    @classmethod
    def paper_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("paperIds must contain unique items")
        return value


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class IngestionFailureResponse(WireModel):
    code: str
    message: str
    retryable: bool


class IngestionSummaryResponse(WireModel):
    job_id: str
    status: IngestionJobStatus
    stage: IngestionStage
    attempt: int
    max_attempts: int
    can_retry: bool
    failure: IngestionFailureResponse | None


class PaperResponse(WireModel):
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
    current_ingestion: IngestionSummaryResponse


class IngestionJobResponse(IngestionSummaryResponse):
    paper_id: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class PaperUploadResponse(WireModel):
    paper: PaperResponse
    ingestion_job: IngestionJobResponse
    duplicate: bool


class PaperListResponse(WireModel):
    items: tuple[PaperResponse, ...]
    total: int


class DeletePaperResponse(WireModel):
    paper_id: str
    deleted: bool


class LibraryFileResponse(WireModel):
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
    current_ingestion: IngestionSummaryResponse | None
    discovered_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class LibraryFilesPageResponse(WireModel):
    items: tuple[LibraryFileResponse, ...]
    total: int
    offset: int
    limit: int


class LibraryFileUploadResponse(WireModel):
    library_file: LibraryFileResponse
    duplicate: bool


class LibraryFileIngestionResponse(WireModel):
    library_file: LibraryFileResponse
    paper: PaperResponse
    ingestion_job: IngestionJobResponse
    duplicate: bool


class LibraryScanFailureResponse(WireModel):
    code: str
    message: str


class LibraryScanResponse(WireModel):
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
    failure: LibraryScanFailureResponse | None


class LibraryInfoResponse(WireModel):
    root_path: str
    supported_extensions: tuple[str, ...]
    scan_in_progress: bool
    latest_scan: LibraryScanResponse | None


class LibraryScanItemResponse(WireModel):
    relative_path: str
    outcome: LibraryScanItemOutcome
    library_file_id: str | None
    paper_id: str | None
    code: str | None
    message: str | None


class LibraryScanItemsPageResponse(WireModel):
    items: tuple[LibraryScanItemResponse, ...]
    total: int
    offset: int
    limit: int
