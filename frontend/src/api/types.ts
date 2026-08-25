export interface ChatStreamRequest {
  content: string;
  paperIds: string[];
}

interface BaseSseEvent {
  schemaVersion: '1.0';
  eventId: string;
  requestId: string;
  runId: string;
  conversationId: string;
  assistantMessageId: string;
  sequence: number;
  timestamp: string;
}

export interface RunStartedEvent extends BaseSseEvent {
  type: 'run.started';
  payload: Record<string, never>;
}

export interface MessageDeltaEvent extends BaseSseEvent {
  type: 'message.delta';
  payload: {
    delta: string;
  };
}

export interface CitationCreatedEvent extends BaseSseEvent {
  type: 'citation.created';
  payload: {
    citationId: string;
    paperId: string;
    paperTitle: string;
    pageNumber: number;
    quote: string;
  };
}

export interface RunCompletedEvent extends BaseSseEvent {
  type: 'run.completed';
  payload: Record<string, never>;
}

export interface RunFailedEvent extends BaseSseEvent {
  type: 'run.failed';
  payload: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

export type ChatSseEvent =
  | RunStartedEvent
  | MessageDeltaEvent
  | CitationCreatedEvent
  | RunCompletedEvent
  | RunFailedEvent;

export interface StreamOpenErrorDetail {
  field: string;
  reason: string;
}

export interface StreamOpenError {
  schemaVersion: '1.0';
  code: string;
  message: string;
  requestId: string;
  retryable: boolean;
  details?: StreamOpenErrorDetail[];
}
