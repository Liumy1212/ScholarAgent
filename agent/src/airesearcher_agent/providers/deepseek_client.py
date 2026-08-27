import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

type ChatMessage = dict[str, object]
type ToolDefinition = dict[str, object]


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: str


class NativeToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    function: FunctionCall

    def to_wire(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
        }


class AssistantTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = "assistant"
    content: str | None = None
    tool_calls: list[NativeToolCall] = Field(default_factory=list)

    def to_wire(self) -> ChatMessage:
        message: ChatMessage = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.to_wire() for call in self.tool_calls]
        return message


class CompletionChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: AssistantTurn


class CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choices: list[CompletionChoice]


class DeepSeekError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class DeepSeekGateway(Protocol):
    async def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantTurn: ...

    def stream_final(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[str]: ...


class DeepSeekHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport

    async def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AssistantTurn:
        payload = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        try:
            async with self._client() as client:
                response = await client.post(self._url, json=payload)
                self._raise_for_status(response)
                parsed = CompletionResponse.model_validate(response.json())
            if not parsed.choices:
                raise DeepSeekError(
                    code="PROVIDER_PROTOCOL_ERROR",
                    message="模型没有返回候选回答。",
                    retryable=True,
                )
            return parsed.choices[0].message
        except DeepSeekError:
            raise
        except httpx.TransportError as error:
            raise DeepSeekError(
                code="PROVIDER_UNAVAILABLE",
                message="DeepSeek 暂时不可用。",
                retryable=True,
            ) from error
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            raise DeepSeekError(
                code="PROVIDER_PROTOCOL_ERROR",
                message="DeepSeek 返回了无法解析的响应。",
                retryable=True,
            ) from error

    async def stream_final(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "none",
            "stream": True,
        }
        try:
            async with (
                self._client() as client,
                client.stream(
                    "POST",
                    self._url,
                    json=payload,
                ) as response,
            ):
                self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield content
                    except (json.JSONDecodeError, AttributeError, IndexError, TypeError) as error:
                        raise DeepSeekError(
                            code="PROVIDER_PROTOCOL_ERROR",
                            message="DeepSeek 流式响应无法解析。",
                            retryable=True,
                        ) from error
        except DeepSeekError:
            raise
        except httpx.TransportError as error:
            raise DeepSeekError(
                code="PROVIDER_UNAVAILABLE",
                message="DeepSeek 流式连接中断。",
                retryable=True,
            ) from error

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self._timeout),
            transport=self._transport,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        retryable = response.status_code == 429 or response.status_code >= 500
        code = "PROVIDER_UNAVAILABLE" if retryable else "PROVIDER_REJECTED"
        message = "DeepSeek 暂时不可用。" if retryable else "DeepSeek 拒绝了模型请求。"
        raise DeepSeekError(code=code, message=message, retryable=retryable)
