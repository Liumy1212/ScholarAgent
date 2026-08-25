import { parseStreamOpenError } from './contractParser';
import {
  ChatTransportError,
  SseProtocolError,
  StreamOpenErrorResponse,
} from './errors';
import { consumeChatSseStream } from './sse';
import type { ChatSseEvent, ChatStreamRequest } from './types';

interface StreamChatOptions {
  conversationId: string;
  requestId: string;
  content: string;
  paperIds: string[];
  signal: AbortSignal;
  onOpen: (requestId: string) => void;
  onEvent: (event: ChatSseEvent) => void;
}

function validateRequestId(
  actual: string | null,
  expected: string,
  message: string,
): string {
  if (!actual || actual !== expected) {
    throw new ChatTransportError(
      'INVALID_REQUEST_ID',
      message,
      expected,
      false,
    );
  }
  return actual;
}

export async function streamChat(options: StreamChatOptions): Promise<void> {
  const requestBody: ChatStreamRequest = {
    content: options.content,
    paperIds: options.paperIds,
  };
  const path = `/api/v1/conversations/${encodeURIComponent(options.conversationId)}/messages/stream`;
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      'X-Request-Id': options.requestId,
    },
    body: JSON.stringify(requestBody),
    signal: options.signal,
  });
  const responseRequestId = response.headers.get('X-Request-Id');

  if (!response.ok) {
    const contentType = response.headers.get('Content-Type') ?? '';
    if (!contentType.toLowerCase().startsWith('application/json')) {
      throw new ChatTransportError(
        'INVALID_OPEN_ERROR',
        '服务器返回了不符合契约的建流错误',
        options.requestId,
      );
    }

    let value: unknown;
    try {
      value = (await response.json()) as unknown;
    } catch {
      throw new ChatTransportError(
        'INVALID_OPEN_ERROR',
        '服务器返回的建流错误不是有效 JSON',
        options.requestId,
      );
    }

    let openError;
    try {
      openError = parseStreamOpenError(value);
    } catch (error) {
      if (error instanceof SseProtocolError) {
        throw new ChatTransportError(
          'INVALID_OPEN_ERROR',
          `服务器返回的建流错误不符合契约：${error.message}`,
          options.requestId,
        );
      }
      throw error;
    }
    validateRequestId(
      responseRequestId,
      openError.requestId,
      '建流错误响应头与错误体的 requestId 不一致',
    );
    validateRequestId(
      openError.requestId,
      options.requestId,
      '服务器未保留调用方的 requestId',
    );
    throw new StreamOpenErrorResponse(openError);
  }

  if (response.status !== 200) {
    throw new ChatTransportError(
      'INVALID_STREAM_STATUS',
      `服务器使用了未定义的成功状态码 ${response.status}`,
      options.requestId,
    );
  }
  const contentType = response.headers.get('Content-Type') ?? '';
  if (!contentType.toLowerCase().startsWith('text/event-stream')) {
    throw new ChatTransportError(
      'INVALID_STREAM_CONTENT_TYPE',
      '服务器响应不是 text/event-stream',
      options.requestId,
    );
  }
  validateRequestId(
    responseRequestId,
    options.requestId,
    '服务器未返回调用方的 requestId',
  );
  if (!response.body) {
    throw new ChatTransportError(
      'EMPTY_STREAM_BODY',
      '服务器未返回 SSE 响应体',
      options.requestId,
    );
  }

  options.onOpen(options.requestId);
  await consumeChatSseStream(response.body, options.onEvent, options.signal);
}
