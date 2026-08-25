import { parseChatSseEvent } from './contractParser';
import { SseProtocolError } from './errors';
import type { ChatSseEvent } from './types';

const MAX_PENDING_TEXT_LENGTH = 1_000_000;

interface WireEvent {
  event: string;
  id: string;
  data: string;
}

function fieldValue(line: string, colonIndex: number): string {
  const raw = colonIndex === -1 ? '' : line.slice(colonIndex + 1);
  return raw.startsWith(' ') ? raw.slice(1) : raw;
}

function parseWireEvent(block: string): WireEvent | null {
  const eventValues: string[] = [];
  const idValues: string[] = [];
  const dataValues: string[] = [];

  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) {
      continue;
    }

    const colonIndex = line.indexOf(':');
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
    const value = fieldValue(line, colonIndex);

    switch (field) {
      case 'event':
        eventValues.push(value);
        break;
      case 'id':
        idValues.push(value);
        break;
      case 'data':
        dataValues.push(value);
        break;
      default:
        throw new SseProtocolError(`SSE 事件包含未声明字段 ${field}`);
    }
  }

  if (
    eventValues.length === 0 &&
    idValues.length === 0 &&
    dataValues.length === 0
  ) {
    return null;
  }
  if (eventValues.length !== 1 || idValues.length !== 1) {
    throw new SseProtocolError('SSE 数据事件必须各包含一个 event 和 id 字段');
  }
  if (dataValues.length === 0) {
    throw new SseProtocolError('SSE 数据事件至少需要一个 data 字段');
  }

  return {
    event: eventValues[0] ?? '',
    id: idValues[0] ?? '',
    data: dataValues.join('\n'),
  };
}

class SseBlockDecoder {
  private buffer = '';
  private pendingCarriageReturn = false;

  push(text: string, final = false): WireEvent[] {
    let normalizedInput = this.pendingCarriageReturn ? `\r${text}` : text;
    this.pendingCarriageReturn = false;

    if (!final && normalizedInput.endsWith('\r')) {
      normalizedInput = normalizedInput.slice(0, -1);
      this.pendingCarriageReturn = true;
    }

    this.buffer += normalizedInput.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const events: WireEvent[] = [];
    let separatorIndex = this.buffer.indexOf('\n\n');
    while (separatorIndex !== -1) {
      const block = this.buffer.slice(0, separatorIndex);
      this.buffer = this.buffer.slice(separatorIndex + 2);
      const event = parseWireEvent(block);
      if (event) {
        events.push(event);
      }
      separatorIndex = this.buffer.indexOf('\n\n');
    }

    if (this.buffer.length > MAX_PENDING_TEXT_LENGTH) {
      throw new SseProtocolError('SSE 事件超过客户端允许的缓冲区大小');
    }

    if (final && (this.pendingCarriageReturn || this.buffer.trim() !== '')) {
      throw new SseProtocolError('SSE 流以未结束的事件块结束');
    }

    return events;
  }
}

function decodeWireEvent(wireEvent: WireEvent): ChatSseEvent {
  let data: unknown;
  try {
    data = JSON.parse(wireEvent.data) as unknown;
  } catch {
    throw new SseProtocolError('SSE data 不是有效 JSON');
  }

  const event = parseChatSseEvent(data);
  if (wireEvent.event !== event.type) {
    throw new SseProtocolError('SSE event 与 JSON type 不一致');
  }
  if (wireEvent.id !== event.eventId) {
    throw new SseProtocolError('SSE id 与 JSON eventId 不一致');
  }
  return event;
}

export async function consumeChatSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: ChatSseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const textDecoder = new TextDecoder('utf-8', { fatal: true });
  const blockDecoder = new SseBlockDecoder();
  const abortReader = () => {
    void reader.cancel(signal?.reason).catch(() => undefined);
  };

  signal?.throwIfAborted();
  signal?.addEventListener('abort', abortReader, { once: true });

  try {
    while (true) {
      const { value, done } = await reader.read();
      signal?.throwIfAborted();
      if (done) {
        break;
      }

      const decoded = textDecoder.decode(value, { stream: true });
      for (const wireEvent of blockDecoder.push(decoded)) {
        onEvent(decodeWireEvent(wireEvent));
      }
    }

    const remainingText = textDecoder.decode();
    for (const wireEvent of blockDecoder.push(remainingText, true)) {
      onEvent(decodeWireEvent(wireEvent));
    }
  } catch (error) {
    if (error instanceof TypeError) {
      throw new SseProtocolError('SSE 响应不是有效的 UTF-8 数据');
    }
    throw error;
  } finally {
    signal?.removeEventListener('abort', abortReader);
    reader.releaseLock();
  }
}
