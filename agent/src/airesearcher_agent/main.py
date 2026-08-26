from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from airesearcher_agent.api.errors import agent_error_handler, request_validation_error_handler
from airesearcher_agent.api.routes import create_agent_router
from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.application.ports import ChatProvider
from airesearcher_agent.application.runtime import RuntimeServices, build_runtime
from airesearcher_agent.application.stream_chat import StreamChatUseCase


def create_app(
    provider: ChatProvider | None = None,
    *,
    runtime: RuntimeServices | None = None,
) -> FastAPI:
    services = runtime or build_runtime()
    use_case = StreamChatUseCase(provider) if provider is not None else services.stream_chat

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
    application.add_exception_handler(AgentError, agent_error_handler)
    application.include_router(create_agent_router(use_case, services.paper_service))

    @application.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "UP"}

    application.state.runtime = services
    return application


app = create_app()
