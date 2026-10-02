import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from './ChatPage';

function responseStream(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;

  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(offset, offset + 13));
      offset += 13;
    },
  });
}

function envelope(
  requestId: string,
  type: string,
  eventId: string,
  sequence: number,
  payload: object,
) {
  return {
    schemaVersion: '1.0',
    type,
    eventId,
    requestId,
    runId: 'run-component-001',
    conversationId: 'replaced-by-request-path',
    assistantMessageId: 'msg-component-001',
    sequence,
    timestamp: `2026-01-01T00:00:0${sequence}Z`,
    payload,
  };
}

function wire(event: ReturnType<typeof envelope>, path: RequestInfo | URL): string {
  event.conversationId = String(path).split('/')[4] ?? '';

  return `event: ${event.type}\nid: ${event.eventId}\ndata: ${JSON.stringify(event)}\n\n`;
}

function paperListResponse(
  init?: RequestInit,
  include = false,
  searchable = include,
): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  const paper = {
    paperId: 'paper-component-001',
    title: 'Synthetic Research Paper',
    authors: ['Demo Author'],
    publicationYear: 2026,
    fileName: 'synthetic.pdf',
    fileSizeBytes: 4096,
    libraryRelativePath: 'uploads/synthetic.pdf',
    sourceStatus: 'AVAILABLE',
    status: 'READY',
    searchable,
    pageCount: 3,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:01:00Z',
    currentIngestion: {
      jobId: 'job-component-001',
      status: 'SUCCEEDED',
      stage: 'COMPLETED',
      attempt: 1,
      maxAttempts: 3,
      canRetry: false,
      failure: null,
    },
  };
  return new Response(
    JSON.stringify({
      code: 'SUCCESS',
      message: 'Success.',
      requestId,
      data: { items: include ? [paper] : [], total: include ? 1 : 0 },
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    },
  );
}

function knowledgeBaseListResponse(init?: RequestInit, include = false): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(
    JSON.stringify({
      code: 'SUCCESS',
      message: 'Success.',
      requestId,
      data: {
        items: include ? [{
          knowledgeBaseId: 'kb-component-001',
          name: '合成知识库',
          paperCount: 2,
          searchablePaperCount: 1,
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:01:00Z',
        }] : [],
        total: include ? 1 : 0,
        offset: 0,
        limit: 200,
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId } },
  );
}

function conversationListResponse(init?: RequestInit): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(JSON.stringify({
    code: 'SUCCESS',
    message: 'Success.',
    requestId,
    data: { items: [], total: 0, offset: 0, limit: 50 },
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
  });
}

beforeEach(() => {
  localStorage.clear();
});

