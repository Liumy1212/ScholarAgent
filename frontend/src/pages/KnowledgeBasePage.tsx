import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Flex,
  List,
  Modal,
  Popconfirm,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  deletePaper,
  listPapers,
  paperFileUrl,
  PaperApiError,
  retryIngestionJob,
  uploadPaper,
} from '../api/papers';
import type { IngestionStage, Paper, PaperStatus } from '../api/types';

const MAX_PDF_BYTES = 50 * 1024 * 1024;

const STATUS_VIEW: Record<PaperStatus, { color: string; label: string }> = {
  PROCESSING: { color: 'processing', label: '入库中' },
  READY: { color: 'success', label: '可问答' },
  FAILED: { color: 'error', label: '入库失败' },
};

const STAGE_LABEL: Record<IngestionStage, string> = {
  QUEUED: '等待 Worker',
  PARSING: '解析 PDF',
  CHUNKING: '按页切分',
  EMBEDDING: '生成向量',
  INDEXING: '写入 Qdrant',
  COMPLETED: '入库完成',
  FAILED: '执行失败',
};

const STAGE_PERCENT: Record<IngestionStage, number> = {
  QUEUED: 8,
  PARSING: 25,
  CHUNKING: 45,
  EMBEDDING: 68,
  INDEXING: 88,
  COMPLETED: 100,
  FAILED: 100,
};

