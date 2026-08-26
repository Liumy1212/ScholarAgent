from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from airesearcher_agent.api.models import (
    ChatStreamRequest,
    DeletePaperResponse,
    IngestionJobResponse,
    PaperListResponse,
    PaperResponse,
    PaperUploadResponse,
)
from airesearcher_agent.api.pdf import paper_file_response
from airesearcher_agent.api.sse import encode_sse
from airesearcher_agent.application.errors import AgentError, ErrorDetail
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.application.stream_chat import StreamChatCommand, StreamChatUseCase

RequestIdHeader = Annotated[
    str,
    Header(alias="X-Request-Id", min_length=1, max_length=128),
]
PaperIdPath = Annotated[str, Path(alias="paperId", min_length=1, max_length=128)]
JobIdPath = Annotated[str, Path(alias="jobId", min_length=1, max_length=128)]


def create_agent_router(
    stream_use_case: StreamChatUseCase,
    paper_service: PaperService,
) -> APIRouter:
    router = APIRouter(prefix="/agent-api/v1")

    @router.post("/papers", response_model=PaperUploadResponse)
    async def upload_paper(
        request: Request,
        response: Response,
        request_id: RequestIdHeader,
    ) -> PaperUploadResponse:
        try:
            form = await request.form()
        except Exception as error:
            raise AgentError(
                status_code=400,
                code="INVALID_MULTIPART",
                message="无法解析 PDF 上传请求。",
                details=(ErrorDetail(field="file", reason="invalid multipart body"),),
            ) from error
        files = form.getlist("file")
        if set(form.keys()) != {"file"} or len(files) != 1 or not isinstance(files[0], UploadFile):
            raise AgentError(
                status_code=400,
                code="INVALID_REQUEST",
                message="请求必须且只能包含一个名为 file 的 PDF。",
                details=(ErrorDetail(field="file", reason="exactly one PDF file is required"),),
            )
        upload = files[0]
        try:
            result = await paper_service.upload(upload)
        finally:
            await upload.close()
        response.headers["X-Request-Id"] = request_id
        return PaperUploadResponse.model_validate(result)

    @router.get("/papers", response_model=PaperListResponse)
    def list_papers(response: Response, request_id: RequestIdHeader) -> PaperListResponse:
        result = paper_service.list_papers()
        response.headers["X-Request-Id"] = request_id
        return PaperListResponse.model_validate(result)

    @router.get("/papers/{paperId}", response_model=PaperResponse)
    def get_paper(
        paper_id: PaperIdPath,
        response: Response,
        request_id: RequestIdHeader,
    ) -> PaperResponse:
        result = paper_service.get_paper(paper_id)
        response.headers["X-Request-Id"] = request_id
        return PaperResponse.model_validate(result)

    @router.delete("/papers/{paperId}", response_model=DeletePaperResponse)
    def delete_paper(
        paper_id: PaperIdPath,
        response: Response,
        request_id: RequestIdHeader,
    ) -> DeletePaperResponse:
        result = paper_service.delete_paper(paper_id)
        response.headers["X-Request-Id"] = request_id
        return DeletePaperResponse.model_validate(result)

    @router.get(
        "/papers/{paperId}/file",
        response_class=StreamingResponse,
        responses={
            200: {"content": {"application/pdf": {}}},
            206: {"content": {"application/pdf": {}}},
        },
    )
    def get_paper_file(
        paper_id: PaperIdPath,
        request_id: RequestIdHeader,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> StreamingResponse:
        paper = paper_service.get_file(paper_id)
        return paper_file_response(
            paper,
            request_id=request_id,
            range_header=range_header,
        )

    @router.get("/ingestion-jobs/{jobId}", response_model=IngestionJobResponse)
    def get_ingestion_job(
        job_id: JobIdPath,
        response: Response,
        request_id: RequestIdHeader,
    ) -> IngestionJobResponse:
        result = paper_service.get_job(job_id)
        response.headers["X-Request-Id"] = request_id
        return IngestionJobResponse.model_validate(result)

    @router.post("/ingestion-jobs/{jobId}/retry", response_model=IngestionJobResponse)
    def retry_ingestion_job(
        job_id: JobIdPath,
        response: Response,
        request_id: RequestIdHeader,
    ) -> IngestionJobResponse:
        result = paper_service.retry_job(job_id)
        response.headers["X-Request-Id"] = request_id
        return IngestionJobResponse.model_validate(result)

    @router.post(
        "/conversations/{conversationId}/messages/stream",
        response_class=StreamingResponse,
        responses={
            200: {"content": {"text/event-stream": {}}},
            400: {"description": "Request validation failed before opening the stream."},
            500: {"description": "Agent failure before opening the stream."},
            503: {"description": "Agent unavailable before opening the stream."},
        },
    )
    async def stream_conversation_message(
        body: ChatStreamRequest,
        conversation_id: Annotated[
            str,
            Path(alias="conversationId", min_length=1, max_length=128),
        ],
        request_id: RequestIdHeader,
    ) -> StreamingResponse:
        command = StreamChatCommand(
            request_id=request_id,
            conversation_id=conversation_id,
            content=body.content,
            paper_ids=tuple(body.paper_ids),
        )
        return StreamingResponse(
            encode_sse(stream_use_case.execute(command)),
            media_type="text/event-stream",
            headers={
                "X-Request-Id": request_id,
                "Cache-Control": "no-cache",
            },
        )

    return router