describe('ChatPage', () => {
  it('通过 POST SSE 展示回答、引用、requestId 和完成状态', async () => {
    let capturedRequestId = '';
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        if (String(input) === '/api/v1/papers') {
          return paperListResponse(init, true);
        }
        if (String(input).startsWith('/api/v1/knowledge-bases')) {
          return knowledgeBaseListResponse(init);
        }
        if (String(input).startsWith('/api/v1/conversations?')) {
          return conversationListResponse(init);
        }
        expect(String(input)).toMatch(/^\/api\/v1\/conversations\/[0-9a-f-]{36}\/messages\/stream$/);
        expect(init?.method).toBe('POST');
        const headers = new Headers(init?.headers);
        capturedRequestId = headers.get('X-Request-Id') ?? '';
        expect(JSON.parse(String(init?.body))).toEqual({
          content: '请给出合成回答',
          paperIds: ['paper-component-001'],
        });

        const citationId = `citation-${'c'.repeat(32)}`;

        const events = [
          envelope(capturedRequestId, 'run.started', 'evt-component-001', 0, {}),
          envelope(capturedRequestId, 'tool.status', 'evt-component-tool-001', 1, {
            toolCallId: 'call-component-001',
            toolName: 'knowledge_base_search',
            status: 'started',
            message: '正在检索并重排论文证据。',
          }),
          envelope(capturedRequestId, 'tool.status', 'evt-component-tool-002', 2, {
            toolCallId: 'call-component-001',
            toolName: 'knowledge_base_search',
            status: 'completed',
            message: '已完成论文证据检索与重排。',
          }),
          envelope(capturedRequestId, 'message.delta', 'evt-component-002', 3, {
            delta: `合成回答。[[citation:${citationId}]]`,
          }),
          envelope(
            capturedRequestId,
            'citation.created',
            'evt-component-003',
            4,
            {
              citationId,
              paperId: 'paper-component-001',
              paperTitle: 'Synthetic Research Paper',
              pageNumber: 3,
              quote: 'This is synthetic evidence.',
              chunkId: 'chunk-component-003',
            },
          ),
          envelope(
            capturedRequestId,
            'run.completed',
            'evt-component-004',
            5,
            { answerMode: 'KNOWLEDGE_BASE' },
          ),
        ];

        return new Response(responseStream(events.map((event) => wire(event, input)).join('')), {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream; charset=utf-8',
            'X-Request-Id': capturedRequestId,
          },
        });
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<ChatPage />);

    expect(
      await screen.findByText('限定 paperId：paper-component-001'),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText('研究问题'), {
      target: { value: '请给出合成回答' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('回答生成完成')).toBeTruthy();
    expect(screen.getByText(/论文证据回答/)).toBeTruthy();
    expect(screen.getByText('[1]').getAttribute('href')).toBe(
      '/api/v1/papers/paper-component-001/file#page=3',
    );
    expect(screen.getByText('knowledge_base_search')).toBeTruthy();
    expect(screen.getByText('已完成论文证据检索与重排。')).toBeTruthy();
    expect(screen.getAllByText('Synthetic Research Paper')).toHaveLength(2);
    expect(screen.getByText('“This is synthetic evidence.”')).toBeTruthy();
    expect(screen.getByText(`请求 ID：${capturedRequestId}`)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it('展示契约定义的建流失败和 requestId', async () => {
    let capturedRequestId = '';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === '/api/v1/papers') {
          return paperListResponse(init);
        }
        if (String(input).startsWith('/api/v1/knowledge-bases')) {
          return knowledgeBaseListResponse(init);
        }
        if (String(input).startsWith('/api/v1/conversations?')) {
          return conversationListResponse(init);
        }
        capturedRequestId =
          new Headers(init?.headers).get('X-Request-Id') ?? '';
        return new Response(
          JSON.stringify({
            schemaVersion: '1.0',
            code: 'INVALID_REQUEST',
            message: '请求内容无效',
            requestId: capturedRequestId,
            retryable: false,
          }),
          {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'X-Request-Id': capturedRequestId,
            },
          },
        );
      }),
    );
    render(<ChatPage />);

    fireEvent.change(screen.getByLabelText('研究问题'), {
      target: { value: '失败场景' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('请求内容无效')).toBeTruthy();
    expect(screen.getByText('错误码：INVALID_REQUEST · 请检查请求后重试')).toBeTruthy();
    expect(screen.getByText(`请求 ID：${capturedRequestId}`)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText('失败')).toBeTruthy();
    });
  });

  it('展示可重试的模型服务失败并保留请求 ID', async () => {
    let capturedRequestId = '';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === '/api/v1/papers') return paperListResponse(init);
        if (String(input).startsWith('/api/v1/knowledge-bases')) {
          return knowledgeBaseListResponse(init);
        }
        if (String(input).startsWith('/api/v1/conversations?')) {
          return conversationListResponse(init);
        }
        capturedRequestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
        const events = [
          envelope(capturedRequestId, 'run.started', 'evt-provider-start', 0, {}),
          envelope(capturedRequestId, 'run.failed', 'evt-provider-failed', 1, {
            code: 'PROVIDER_UNAVAILABLE',
            message: '模型服务暂不可用',
            retryable: true,
          }),
        ];
        return new Response(responseStream(events.map((event) => wire(event, input)).join('')), {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream; charset=utf-8',
            'X-Request-Id': capturedRequestId,
          },
        });
      }),
    );
    render(<ChatPage />);

    await ask('模型失败场景');

    expect(await screen.findByText('模型服务暂不可用')).toBeTruthy();
    expect(screen.getByText('错误码：PROVIDER_UNAVAILABLE · 可以重试')).toBeTruthy();
    expect(screen.getByText(`请求 ID：${capturedRequestId}`)).toBeTruthy();
    expect(screen.getByText('失败')).toBeTruthy();
  });

  it('在终止事件前断流时展示中断状态并保留已生成文本', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === '/api/v1/papers') {
          return paperListResponse(init);
        }
        if (String(input).startsWith('/api/v1/knowledge-bases')) {
          return knowledgeBaseListResponse(init);
        }
        if (String(input).startsWith('/api/v1/conversations?')) {
          return conversationListResponse(init);
        }
        const requestId =
          new Headers(init?.headers).get('X-Request-Id') ?? '';
        const partialStream = [
          envelope(requestId, 'run.started', 'evt-interrupt-001', 0, {}),
          envelope(requestId, 'message.delta', 'evt-interrupt-002', 1, {
            delta: '尚未完成的回答',
          }),
        ]
          .map((event) => wire(event, input))
          .join('');

        return new Response(responseStream(partialStream), {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'X-Request-Id': requestId,
          },
        });
      }),
    );
    render(<ChatPage />);

    fireEvent.change(screen.getByLabelText('研究问题'), {
      target: { value: '中断场景' },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('本次生成已中断')).toBeTruthy();
    expect(screen.getByText('尚未完成的回答')).toBeTruthy();
    expect(screen.getByText('已中断')).toBeTruthy();
  });

  it('不允许选择 READY 但 searchable=false 的论文', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
        if (String(input).startsWith('/api/v1/conversations?')) return conversationListResponse(init);
        return paperListResponse(init, true, false);
      }),
    );
    render(<ChatPage />);

    expect(
      await screen.findByText(
        '当前没有可检索论文；全部论文范围仍可用于普通模型回答。',
      ),
    ).toBeTruthy();
    expect(screen.getAllByText('全部可检索论文').length).toBeGreaterThan(0);
    expect(screen.queryByText('Synthetic Research Paper')).toBeNull();
  });

  it('选择知识库时只发送 knowledgeBaseId 并清空 paperIds', async () => {
    let body: unknown;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/v1/papers') return paperListResponse(init, true);
      if (String(input).startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init, true);
      if (String(input).startsWith('/api/v1/conversations?')) return conversationListResponse(init);
      body = JSON.parse(String(init?.body));
      const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
      const events = [
        envelope(requestId, 'run.started', 'evt-kb-start', 0, {}),
        envelope(requestId, 'run.completed', 'evt-kb-done', 1, { answerMode: 'MODEL_KNOWLEDGE' }),
      ];
      return new Response(responseStream(events.map((event) => wire(event, input)).join('')), {
        headers: { 'Content-Type': 'text/event-stream', 'X-Request-Id': requestId },
      });
    }));
    render(<ChatPage />);

    fireEvent.mouseDown(await screen.findByRole('combobox', { name: '检索范围' }));
    fireEvent.click(await screen.findByText('合成知识库 · 1/2 篇可检索'));
    await ask('跨论文比较');
    await screen.findByText('回答生成完成');

    expect(body).toEqual({
      content: '跨论文比较',
      paperIds: [],
      knowledgeBaseId: 'kb-component-001',
    });
  });
});


