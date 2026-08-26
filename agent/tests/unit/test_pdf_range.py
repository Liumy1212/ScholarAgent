import asyncio
from pathlib import Path

import pytest

from airesearcher_agent.api.pdf import paper_file_response
from airesearcher_agent.application.errors import AgentError
from airesearcher_agent.domain.papers import StoredPaperFile


async def _body(response: object) -> bytes:
    from starlette.responses import StreamingResponse

    assert isinstance(response, StreamingResponse)
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode() if isinstance(chunk, str) else bytes(chunk))
    return b"".join(chunks)


def test_pdf_response_supports_single_byte_range_and_required_headers(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-0123456789")
    stored = StoredPaperFile(
        paper_id="paper-range",
        path=str(path),
        file_name="paper.pdf",
        file_size_bytes=15,
        sha256="a" * 64,
    )

    response = paper_file_response(
        stored,
        request_id="req-range",
        range_header="bytes=5-9",
    )

    assert response.status_code == 206
    assert response.headers["Content-Range"] == "bytes 5-9/15"
    assert response.headers["Content-Length"] == "5"
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Type"] == "application/pdf"
    assert response.headers["X-Request-Id"] == "req-range"
    assert response.headers["ETag"] == (
        '"sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"'
    )
    assert asyncio.run(_body(response)) == b"01234"


def test_pdf_response_rejects_multiple_ranges(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-test")
    stored = StoredPaperFile(
        paper_id="paper-range",
        path=str(path),
        file_name="paper.pdf",
        file_size_bytes=9,
        sha256="b" * 64,
    )

    with pytest.raises(AgentError) as captured:
        paper_file_response(
            stored,
            request_id="req-range",
            range_header="bytes=0-1,3-4",
        )

    assert captured.value.status_code == 416
    assert captured.value.code == "RANGE_NOT_SATISFIABLE"
