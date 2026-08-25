import { describe, expect, it } from 'vitest';
import type {
  ChatSseEvent,
  CitationCreatedEvent,
  MessageDeltaEvent,
  RunCompletedEvent,
  RunFailedEvent,
  RunStartedEvent,
} from '../api/types';
import {
  applyChatEvent,
  markStreamEnded,
  markStreamProtocolViolation,
  startChatRequest,
  type ChatState,
} from './chatState';

const base = {
  schemaVersion: '1.0' as const,
  requestId: 'req-state-001',
  runId: 'run-state-001',
  conversationId: 'conv-state-001',
  assistantMessageId: 'msg-state-001',
  timestamp: '2026-01-01T00:00:00Z',
};

const started: RunStartedEvent = {
  ...base,
  type: 'run.started',
  eventId: 'evt-state-001',
  sequence: 0,
  payload: {},
};

function reduceEvents(events: ChatSseEvent[]): ChatState {
  return events.reduce(
    (state, event) => applyChatEvent(state, event),
    startChatRequest(base.requestId, base.conversationId),
  );
}

describe('chat stream state transitions', () => {
  it('累积文本与引用并进入完成状态', () => {
    const delta: MessageDeltaEvent = {
      ...base,
      type: 'message.delta',
      eventId: 'evt-state-002',
      sequence: 1,
      payload: { delta: '合成回答。' },
    };
    const citation: CitationCreatedEvent = {
      ...base,
      type: 'citation.created',
      eventId: 'evt-state-003',
      sequence: 2,
      payload: {
        citationId: 'citation-state-001',
        paperId: 'paper-state-001',
        paperTitle: 'Synthetic Paper',
        pageNumber: 4,
        quote: 'Synthetic evidence.',
      },
    };
    const completed: RunCompletedEvent = {
      ...base,
      type: 'run.completed',
      eventId: 'evt-state-004',
      sequence: 3,
      payload: {},
    };

    const state = reduceEvents([started, delta, citation, completed]);

    expect(state.status).toBe('completed');
    expect(state.answer).toBe('合成回答。');
    expect(state.citations).toEqual([citation.payload]);
    expect(markStreamEnded(state)).toBe(state);
  });

  it('把 run.failed 映射为失败状态', () => {
    const failed: RunFailedEvent = {
      ...base,
      type: 'run.failed',
      eventId: 'evt-state-002',
      sequence: 1,
      payload: {
        code: 'PROVIDER_FAILURE',
        message: 'Synthetic provider failure.',
        retryable: true,
      },
    };

    const state = reduceEvents([started, failed]);

    expect(state.status).toBe('failed');
    expect(state.failure).toEqual(failed.payload);
  });

  it('把没有终止事件的断流映射为中断状态', () => {
    const streaming = applyChatEvent(
      startChatRequest(base.requestId, base.conversationId),
      started,
    );

    const state = markStreamEnded(streaming);

    expect(state.status).toBe('interrupted');
    expect(state.failure?.code).toBe('STREAM_INTERRUPTED');
  });

  it('拒绝序号跳跃和终止事件后的数据', () => {
    const gap: RunCompletedEvent = {
      ...base,
      type: 'run.completed',
      eventId: 'evt-state-003',
      sequence: 2,
      payload: {},
    };
    const streaming = applyChatEvent(
      startChatRequest(base.requestId, base.conversationId),
      started,
    );

    expect(() => applyChatEvent(streaming, gap)).toThrow('事件序号不连续');

    const completed: RunCompletedEvent = {
      ...gap,
      eventId: 'evt-state-002',
      sequence: 1,
    };
    const terminal = applyChatEvent(streaming, completed);
    expect(() => applyChatEvent(terminal, completed)).toThrow(
      '终止状态后不能继续接收数据事件',
    );
    expect(markStreamProtocolViolation(terminal, '存在重复终止事件').status).toBe(
      'interrupted',
    );
  });
});