async function ask(question: string) {
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: question } });
  await waitFor(() => expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '开始生成' }));
}

it('保留多轮问答，新建与切换范围会隔离会话', async () => {
  const paths: string[] = [];
  const bodies: object[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === '/api/v1/papers') return paperListResponse(init, true);
    if (String(input).startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    if (String(input).startsWith('/api/v1/conversations?')) return conversationListResponse(init);
    paths.push(String(input));
    bodies.push(JSON.parse(String(init?.body)) as object);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    const events = [
      envelope(requestId, 'run.started', 'evt-start', 0, {}),
      envelope(requestId, 'message.delta', 'evt-answer', 1, { delta: `回答第${paths.length}轮` }),
      envelope(requestId, 'run.completed', 'evt-done', 2, { answerMode: 'MODEL_KNOWLEDGE' }),
    ];
    return new Response(responseStream(events.map((event) => wire(event, input)).join('')), {
      headers: { 'Content-Type': 'text/event-stream', 'X-Request-Id': requestId },
    });
  }));
  const page = render(<ChatPage />);
  await ask('介绍方法');
  await screen.findByText('回答第1轮');
  await ask('它有什么限制');
  await screen.findByText('回答第2轮');
  expect(screen.getByText('介绍方法')).toBeTruthy();
  expect(screen.getByText('回答第1轮')).toBeTruthy();
  expect(paths[1]).toBe(paths[0]);
  fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: '未发送草稿' } });
  fireEvent.click(screen.getByRole('button', { name: '新建会话' }));
  expect(screen.queryByText('回答第1轮')).toBeNull();
  expect((screen.getByLabelText('研究问题') as HTMLTextAreaElement).value).toBe('');
  await ask('新话题');
  await screen.findByText('回答第3轮');
  expect(paths[2]).not.toBe(paths[1]);
  expect(bodies[2]).toEqual({ content: '新话题', paperIds: ['paper-component-001'] });
  const clear = page.container.querySelector('.ant-select-clear');
  expect(clear).not.toBeNull();
  fireEvent.mouseDown(clear!);
  expect(screen.queryByText('回答第3轮')).toBeNull();
  await ask('全部论文');
  await screen.findByText('回答第4轮');
  expect(paths[3]).not.toBe(paths[2]);
  expect(bodies[3]).toEqual({ content: '全部论文', paperIds: [] });
});

