import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
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
  getLibraryInfo,
  getLibraryScan,
  ingestLibraryFile,
  libraryFileUrl,
  listLibraryFiles,
  listLibraryScanItems,
  uploadLibraryFile,
} from '../api/library';
import { deletePaper, PaperApiError, retryIngestionJob } from '../api/papers';
import type {
  IngestionStage,
  LibraryFile,
  LibraryFileKnowledgeStatus,
  LibraryFileUploadData,
  LibraryInfo,
  LibraryScan,
  LibraryScanItem,
  LibraryScanStatus,
  LibraryStateFilter,
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
  NOT_INGESTED: { color: 'default', label: '未存入知识库' },
  PROCESSING: { color: 'processing', label: '入库中' },
  READY: { color: 'success', label: '已存入知识库' },
  FAILED: { color: 'error', label: '入库失败' },
  EXCLUDED: { color: 'warning', label: '兼容排除状态' },
};

const LIBRARY_FILTERS: ReadonlyArray<{
  label: string;
  value: LibraryStateFilter | null;
}> = [
  { label: '全部', value: null },
  { label: '原件缺失', value: 'ORIGINAL_MISSING' },
  { label: '未存入知识库', value: 'NOT_INGESTED' },
  { label: '已存入知识库', value: 'INGESTED' },
];

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

