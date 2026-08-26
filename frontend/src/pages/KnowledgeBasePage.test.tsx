import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { KnowledgeBasePage } from './KnowledgeBasePage';

function paper(status: 'PROCESSING' | 'READY' = 'READY') {
  return {
    paperId: 'paper-knowledge-001',
    title: 'Runtime Bilingual Paper',
    authors: ['Ada Example'],
    publicationYear: 2026,
    fileName: 'runtime.pdf',
    fileSizeBytes: 4096,
    status,
    pageCount: status === 'READY' ? 2 : null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:01:00Z',
    currentIngestion: {
      jobId: 'job-knowledge-001',
      status: status === 'READY' ? 'SUCCEEDED' : 'RUNNING',
      stage: status === 'READY' ? 'COMPLETED' : 'EMBEDDING',
      attempt: 1,
      maxAttempts: 3,
      canRetry: false,
      failure: null,
    },
  };
}

function jsonResponse(init: RequestInit | undefined, data: unknown): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(
    JSON.stringify({ code: 'SUCCESS', message: 'Success.', requestId, data }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    },
  );
}

describe('KnowledgeBasePage', () => {
  it('展示 READY 论文并用浏览器原生 PDF 地址预览', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
        jsonResponse(init, { items: [paper()], total: 1 }),
      ),
    );

    render(<KnowledgeBasePage />);

    expect(await screen.findByText('Runtime Bilingual Paper')).toBeTruthy();
    expect(screen.getByText('可问答')).toBeTruthy();
    expect(screen.getByText('当前阶段：入库完成')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '预览 PDF' }));
    const frame = await screen.findByTitle('Runtime Bilingual Paper PDF 预览');
    expect(frame.getAttribute('src')).toBe(
      '/api/v1/papers/paper-knowledge-001/file#page=1',
    );
  });

  it('上传单个 PDF 后展示后台入库阶段', async () => {
    let listCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        if (String(input) === '/api/v1/papers' && init?.method === 'POST') {
          expect(init.body).toBeInstanceOf(FormData);
          return jsonResponse(init, {
            paper: paper('PROCESSING'),
            ingestionJob: {
              ...paper('PROCESSING').currentIngestion,
              paperId: 'paper-knowledge-001',
              createdAt: '2026-01-01T00:00:00Z',
              startedAt: null,
              completedAt: null,
            },
            duplicate: false,
          });
        }
        listCalls += 1;
        return jsonResponse(
          init,
          listCalls === 1
            ? { items: [], total: 0 }
            : { items: [paper('PROCESSING')], total: 1 },
        );
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<KnowledgeBasePage />);
    expect(await screen.findByText('还没有论文，请先上传一篇文本型 PDF')).toBeTruthy();

    const file = new File(['%PDF-runtime'], 'runtime.pdf', {
      type: 'application/pdf',
    });
    fireEvent.change(screen.getByLabelText('选择单个 PDF'), {
      target: { files: [file] },
    });
    fireEvent.click(await screen.findByRole('button', { name: '上传并入库' }));

    expect(
      await screen.findByText('上传完成，后台 Worker 正在解析并建立向量索引。'),
    ).toBeTruthy();
    expect(await screen.findByText('当前阶段：生成向量')).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});
