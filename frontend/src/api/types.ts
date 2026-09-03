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
    chunkId: string;
  };
}

export type ToolName = 'knowledge_base_search' | 'document_lookup';
export type ToolStatus = 'started' | 'completed' | 'failed';

export interface ToolStatusEvent extends BaseSseEvent {
  type: 'tool.status';
  payload: {
    toolCallId: string;
    toolName: ToolName;
    status: ToolStatus;
    message: string;
  };
}

export type AnswerMode =
  | 'KNOWLEDGE_BASE'
  | 'DOCUMENT_LOOKUP'
  | 'MODEL_KNOWLEDGE';

export interface RunCompletedEvent extends BaseSseEvent {
  type: 'run.completed';
  payload: {
    answerMode: AnswerMode;
  };
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
  | ToolStatusEvent
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

export type PaperStatus = 'PROCESSING' | 'READY' | 'FAILED' | 'EXCLUDED';
export type PaperSourceStatus = 'AVAILABLE' | 'MISSING' | 'REPLACED';
export type LibraryFileKnowledgeStatus =
  | 'NOT_INGESTED'
  | 'PROCESSING'
  | 'READY'
  | 'FAILED'
  | 'EXCLUDED';
export type LibraryStateFilter =
  | 'ORIGINAL_MISSING'
  | 'NOT_INGESTED'
  | 'INGESTED';
export type LibraryScanStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
export type LibraryScanItemOutcome =
  | 'REGISTERED'
  | 'UNCHANGED'
  | 'MOVED'
  | 'DUPLICATE'
  | 'EXCLUDED'
  | 'SKIPPED'
  | 'FAILED';
export type IngestionJobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
export type IngestionStage =
  | 'QUEUED'
  | 'PARSING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'INDEXING'
  | 'COMPLETED'
  | 'FAILED';

export interface IngestionFailure {
  code: string;
  message: string;
  retryable: boolean;
}

export interface IngestionSummary {
  jobId: string;
  status: IngestionJobStatus;
  stage: IngestionStage;
  attempt: number;
  maxAttempts: number;
  canRetry: boolean;
  failure: IngestionFailure | null;
}

export interface Paper {
  paperId: string;
  title: string;
  authors: string[];
  publicationYear: number | null;
  fileName: string;
  fileSizeBytes: number;
  libraryRelativePath: string;
  sourceStatus: PaperSourceStatus;
  status: PaperStatus;
  searchable: boolean;
  pageCount: number | null;
  createdAt: string;
  updatedAt: string;
  currentIngestion: IngestionSummary;
}

export interface LibraryFile {
  libraryFileId: string;
  relativePath: string;
  fileName: string;
  fileSizeBytes: number;
  sha256: string;
  sourceStatus: PaperSourceStatus;
  knowledgeStatus: LibraryFileKnowledgeStatus;
  paperId: string | null;
  paperTitle: string | null;
  searchable: boolean;
  currentIngestion: IngestionSummary | null;
  discoveredAt: string;
  lastSeenAt: string;
  updatedAt: string;
}

export interface LibraryFilesPage {
  items: LibraryFile[];
  total: number;
  offset: number;
  limit: number;
}

export interface LibraryFileUploadData {
  libraryFile: LibraryFile;
  duplicate: boolean;
}

export interface LibraryFileIngestionData {
  libraryFile: LibraryFile;
  paper: Paper;
  ingestionJob: IngestionJob;
  duplicate: boolean;
}

export interface LibraryScanFailure {
  code: string;
  message: string;
}

export interface LibraryScan {
  scanId: string;
  status: LibraryScanStatus;
  discoveredCount: number;
  registeredCount: number;
  unchangedCount: number;
  duplicateCount: number;
  excludedCount: number;
  skippedCount: number;
  failedCount: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  failure: LibraryScanFailure | null;
}

export interface LibraryInfo {
  rootPath: string;
  originalsPath: string;
  supportedExtensions: string[];
  scanInProgress: boolean;
  latestScan: LibraryScan | null;
}

export interface LibraryScanItem {
  relativePath: string;
  outcome: LibraryScanItemOutcome;
  libraryFileId: string | null;
  paperId: string | null;
  code: string | null;
  message: string | null;
}

export interface LibraryScanItemsPage {
  items: LibraryScanItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface IngestionJob extends IngestionSummary {
  paperId: string;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export interface PaperUploadData {
  paper: Paper;
  ingestionJob: IngestionJob;
  duplicate: boolean;
}

export interface PaperListData {
  items: Paper[];
  total: number;
}

export interface DeletePaperData {
  paperId: string;
  deleted: true;
}

export interface ApiResult<T> {
  code: 'SUCCESS';
  message: string;
  data: T;
  requestId: string;
}

export interface ApiErrorResult {
  code: string;
  message: string;
  requestId: string;
}
