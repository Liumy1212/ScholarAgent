import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Flex,
  List,
  Modal,
  Pagination,
  Popconfirm,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  createLibraryScan,
  excludePaper,
  getLibraryInfo,
  getLibraryScan,
  ingestLibraryFile,
  libraryFileUrl,
  listLibraryFiles,
  listLibraryScanItems,
  restorePaper,
  uploadLibraryFile,
} from '../api/library';
import { PaperApiError, retryIngestionJob } from '../api/papers';
import type {
  IngestionStage,
  LibraryFile,
  LibraryFileKnowledgeStatus,
  LibraryInfo,
  LibraryScan,
  LibraryScanItem,
  LibraryScanStatus,
  PaperSourceStatus,
} from '../api/types';

const MAX_PDF_BYTES = 50 * 1024 * 1024;
const PAGE_SIZE = 10;
const SCAN_POLL_INTERVAL_MS = 1200;
const INGESTION_POLL_INTERVAL_MS = 1500;

const KNOWLEDGE_VIEW: Record<
  LibraryFileKnowledgeStatus,
  { color: string; label: string }
> = {
  NOT_INGESTED: { color: 'default', label: '未录入知识库' },
  PROCESSING: { color: 'processing', label: '入库中' },
  READY: { color: 'success', label: '已录入' },
  FAILED: { color: 'error', label: '入库失败' },
  EXCLUDED: { color: 'warning', label: '已移出知识库' },
};

const SOURCE_VIEW: Record<PaperSourceStatus, { color: string; label: string }> = {
  AVAILABLE: { color: 'blue', label: '原件可用' },
  MISSING: { color: 'error', label: '原件缺失' },
  REPLACED: { color: 'warning', label: '原件已替换' },
};

