import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
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
  Select,
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
import { listPapers, paperFileUrl, PaperApiError } from '../api/papers';
import { listKnowledgeBases } from '../api/knowledgeBases';
import type { AnswerMode, KnowledgeBase, Paper } from '../api/types';
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
  type Citation,
} from '../chat/chatState';

interface ChatTurn {
  id: string;
  question: string;
  state: ChatState;
}

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

const ANSWER_MODE_LABEL: Record<AnswerMode, string> = {
  KNOWLEDGE_BASE: '论文证据回答',
  DOCUMENT_LOOKUP: '论文信息回答',
  MODEL_KNOWLEDGE: '模型知识回答',
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
    return (
      <Alert
        type="success"
        showIcon
        message="回答生成完成"
        description={
          state.answerMode ? `回答模式：${ANSWER_MODE_LABEL[state.answerMode]}` : undefined
        }
      />
    );
  }
  return null;
}

function AnswerText({ answer, citations }: { answer: string; citations: readonly Citation[] }) {
  const citationById = new Map(citations.map((citation) => [citation.citationId, citation]));
  const matcher = /\[\[citation:([^\]]+)\]\]/g;
  const content: ReactNode[] = [];
  let cursor = 0;
  let match = matcher.exec(answer);
  while (match) {
    if (match.index > cursor) {
      content.push(answer.slice(cursor, match.index));
    }
    const citationId = match[1] ?? '';
    const citation = citationById.get(citationId);
    if (citation) {
      const index = citations.findIndex((item) => item.citationId === citationId) + 1;
      content.push(
        <a
          key={`${citationId}-${match.index}`}
          className="inline-citation"
          href={paperFileUrl(citation.paperId, citation.pageNumber)}
          target="_blank"
          rel="noreferrer"
          title={`打开 ${citation.paperTitle} 第 ${citation.pageNumber} 页`}
        >
          [{index}]
        </a>,
      );
    }
    cursor = match.index + match[0].length;
    match = matcher.exec(answer);
  }
  if (cursor < answer.length) {
    content.push(answer.slice(cursor));
  }
  return <>{content}</>;
}

function paperLoadError(error: unknown): string {
  if (error instanceof PaperApiError) {
    return `${error.message}（${error.code}）`;
  }
  return error instanceof Error ? error.message : '无法读取论文列表。';
}

function ConversationTurn({ question, state }: { question: string; state: ChatState }) {
  const active = isActive(state);
  const statusPresentation = STATUS_PRESENTATION[state.status];
  const requestLabel = useMemo(
    () => (state.requestId ? `请求 ID：${state.requestId}` : '尚未发起请求'),
    [state.requestId],
  );
  const latestTools = useMemo(() => {
    const tools = new Map<string, ChatState['tools'][number]>();
    for (const tool of state.tools) {
      tools.set(tool.toolCallId, tool);
    }
    return [...tools.values()];
  }, [state.tools]);

  return (
    <section aria-label={`问答：${question}`}>
      <Space direction="vertical" size={16} className="full-width">
        <Card title="你的问题"><Typography.Paragraph>{question}</Typography.Paragraph></Card>
        <Card
          className="surface-card"
          title="回答（模型生成）"
          extra={<Tag color={statusPresentation.color}>{statusPresentation.label}</Tag>}
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
                <AnswerText answer={state.answer} citations={state.citations} />
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
                    : '已连接，等待模型或工具返回…'}
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

        <Card className="surface-card" title="工具执行状态（非思维链）">
          {latestTools.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未调用只读工具" />
          ) : (
            <List
              dataSource={latestTools}
              renderItem={(tool) => (
                <List.Item key={tool.toolCallId}>
                  <Flex gap={10} align="center" wrap>
                    <Tag
                      color={
                        tool.status === 'completed'
                          ? 'success'
                          : tool.status === 'failed'
                            ? 'error'
                            : 'processing'
                      }
                    >
                      {tool.status}
                    </Tag>
                    <Typography.Text code>{tool.toolName}</Typography.Text>
                    <Typography.Text>{tool.message}</Typography.Text>
                  </Flex>
                </List.Item>
              )}
            />
          )}
        </Card>

        <Card className="surface-card" title="论文证据与引用">
          {state.citations.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前还没有论文引用" />
          ) : (
            <List
              dataSource={[...state.citations]}
              renderItem={(citation, index) => (
                <List.Item key={citation.citationId}>
                  <article className="citation-item">
                    <Flex gap={8} align="center" wrap>
                      <Tag color="blue">引用 {index + 1}</Tag>
                      <Typography.Text strong>{citation.paperTitle}</Typography.Text>
                      <a
                        href={paperFileUrl(citation.paperId, citation.pageNumber)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        打开第 {citation.pageNumber} 页
                      </a>
                    </Flex>
                    <Divider className="citation-divider" />
                    <Typography.Paragraph className="citation-quote">
                      “{citation.quote}”
                    </Typography.Paragraph>
                    <Typography.Text type="secondary" className="citation-ids">
                      Paper ID：{citation.paperId} · Chunk ID：{citation.chunkId}
                    </Typography.Text>
                  </article>
                </List.Item>
              )}
            />
          )}
        </Card>
      </Space>
    </section>
  );
}

