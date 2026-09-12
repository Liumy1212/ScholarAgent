import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator

from anyio import CancelScope
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from airesearcher_agent.domain.sse import SseEvent


class ChatStreamingResponse(StreamingResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A failed ASGI send can leave the body generator suspended at yield.
            with CancelScope(shield=True):
                if isinstance(self.body_iterator, AsyncGenerator):
                    await self.body_iterator.aclose()


async def encode_sse(
    events: AsyncIterator[SseEvent], *, heartbeat_seconds: float = 2.0
) -> AsyncGenerator[bytes]:
    pending: asyncio.Future[SseEvent] | None = None
    try:
        while True:
            pending = asyncio.ensure_future(anext(events))
            while not (await asyncio.wait({pending}, timeout=heartbeat_seconds))[0]:
                yield b": heartbeat\n\n"
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            data = json.dumps(event.to_wire(), ensure_ascii=False, separators=(",", ":"))
            block = f"event: {event.type}\nid: {event.event_id}\ndata: {data}\n\n"
            yield block.encode("utf-8")
    finally:
        with CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            if isinstance(events, AsyncGenerator):
                await events.aclose()
