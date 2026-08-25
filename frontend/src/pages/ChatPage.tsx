import { useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Divider,
  Empty,
  Flex,
  Form,
  Input,
  List,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { streamChat } from '../api/chat';
import {
  ChatTransportError,
  SseProtocolError,
  StreamOpenErrorResponse,
} from '../api/errors';
import {
  applyChatEvent,
  confirmStreamOpened,
  initialChatState,
  markOpenFailed,
  markStreamEnded,
  markStreamInterrupted,
  markStreamProtocolViolation,
  startChatRequest,
  type ChatState,
  type ChatStatus,
} from '../chat/chatState';

const CONVERSATION_ID = 'phase0-demo';

const STATUS_PRESENTATION: Record<
  ChatStatus,
  { label: string; color: string }
> = {
  idle: { label: '等待提问', color: 'default' },
  connecting: { label: '正在连接', color: 'processing' },
  streaming: { label: '生成中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  interrupted: { label: '已中断', color: 'warning' },
};

function createRequestId(): string {
  return `req-${crypto.randomUUID()}`;
}

function isActive(state: ChatState): boolean {
  return state.status === 'connecting' || state.status === 'streaming';
}

function AnswerStatus({ state }: { state: ChatState }) {
  if (state.status === 'failed' && state.failure) {
    return (
      <Alert
        type="error"
        showIcon
        message={state.failure.message}
        description={`错误码：${state.failure.code} · ${
          state.failure.retryable ? '可以重试' : '请检查请求后重试'
        }`}
      />
    );
  }
  if (state.status === 'interrupted' && state.failure) {
    return (
      <Alert
        type="warning"
        showIcon
        message="本次生成已中断"
        description={state.failure.message}
      />
    );
  }
  if (state.status === 'completed') {
    return <Alert type="success" showIcon message="回答生成完成" />;
  }
  return null;
}

export function ChatPage() {
  const [draft, setDraft] = useState('');
  const [state, setState] = useState<ChatState>(initialChatState);
  const controllerRef = useRef<AbortController | null>(null);
  const active = isActive(state);
  const statusPresentation = STATUS_PRESENTATION[state.status];
  const canSubmit = draft.trim().length > 0 && !active;

  const requestLabel = useMemo(
    () => (state.requestId ? `请求 ID：${state.requestId}` : '尚未发起请求'),
    [state.requestId],
  );

  const submit = async () => {
    const content = draft.trim();
    if (!content || controllerRef.current) {
      return;
    }

    const requestId = createRequestId();
    const controller = new AbortController();
    controllerRef.current = controller;
    let currentState = startChatRequest(requestId, CONVERSATION_ID);
    let streamOpened = false;
    setState(currentState);

    try {
      await streamChat({
        conversationId: CONVERSATION_ID,
        requestId,
        content,
        paperIds: [],
        signal: controller.signal,
        onOpen: (responseRequestId) => {
          streamOpened = true;
          currentState = confirmStreamOpened(currentState, responseRequestId);
          setState(currentState);
        },
        onEvent: (event) => {
          currentState = applyChatEvent(currentState, event);
          setState(currentState);
        },
      });
      currentState = markStreamEnded(currentState);
      setState(currentState);
    } catch (error) {
      if (controller.signal.aborted) {
        currentState = markStreamInterrupted(
          currentState,
          '你已停止本次生成。重新发送问题会创建一个新的请求。',
          'USER_ABORTED',
        );
      } else if (error instanceof StreamOpenErrorResponse) {
        currentState = markOpenFailed(
          currentState,
          {
            code: error.response.code,
            message: error.response.message,
            retryable: error.response.retryable,
          },
          error.response.requestId,
        );
      } else if (error instanceof ChatTransportError) {
        currentState = streamOpened
          ? markStreamInterrupted(currentState, error.message, error.code)
          : markOpenFailed(currentState, {
              code: error.code,
              message: error.message,
              retryable: error.retryable,
            });
      } else if (error instanceof SseProtocolError) {
        currentState = markStreamProtocolViolation(
          currentState,
          `流式响应不符合 SSE v1 契约：${error.message}`,
        );
      } else {
        const message = error instanceof Error ? error.message : '未知网络错误';
        currentState = streamOpened
          ? markStreamInterrupted(currentState, message)
          : markOpenFailed(currentState, {
              code: 'REQUEST_FAILED',
              message: `无法建立流式连接：${message}`,
              retryable: true,
            });
      }
      setState(currentState);
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  };

  const stop = () => {
    controllerRef.current?.abort(
      new DOMException('用户停止生成', 'AbortError'),
    );
  };

  return (
    <main className="page-shell" aria-labelledby="chat-title">
      <Space direction="vertical" size={24} className="full-width">
        <div>
          <Tag color="geekblue">默认知识库</Tag>
          <Typography.Title id="chat-title" level={2}>
            论文问答
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            问题会经由 Java BFF 发送，回答与论文引用将实时呈现。
          </Typography.Paragraph>
        </div>

        <Card className="surface-card">
          <Form layout="vertical" onFinish={() => void submit()}>
            <Form.Item label="研究问题" required>
              <Input.TextArea
                aria-label="研究问题"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                autoSize={{ minRows: 4, maxRows: 10 }}
                placeholder="例如：请概括知识库中的主要观点。"
                disabled={active}
              />
            </Form.Item>
            <Flex gap={12} wrap align="center">
              <Button
                type="primary"
                htmlType="submit"
                loading={state.status === 'connecting'}
                disabled={!canSubmit}
              >
                开始生成
              </Button>
              {active ? (
                <Button danger onClick={stop}>
                  停止生成
                </Button>
              ) : null}
              <Typography.Text type="secondary">
                Phase 0 使用全库范围（paperIds: []）
              </Typography.Text>
            </Flex>
          </Form>
        </Card>

        <Card
          className="surface-card"
          title="回答（模型生成）"
          extra={
            <Tag color={statusPresentation.color}>
              {statusPresentation.label}
            </Tag>
          }
        >
          <Space direction="vertical" size={16} className="full-width">
            <Typography.Text
              className="request-id"
              type={state.requestId ? undefined : 'secondary'}
              copyable={state.requestId ? { text: state.requestId } : false}
            >
              {requestLabel}
            </Typography.Text>
            <AnswerStatus state={state} />
            {state.answer ? (
              <Typography.Paragraph className="streaming-answer">
                {state.answer}
                {state.status === 'streaming' ? (
                  <span className="streaming-cursor" aria-label="正在生成" />
                ) : null}
              </Typography.Paragraph>
            ) : active ? (
              <Flex gap={12} align="center" className="empty-answer">
                <Spin size="small" />
                <Typography.Text type="secondary">
                  {state.status === 'connecting'
                    ? '正在建立流式连接…'
                    : '已连接，等待回答内容…'}
                </Typography.Text>
              </Flex>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="提交问题后，流式回答会显示在这里"
              />
            )}
          </Space>
        </Card>

        <Card className="surface-card" title="论文证据与引用">
          {state.citations.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="当前还没有论文引用"
            />
          ) : (
            <List
              dataSource={[...state.citations]}
              renderItem={(citation, index) => (
                <List.Item key={citation.citationId}>
                  <article className="citation-item">
                    <Flex gap={8} align="center" wrap>
                      <Tag color="blue">引用 {index + 1}</Tag>
                      <Typography.Text strong>
                        {citation.paperTitle}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        第 {citation.pageNumber} 页
                      </Typography.Text>
                    </Flex>
                    <Divider className="citation-divider" />
                    <Typography.Paragraph className="citation-quote">
                      “{citation.quote}”
                    </Typography.Paragraph>
                    <Typography.Text type="secondary">
                      Paper ID：{citation.paperId}
                    </Typography.Text>
                  </article>
                </List.Item>
              )}
            />
          )}
        </Card>
      </Space>
    </main>
  );
}
