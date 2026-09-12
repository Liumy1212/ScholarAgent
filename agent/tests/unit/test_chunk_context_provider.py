import json
from pathlib import Path

import httpx
import pytest
from tests.support import runtime_settings

from airesearcher_agent.ingestion.context import ChunkContextError, ChunkContextRequest
from airesearcher_agent.providers.chunk_context import DeepSeekChunkContextProvider


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self.close_calls = 0
        self._responses = iter(responses)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = next(self._responses)
        response.request = request
        return response

    def close(self) -> None:
        self.close_calls += 1


def _request() -> ChunkContextRequest:
    return ChunkContextRequest(
        paper_title="Contextual Retrieval",
        section_path=("2 Methods",),
        section_outline=("1 Introduction", "2 Methods"),
        previous_text="The method is introduced.",
        current_text="It improves retrieval.",
        next_text="The experiment follows.",
    )


def test_context_provider_sends_structural_context_and_returns_clean_text(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport(
        [
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "  本段说明该方法的检索改进。\n"}}]},
            ),
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "第二个片段的上下文。"}}]},
            ),
        ]
    )

    provider = DeepSeekChunkContextProvider(
        runtime_settings(tmp_path),
        transport=transport,
    )

    assert provider.generate(_request()) == "本段说明该方法的检索改进。"
    assert provider.generate(_request()) == "第二个片段的上下文。"
    assert len(transport.requests) == 2
    assert transport.close_calls == 0
    captured = json.loads(transport.requests[0].content)
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "2 Methods" in str(messages)
    assert "It improves retrieval." in str(messages)
    provider.close()
    assert transport.close_calls == 1


def test_context_provider_rejects_empty_or_oversized_responses(tmp_path: Path) -> None:
    responses = iter(["", "x" * 501])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": next(responses)}}]},
        )

    provider = DeepSeekChunkContextProvider(
        runtime_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ChunkContextError):
        provider.generate(_request())
    with pytest.raises(ChunkContextError):
        provider.generate(_request())
    provider.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, content=b"not-json"),
    ],
)
def test_context_provider_maps_http_and_protocol_failures(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    provider = DeepSeekChunkContextProvider(
        runtime_settings(tmp_path),
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(ChunkContextError):
        provider.generate(_request())
    provider.close()
