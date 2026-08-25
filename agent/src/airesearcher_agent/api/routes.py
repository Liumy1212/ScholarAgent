from typing import Annotated

from fastapi import APIRouter, Header, Path
from fastapi.responses import StreamingResponse

from airesearcher_agent.api.models import ChatStreamRequest
from airesearcher_agent.api.sse import encode_sse
from airesearcher_agent.application.stream_chat import StreamChatCommand, StreamChatUseCase


def create_agent_router(use_case: StreamChatUseCase) -> APIRouter:
    router = APIRouter(prefix="/agent-api/v1")

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
        request_id: Annotated[
            str,
            Header(alias="X-Request-Id", min_length=1, max_length=128),
        ],
    ) -> StreamingResponse:
        command = StreamChatCommand(
            request_id=request_id,
            conversation_id=conversation_id,
            content=body.content,
            paper_ids=tuple(body.paper_ids),
        )
        return StreamingResponse(
            encode_sse(use_case.execute(command)),
            media_type="text/event-stream",
            headers={
                "X-Request-Id": request_id,
                "Cache-Control": "no-cache",
            },
        )

    return router
