from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from airesearcher_agent.domain.papers import (
    IngestionJobStatus,
    IngestionStage,
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
    status: PaperStatus
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
