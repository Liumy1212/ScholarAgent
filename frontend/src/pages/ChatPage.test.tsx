import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
    conversationId: 'phase0-demo',
    assistantMessageId: 'msg-component-001',
    sequence,
    timestamp: `2026-01-01T00:00:0${sequence}Z`,
    payload,
  };
}

function wire(event: ReturnType<typeof envelope>): string {
  return `event: ${event.type}\nid: ${event.eventId}\ndata: ${JSON.stringify(event)}\n\n`;
}

describe('ChatPage', () => {
  it('通过 POST SSE 展示回答、引用、requestId 和完成状态', async () => {
    let capturedRequestId = '';
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        expect(String(input)).toBe(
          '/api/v1/conversations/phase0-demo/messages/stream',
        );
        expect(init?.method).toBe('POST');
        const headers = new Headers(init?.headers);
        capturedRequestId = headers.get('X-Request-Id') ?? '';
        expect(JSON.parse(String(init?.body))).toEqual({
          content: '请给出合成回答',
          paperIds: [],
        });

        const events = [
          envelope(capturedRequestId, 'run.started', 'evt-component-001', 0, {}),
          envelope(capturedRequestId, 'message.delta', 'evt-component-002', 1, {
            delta: '合成回答。',
          }),
          envelope(
            capturedRequestId,
            'citation.created',
            'evt-component-003',
            2,
            {
              citationId: 'citation-component-001',
              paperId: 'paper-component-001',
              paperTitle: 'Synthetic Research Paper',
              pageNumber: 3,
              quote: 'This is synthetic evidence.',
            },
          ),
          envelope(
            capturedRequestId,
            'run.completed',
            'evt-component-004',
            3,
            {},
          ),
        ];

        return new Response(responseStream(events.map(wire).join('')), {
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

    fireEvent.change(screen.getByLabelText('研究问题'), {
      target: { value: '请给出合成回答' },
    });
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('回答生成完成')).toBeTruthy();
    expect(screen.getByText('合成回答。')).toBeTruthy();
    expect(screen.getByText('Synthetic Research Paper')).toBeTruthy();
    expect(screen.getByText('“This is synthetic evidence.”')).toBeTruthy();
    expect(screen.getByText(`请求 ID：${capturedRequestId}`)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('展示契约定义的建流失败和 requestId', async () => {
    let capturedRequestId = '';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
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
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('请求内容无效')).toBeTruthy();
    expect(screen.getByText('错误码：INVALID_REQUEST · 请检查请求后重试')).toBeTruthy();
    expect(screen.getByText(`请求 ID：${capturedRequestId}`)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText('失败')).toBeTruthy();
    });
  });

  it('在终止事件前断流时展示中断状态并保留已生成文本', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const requestId =
          new Headers(init?.headers).get('X-Request-Id') ?? '';
        const partialStream = [
          envelope(requestId, 'run.started', 'evt-interrupt-001', 0, {}),
          envelope(requestId, 'message.delta', 'evt-interrupt-002', 1, {
            delta: '尚未完成的回答',
          }),
        ]
          .map(wire)
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
    fireEvent.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText('本次生成已中断')).toBeTruthy();
    expect(screen.getByText('尚未完成的回答')).toBeTruthy();
    expect(screen.getByText('已中断')).toBeTruthy();
  });
});
