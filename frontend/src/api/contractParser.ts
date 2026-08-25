import { SseProtocolError } from './errors';
import type {
  ChatSseEvent,
  CitationCreatedEvent,
  MessageDeltaEvent,
  RunCompletedEvent,
  RunFailedEvent,
  RunStartedEvent,
  StreamOpenError,
  StreamOpenErrorDetail,
} from './types';

type JsonRecord = Record<string, unknown>;

const EVENT_KEYS = [
  'schemaVersion',
  'type',
  'eventId',
  'requestId',
  'runId',
  'conversationId',
  'assistantMessageId',
  'sequence',
  'timestamp',
  'payload',
] as const;

const RFC_3339_DATE_TIME =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function assertRecord(value: unknown, label: string): asserts value is JsonRecord {
  if (!isRecord(value)) {
    throw new SseProtocolError(`${label} 必须是 JSON 对象`);
  }
}

function assertExactKeys(
  value: JsonRecord,
  required: readonly string[],
  optional: readonly string[] = [],
): void {
  const permitted = new Set([...required, ...optional]);
  const missing = required.find((key) => !(key in value));
  const unexpected = Object.keys(value).find((key) => !permitted.has(key));

  if (missing) {
    throw new SseProtocolError(`缺少字段 ${missing}`);
  }
  if (unexpected) {
    throw new SseProtocolError(`包含未声明字段 ${unexpected}`);
  }
}

function readString(
  value: JsonRecord,
  key: string,
  minLength = 1,
  maxLength?: number,
): string {
  const candidate = value[key];
  if (
    typeof candidate !== 'string' ||
    candidate.length < minLength ||
    (maxLength !== undefined && candidate.length > maxLength)
  ) {
    throw new SseProtocolError(`字段 ${key} 不是有效字符串`);
  }
  return candidate;
}

function readBoolean(value: JsonRecord, key: string): boolean {
  const candidate = value[key];
  if (typeof candidate !== 'boolean') {
    throw new SseProtocolError(`字段 ${key} 不是布尔值`);
  }
  return candidate;
}

function readInteger(value: JsonRecord, key: string, minimum: number): number {
  const candidate = value[key];
  if (!Number.isInteger(candidate) || (candidate as number) < minimum) {
    throw new SseProtocolError(`字段 ${key} 不是有效整数`);
  }
  return candidate as number;
}

function parseBase(value: JsonRecord) {
  assertExactKeys(value, EVENT_KEYS);
  if (value.schemaVersion !== '1.0') {
    throw new SseProtocolError('schemaVersion 必须为 1.0');
  }

  const timestamp = readString(value, 'timestamp');
  if (!RFC_3339_DATE_TIME.test(timestamp) || Number.isNaN(Date.parse(timestamp))) {
    throw new SseProtocolError('timestamp 必须是有效的 date-time');
  }

  return {
    schemaVersion: '1.0' as const,
    eventId: readString(value, 'eventId', 1, 128),
    requestId: readString(value, 'requestId', 1, 128),
    runId: readString(value, 'runId', 1, 128),
    conversationId: readString(value, 'conversationId', 1, 128),
    assistantMessageId: readString(value, 'assistantMessageId', 1, 128),
    sequence: readInteger(value, 'sequence', 0),
    timestamp,
  };
}

function parseEmptyPayload(payload: unknown): Record<string, never> {
  assertRecord(payload, 'payload');
  assertExactKeys(payload, []);
  return {};
}

export function parseChatSseEvent(value: unknown): ChatSseEvent {
  assertRecord(value, 'SSE data');
  const base = parseBase(value);

  switch (value.type) {
    case 'run.started':
      return {
        ...base,
        type: 'run.started',
        payload: parseEmptyPayload(value.payload),
      } satisfies RunStartedEvent;
    case 'message.delta': {
      const payload = value.payload;
      assertRecord(payload, 'message.delta payload');
      assertExactKeys(payload, ['delta']);
      return {
        ...base,
        type: 'message.delta',
        payload: { delta: readString(payload, 'delta') },
      } satisfies MessageDeltaEvent;
    }
    case 'citation.created': {
      const payload = value.payload;
      assertRecord(payload, 'citation.created payload');
      assertExactKeys(payload, [
        'citationId',
        'paperId',
        'paperTitle',
        'pageNumber',
        'quote',
      ]);
      return {
        ...base,
        type: 'citation.created',
        payload: {
          citationId: readString(payload, 'citationId', 1, 128),
          paperId: readString(payload, 'paperId', 1, 128),
          paperTitle: readString(payload, 'paperTitle'),
          pageNumber: readInteger(payload, 'pageNumber', 1),
          quote: readString(payload, 'quote'),
        },
      } satisfies CitationCreatedEvent;
    }
    case 'run.completed':
      return {
        ...base,
        type: 'run.completed',
        payload: parseEmptyPayload(value.payload),
      } satisfies RunCompletedEvent;
    case 'run.failed': {
      const payload = value.payload;
      assertRecord(payload, 'run.failed payload');
      assertExactKeys(payload, ['code', 'message', 'retryable']);
      return {
        ...base,
        type: 'run.failed',
        payload: {
          code: readString(payload, 'code', 1, 128),
          message: readString(payload, 'message', 1, 2048),
          retryable: readBoolean(payload, 'retryable'),
        },
      } satisfies RunFailedEvent;
    }
    default:
      throw new SseProtocolError('type 不是受支持的 SSE 事件类型');
  }
}

function parseOpenErrorDetail(value: unknown): StreamOpenErrorDetail {
  assertRecord(value, '错误详情');
  assertExactKeys(value, ['field', 'reason']);
  return {
    field: readString(value, 'field', 1, 256),
    reason: readString(value, 'reason', 1, 1024),
  };
}

export function parseStreamOpenError(value: unknown): StreamOpenError {
  assertRecord(value, '建流错误');
  assertExactKeys(
    value,
    ['schemaVersion', 'code', 'message', 'requestId', 'retryable'],
    ['details'],
  );
  if (value.schemaVersion !== '1.0') {
    throw new SseProtocolError('建流错误 schemaVersion 必须为 1.0');
  }
  if (value.details !== undefined && !Array.isArray(value.details)) {
    throw new SseProtocolError('建流错误 details 必须是数组');
  }

  return {
    schemaVersion: '1.0',
    code: readString(value, 'code', 1, 128),
    message: readString(value, 'message', 1, 2048),
    requestId: readString(value, 'requestId', 1, 128),
    retryable: readBoolean(value, 'retryable'),
    ...(value.details === undefined
      ? {}
      : { details: value.details.map(parseOpenErrorDetail) }),
  };
}
