# Agent API contract

`agent-openapi-v1.yaml` 是 Python Agent 由 Java BFF 消费的已接受契约。本地原件库相关
Agent 与 Java 实现已接入；浏览器页面状态仍以路线图阶段 1.4 为准。

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