function formatBytes(value: number): string {
  if (value < 1024 * 1024) {
    return `${Math.max(1, Math.round(value / 1024))} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function errorMessage(error: unknown): string {
  if (error instanceof PaperApiError) {
    return `${error.message}（${error.code}）`;
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试。';
}

export function KnowledgeBasePage() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [busyPaperId, setBusyPaperId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async (foreground = true) => {
    if (foreground) {
      setLoading(true);
    }
    try {
      const result = await listPapers();
      setPapers(result.items);
      setError(null);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      if (foreground) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActiveIngestion = papers.some(
    (paper) => paper.status === 'PROCESSING',
  );
  useEffect(() => {
    if (!hasActiveIngestion) {
      return undefined;
    }
    const timer = window.setInterval(() => void refresh(false), 1500);
    return () => window.clearInterval(timer);
  }, [hasActiveIngestion, refresh]);

  const readyCount = useMemo(
    () => papers.filter((paper) => paper.status === 'READY').length,
    [papers],
  );

  const selectFile = (file: File | null) => {
    setNotice(null);
    setError(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    if (
      !file.name.toLowerCase().endsWith('.pdf') ||
      file.type !== 'application/pdf'
    ) {
      setSelectedFile(null);
      setError('请选择 Content-Type 为 application/pdf 的 PDF 文件。');
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setSelectedFile(null);
      setError('PDF 不能超过 50 MB。');
      return;
    }
    setSelectedFile(file);
  };

  const submitUpload = async () => {
    if (!selectedFile || uploading) {
      return;
    }
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const result = await uploadPaper(selectedFile);
      setSelectedFile(null);
      setNotice(
        result.duplicate
          ? '检测到相同 SHA-256，已返回知识库中的既有论文。'
          : '上传完成，后台 Worker 正在解析并建立向量索引。',
      );
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setUploading(false);
    }
  };

  const retry = async (paper: Paper) => {
    setBusyJobId(paper.currentIngestion.jobId);
    setError(null);
    try {
      await retryIngestionJob(paper.currentIngestion.jobId);
      setNotice('任务已重新排队。');
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyJobId(null);
    }
  };

  const remove = async (paper: Paper) => {
    setBusyPaperId(paper.paperId);
    setError(null);
    try {
      await deletePaper(paper.paperId);
      if (preview?.paperId === paper.paperId) {
        setPreview(null);
      }
      setNotice('论文、chunk 与向量已删除。');
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyPaperId(null);
    }
  };

  return (
    <main className="page-shell page-shell-wide" aria-labelledby="knowledge-base-title">
      <Space direction="vertical" size={24} className="full-width">
        <div>
          <Tag color="blue">单篇论文 Demo</Tag>
          <Typography.Title id="knowledge-base-title" level={2}>
            论文知识库
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            上传文本型 PDF 后，Worker 会按页解析、生成 BGE-M3 向量并写入 Qdrant。
          </Typography.Paragraph>
        </div>

        <Card className="surface-card" title="上传 PDF">
          <Space direction="vertical" size={16} className="full-width">
            <label className="file-picker">
              <Typography.Text strong>选择单个 PDF</Typography.Text>
              <input
                aria-label="选择单个 PDF"
                type="file"
                accept="application/pdf,.pdf"
                disabled={uploading}
                onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              />
              <Typography.Text type="secondary">
                仅文本型 PDF，最大 50 MB / 500 页
              </Typography.Text>
            </label>
            {selectedFile ? (
              <Flex gap={12} align="center" wrap>
                <Tag color="geekblue">{selectedFile.name}</Tag>
                <Typography.Text type="secondary">
                  {formatBytes(selectedFile.size)}
                </Typography.Text>
                <Button type="primary" loading={uploading} onClick={() => void submitUpload()}>
                  上传并入库
                </Button>
              </Flex>
            ) : null}
            {notice ? <Alert type="success" showIcon message={notice} /> : null}
            {error ? <Alert type="error" showIcon message={error} /> : null}
          </Space>
        </Card>

        <Card
          className="surface-card"
          title={`论文列表（${papers.length}）`}
          extra={
            <Flex gap={10} align="center">
              <Tag color="success">READY {readyCount}</Tag>
              <Button size="small" onClick={() => void refresh()} disabled={loading}>
                刷新
              </Button>
            </Flex>
          }
        >
          {loading ? (
            <div className="center-state">
              <Spin />
              <Typography.Text type="secondary">正在读取知识库…</Typography.Text>
            </div>
          ) : papers.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有论文，请先上传一篇文本型 PDF"
            />
          ) : (
            <List
              dataSource={papers}
              renderItem={(paper) => {
                const view = STATUS_VIEW[paper.status];
                const ingestion = paper.currentIngestion;
                return (
                  <List.Item key={paper.paperId} className="paper-list-item">
                    <article className="paper-item">
                      <Flex justify="space-between" gap={16} wrap="wrap">
                        <div className="paper-main">
                          <Flex gap={8} align="center" wrap>
                            <Tag color={view.color}>{view.label}</Tag>
                            <Typography.Title level={4}>{paper.title}</Typography.Title>
                          </Flex>
                          <Typography.Text type="secondary">
                            {paper.authors.length > 0 ? paper.authors.join('、') : '作者未知'}
                            {paper.publicationYear ? ` · ${paper.publicationYear}` : ''}
                          </Typography.Text>
                          <div className="paper-meta">
                            {paper.fileName} · {formatBytes(paper.fileSizeBytes)} ·{' '}
                            {paper.pageCount ? `${paper.pageCount} 页` : '页数待解析'}
                          </div>
                        </div>
                        <Flex gap={8} align="flex-start" wrap>
                          <Button onClick={() => setPreview(paper)}>预览 PDF</Button>
                          {ingestion.canRetry ? (
                            <Button
                              type="primary"
                              loading={busyJobId === ingestion.jobId}
                              onClick={() => void retry(paper)}
                            >
                              重试入库
                            </Button>
                          ) : null}
                          <Popconfirm
                            title="删除这篇论文？"
                            description="文件、chunk 和 Qdrant 向量都会删除。"
                            okText="删除"
                            cancelText="取消"
                            onConfirm={() => remove(paper)}
                          >
                            <Button danger loading={busyPaperId === paper.paperId}>
                              删除
                            </Button>
                          </Popconfirm>
                        </Flex>
                      </Flex>
                      <div className="ingestion-progress">
                        <Flex justify="space-between" gap={12} wrap>
                          <Typography.Text>
                            当前阶段：{STAGE_LABEL[ingestion.stage]}
                          </Typography.Text>
                          <Typography.Text type="secondary">
                            尝试 {ingestion.attempt}/{ingestion.maxAttempts}
                          </Typography.Text>
                        </Flex>
                        <Progress
                          percent={STAGE_PERCENT[ingestion.stage]}
                          status={paper.status === 'FAILED' ? 'exception' : undefined}
                          showInfo={false}
                          size="small"
                        />
                        {ingestion.failure ? (
                          <Alert
                            className="ingestion-error"
                            type="error"
                            showIcon
                            message={ingestion.failure.message}
                            description={`错误码：${ingestion.failure.code}`}
                          />
                        ) : null}
                      </div>
                    </article>
                  </List.Item>
                );
              }}
            />
          )}
        </Card>
      </Space>

      <Modal
        open={preview !== null}
        title={preview ? `${preview.title} · 原生 PDF 预览` : 'PDF 预览'}
        footer={null}
        width="min(1100px, 94vw)"
        onCancel={() => setPreview(null)}
      >
        {preview ? (
          <iframe
            className="pdf-preview"
            title={`${preview.title} PDF 预览`}
            src={paperFileUrl(preview.paperId, 1)}
          />
        ) : null}
      </Modal>
    </main>
  );
}
