import { SseProtocolError } from '../api/errors';
import type { ChatSseEvent, CitationCreatedEvent } from '../api/types';

export type ChatStatus =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'completed'
  | 'failed'
  | 'interrupted';

export interface ChatFailure {
  code: string;
  message: string;
  retryable: boolean;
}

export type Citation = CitationCreatedEvent['payload'];

interface StreamProgress {
  started: boolean;
  nextSequence: number;
  runId: string | null;
  assistantMessageId: string | null;
  eventIds: readonly string[];
}

export interface ChatState {
  status: ChatStatus;
  requestId: string | null;
  conversationId: string | null;
  answer: string;
  citations: readonly Citation[];
  failure: ChatFailure | null;
  stream: StreamProgress;
}

const EMPTY_PROGRESS: StreamProgress = {
  started: false,
  nextSequence: 0,
  runId: null,
  assistantMessageId: null,
  eventIds: [],
};

export const initialChatState: ChatState = {
  status: 'idle',
  requestId: null,
  conversationId: null,
  answer: '',
  citations: [],
  failure: null,
  stream: EMPTY_PROGRESS,
};

function isActive(status: ChatStatus): boolean {
  return status === 'connecting' || status === 'streaming';
}

function requireCondition(condition: boolean, message: string): void {
  if (!condition) {
    throw new SseProtocolError(message);
  }
}

export function startChatRequest(
  requestId: string,
  conversationId: string,
): ChatState {
  return {
    status: 'connecting',
    requestId,
    conversationId,
    answer: '',
    citations: [],
    failure: null,
    stream: EMPTY_PROGRESS,
  };
}

export function confirmStreamOpened(
  state: ChatState,
  responseRequestId: string,
): ChatState {
  requireCondition(state.status === 'connecting', '只有连接中状态可以建立流');
  requireCondition(
    state.requestId === responseRequestId,
    '响应头 requestId 与当前请求不一致',
  );
  return state;
}

export function applyChatEvent(
  state: ChatState,
  event: ChatSseEvent,
): ChatState {
  requireCondition(isActive(state.status), '终止状态后不能继续接收数据事件');
  requireCondition(event.requestId === state.requestId, '事件 requestId 在流内不一致');
  requireCondition(
    event.conversationId === state.conversationId,
    '事件 conversationId 与请求路径不一致',
  );
  requireCondition(
    event.sequence === state.stream.nextSequence,
    `事件序号不连续：期望 ${state.stream.nextSequence}，实际 ${event.sequence}`,
  );
  requireCondition(
    !state.stream.eventIds.includes(event.eventId),
    '事件 eventId 在流内重复',
  );

  if (!state.stream.started) {
    requireCondition(
      event.type === 'run.started' && event.sequence === 0,
      '第一个数据事件必须是 sequence 0 的 run.started',
    );
  } else {
    requireCondition(event.type !== 'run.started', 'run.started 只能出现一次');
    requireCondition(event.runId === state.stream.runId, '事件 runId 在流内不一致');
    requireCondition(
      event.assistantMessageId === state.stream.assistantMessageId,
      '事件 assistantMessageId 在流内不一致',
    );
  }

  const stream: StreamProgress = {
    started: true,
    nextSequence: event.sequence + 1,
    runId: state.stream.runId ?? event.runId,
    assistantMessageId:
      state.stream.assistantMessageId ?? event.assistantMessageId,
    eventIds: [...state.stream.eventIds, event.eventId],
  };

  switch (event.type) {
    case 'run.started':
      return { ...state, status: 'streaming', stream };
    case 'message.delta':
      return {
        ...state,
        status: 'streaming',
        answer: state.answer + event.payload.delta,
        stream,
      };
    case 'citation.created':
      return {
        ...state,
        status: 'streaming',
        citations: [...state.citations, event.payload],
        stream,
      };
    case 'run.completed':
      return { ...state, status: 'completed', stream };
    case 'run.failed':
      return {
        ...state,
        status: 'failed',
        failure: event.payload,
        stream,
      };
  }
}

export function markStreamEnded(state: ChatState): ChatState {
  if (!isActive(state.status)) {
    return state;
  }
  return {
    ...state,
    status: 'interrupted',
    failure: {
      code: 'STREAM_INTERRUPTED',
      message: '连接在收到完成或失败事件前结束。请重新发起问题。',
      retryable: true,
    },
  };
}

export function markStreamInterrupted(
  state: ChatState,
  message: string,
  code = 'STREAM_INTERRUPTED',
): ChatState {
  if (!isActive(state.status)) {
    return state;
  }
  return {
    ...state,
    status: 'interrupted',
    failure: { code, message, retryable: true },
  };
}

export function markStreamProtocolViolation(
  state: ChatState,
  message: string,
): ChatState {
  return {
    ...state,
    status: 'interrupted',
    failure: {
      code: 'INVALID_SSE_STREAM',
      message,
      retryable: true,
    },
  };
}

export function markOpenFailed(
  state: ChatState,
  failure: ChatFailure,
  requestId = state.requestId,
): ChatState {
  requireCondition(isActive(state.status), '只有活动请求可以标记为失败');
  return {
    ...state,
    status: 'failed',
    requestId,
    failure,
  };
}
