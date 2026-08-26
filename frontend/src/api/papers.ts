import type {
  ApiErrorResult,
  ApiResult,
  DeletePaperData,
  IngestionJob,
  Paper,
  PaperListData,
  PaperUploadData,
} from './types';

type JsonRecord = Record<string, unknown>;

export class PaperApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'PaperApiError';
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function createRequestId(): string {
  return `req-${crypto.randomUUID()}`;
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const requestId = createRequestId();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  headers.set('X-Request-Id', requestId);
  const response = await fetch(path, { ...init, headers });
  const responseRequestId = response.headers.get('X-Request-Id');
  const contentType = response.headers.get('Content-Type') ?? '';
  if (!contentType.toLowerCase().startsWith('application/json')) {
    throw new PaperApiError(
      'INVALID_RESPONSE',
      '服务器返回了无法解析的响应。',
      requestId,
      response.status,
    );
  }

  let value: unknown;
  try {
    value = (await response.json()) as unknown;
  } catch {
    throw new PaperApiError(
      'INVALID_RESPONSE',
      '服务器返回的内容不是有效 JSON。',
      requestId,
      response.status,
    );
  }
  if (!isRecord(value)) {
    throw new PaperApiError(
      'INVALID_RESPONSE',
      '服务器返回的 JSON 结构无效。',
      requestId,
      response.status,
    );
  }
  const bodyRequestId = typeof value.requestId === 'string' ? value.requestId : requestId;
  if (responseRequestId !== bodyRequestId || bodyRequestId !== requestId) {
    throw new PaperApiError(
      'INVALID_REQUEST_ID',
      '服务器未保留本次请求 ID。',
      requestId,
      response.status,
    );
  }
  if (!response.ok) {
    const error = value as unknown as ApiErrorResult;
    throw new PaperApiError(
      typeof error.code === 'string' ? error.code : 'REQUEST_FAILED',
      typeof error.message === 'string' ? error.message : '请求失败。',
      bodyRequestId,
      response.status,
    );
  }
  if (value.code !== 'SUCCESS' || typeof value.message !== 'string' || !('data' in value)) {
    throw new PaperApiError(
      'INVALID_RESPONSE',
      '服务器成功响应不符合接口契约。',
      requestId,
      response.status,
    );
  }
  return value as unknown as ApiResult<T>;
}

export async function listPapers(signal?: AbortSignal): Promise<PaperListData> {
  return (await requestJson<PaperListData>('/api/v1/papers', { signal })).data;
}

export async function uploadPaper(file: File): Promise<PaperUploadData> {
  const form = new FormData();
  form.append('file', file, file.name);
  return (
    await requestJson<PaperUploadData>('/api/v1/papers', {
      method: 'POST',
      body: form,
    })
  ).data;
}

export async function getPaper(paperId: string, signal?: AbortSignal): Promise<Paper> {
  return (
    await requestJson<Paper>(`/api/v1/papers/${encodeURIComponent(paperId)}`, {
      signal,
    })
  ).data;
}

export async function deletePaper(paperId: string): Promise<DeletePaperData> {
  return (
    await requestJson<DeletePaperData>(
      `/api/v1/papers/${encodeURIComponent(paperId)}`,
      { method: 'DELETE' },
    )
  ).data;
}

export async function getIngestionJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<IngestionJob> {
  return (
    await requestJson<IngestionJob>(
      `/api/v1/ingestion-jobs/${encodeURIComponent(jobId)}`,
      { signal },
    )
  ).data;
}

export async function retryIngestionJob(jobId: string): Promise<IngestionJob> {
  return (
    await requestJson<IngestionJob>(
      `/api/v1/ingestion-jobs/${encodeURIComponent(jobId)}/retry`,
      { method: 'POST' },
    )
  ).data;
}

export function paperFileUrl(paperId: string, page?: number): string {
  const path = `/api/v1/papers/${encodeURIComponent(paperId)}/file`;
  return page === undefined ? path : `${path}#page=${page}`;
}