function hasActiveIngestionJob(file: LibraryFile): boolean {
  return (
    file.currentIngestion?.status === 'QUEUED' ||
    file.currentIngestion?.status === 'RUNNING'
  );
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
  const [libraryState, setLibraryState] = useState<LibraryStateFilter | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<LibraryFileUploadData | null>(null);
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
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(
    async (
      foreground = true,
      requestedOffset = offset,
      requestedState = libraryState,
    ) => {
      if (foreground) {
        setLoading(true);
      }
      try {
        const [info, page] = await Promise.all([
          getLibraryInfo(),
          listLibraryFiles(requestedOffset, PAGE_SIZE, requestedState ?? undefined),
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
    [libraryState, offset],
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
    setUploadResult(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const acceptedMime =
      file.type === '' ||
      file.type === 'application/pdf' ||
      file.type === 'application/octet-stream';
    if (!file.name.toLowerCase().endsWith('.pdf') || !acceptedMime) {
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      setError('请选择扩展名为 .pdf 的 PDF 文件。');
      return;
    }
    if (file.size === 0) {
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      setError('PDF 文件不能为空。');
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
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
      const result = await uploadLibraryFile(selectedFile);
      setSelectedFile(null);
      setUploadResult(result);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      setLibraryState(null);
      setOffset(0);
      setFiles((current) => [
        result.libraryFile,
        ...current.filter(
          (file) => file.libraryFileId !== result.libraryFile.libraryFileId,
        ),
      ].slice(0, PAGE_SIZE));
      setTotal((current) => (result.duplicate ? Math.max(current, 1) : current + 1));
      await refresh(false, 0, null);
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
      setNotice('扫描任务已创建；扫描只登记原件，不会自动存入知识库。');
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

  const deleteKnowledge = async (file: LibraryFile) => {
    if (!file.paperId) {
      return;
    }
    const action = `delete:${file.libraryFileId}`;
    setBusyAction(action);
    setError(null);
    try {
      await deletePaper(file.paperId);
      const originalAvailable = file.sourceStatus === 'AVAILABLE';
      const remainsInCurrentFilter =
        originalAvailable &&
        (libraryState === null || libraryState === 'NOT_INGESTED');
      const unIngested: LibraryFile = {
        ...file,
        knowledgeStatus: 'NOT_INGESTED',
        paperId: null,
        paperTitle: null,
        searchable: false,
        currentIngestion: null,
      };
      setFiles((current) =>
        current.flatMap((item) => {
          if (item.libraryFileId !== file.libraryFileId) {
            return [item];
          }
          return remainsInCurrentFilter ? [unIngested] : [];
        }),
      );
      if (!remainsInCurrentFilter) {
        setTotal((current) => Math.max(0, current - 1));
      }
      if (preview?.libraryFileId === file.libraryFileId) {
        setPreview(null);
      }
      setNotice(
        originalAvailable
          ? '知识、任务、chunk 和向量已删除；PDF 原件仍保留，当前为未存入知识库。'
          : '知识、任务、chunk 和向量已删除；缺失原件登记已清理。',
      );
      await refresh(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction(null);
    }
  };

  const changeLibraryState = (state: LibraryStateFilter | null) => {
    setLibraryState(state);
    setOffset(0);
    setError(null);
    setNotice(null);
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
    const activeIngestion = hasActiveIngestionJob(file);
    let primaryAction: ReactNode = null;
    if (file.sourceStatus === 'AVAILABLE') {
      switch (file.knowledgeStatus) {
        case 'NOT_INGESTED':
          primaryAction = (
            <Button
              type="primary"
              loading={busyAction === `ingest:${file.libraryFileId}`}
              onClick={() => void ingest(file)}
            >
              存入知识库
            </Button>
          );
          break;
        case 'PROCESSING':
          primaryAction = <Button disabled>正在存入知识库</Button>;
          break;
        case 'FAILED':
          primaryAction = (
            <Button
              type="primary"
              disabled={!file.currentIngestion?.canRetry}
              loading={busyAction === `retry:${file.libraryFileId}`}
              onClick={() => void retry(file)}
            >
              {file.currentIngestion?.canRetry ? '重试入库' : '无法重试'}
            </Button>
          );
          break;
        case 'READY':
          primaryAction = (
            <Button onClick={() => setPreview(file)}>预览 PDF</Button>
          );
          break;
        case 'EXCLUDED':
          primaryAction = <Button disabled>请先删除旧知识</Button>;
          break;
      }
    }

    const deleteDisabled = file.paperId === null || activeIngestion;
    const deleteButton = (
      <Button
        danger
        disabled={deleteDisabled}
        title={
          file.paperId === null
            ? '暂无知识可删'
            : activeIngestion
              ? '入库进行中，暂不能删除知识'
              : undefined
        }
        loading={busyAction === `delete:${file.libraryFileId}`}
      >
        删除知识
      </Button>
    );

    return (
      <>
        {primaryAction}
        {deleteDisabled ? (
          deleteButton
        ) : (
          <Popconfirm
            title="删除该论文的知识库内容？"
            description="只清理知识、任务、chunk 和向量，不会删除 PDF 原件。"
            okText="确认删除知识"
            cancelText="取消"
            onConfirm={() => deleteKnowledge(file)}
          >
            {deleteButton}
          </Popconfirm>
        )}
      </>
    );
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
              {scanActive ? '扫描进行中' : '扫描文件夹'}
            </Button>
          }
        >
          <Space direction="vertical" size={14} className="full-width">
            <div className="library-location">
              <Typography.Text type="secondary">实际扫描目录</Typography.Text>
              <Typography.Text
                code
                copyable={
                  library?.originalsPath ? { text: library.originalsPath } : false
                }
              >
                {library?.originalsPath ?? '正在读取…'}
              </Typography.Text>
              <Typography.Text type="secondary">
                可将 PDF 直接放入该目录或任意子目录；扫描只登记和同步状态，不会自动存入知识库。
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
            <Alert type="info" showIcon message="上传只保存原件，不会自动存入知识库。" />
            <label className="file-picker">
              <Typography.Text strong>选择单个 PDF</Typography.Text>
              <input
                ref={fileInputRef}
                aria-label="选择单个 PDF"
                type="file"
                accept=".pdf,application/pdf,application/octet-stream"
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
              </Flex>
            ) : null}
            <Button
              type="primary"
              loading={uploading}
              disabled={selectedFile === null || uploading}
              onClick={() => void submitUpload()}
            >
              提交 PDF
            </Button>
            {uploadResult ? (
              <Alert
                type="success"
                showIcon
                message="原件已保存"
                description={
                  <Space direction="vertical" size={2}>
                    <Typography.Text>
                      保存路径：{uploadResult.libraryFile.relativePath}
                    </Typography.Text>
                    <Typography.Text>
                      {uploadResult.duplicate
                        ? '相同内容的原件已登记；尚未自动存入知识库。'
                        : '尚未存入知识库，请在下方列表中手动操作。'}
                    </Typography.Text>
                  </Space>
                }
              />
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
          <div className="library-filters" aria-label="论文列表筛选">
            {LIBRARY_FILTERS.map((filter) => (
              <Button
                key={filter.label}
                type={libraryState === filter.value ? 'primary' : 'default'}
                aria-pressed={libraryState === filter.value}
                onClick={() => changeLibraryState(filter.value)}
              >
                {filter.label}
              </Button>
            ))}
          </div>
          {loading ? (
            <div className="center-state">
              <Spin />
              <Typography.Text type="secondary">正在读取原件库…</Typography.Text>
            </div>
          ) : files.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                libraryState === null
                  ? '还没有登记原件；可上传 PDF 或扫描 originals 目录'
                  : '当前筛选条件下没有论文原件'
              }
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