it('自动恢复本机记住的成功会话并保留已删除论文的引用快照', async () => {
  const conversationId = 'conversation-history-001';
  localStorage.setItem('airesearcher.activeConversationId.v1', conversationId);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return paperListResponse(init, true);
    if (path.startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    const conversation = {
      conversationId,
      title: '历史问题',
      preview: '历史回答',
      scope: { type: 'PAPERS', scopeId: null, paperIds: ['paper-component-001'] },
      turnCount: 1,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:01:00Z',
    };
    const data = path.includes('?')
      ? { items: [conversation], total: 1, offset: 0, limit: 50 }
      : {
          conversation,
          turns: [{
            runId: 'run-history-001',
            requestId: null,
            assistantMessageId: 'message-history-001',
            question: '历史问题',
            answer: '历史回答 [[citation:citation-history-001]]',
            answerMode: 'KNOWLEDGE_BASE',
            tools: [],
            citations: [{
              citationId: 'citation-history-001',
              paperId: null,
              paperTitle: '已删除论文',
              pageNumber: 7,
              quote: '仍然保留的历史证据',
              chunkId: 'chunk-history-001',
            }],
            createdAt: '2026-01-01T00:00:00Z',
            completedAt: '2026-01-01T00:01:00Z',
          }],
          totalTurns: 1,
          truncated: false,
        };
    return new Response(JSON.stringify({ code: 'SUCCESS', message: 'Success.', requestId, data }), {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    });
  }));

  render(<ChatPage />);

  await waitFor(() => expect(screen.getAllByText('历史问题').length).toBeGreaterThanOrEqual(2));
  expect(screen.getByText('仍然保留的历史证据', { exact: false })).toBeTruthy();
  expect(screen.getByText('第 7 页 · 原论文已不可用')).toBeTruthy();
  expect(screen.queryByText('打开第 7 页')).toBeNull();
  expect(screen.getByText('历史记录未保存请求 ID')).toBeTruthy();
});

it('stale localStorage 会回退到空白新会话', async () => {
  localStorage.setItem('airesearcher.activeConversationId.v1', 'missing-conversation');
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return paperListResponse(init);
    if (path.startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    if (path.includes('?')) return conversationListResponse(init);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    return new Response(JSON.stringify({
      code: 'CONVERSATION_NOT_FOUND', message: 'Not found.', requestId,
    }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    });
  }));

  render(<ChatPage />);

  expect(await screen.findByText('提交问题后，连续问答会显示在这里')).toBeTruthy();
  await waitFor(() => expect(localStorage.getItem('airesearcher.activeConversationId.v1')).not.toBe('missing-conversation'));
});

it('点击会话列表的“打开”按钮会切换到该会话', async () => {
  const conversationId = 'conv-switch-001';
  const conversation = {
    conversationId,
    title: '历史问题',
    preview: '历史回答',
    scope: { type: 'ALL', scopeId: null, paperIds: [] },
    turnCount: 1,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:01:00Z',
  };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return paperListResponse(init, true);
    if (path.startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    const data = path.includes('?')
      ? { items: [conversation], total: 1, offset: 0, limit: 50 }
      : {
          conversation,
          turns: [{
            runId: 'run-switch-001',
            requestId: 'req-switch-001',
            assistantMessageId: 'message-switch-001',
            question: '历史问题',
            answer: '历史回答',
            answerMode: 'MODEL_KNOWLEDGE',
            tools: [],
            citations: [],
            createdAt: '2026-01-01T00:00:00Z',
            completedAt: '2026-01-01T00:01:00Z',
          }],
          totalTurns: 1,
          truncated: false,
        };
    return new Response(JSON.stringify({ code: 'SUCCESS', message: 'Success.', requestId, data }), {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    });
  }));

  render(<ChatPage />);

  const open = await screen.findByRole('button', { name: '打开' });
  expect(screen.getAllByText('历史问题')).toHaveLength(1);
  fireEvent.click(open);

  expect(await screen.findByRole('button', { name: '当前会话' })).toBeTruthy();
  expect(screen.getAllByText('历史问题').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText('请求 ID：req-switch-001')).toBeTruthy();
});

