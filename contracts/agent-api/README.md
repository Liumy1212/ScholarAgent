# Agent API contract

`agent-openapi-v1.yaml` 是 Python Agent 由 Java BFF 消费的已接受契约。阶段 1.4 的本地
原件库基线已接入；`libraryState`、`originalsPath`、知识删除和上传 MIME 语义已经由
Agent 与 Java 消费，并通过模块测试及合成 PDF 全栈验收。

```text
GET    /agent-api/v1/library
GET    /agent-api/v1/library/files
POST   /agent-api/v1/library/files
GET    /agent-api/v1/library/files/{libraryFileId}/file
POST   /agent-api/v1/library/files/{libraryFileId}/ingestion
POST   /agent-api/v1/library/scans
GET    /agent-api/v1/library/scans/{scanId}
GET    /agent-api/v1/library/scans/{scanId}/items
POST   /agent-api/v1/papers
GET    /agent-api/v1/papers
GET    /agent-api/v1/papers/{paperId}
DELETE /agent-api/v1/papers/{paperId}
GET    /agent-api/v1/papers/{paperId}/file
POST   /agent-api/v1/papers/{paperId}/exclusion
DELETE /agent-api/v1/papers/{paperId}/exclusion
GET    /agent-api/v1/ingestion-jobs/{jobId}
POST   /agent-api/v1/ingestion-jobs/{jobId}/retry
POST   /agent-api/v1/conversations/{conversationId}/messages/stream
```

Java 调用 Agent 时必须传入 `X-Request-Id`。普通 JSON 响应使用直接 DTO；PDF 保留 Range
语义；流式成功和建流前错误分别使用共享 SSE v1 与 `StreamOpenError`。

创建扫描返回 `202`；存在 `QUEUED/RUNNING` 扫描时返回
`409 LIBRARY_SCAN_ACTIVE`。扫描项支持 `offset`、`limit` 和可选 `outcome`。扫描与原件上传
只登记 `LibraryFile`，不会创建 `Paper`、入库任务或向量；用户必须显式调用原件的
`ingestion` 接口。排除接口保留原件并清理当前 chunk/向量；恢复要求原件可用并创建新的
入库任务。兼容性 `POST /papers` 暂时保留并标记为 deprecated。

`GET /library/files` 可选 `libraryState`：`ORIGINAL_MISSING` 表示有关联知识但原件为
`MISSING/REPLACED`，`NOT_INGESTED` 表示原件可用但当前不可检索，`INGESTED` 表示原件
可用且论文 `READY`、`searchable=true`；筛选必须先于分页并同时决定 `items` 与 `total`。
`LibraryInfo.originalsPath` 是扫描器实际遍历目录。`DELETE /papers/{paperId}` 只删除 Paper、
任务、chunk 和向量，保留所有仍存在的 PDF；活动任务返回 `409 PAPER_BUSY`，Qdrant 或
数据库不可用返回可重试的 `503`。上传接受 `application/pdf`、
`application/octet-stream` 或未提供 MIME，但仍要求 `.pdf`、50 MB 上限和 `%PDF-` 签名。
