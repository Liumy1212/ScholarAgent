import asyncio
import json
from collections.abc import AsyncIterator
from typing import cast

import httpx

from airesearcher_agent.providers.deepseek_client import (
    ChatMessage,
    DeepSeekHttpClient,
    ToolDefinition,
)


def test_final_stream_explicitly_disables_additional_tool_calls() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(cast(dict[str, object], json.loads(request.content)))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                'data: {"choices":[{"delta":{"content":"Final answer."}}]}\n\ndata: [DONE]\n\n'
            ),
        )

    client = DeepSeekHttpClient(
        base_url="https://api.example.test",
        api_key="synthetic-test-key",
        model="deepseek-v4-flash",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    messages: list[ChatMessage] = [{"role": "user", "content": "Answer now."}]
    tools: list[ToolDefinition] = [
        {
            "type": "function",
            "function": {
                "name": "document_lookup",
                "description": "Synthetic read-only tool.",
                "parameters": {"type": "object"},
            },
        }
    ]

    async def collect() -> list[str]:
        stream: AsyncIterator[str] = client.stream_final(messages, tools)
        return [fragment async for fragment in stream]

    fragments = asyncio.run(collect())

    assert fragments == ["Final answer."]
    assert len(requests) == 1
    assert requests[0]["tools"] == tools
    assert requests[0]["tool_choice"] == "none"
    assert requests[0]["stream"] is True
