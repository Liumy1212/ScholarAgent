from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    field: str
    reason: str


class AgentError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: tuple[ErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details


class IngestionError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
