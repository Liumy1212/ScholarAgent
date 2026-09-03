import { describe, expect, it, vi } from 'vitest';
import {
  excludePaper,
  libraryFileUrl,
  listLibraryFiles,
  restorePaper,
} from './library';

function paperResult(init?: RequestInit): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(
    JSON.stringify({
      code: 'SUCCESS',
      message: 'Success.',
      requestId,
      data: {
        paperId: 'paper-001',
        title: 'Synthetic Research Paper',
        authors: [],
        publicationYear: null,
        fileName: 'synthetic.pdf',
        fileSizeBytes: 4096,
        libraryRelativePath: 'uploads/synthetic.pdf',
        sourceStatus: 'AVAILABLE',
        status: 'EXCLUDED',
        searchable: false,
        pageCount: 1,
        createdAt: '2026-08-30T08:00:00Z',
        updatedAt: '2026-08-30T08:00:00Z',
        currentIngestion: {
          jobId: 'job-001',
          status: 'SUCCEEDED',
          stage: 'COMPLETED',
          attempt: 1,
          maxAttempts: 3,
          canRetry: false,
          failure: null,
        },
      },
    }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-Id': requestId,
      },
    },
  );
}

describe('library API', () => {
  it('使用 exclusion POST/DELETE 并从原件路由生成预览地址', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
        paperResult(init),
    );
    vi.stubGlobal('fetch', fetchMock);

    await excludePaper('paper-001');
    await restorePaper('paper-001');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/papers/paper-001/exclusion',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/papers/paper-001/exclusion',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(libraryFileUrl('library/file 001', 3)).toBe(
      '/api/v1/library/files/library%2Ffile%20001/file#page=3',
    );
  });

  it('仅在选择筛选项时发送 libraryState', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
        return new Response(
          JSON.stringify({
            code: 'SUCCESS',
            message: 'Success.',
            requestId,
            data: { items: [], total: 0, offset: 0, limit: 25 },
          }),
          {
            status: 200,
            headers: {
              'Content-Type': 'application/json',
              'X-Request-Id': requestId,
            },
          },
        );
      },
    );
    vi.stubGlobal('fetch', fetchMock);

    await listLibraryFiles(0, 25);
    await listLibraryFiles(0, 25, 'ORIGINAL_MISSING');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/library/files?offset=0&limit=25');
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/v1/library/files?offset=0&limit=25&libraryState=ORIGINAL_MISSING',
    );
  });
});
