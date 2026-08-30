import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  IngestionStage,
  LibraryFile,
  LibraryFileKnowledgeStatus,
  LibraryScan,
  PaperSourceStatus,
} from '../api/types';
import { KnowledgeBasePage } from './KnowledgeBasePage';

const NOW = '2026-08-30T08:00:00Z';

function jsonResponse(init: RequestInit | undefined, data: unknown, status = 200): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(
    JSON.stringify({ code: 'SUCCESS', message: 'Success.', requestId, data }),
    {
      status,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-Id': requestId,
      },
    },
  );
}

function scan(status: LibraryScan['status'], failedCount = 0): LibraryScan {
  return {
    scanId: 'scan-001',
    status,
    discoveredCount: status === 'SUCCEEDED' ? 2 : 0,
    registeredCount: status === 'SUCCEEDED' ? 1 : 0,
    unchangedCount: 0,
    duplicateCount: 0,
    excludedCount: 0,
    skippedCount: 0,
    failedCount,
    createdAt: NOW,
    startedAt: status === 'QUEUED' ? null : NOW,
    completedAt: status === 'SUCCEEDED' || status === 'FAILED' ? NOW : null,
    failure: status === 'FAILED' ? { code: 'SCAN_FAILED', message: '扫描终止' } : null,
  };
}

function libraryInfo(latestScan: LibraryScan | null = null) {
  return {
    rootPath: 'D:/AIResearcher/.private/paper-library',
    supportedExtensions: ['.pdf'],
    scanInProgress:
      latestScan?.status === 'QUEUED' || latestScan?.status === 'RUNNING',
    latestScan,
  };
}

function stageFor(status: LibraryFileKnowledgeStatus): IngestionStage {
  if (status === 'READY') return 'COMPLETED';
  if (status === 'FAILED') return 'FAILED';
  return 'QUEUED';
}

