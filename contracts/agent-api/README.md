# Agent API contracts

`agent-openapi-v1.yaml` 定义 Python Agent 由 Java BFF 消费的 Demo API：

```text
POST   /agent-api/v1/papers
GET    /agent-api/v1/papers
GET    /agent-api/v1/papers/{paperId}
GET    /agent-api/v1/papers/{paperId}/file
DELETE /agent-api/v1/papers/{paperId}
GET    /agent-api/v1/ingestion-jobs/{jobId}
POST   /agent-api/v1/ingestion-jobs/{jobId}/retry
POST   /agent-api/v1/conversations/{conversationId}/messages/stream
```

Java 调用 Agent 时每个请求都必须传入 `X-Request-Id`。Agent 普通 JSON 响应使用直接 DTO，不使用 Java `Result<T>`；PDF 保留 Range 语义；流式成功响应和建流前错误分别使用共享 SSE v1 与 `StreamOpenError`。