it('恢复 LEGACY 范围会话时提示范围不可继续并保持只读', async () => {
  localStorage.setItem('airesearcher.activeConversationId.v1', 'conv-legacy-001');
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return paperListResponse(init, true);
    if (path.startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    if (path.includes('?')) return conversationListResponse(init);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    return new Response(JSON.stringify({
      code: 'SUCCESS',
      message: 'Success.',
      requestId,
      data: {
        conversation: {
          conversationId: 'conv-legacy-001',
          title: '历史问题',
          preview: '历史回答',
          scope: { type: 'LEGACY', scopeId: null, paperIds: [] },
          turnCount: 1,
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:01:00Z',
        },
        turns: [{
          runId: 'run-legacy-001',
          requestId: null,
          assistantMessageId: 'message-legacy-001',
          question: '历史问题',
          answer: '历史回答',
          answerMode: 'MODEL_KNOWLEDGE',
          tools: [],
          citations: [],
          createdAt: '2026-01-01T00:00:00Z',
          completedAt: '2026-01-01T00:01:00Z',
        }],
        totalTurns: 1,
        truncated: false,
      },
    }), {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    });
  }));

  render(<ChatPage />);

  expect(await screen.findByText('历史检索范围当前不可继续')).toBeTruthy();
  expect(screen.getByText('历史问答仍可查看。请选择有效范围并新建会话后再继续提问。')).toBeTruthy();
  expect(screen.getByText('历史回答')).toBeTruthy();
  expect((screen.getByLabelText('研究问题') as HTMLTextAreaElement).disabled).toBe(true);
  expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(true);
});

it('恢复的会话超过 100 轮时展示截断提示', async () => {
  localStorage.setItem('airesearcher.activeConversationId.v1', 'conv-truncated-001');
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return paperListResponse(init, true);
    if (path.startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    if (path.includes('?')) return conversationListResponse(init);
    const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
    return new Response(JSON.stringify({
      code: 'SUCCESS',
      message: 'Success.',
      requestId,
      data: {
        conversation: {
          conversationId: 'conv-truncated-001',
          title: '截断问题',
          preview: '截断回答',
          scope: { type: 'ALL', scopeId: null, paperIds: [] },
          turnCount: 101,
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:01:00Z',
        },
        turns: [{
          runId: 'run-truncated-001',
          requestId: null,
          assistantMessageId: 'message-truncated-001',
          question: '截断问题',
          answer: '截断回答',
          answerMode: 'MODEL_KNOWLEDGE',
          tools: [],
          citations: [],
          createdAt: '2026-01-01T00:00:00Z',
          completedAt: '2026-01-01T00:01:00Z',
        }],
        totalTurns: 101,
        truncated: true,
      },
    }), {
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
    });
  }));

  render(<ChatPage />);

  expect(await screen.findByText('该会话较长，当前仅展示最近 100 轮成功问答。')).toBeTruthy();
  expect(screen.getByText('截断回答')).toBeTruthy();
});

it('生成中禁用会话操作，停止后可继续，卸载取消待处理请求', async () => {
  const signals: AbortSignal[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === '/api/v1/papers') return paperListResponse(init, true);
    if (String(input).startsWith('/api/v1/knowledge-bases')) return knowledgeBaseListResponse(init);
    if (String(input).startsWith('/api/v1/conversations?')) return conversationListResponse(init);
    const signal = init?.signal;
    if (!signal) throw new Error('missing signal');
    signals.push(signal);
    return new Promise<Response>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    });
  }));
  const page = render(<ChatPage />);
  await ask('等待模型');
  await waitFor(() => expect(signals).toHaveLength(1));
  expect(screen.getByRole('button', { name: '新建会话' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('combobox', { name: '检索范围' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: /开始生成/ }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '停止生成' }));
  await screen.findByText('本次生成已中断');
  expect(signals[0]?.aborted).toBe(true);
  await ask('继续');
  await waitFor(() => expect(signals).toHaveLength(2));
  await act(async () => page.unmount());
  expect(signals[1]?.aborted).toBe(true);
});
