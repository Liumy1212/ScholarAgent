# Agent API contracts

`agent-openapi-v1.yaml` 定义 Python Agent 由 Java BFF 消费的 Demo API：

```text
GET    /agent-api/v1/library
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

Java 调用 Agent 时每个请求都必须传入 `X-Request-Id`。Agent 普通 JSON 响应使用直接 DTO，不使用 Java `Result<T>`；PDF 保留 Range 语义；流式成功响应和建流前错误分别使用共享 SSE v1 与 `StreamOpenError`。

创建扫描返回 `202`；已有 `QUEUED/RUNNING` 扫描时返回 `409 LIBRARY_SCAN_ACTIVE`。扫描项
支持 `offset`、`limit` 和可选 `outcome`。排除接口保留原件并清理当前 chunk/向量，解除排除
要求原件可用并重新创建入库任务。
