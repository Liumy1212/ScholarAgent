from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _valid_request_id(value: str | None) -> bool:
    return value is not None and 1 <= len(value) <= 128


def _effective_request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-Id")
    if supplied is not None and _valid_request_id(supplied):
        return supplied
    return f"req-{uuid4().hex}"


def _field_name(error: dict[str, Any]) -> str:
    location = error.get("loc", ())
    parts = [str(part) for part in location if part not in {"body", "path", "header"}]
    if parts == ["x-request-id"]:
        return "X-Request-Id"
    return ".".join(parts) or "request"


async def request_validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    request_id = _effective_request_id(request)
    details = [
        {
            "field": _field_name(item),
            "reason": str(item.get("msg", "is invalid"))[:1024],
        }
        for item in error.errors()
    ]
    content = {
        "schemaVersion": "1.0",
        "code": "INVALID_REQUEST",
        "message": "Request validation failed.",
        "requestId": request_id,
        "retryable": False,
        "details": details,
    }
    return JSONResponse(
        status_code=400,
        content=content,
        headers={"X-Request-Id": request_id},
    )
