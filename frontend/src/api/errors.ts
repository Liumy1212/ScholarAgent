import type { StreamOpenError } from './types';

export class SseProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SseProtocolError';
  }
}

export class StreamOpenErrorResponse extends Error {
  readonly response: StreamOpenError;

  constructor(response: StreamOpenError) {
    super(response.message);
    this.name = 'StreamOpenErrorResponse';
    this.response = response;
  }
}

export class ChatTransportError extends Error {
  readonly code: string;
  readonly requestId: string;
  readonly retryable: boolean;

  constructor(
    code: string,
    message: string,
    requestId: string,
    retryable = false,
  ) {
    super(message);
    this.name = 'ChatTransportError';
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
  }
}
