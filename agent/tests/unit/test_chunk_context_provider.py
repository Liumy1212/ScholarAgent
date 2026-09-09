import json
from pathlib import Path

import httpx
import pytest
from tests.support import runtime_settings

from airesearcher_agent.ingestion.context import ChunkContextError, ChunkContextRequest
from airesearcher_agent.providers.chunk_context import DeepSeekChunkContextProvider


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
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  本段说明该方法的检索改进。\n"}}]},
        )

    provider = DeepSeekChunkContextProvider(
        runtime_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    assert provider.generate(_request()) == "本段说明该方法的检索改进。"
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "2 Methods" in str(messages)
    assert "It improves retrieval." in str(messages)


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
