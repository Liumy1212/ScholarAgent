# Web API contracts

`web-openapi-v1.yaml` 定义 Java BFF 由 React 消费的 Demo API：

```text
GET    /api/v1/library
POST   /api/v1/library/scans
GET    /api/v1/library/scans/{scanId}
GET    /api/v1/library/scans/{scanId}/items
POST   /api/v1/papers
GET    /api/v1/papers
GET    /api/v1/papers/{paperId}
GET    /api/v1/papers/{paperId}/file
POST   /api/v1/papers/{paperId}/exclusion
DELETE /api/v1/papers/{paperId}/exclusion
GET    /api/v1/ingestion-jobs/{jobId}
POST   /api/v1/ingestion-jobs/{jobId}/retry
POST   /api/v1/conversations/{conversationId}/messages/stream
```

浏览器可以传入 `X-Request-Id`；缺失时 Java 必须生成并向 Agent 转发。普通 JSON API 使用 `Result<T>`；PDF 成功/错误、SSE 成功流和 `StreamOpenError` 均不包装。Java 必须保留下游 PDF 的 Range、Content-Range、Content-Length、Content-Type、Accept-Ranges 和 ETag 语义。

创建扫描保持 Agent 的 `202`，活动扫描冲突映射为 `409 LIBRARY_SCAN_ACTIVE`。扫描项支持
`offset`、`limit` 和可选 `outcome`。浏览器不得传入任意本机路径，只能触发配置好的原件库扫描。
