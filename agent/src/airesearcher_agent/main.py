from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from airesearcher_agent.api.errors import request_validation_error_handler
from airesearcher_agent.api.routes import create_agent_router
from airesearcher_agent.application.ports import ChatProvider
from airesearcher_agent.application.stream_chat import StreamChatUseCase
from airesearcher_agent.providers.fake import FakeChatProvider


def create_app(provider: ChatProvider | None = None) -> FastAPI:
    selected_provider: ChatProvider = provider if provider is not None else FakeChatProvider()
    use_case = StreamChatUseCase(selected_provider)

    application = FastAPI(
        title="AIResearcher Agent API",
        version="1.0.0",
        docs_url=None,
        openapi_url=None,
        redoc_url=None,
    )
    application.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )
    application.include_router(create_agent_router(use_case))
    return application


app = create_app()
