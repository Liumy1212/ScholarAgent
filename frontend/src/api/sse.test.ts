import { describe, expect, it } from 'vitest';
import { SseProtocolError } from './errors';
import { consumeChatSseStream } from './sse';
import type { ChatSseEvent } from './types';

function eventEnvelope(
  type: ChatSseEvent['type'],
  eventId: string,
  sequence: number,
  payload: object,
) {
  return {
    schemaVersion: '1.0',
    type,
    eventId,
    requestId: 'req-test-001',
    runId: 'run-test-001',
    conversationId: 'conv-test-001',
    assistantMessageId: 'msg-test-001',
    sequence,
    timestamp: `2026-01-01T00:00:0${sequence}Z`,
    payload,
  };
}

function chunkedStream(text: string, chunkSize: number): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;

  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(offset, offset + chunkSize));
      offset += chunkSize;
    },
  });
}

function wireEvent(event: object, wireType: string, wireId: string): string {
  return `event: ${wireType}\nid: ${wireId}\ndata: ${JSON.stringify(event)}\n\n`;
}

describe('consumeChatSseStream', () => {
  it('解析跨 UTF-8 分块、CRLF、心跳和多行 data', async () => {
    const started = eventEnvelope('run.started', 'evt-001', 0, {});
    const delta = eventEnvelope('message.delta', 'evt-002', 1, {
      delta: '跨块中文回答。',
    });
    const startedJson = JSON.stringify(started);
    const splitIndex = startedJson.indexOf('"type"');
    const streamText = [
      ': heartbeat\r\n\r\n',
      'event: run.started\r\n',
      'id: evt-001\r\n',
      `data: ${startedJson.slice(0, splitIndex)}\r\n`,
      `data: ${startedJson.slice(splitIndex)}\r\n\r\n`,
      wireEvent(delta, 'message.delta', 'evt-002').replace(/\n/g, '\r\n'),
    ].join('');
    const events: ChatSseEvent[] = [];

    await consumeChatSseStream(chunkedStream(streamText, 5), (event) => {
      events.push(event);
    });

    expect(events).toHaveLength(2);
    expect(events[0]?.type).toBe('run.started');
    expect(events[1]).toMatchObject({
      type: 'message.delta',
      payload: { delta: '跨块中文回答。' },
    });
  });

  it('拒绝 wire event 与 JSON type 不一致', async () => {
    const started = eventEnvelope('run.started', 'evt-001', 0, {});
    const stream = chunkedStream(
      wireEvent(started, 'message.delta', 'evt-001'),
      64,
    );

    await expect(
      consumeChatSseStream(stream, () => undefined),
    ).rejects.toThrow('SSE event 与 JSON type 不一致');
  });

  it('解析安全的工具状态和回答模式，并拒绝泄漏参数', async () => {
    const started = eventEnvelope('run.started', 'evt-001', 0, {});
    const toolStarted = eventEnvelope('tool.status', 'evt-002', 1, {
      toolCallId: 'call-001',
      toolName: 'knowledge_base_search',
      status: 'started',
      message: '正在检索证据。',
    });
    const completed = eventEnvelope('run.completed', 'evt-003', 2, {
      answerMode: 'KNOWLEDGE_BASE',
    });
    const events: ChatSseEvent[] = [];
    const text = [started, toolStarted, completed]
      .map((event) => wireEvent(event, event.type, event.eventId))
      .join('');

    await consumeChatSseStream(chunkedStream(text, 17), (event) => events.push(event));

    expect(events[1]).toMatchObject({
      type: 'tool.status',
      payload: { toolName: 'knowledge_base_search', status: 'started' },
    });
    expect(events[2]).toMatchObject({
      type: 'run.completed',
      payload: { answerMode: 'KNOWLEDGE_BASE' },
    });

    const leakingTool = eventEnvelope('tool.status', 'evt-leak', 1, {
      ...(toolStarted.payload as object),
      arguments: { query: 'private' },
    });
    await expect(
      consumeChatSseStream(
        chunkedStream(wireEvent(leakingTool, 'tool.status', 'evt-leak'), 64),
        () => undefined,
      ),
    ).rejects.toThrow('包含未声明字段 arguments');
  });

  it('拒绝没有空行结束符的事件块', async () => {
    const started = eventEnvelope('run.started', 'evt-001', 0, {});
    const incomplete = wireEvent(started, 'run.started', 'evt-001').trimEnd();

    await expect(
      consumeChatSseStream(chunkedStream(incomplete, 9), () => undefined),
    ).rejects.toBeInstanceOf(SseProtocolError);
  });
});
