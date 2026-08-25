from collections.abc import AsyncIterator
from typing import Protocol

from airesearcher_agent.domain.chat import ChatPrompt, ProviderEvent


class ChatProviderError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        if not code or len(code) > 128:
            raise ValueError("provider error code must contain 1 to 128 characters")
        if not message or len(message) > 2048:
            raise ValueError("provider error message must contain 1 to 2048 characters")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ChatProvider(Protocol):
    def stream(self, prompt: ChatPrompt) -> AsyncIterator[ProviderEvent]: ...
