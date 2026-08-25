import json
from collections.abc import AsyncIterator

from airesearcher_agent.domain.sse import SseEvent


async def encode_sse(events: AsyncIterator[SseEvent]) -> AsyncIterator[bytes]:
    async for event in events:
        data = json.dumps(event.to_wire(), ensure_ascii=False, separators=(",", ":"))
        block = f"event: {event.type}\nid: {event.event_id}\ndata: {data}\n\n"
        yield block.encode("utf-8")