export function ChatPage() {
  const [draft, setDraft] = useState('');
  const [conversationId, setConversationId] = useState(() => crypto.randomUUID());
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const state = turns.at(-1)?.state ?? initialChatState;
  const [readyPapers, setReadyPapers] = useState<Paper[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedScope, setSelectedScope] = useState('all');
  const [paperLoading, setPaperLoading] = useState(true);
  const [knowledgeBaseLoading, setKnowledgeBaseLoading] = useState(true);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [knowledgeBaseError, setKnowledgeBaseError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const active = pending || isActive(state);
  const selectedPaperId = selectedScope.startsWith('paper:') ? selectedScope.slice(6) : undefined;
  const selectedKnowledgeBaseId = selectedScope.startsWith('kb:') ? selectedScope.slice(3) : undefined;
  const selectedKnowledgeBase = knowledgeBases.find((item) => item.knowledgeBaseId === selectedKnowledgeBaseId);
  const scopeReady = selectedKnowledgeBaseId
    ? !knowledgeBaseLoading && Boolean(selectedKnowledgeBase?.searchablePaperCount)
    : !paperLoading;
  const canSubmit = draft.trim().length > 0 && !active && scopeReady;

  useEffect(() => {
    const controller = new AbortController();
    void listPapers(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        const ready = result.items.filter((paper) => paper.searchable);
        setReadyPapers(ready);
        setSelectedScope((current) => current === 'all' && ready[0] ? `paper:${ready[0].paperId}` : current);
        setPaperError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setPaperError(paperLoadError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setPaperLoading(false);
        }
      });
    return () => {
      controller.abort();
      const pending = controllerRef.current;
      controllerRef.current = null;
      pending?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void listKnowledgeBases(0, 200, controller.signal)
      .then((result) => { setKnowledgeBases(result.items); setKnowledgeBaseError(null); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setKnowledgeBaseError(paperLoadError(error)); })
      .finally(() => { if (!controller.signal.aborted) setKnowledgeBaseLoading(false); });
    return () => controller.abort();
  }, []);

  const selectedPaper = readyPapers.find(
    (paper) => paper.paperId === selectedPaperId,
  );

  const submit = async () => {
    const content = draft.trim();
    if (!content || !scopeReady || controllerRef.current) {
      return;
    }

    const requestId = createRequestId();
    const controller = new AbortController();
    controllerRef.current = controller;
    setPending(true);
    let currentState = startChatRequest(requestId, conversationId);
    let streamOpened = false;
    setDraft('');
    const initialState = currentState;
    setTurns((previous) => [...previous, { id: requestId, question: content, state: initialState }]);
    const publish = () => {
      if (controllerRef.current !== controller) return;
      const snapshot = currentState;
      setTurns((previous) => previous.map((turn) =>
        turn.id === requestId ? { ...turn, state: snapshot } : turn,
      ));
    };
    publish();

    try {
      await streamChat({
        conversationId,
        requestId,
        content,
        paperIds: selectedPaperId ? [selectedPaperId] : [],
        knowledgeBaseId: selectedKnowledgeBaseId,
        signal: controller.signal,
        onOpen: (responseRequestId) => {
          if (controllerRef.current !== controller || controller.signal.aborted) return;
          streamOpened = true;
          currentState = confirmStreamOpened(currentState, responseRequestId);
          publish();
        },
        onEvent: (event) => {
          if (controllerRef.current !== controller || controller.signal.aborted) return;
          currentState = applyChatEvent(currentState, event);
          publish();
        },
      });
      currentState = markStreamEnded(currentState);
      publish();
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
      publish();
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setPending(false);
      }
    }
  };

  const newConversation = () => {
    if (controllerRef.current) return;
    setConversationId(crypto.randomUUID());
    setTurns([]);
    setDraft('');
  };

  const stop = () => {
    controllerRef.current?.abort(new DOMException('用户停止生成', 'AbortError'));
  };

  return (
    <main className="page-shell" aria-labelledby="chat-title">
      <Space direction="vertical" size={24} className="full-width">
        <div>
          <Tag color={selectedPaper || selectedKnowledgeBase ? 'geekblue' : 'default'}>
            {selectedPaper?.title ?? selectedKnowledgeBase?.name ?? '全部可检索论文'}
          </Tag>
          <Typography.Title id="chat-title" level={2}>
            论文问答
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            仅最近 10 轮同范围的成功问答参与上下文，并受文本总量限制。刷新、离开此页或切换范围都会开启新会话。
          </Typography.Paragraph>
        </div>

        <Card className="surface-card">
          <Form layout="vertical" onFinish={() => void submit()}>
            <Form.Item label="检索范围">
              <Select
                aria-label="检索范围"
                loading={paperLoading && knowledgeBaseLoading}
                disabled={active}
                value={selectedScope}
                allowClear={selectedScope !== 'all'}
                options={[
                  { label: '全部', options: [{ value: 'all', label: '全部可检索论文' }] },
                  { label: '知识库', options: knowledgeBases.map((base) => ({
                    value: `kb:${base.knowledgeBaseId}`,
                    label: `${base.name} · ${base.searchablePaperCount}/${base.paperCount} 篇可检索`,
                    disabled: base.searchablePaperCount === 0,
                  })) },
                  { label: '单篇论文', options: readyPapers.map((paper) => ({
                    value: `paper:${paper.paperId}`,
                    label: `${paper.title}${paper.pageCount ? ` · ${paper.pageCount} 页` : ''}`,
                  })) },
                ]}
                onChange={(value: string | undefined) => {
                  const nextScope = value ?? 'all';
                  if (controllerRef.current || nextScope === selectedScope) return;
                  setSelectedScope(nextScope);
                  newConversation();
                }}
              />
              {paperError ? (
                <Alert className="field-alert" type="warning" showIcon message={paperError} />
              ) : null}
              {knowledgeBaseError ? (
                <Alert className="field-alert" type="warning" showIcon message={`知识库列表读取失败：${knowledgeBaseError}`} />
              ) : null}
              {selectedKnowledgeBase && selectedKnowledgeBase.searchablePaperCount === 0 ? (
                <Alert className="field-alert" type="info" showIcon message="该知识库当前没有可检索论文。" />
              ) : null}
              {!paperLoading && readyPapers.length === 0 ? (
                <Alert
                  className="field-alert"
                  type="info"
                  showIcon
                  message="当前没有可检索论文；全部论文范围仍可用于普通模型回答。"
                />
              ) : null}
            </Form.Item>
            <Form.Item label="研究问题" required>
              <Input.TextArea
                aria-label="研究问题"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                autoSize={{ minRows: 4, maxRows: 10 }}
                placeholder="例如：论文第二页报告的实验提升是多少？请给出引用。"
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
              <Button onClick={newConversation} disabled={active}>新建会话</Button>
              {active ? (
                <Button danger onClick={stop}>
                  停止生成
                </Button>
              ) : null}
              <Typography.Text type="secondary">
                {selectedPaper ? `限定 paperId：${selectedPaper.paperId}` : selectedKnowledgeBase ? `限定知识库：${selectedKnowledgeBase.name}` : '检索全部可检索论文'}
              </Typography.Text>
            </Flex>
          </Form>
        </Card>

        {turns.length === 0 ? (
          <Empty description="提交问题后，连续问答会显示在这里" />
        ) : turns.map((turn) => (
          <ConversationTurn key={turn.id} question={turn.question} state={turn.state} />
        ))}
      </Space>
    </main>
  );
}
