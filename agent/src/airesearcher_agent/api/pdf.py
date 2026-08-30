from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from fastapi.responses import StreamingResponse

from airesearcher_agent.application.errors import AgentError


class StoredPdfFile(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def file_name(self) -> str: ...

    @property
    def file_size_bytes(self) -> int: ...

    @property
    def sha256(self) -> str: ...


FILE_CHUNK_BYTES = 1024 * 1024


def _parse_range(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise _range_error()
    spec = value.removeprefix("bytes=")
    if "-" not in spec:
        raise _range_error()
    start_text, end_text = spec.split("-", maxsplit=1)
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
            if start < 0 or end < start or start >= size:
                raise _range_error()
            return start, min(end, size - 1)
        suffix = int(end_text)
        if suffix <= 0:
            raise _range_error()
        return max(size - suffix, 0), size - 1
    except ValueError as error:
        raise _range_error() from error


def _range_error() -> AgentError:
    return AgentError(
        status_code=416,
        code="RANGE_NOT_SATISFIABLE",
        message="请求的 PDF 字节范围无效。",
        retryable=False,
    )


def _read_bytes(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining > 0:
            block = source.read(min(FILE_CHUNK_BYTES, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def pdf_file_response(
    pdf_file: StoredPdfFile,
    *,
    request_id: str,
    range_header: str | None,
) -> StreamingResponse:
    path = Path(pdf_file.path)
    size = pdf_file.file_size_bytes
    start, end = (0, size - 1) if range_header is None else _parse_range(range_header, size)
    content_length = end - start + 1
    status_code = 200 if range_header is None else 206
    headers = {
        "X-Request-Id": request_id,
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "ETag": f'"sha256-{pdf_file.sha256}"',
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(pdf_file.file_name)}",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _read_bytes(path, start, content_length),
        status_code=status_code,
        media_type="application/pdf",
        headers=headers,
    )


paper_file_response = pdf_file_response
