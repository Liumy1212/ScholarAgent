# Agent API contract

`agent-openapi-v1.yaml` 是 Python Agent 由 Java BFF 消费的已接受目标契约。当前本地原件库
相关消费者实现仍在路线图阶段 1.4，不能仅根据本文件判断运行时已经支持相应接口。

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

Java 调用 Agent 时必须传入 `X-Request-Id`。普通 JSON 响应使用直接 DTO；PDF 保留 Range
语义；流式成功和建流前错误分别使用共享 SSE v1 与 `StreamOpenError`。

创建扫描返回 `202`；存在 `QUEUED/RUNNING` 扫描时返回
`409 LIBRARY_SCAN_ACTIVE`。扫描项支持 `offset`、`limit` 和可选 `outcome`。排除接口保留
原件并清理当前 chunk/向量；恢复要求原件可用并创建新的入库任务。
