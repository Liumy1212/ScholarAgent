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

function jsonResponse(
  init: RequestInit | undefined,
  data: unknown,
  status = 200,
): Response {
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
    originalsPath: 'D:/AIResearcher/.private/paper-library/originals',
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

function ingestionData(file: LibraryFile, duplicate = false) {
  return {
    libraryFile: file,
    paper: paperData(file),
    ingestionJob: {
      ...file.currentIngestion,
      paperId: file.paperId ?? 'paper-001',
      createdAt: NOW,
      startedAt: null,
      completedAt: null,
    },
    duplicate,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('KnowledgeBasePage', () => {
  it('明确提交 PDF，立即展示保存路径并允许再次选择相同文件', async () => {
    let uploaded = false;
    const uploadedFile = libraryFile('NOT_INGESTED');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page(uploaded ? [uploadedFile] : []));
        }
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          expect(init.body).toBeInstanceOf(FormData);
          uploaded = true;
          return jsonResponse(init, { libraryFile: uploadedFile, duplicate: false });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');
    const submit = screen.getByRole('button', { name: '仅上传原件' });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '原件缺失' }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([request]) =>
          String(request).includes('libraryState=ORIGINAL_MISSING'),
        ),
      ).toBe(true);
    });
    const input = screen.getByLabelText('选择 PDF（最多 10 篇）') as HTMLInputElement;
    const file = new File(['%PDF-1.7 synthetic'], 'synthetic.pdf');
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('synthetic.pdf')).toBeTruthy();
    expect(screen.getByText('1 KB')).toBeTruthy();
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);

    expect(await screen.findByText('原件已上传')).toBeTruthy();
    expect(screen.getByText('保存路径：uploads/synthetic.pdf')).toBeTruthy();
    expect(
      screen.getByText('批量上传处理完成；原件不会自动存入知识库。'),
    ).toBeTruthy();
    expect((await screen.findAllByText('未存入知识库')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '存入知识库' })).toBeTruthy();
    expect(
      screen.getByRole('button', { name: /全\s*部/ }).getAttribute('aria-pressed'),
    ).toBe('true');
    const uploadCallIndex = fetchMock.mock.calls.findIndex(
      ([request, init]) =>
        String(request) === '/api/v1/library/files' && init?.method === 'POST',
    );
    expect(
      fetchMock.mock.calls
        .slice(uploadCallIndex + 1)
        .some(
          ([request]) =>
            String(request) === '/api/v1/library/files?offset=0&limit=10',
        ),
    ).toBe(true);
    expect(input.value).toBe('');

    fireEvent.change(input, { target: { files: [file] } });
    expect(
      (screen.getByRole('button', { name: '仅上传原件' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([request]) => String(request).endsWith('/ingestion')),
    ).toBe(false);
  });

  it('允许空 MIME 和 octet-stream 的 .pdf 文件', async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');

    const input = screen.getByLabelText('选择 PDF（最多 10 篇）');
    fireEvent.change(input, {
      target: { files: [new File(['%PDF-empty-mime'], 'empty-mime.pdf')] },
    });
    expect(screen.queryByText(/请选择扩展名/)).toBeNull();
    fireEvent.change(input, {
      target: {
        files: [
          new File(['%PDF-octet'], 'octet.pdf', {
            type: 'application/octet-stream',
          }),
        ],
      },
    });
    expect(screen.queryByText(/请选择扩展名/)).toBeNull();
    expect(screen.getByText('octet.pdf')).toBeTruthy();
  });

  it('上传失败时保留服务端错误码和消息', async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          const requestId = new Headers(init.headers).get('X-Request-Id') ?? '';
          return new Response(
            JSON.stringify({
              code: 'INVALID_PDF',
              message: 'PDF 签名无效',
              requestId,
            }),
            {
              status: 422,
              headers: {
                'Content-Type': 'application/json',
                'X-Request-Id': requestId,
              },
            },
          );
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');

    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: {
        files: [
          new File(['%PDF-invalid'], 'invalid.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '仅上传原件' }));

    expect(await screen.findByText('PDF 签名无效（INVALID_PDF）')).toBeTruthy();
    expect(screen.getByText('invalid.pdf')).toBeTruthy();
  });

  it('按选择顺序串行上传并逐篇创建入库任务', async () => {
    const actions: string[] = [];
    const uploadedById = new Map<string, LibraryFile>();
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page(Array.from(uploadedById.values())));
        }
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          const upload = (init.body as FormData).get('file') as File;
          const ordinal = upload.name === 'first.pdf' ? '001' : '002';
          const registered = libraryFile('NOT_INGESTED', 'AVAILABLE', {
            libraryFileId: `library-file-${ordinal}`,
            fileName: upload.name,
            relativePath: upload.name,
          });
          uploadedById.set(registered.libraryFileId, registered);
          actions.push(`upload:${upload.name}`);
          return jsonResponse(init, { libraryFile: registered, duplicate: false });
        }
        if (url.endsWith('/ingestion') && init?.method === 'POST') {
          const libraryFileId = url.split('/').at(-2) ?? '';
          const registered = uploadedById.get(libraryFileId);
          if (!registered) throw new Error(`Missing upload for ${libraryFileId}`);
          const queued = libraryFile('PROCESSING', 'AVAILABLE', {
            ...registered,
            paperId: `paper-${libraryFileId.slice(-3)}`,
            paperTitle: registered.fileName,
          });
          uploadedById.set(libraryFileId, queued);
          actions.push(`ingest:${registered.fileName}`);
          return jsonResponse(init, ingestionData(queued));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');

    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: {
        files: [
          new File(['%PDF-first'], 'first.pdf', { type: 'application/pdf' }),
          new File(['%PDF-second'], 'second.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并存入知识库' }));

    expect(
      await screen.findByText('批量导入处理完成；成功项已进入现有入库队列。'),
    ).toBeTruthy();
    expect(actions).toEqual([
      'upload:first.pdf',
      'ingest:first.pdf',
      'upload:second.pdf',
      'ingest:second.pdf',
    ]);
    expect(screen.getByText(/共 2 · 已处理 2 · 成功 2 · 失败 0/)).toBeTruthy();
    expect(screen.getAllByText('已进入入库队列')).toHaveLength(2);
  });

  it('单篇上传失败后继续处理并可重试失败项', async () => {
    let firstAttempts = 0;
    const actions: string[] = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          const upload = (init.body as FormData).get('file') as File;
          actions.push(`upload:${upload.name}`);
          if (upload.name === 'first.pdf' && firstAttempts++ === 0) {
            const requestId = new Headers(init.headers).get('X-Request-Id') ?? '';
            return new Response(
              JSON.stringify({ code: 'INVALID_PDF', message: '第一篇失败', requestId }),
              {
                status: 422,
                headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
              },
            );
          }
          const ordinal = upload.name === 'first.pdf' ? '001' : '002';
          return jsonResponse(init, {
            libraryFile: libraryFile('NOT_INGESTED', 'AVAILABLE', {
              libraryFileId: `library-file-${ordinal}`,
              fileName: upload.name,
              relativePath: upload.name,
            }),
            duplicate: false,
          });
        }
        if (url.endsWith('/ingestion') && init?.method === 'POST') {
          actions.push(`ingest:${url.split('/').at(-2)}`);
          const ordinal = url.includes('001') ? '001' : '002';
          const queued = libraryFile('PROCESSING', 'AVAILABLE', {
            libraryFileId: `library-file-${ordinal}`,
            fileName: ordinal === '001' ? 'first.pdf' : 'second.pdf',
            relativePath: ordinal === '001' ? 'first.pdf' : 'second.pdf',
            paperId: `paper-${ordinal}`,
          });
          return jsonResponse(init, ingestionData(queued));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');

    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: {
        files: [
          new File(['%PDF-first'], 'first.pdf', { type: 'application/pdf' }),
          new File(['%PDF-second'], 'second.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并存入知识库' }));

    expect(await screen.findByText('第一篇失败（INVALID_PDF）')).toBeTruthy();
    expect(actions).toContain('ingest:library-file-002');
    fireEvent.click(screen.getByRole('button', { name: '重试失败项（1）' }));
    await waitFor(() => {
      expect(actions).toContain('ingest:library-file-001');
    });
    expect(actions.filter((action) => action === 'upload:second.pdf')).toHaveLength(1);
    expect(await screen.findByText(/共 2 · 已处理 2 · 成功 2 · 失败 0/)).toBeTruthy();
  });

  it('入库请求失败时重试不重复上传原件', async () => {
    let uploadCalls = 0;
    let ingestionCalls = 0;
    const registered = libraryFile('NOT_INGESTED');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          uploadCalls += 1;
          return jsonResponse(init, { libraryFile: registered, duplicate: false });
        }
        if (url.endsWith('/ingestion') && init?.method === 'POST') {
          ingestionCalls += 1;
          if (ingestionCalls === 1) {
            const requestId = new Headers(init.headers).get('X-Request-Id') ?? '';
            return new Response(
              JSON.stringify({
                code: 'DATABASE_UNAVAILABLE',
                message: '数据库暂不可用',
                requestId,
              }),
              {
                status: 502,
                headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
              },
            );
          }
          return jsonResponse(init, ingestionData(libraryFile('PROCESSING')));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');
    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: { files: [new File(['%PDF-retry'], 'retry.pdf')] },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并存入知识库' }));

    expect(await screen.findByText('数据库暂不可用（DATABASE_UNAVAILABLE）')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试失败项（1）' }));
    expect(await screen.findByText(/共 1 · 已处理 1 · 成功 1 · 失败 0/)).toBeTruthy();
    expect(uploadCalls).toBe(1);
    expect(ingestionCalls).toBe(2);
  });

  it('复用到可重试失败任务时调用现有任务重试接口', async () => {
    const failed = libraryFile('FAILED');
    const requestedActions: string[] = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        if (url === '/api/v1/library/files' && init?.method === 'POST') {
          requestedActions.push('upload');
          return jsonResponse(init, {
            libraryFile: libraryFile('NOT_INGESTED'),
            duplicate: true,
          });
        }
        if (url.endsWith('/ingestion') && init?.method === 'POST') {
          requestedActions.push('ingest');
          return jsonResponse(init, ingestionData(failed, true));
        }
        if (url === '/api/v1/ingestion-jobs/job-001/retry' && init?.method === 'POST') {
          requestedActions.push('retry-job');
          return jsonResponse(init, {
            ...libraryFile('PROCESSING').currentIngestion,
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
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');
    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: { files: [new File(['%PDF-existing'], 'existing.pdf')] },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传并存入知识库' }));

    expect(await screen.findByText('合成解析失败（PARSE_FAILED）')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试失败项（1）' }));
    expect(await screen.findByText(/共 1 · 已处理 1 · 成功 1 · 失败 0/)).toBeTruthy();
    expect(requestedActions).toEqual(['upload', 'ingest', 'retry-job']);
  });

  it('超过十篇时拒绝整次选择', async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) return jsonResponse(init, page([]));
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录');

    fireEvent.change(screen.getByLabelText('选择 PDF（最多 10 篇）'), {
      target: {
        files: Array.from(
          { length: 11 },
          (_, index) => new File(['%PDF'], `paper-${index}.pdf`),
        ),
      },
    });

    expect(await screen.findByText('一次最多选择 10 篇 PDF。')).toBeTruthy();
    expect((screen.getByRole('button', { name: '仅上传原件' }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it('对未存入原件显式创建入库任务', async () => {
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

    fireEvent.click(await screen.findByRole('button', { name: '存入知识库' }));

    expect(await screen.findByText('已创建后台入库任务。')).toBeTruthy();
    expect(await screen.findByText('当前阶段：等待 Worker')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/library/files/library-file-001/ingestion',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('展示 READY 论文预览和始终可见的删除知识按钮', async () => {
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

    expect(
      await screen.findByRole('heading', { name: 'Synthetic Research Paper' }),
    ).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: '预览 PDF' }));
    const preview = await screen.findByTitle('synthetic.pdf PDF 预览');
    expect(preview.getAttribute('src')).toBe(
      '/api/v1/library/files/library-file-001/file#page=1',
    );
    expect(screen.getByRole('button', { name: '删除知识' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '移出知识库' })).toBeNull();
  });

  it('未创建 Paper 时禁用删除知识并说明原因', async () => {
    const current = libraryFile('NOT_INGESTED');
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

    const deleteButton = await screen.findByRole('button', { name: '删除知识' });
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true);
    expect(deleteButton.getAttribute('title')).toBe('暂无知识可删');
  });

  it('活动入库任务期间禁用删除知识', async () => {
    const current = libraryFile('PROCESSING');
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

    expect(await screen.findByRole('button', { name: '正在存入知识库' })).toBeTruthy();
    const deleteButton = screen.getByRole('button', { name: '删除知识' });
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true);
    expect(deleteButton.getAttribute('title')).toBe('入库进行中，暂不能删除知识');
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

  it('展示实际扫描目录并在扫描结束后刷新当前筛选', async () => {
    let completed = false;
    const fileQueries: string[] = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') {
          return jsonResponse(init, libraryInfo(completed ? scan('SUCCEEDED', 1) : null));
        }
        if (url.startsWith('/api/v1/library/files?')) {
          fileQueries.push(url);
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

    expect(
      await screen.findByText('D:/AIResearcher/.private/paper-library/originals'),
    ).toBeTruthy();
    expect(
      screen.getByText(
        '可将 PDF 直接放入该目录或任意子目录；扫描只登记和同步状态，不会自动存入知识库。',
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '未存入知识库' }));
    await waitFor(() => {
      expect(fileQueries.some((url) => url.includes('libraryState=NOT_INGESTED'))).toBe(true);
    });
    const beforeScanRefreshes = fileQueries.filter((url) =>
      url.includes('libraryState=NOT_INGESTED'),
    ).length;

    fireEvent.click(screen.getByRole('button', { name: '扫描文件夹' }));
    expect(
      await screen.findByText('扫描任务已创建；扫描只登记原件，不会自动存入知识库。'),
    ).toBeTruthy();
    expect(
      await screen.findByText('扫描完成：新增登记 1，失败 1。', {}, { timeout: 3500 }),
    ).toBeTruthy();
    await waitFor(() => {
      expect(
        fileQueries.filter((url) => url.includes('libraryState=NOT_INGESTED')).length,
      ).toBeGreaterThan(beforeScanRefreshes);
    });
    fireEvent.click(await screen.findByRole('button', { name: '查看失败扫描项' }));
    expect(await screen.findByText('broken.pdf')).toBeTruthy();
    expect(screen.getByText('不是有效 PDF（INVALID_PDF）')).toBeTruthy();
  });

  it('三类筛选使用服务端参数并重置到第一页', async () => {
    const queries: string[] = [];
    const missing = libraryFile('READY', 'MISSING', {
      libraryFileId: 'library-file-missing',
      relativePath: 'missing.pdf',
      fileName: 'missing.pdf',
      searchable: false,
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          queries.push(url);
          const query = new URLSearchParams(url.split('?')[1]);
          const state = query.get('libraryState');
          const requestOffset = Number(query.get('offset'));
          if (state === 'ORIGINAL_MISSING') return jsonResponse(init, page([missing]));
          if (state === 'NOT_INGESTED') {
            return jsonResponse(init, page([libraryFile('NOT_INGESTED')]));
          }
          if (state === 'INGESTED') return jsonResponse(init, page([libraryFile('READY')]));
          return jsonResponse(
            init,
            page([libraryFile('READY')], requestOffset, 12),
          );
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    await screen.findByText('Synthetic Research Paper');
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => {
      expect(queries.some((url) => url.includes('offset=10&limit=10'))).toBe(true);
    });

    fireEvent.click(screen.getByRole('button', { name: '原件缺失' }));
    await screen.findByText(/路径：missing\.pdf/);
    expect(
      queries.some((url) =>
        url.includes('offset=0&limit=10&libraryState=ORIGINAL_MISSING'),
      ),
    ).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '未存入知识库' }));
    await waitFor(() => {
      expect(queries.some((url) => url.includes('libraryState=NOT_INGESTED'))).toBe(true);
    });

    fireEvent.click(screen.getByRole('button', { name: '已存入知识库' }));
    await waitFor(() => {
      expect(queries.some((url) => url.includes('libraryState=INGESTED'))).toBe(true);
    });
  });

  it('删除现存原件的知识后保留该行并变成未存入状态', async () => {
    let current: LibraryFile | null = libraryFile('READY');
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page(current ? [current] : []));
        }
        if (url === '/api/v1/papers/paper-001' && init?.method === 'DELETE') {
          current = libraryFile('NOT_INGESTED');
          return jsonResponse(init, { paperId: 'paper-001', deleted: true });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    fireEvent.click(await screen.findByRole('button', { name: '删除知识' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除知识' }));

    expect(
      await screen.findByText(
        '知识、任务、chunk 和向量已删除；PDF 原件仍保留，当前为未存入知识库。',
      ),
    ).toBeTruthy();
    expect((await screen.findAllByText('未存入知识库')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '存入知识库' })).toBeTruthy();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes('/exclusion')),
    ).toBe(false);
  });

  it('原件缺失时仍可删除知识，成功后该行消失', async () => {
    let current: LibraryFile | null = libraryFile('READY', 'MISSING', {
      searchable: false,
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/library') return jsonResponse(init, libraryInfo());
        if (url.startsWith('/api/v1/library/files?')) {
          return jsonResponse(init, page(current ? [current] : []));
        }
        if (url === '/api/v1/papers/paper-001' && init?.method === 'DELETE') {
          current = null;
          return jsonResponse(init, { paperId: 'paper-001', deleted: true });
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);

    expect(await screen.findByText('原件缺失')).toBeTruthy();
    const deleteButton = screen.getByRole('button', { name: '删除知识' });
    expect((deleteButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(deleteButton);
    fireEvent.click(await screen.findByRole('button', { name: '确认删除知识' }));

    expect(
      await screen.findByText('知识、任务、chunk 和向量已删除；缺失原件登记已清理。'),
    ).toBeTruthy();
    expect(
      await screen.findByText('还没有登记原件；可上传 PDF 或扫描 originals 目录'),
    ).toBeTruthy();
    expect(screen.queryByText('Synthetic Research Paper')).toBeNull();
  });
});