const SCAN_VIEW: Record<LibraryScanStatus, { color: string; label: string }> = {
  QUEUED: { color: 'default', label: '等待扫描' },
  RUNNING: { color: 'processing', label: '扫描中' },
  SUCCEEDED: { color: 'success', label: '扫描完成' },
  FAILED: { color: 'error', label: '扫描失败' },
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

function isActiveScan(scan: LibraryScan | null): boolean {
  return scan?.status === 'QUEUED' || scan?.status === 'RUNNING';
}

function unavailableMessage(status: PaperSourceStatus): string | null {
  if (status === 'MISSING') {
    return '文件夹中已找不到该原件，请恢复文件后重新扫描。';
  }
  if (status === 'REPLACED') {
    return '同一路径的内容已经变化，请重新扫描并使用新登记的原件。';
  }
  return null;
}

export function KnowledgeBasePage() {
  const [library, setLibrary] = useState<LibraryInfo | null>(null);
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<LibraryFile | null>(null);
  const [latestScan, setLatestScan] = useState<LibraryScan | null>(null);
  const [scanItems, setScanItems] = useState<LibraryScanItem[]>([]);
  const [scanItemsOpen, setScanItemsOpen] = useState(false);
  const [scanItemsLoading, setScanItemsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [creatingScan, setCreatingScan] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(
    async (foreground = true) => {
      if (foreground) {
        setLoading(true);
      }
      try {
        const [info, page] = await Promise.all([
          getLibraryInfo(),
          listLibraryFiles(offset, PAGE_SIZE),
        ]);
        setLibrary(info);
        setLatestScan(info.latestScan);
        setFiles(page.items);
        setTotal(page.total);
        setError(null);
      } catch (requestError) {
        setError(errorMessage(requestError));
      } finally {
        if (foreground) {
          setLoading(false);
        }
      }
    },
    [offset],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActiveIngestion = files.some(
    (file) => file.knowledgeStatus === 'PROCESSING',
  );
  useEffect(() => {
    if (!hasActiveIngestion) {
      return undefined;
    }
    const timer = window.setInterval(
      () => void refresh(false),
      INGESTION_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [hasActiveIngestion, refresh]);

  useEffect(() => {
    if (latestScan === null || !isActiveScan(latestScan)) {
      return undefined;
    }
    const scanId = latestScan.scanId;
    const timer = window.setInterval(() => {
      void getLibraryScan(scanId)
        .then(async (scan) => {
          setLatestScan(scan);
          if (!isActiveScan(scan)) {
            setNotice(
              scan.status === 'SUCCEEDED'
                ? `扫描完成：新增登记 ${scan.registeredCount}，失败 ${scan.failedCount}。`
                : '原件库扫描失败，请查看最近扫描结果。',
            );
            await refresh(false);
          }
        })
        .catch((requestError: unknown) => setError(errorMessage(requestError)));
    }, SCAN_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [latestScan, refresh]);

  const counts = useMemo(() => {
    const ready = files.filter((file) => file.searchable).length;
    const notIngested = files.filter(
      (file) => file.knowledgeStatus === 'NOT_INGESTED',
    ).length;
    return { ready, notIngested };
  }, [files]);

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

  const refreshFromFirstPage = async () => {
    if (offset === 0) {
      await refresh(false);
    } else {
      setOffset(0);
    }
  };

  const submitUpload = async () => {
    if (!selectedFile || uploading) {
      return;
    }
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const result = await uploadLibraryFile(selectedFile);
      setSelectedFile(null);
      setNotice(
        result.duplicate
          ? '相同 SHA-256 的原件已经登记，没有重复保存或自动入库。'
          : '原件已保存，但尚未录入知识库。请在清单中手动确认入库。',
      );
      await refreshFromFirstPage();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setUploading(false);
    }
  };

  const startScan = async () => {
    setCreatingScan(true);
    setError(null);
    setNotice(null);
    try {
      const scan = await createLibraryScan();
      setLatestScan(scan);
      setLibrary((current) =>
        current ? { ...current, scanInProgress: true, latestScan: scan } : current,
      );
      setNotice('扫描任务已创建；扫描只登记原件，不会自动录入知识库。');
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setCreatingScan(false);
    }
  };

  const ingest = async (file: LibraryFile) => {
    const action = `ingest:${file.libraryFileId}`;
    setBusyAction(action);
    setError(null);
    try {
      const result = await ingestLibraryFile(file.libraryFileId);
      setNotice(
        result.duplicate
          ? '已复用相同内容的既有论文和索引。'
          : '已创建后台入库任务。',
      );
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction(null);
    }
  };

  const retry = async (file: LibraryFile) => {
    if (!file.currentIngestion) {
      return;
    }
    const action = `retry:${file.libraryFileId}`;
    setBusyAction(action);
    setError(null);
    try {
      await retryIngestionJob(file.currentIngestion.jobId);
      setNotice('入库任务已重新排队。');
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction(null);
    }
  };

  const exclude = async (file: LibraryFile) => {
    if (!file.paperId) {
      return;
    }
    const action = `exclude:${file.libraryFileId}`;
    setBusyAction(action);
    setError(null);
    try {
      await excludePaper(file.paperId);
      setNotice('论文已移出知识库；本地原件仍然保留。');
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction(null);
    }
  };

  const restore = async (file: LibraryFile) => {
    if (!file.paperId) {
      return;
    }
    const action = `restore:${file.libraryFileId}`;
    setBusyAction(action);
    setError(null);
    try {
      await restorePaper(file.paperId);
      setNotice('论文已恢复，并创建新的后台入库任务。');
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction(null);
    }
  };

  const showFailedItems = async (scan: LibraryScan) => {
    setScanItemsOpen(true);
    setScanItemsLoading(true);
    try {
      const page = await listLibraryScanItems(scan.scanId, 0, 200, 'FAILED');
      setScanItems(page.items);
    } catch (requestError) {
      setError(errorMessage(requestError));
      setScanItemsOpen(false);
    } finally {
      setScanItemsLoading(false);
    }
  };

  const renderActions = (file: LibraryFile) => {
    if (file.sourceStatus !== 'AVAILABLE') {
      return <Button disabled>请重新扫描</Button>;
    }
    switch (file.knowledgeStatus) {
      case 'NOT_INGESTED':
        return (
          <Button
            type="primary"
            loading={busyAction === `ingest:${file.libraryFileId}`}
            onClick={() => void ingest(file)}
          >
            录入知识库
          </Button>
        );
      case 'PROCESSING':
        return <Button disabled>正在入库</Button>;
      case 'FAILED':
        return (
          <>
            <Button
              type="primary"
              disabled={!file.currentIngestion?.canRetry}
              loading={busyAction === `retry:${file.libraryFileId}`}
              onClick={() => void retry(file)}
            >
              {file.currentIngestion?.canRetry ? '重试入库' : '无法重试'}
            </Button>
            <Popconfirm
              title="将论文移出知识库？"
              description="本地原件会保留，chunk 与向量将被清理。"
              okText="移出"
              cancelText="取消"
              onConfirm={() => exclude(file)}
            >
              <Button danger loading={busyAction === `exclude:${file.libraryFileId}`}>
                移出知识库
              </Button>
            </Popconfirm>
          </>
        );
      case 'READY':
        return (
          <>
            <Button onClick={() => setPreview(file)}>预览 PDF</Button>
            <Popconfirm
              title="将论文移出知识库？"
              description="本地原件会保留，chunk 与向量将被清理。"
              okText="移出"
              cancelText="取消"
              onConfirm={() => exclude(file)}
            >
              <Button danger loading={busyAction === `exclude:${file.libraryFileId}`}>
                移出知识库
              </Button>
            </Popconfirm>
          </>
        );
      case 'EXCLUDED':
        return (
          <>
            <Button onClick={() => setPreview(file)}>预览 PDF</Button>
            <Button
              type="primary"
              loading={busyAction === `restore:${file.libraryFileId}`}
              onClick={() => void restore(file)}
            >
              重新录入
            </Button>
          </>
        );
    }
  };

  const scan = latestScan ?? library?.latestScan ?? null;
  const scanActive = isActiveScan(scan) || library?.scanInProgress === true;

  return (
    <main className="page-shell page-shell-wide" aria-labelledby="knowledge-base-title">
      <Space direction="vertical" size={24} className="full-width">
        <div>
          <Tag color="blue">本地论文原件库</Tag>
          <Typography.Title id="knowledge-base-title" level={2}>
            论文知识库
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            原件登记与知识库入库彼此独立；只有你手动确认后，Worker 才会解析并建立向量索引。
          </Typography.Paragraph>
        </div>

        <Card
          className="surface-card"
          title="原件库与目录扫描"
          extra={
            <Button
              type="primary"
              loading={creatingScan || scanActive}
              disabled={scanActive}
              onClick={() => void startScan()}
            >
              {scanActive ? '扫描进行中' : '手动扫描'}
            </Button>
          }
        >
          <Space direction="vertical" size={14} className="full-width">
            <div className="library-location">
              <Typography.Text type="secondary">原件库路径</Typography.Text>
              <Typography.Text
                code
                copyable={library?.rootPath ? { text: library.rootPath } : false}
              >
                {library?.rootPath ?? '正在读取…'}
              </Typography.Text>
            </div>
            <Flex gap={8} align="center" wrap>
              <Typography.Text type="secondary">支持格式</Typography.Text>
              {(library?.supportedExtensions ?? ['.pdf']).map((extension) => (
                <Tag key={extension}>{extension}</Tag>
              ))}
            </Flex>
            {scan ? (
              <div className="scan-summary">
                <Flex gap={8} align="center" wrap>
                  <Tag color={SCAN_VIEW[scan.status].color}>{SCAN_VIEW[scan.status].label}</Tag>
                  <Typography.Text>最近扫描：{scan.scanId}</Typography.Text>
                </Flex>
                <Typography.Text type="secondary">
                  发现 {scan.discoveredCount} · 新增 {scan.registeredCount} · 未变化/移动{' '}
                  {scan.unchangedCount} · 重复 {scan.duplicateCount} · 跳过 {scan.skippedCount} ·
                  失败 {scan.failedCount}
                </Typography.Text>
                {scan.failedCount > 0 ? (
                  <Button size="small" danger onClick={() => void showFailedItems(scan)}>
                    查看失败扫描项
                  </Button>
                ) : null}
                {scan.failure ? (
                  <Alert
                    type="error"
                    showIcon
                    message={scan.failure.message}
                    description={`错误码：${scan.failure.code}`}
                  />
                ) : null}
              </div>
            ) : (
              <Typography.Text type="secondary">尚未执行目录扫描。</Typography.Text>
            )}
          </Space>
        </Card>

        <Card className="surface-card" title="上传 PDF 原件">
          <Space direction="vertical" size={16} className="full-width">
            <Alert type="info" showIcon message="上传只保存原件，不会自动录入知识库。" />
            <label className="file-picker">
              <Typography.Text strong>选择单个 PDF</Typography.Text>
              <input
                aria-label="选择单个 PDF"
                type="file"
                accept="application/pdf,.pdf"
                disabled={uploading}
                onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              />
              <Typography.Text type="secondary">仅 PDF，最大 50 MB</Typography.Text>
            </label>
            {selectedFile ? (
              <Flex gap={12} align="center" wrap>
                <Tag color="geekblue">{selectedFile.name}</Tag>
                <Typography.Text type="secondary">
                  {formatBytes(selectedFile.size)}
                </Typography.Text>
                <Button type="primary" loading={uploading} onClick={() => void submitUpload()}>
                  仅保存原件
                </Button>
              </Flex>
            ) : null}
            {notice ? <Alert type="success" showIcon message={notice} /> : null}
            {error ? <Alert type="error" showIcon message={error} /> : null}
          </Space>
        </Card>

        <Card
          className="surface-card"
          title={`统一原件清单（${total}）`}
          extra={
            <Flex gap={8} align="center" wrap>
              <Tag color="default">本页未入库 {counts.notIngested}</Tag>
              <Tag color="success">本页可检索 {counts.ready}</Tag>
              <Button size="small" onClick={() => void refresh()} disabled={loading}>
                刷新
              </Button>
            </Flex>
          }
        >
          {loading ? (
            <div className="center-state">
              <Spin />
              <Typography.Text type="secondary">正在读取原件库…</Typography.Text>
            </div>
          ) : files.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有登记原件；可上传 PDF 或扫描 originals 目录"
            />
          ) : (
            <>
              <List
                dataSource={files}
                renderItem={(file) => {
                  const sourceView = SOURCE_VIEW[file.sourceStatus];
                  const knowledgeView = KNOWLEDGE_VIEW[file.knowledgeStatus];
                  const ingestion = file.currentIngestion;
                  const unavailable = unavailableMessage(file.sourceStatus);
                  return (
                    <List.Item key={file.libraryFileId} className="paper-list-item">
                      <article className="paper-item">
                        <Flex justify="space-between" gap={16} wrap="wrap">
                          <div className="paper-main">
                            <Flex gap={8} align="center" wrap>
                              <Tag color={sourceView.color}>{sourceView.label}</Tag>
                              <Tag color={knowledgeView.color}>{knowledgeView.label}</Tag>
                              {file.searchable ? <Tag color="success">可检索</Tag> : null}
                              <Typography.Title level={4}>
                                {file.paperTitle ?? file.fileName}
                              </Typography.Title>
                            </Flex>
                            <div className="paper-meta">
                              路径：{file.relativePath} · {formatBytes(file.fileSizeBytes)}
                            </div>
                            <div className="paper-meta">SHA-256：{file.sha256}</div>
                            {file.paperId ? (
                              <div className="paper-meta">Paper ID：{file.paperId}</div>
                            ) : null}
                          </div>
                          <Flex gap={8} align="flex-start" wrap>
                            {renderActions(file)}
                          </Flex>
                        </Flex>
                        {unavailable ? (
                          <Alert
                            className="ingestion-progress"
                            type="warning"
                            showIcon
                            message={unavailable}
                          />
                        ) : ingestion ? (
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
                              status={file.knowledgeStatus === 'FAILED' ? 'exception' : undefined}
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
                        ) : (
                          <Typography.Paragraph className="not-ingested-note" type="secondary">
                            该原件尚未创建 Paper、入库任务或向量。
                          </Typography.Paragraph>
                        )}
                      </article>
                    </List.Item>
                  );
                }}
              />
              <Flex justify="flex-end" className="library-pagination">
                <Pagination
                  current={Math.floor(offset / PAGE_SIZE) + 1}
                  pageSize={PAGE_SIZE}
                  total={total}
                  hideOnSinglePage
                  showSizeChanger={false}
                  onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
                />
              </Flex>
            </>
          )}
        </Card>
      </Space>

      <Modal
        open={preview !== null}
        title={preview ? `${preview.fileName} · 原件 PDF 预览` : 'PDF 预览'}
        footer={null}
        width="min(1100px, 94vw)"
        onCancel={() => setPreview(null)}
      >
        {preview ? (
          <iframe
            className="pdf-preview"
            title={`${preview.fileName} PDF 预览`}
            src={libraryFileUrl(preview.libraryFileId, 1)}
          />
        ) : null}
      </Modal>

      <Modal
        open={scanItemsOpen}
        title="失败扫描项"
        footer={null}
        onCancel={() => setScanItemsOpen(false)}
      >
        {scanItemsLoading ? (
          <div className="center-state">
            <Spin />
          </div>
        ) : scanItems.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有失败扫描项" />
        ) : (
          <List
            dataSource={scanItems}
            renderItem={(item) => (
              <List.Item key={`${item.relativePath}:${item.code ?? 'FAILED'}`}>
                <List.Item.Meta
                  title={item.relativePath}
                  description={`${item.message ?? '扫描失败'}${item.code ? `（${item.code}）` : ''}`}
                />
              </List.Item>
            )}
          />
        )}
      </Modal>
    </main>
  );
}