function libraryFile(
  knowledgeStatus: LibraryFileKnowledgeStatus,
  sourceStatus: PaperSourceStatus = 'AVAILABLE',
  overrides: Partial<LibraryFile> = {},
): LibraryFile {
  const hasPaper = knowledgeStatus !== 'NOT_INGESTED';
  const stage = stageFor(knowledgeStatus);
  return {
    libraryFileId: 'library-file-001',
    relativePath: 'uploads/synthetic.pdf',
    fileName: 'synthetic.pdf',
    fileSizeBytes: 4096,
    sha256: 'a'.repeat(64),
    sourceStatus,
    knowledgeStatus,
    paperId: hasPaper ? 'paper-001' : null,
    paperTitle: hasPaper ? 'Synthetic Research Paper' : null,
    searchable: knowledgeStatus === 'READY' && sourceStatus === 'AVAILABLE',
    currentIngestion: hasPaper
      ? {
          jobId: 'job-001',
          status:
            knowledgeStatus === 'READY'
              ? 'SUCCEEDED'
              : knowledgeStatus === 'FAILED'
                ? 'FAILED'
                : 'QUEUED',
          stage,
          attempt: 1,
          maxAttempts: 3,
          canRetry: knowledgeStatus === 'FAILED',
          failure:
            knowledgeStatus === 'FAILED'
              ? { code: 'PARSE_FAILED', message: '合成解析失败', retryable: true }
              : null,
        }
      : null,
    discoveredAt: NOW,
    lastSeenAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

function page(items: LibraryFile[], offset = 0, total = items.length) {
  return { items, total, offset, limit: 10 };
}

function paperData(file: LibraryFile) {
  return {
    paperId: file.paperId ?? 'paper-001',
    title: file.paperTitle ?? file.fileName,
    authors: [],
    publicationYear: null,
    fileName: file.fileName,
    fileSizeBytes: file.fileSizeBytes,
    libraryRelativePath: file.relativePath,
    sourceStatus: file.sourceStatus,
    status: file.knowledgeStatus === 'EXCLUDED' ? 'EXCLUDED' : 'PROCESSING',
    searchable: file.searchable,
    pageCount: null,
    createdAt: NOW,
    updatedAt: NOW,
    currentIngestion:
      file.currentIngestion ?? {
        jobId: 'job-001',
        status: 'QUEUED',
        stage: 'QUEUED',
        attempt: 1,
        maxAttempts: 3,
        canRetry: false,
        failure: null,
      },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('KnowledgeBasePage', () => {
  it('上传只登记原件，不会自动创建入库请求', async () => {
    let uploaded = false;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page(uploaded ? [libraryFile('NOT_INGESTED')] : []));
        }
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          expect(init.body).toBeInstanceOf(FormData);
          uploaded = true;
          const file = libraryFile('NOT_INGESTED');
          return jsonResponse(init, { libraryFile: file, duplicate: false }, 201);
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');
    const file = new File(['%PDF-1.7 synthetic'], 'synthetic.pdf', {
      type: 'application/pdf',
    });
    fireEvent.change(screen.getByLabelText('选择单个 PDF'), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole('button', { name: '仅保存原件' }));

    expect(
      await screen.findByText('原件已保存，但尚未录入知识库。请在清单中手动确认入库。'),
    ).toBeTruthy();
    expect(await screen.findByText('未录入知识库')).toBeTruthy();
    expect(screen.getByRole('button', { name: '录入知识库' })).toBeTruthy();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).endsWith('/ingestion')),
    ).toBe(false);
  });

  it('对未录入原件显式创建入库任务', async () => {
    let current = libraryFile('NOT_INGESTED');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page([current]));
        }
        if (url === '/api/v1/library/files/library-file-001/ingestion') {
          expect(init?.method).toBe('POST');
          current = libraryFile('PROCESSING');
          return jsonResponse(init, {
            libraryFile: current,
            paper: paperData(current),
            ingestionJob: {
              ...current.currentIngestion,
              paperId: 'paper-001',
              createdAt: NOW,
              startedAt: null,
              completedAt: null,
            },
            duplicate: false,
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    fireEvent.click(await screen.findByRole('button', { name: '录入知识库' }));

    expect(await screen.findByText('已创建后台入库任务。')).toBeTruthy();
    expect(await screen.findByText('当前阶段：等待 Worker')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/library/files/library-file-001/ingestion',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('通过原件地址预览 READY 论文且不提供原件硬删除', async () => {
    const current = libraryFile('READY');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page([current]));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    fireEvent.click(await screen.findByRole('button', { name: '预览 PDF' }));
    const preview = await screen.findByTitle('synthetic.pdf PDF 预览');
    expect(preview.getAttribute('src')).toBe(
      '/api/v1/library/files/library-file-001/file#page=1',
    );
    expect(screen.queryByRole('button', { name: '删除' })).toBeNull();
    expect(screen.getByRole('button', { name: '移出知识库' })).toBeTruthy();
  });

  it('允许将已移出论文重新录入知识库', async () => {
    let current = libraryFile('EXCLUDED');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page([current]));
        }
        if (url === '/api/v1/papers/paper-001/exclusion' && init?.method === 'DELETE') {
          current = libraryFile('PROCESSING');
          return jsonResponse(init, paperData(current));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    fireEvent.click(await screen.findByRole('button', { name: '重新录入' }));
    expect(
      await screen.findByText('论文已恢复，并创建新的后台入库任务。'),
    ).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/papers/paper-001/exclusion',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('允许重试失败任务并显示契约错误原因', async () => {
    let current = libraryFile('FAILED');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page([current]));
        }
        if (url === '/api/v1/ingestion-jobs/job-001/retry') {
          expect(init?.method).toBe('POST');
          current = libraryFile('PROCESSING');
          return jsonResponse(init, {
            ...current.currentIngestion,
            paperId: 'paper-001',
            createdAt: NOW,
            startedAt: null,
            completedAt: null,
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    expect(await screen.findByText('合成解析失败')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试入库' }));
    expect(await screen.findByText('入库任务已重新排队。')).toBeTruthy();
  });

  it('轮询扫描到终态并展示失败扫描项', async () => {
    let completed = false;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') {
          return jsonResponse(init, libraryInfo(completed ? scan('SUCCEEDED', 1) : null));
        }
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page([]));
        }
        if (url === '/api/v1/library/scans' && init?.method === 'POST') {
          return jsonResponse(init, scan('RUNNING'), 202);
        }
        if (url === '/api/v1/library/scans/scan-001') {
          completed = true;
          return jsonResponse(init, scan('SUCCEEDED', 1));
        }
        if (url.startsWith('/api/v1/library/scans/scan-001/items?')) {
          expect(url).toContain('outcome=FAILED');
          return jsonResponse(init, {
            items: [
              {
                relativePath: 'broken.pdf',
                outcome: 'FAILED',
                libraryFileId: null,
                paperId: null,
                code: 'INVALID_PDF',
                message: '不是有效 PDF',
              },
            ],
            total: 1,
            offset: 0,
            limit: 200,
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    fireEvent.click(await screen.findByRole('button', { name: '手动扫描' }));
    expect(
      await screen.findByText('扫描任务已创建；扫描只登记原件，不会自动录入知识库。'),
    ).toBeTruthy();
    expect(
      await screen.findByText('扫描完成：新增登记 1，失败 1。', {}, { timeout: 3500 }),
    ).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: '查看失败扫描项' }));
    expect(await screen.findByText('broken.pdf')).toBeTruthy();
    expect(screen.getByText('不是有效 PDF（INVALID_PDF）')).toBeTruthy();
  });

  it('分页展示缺失和已替换原件，并禁用预览和录入', async () => {
    const missing = libraryFile('NOT_INGESTED', 'MISSING', {
      libraryFileId: 'library-file-missing',
      relativePath: 'missing.pdf',
      fileName: 'missing.pdf',
    });
    const replaced = libraryFile('NOT_INGESTED', 'REPLACED', {
      libraryFileId: 'library-file-replaced',
      relativePath: 'replaced.pdf',
      fileName: 'replaced.pdf',
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.includes('/api/v1/library/files?offset=0')) {
          return jsonResponse(init, page([libraryFile('READY')], 0, 12));
        }
        if (url.includes('/api/v1/library/files?offset=10')) {
          return jsonResponse(init, page([missing, replaced], 10, 12));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    await screen.findByText('Synthetic Research Paper');
    fireEvent.click(screen.getByTitle('2'));
    expect(
      await screen.findByText('文件夹中已找不到该原件，请恢复文件后重新扫描。'),
    ).toBeTruthy();
    expect(
      screen.getByText('同一路径的内容已经变化，请重新扫描并使用新登记的原件。'),
    ).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '请重新扫描' })).toHaveLength(2);
    expect(screen.queryByRole('button', { name: '录入知识库' })).toBeNull();
    expect(screen.queryByRole('button', { name: '预览 PDF' })).toBeNull();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes('/api/v1/library/files?offset=10&limit=10'),
        ),
      ).toBe(true);
    });
  });
});
