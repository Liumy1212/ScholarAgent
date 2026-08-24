# Agent API contracts

`agent-openapi-v1.yaml` 定义 Python Agent 由 Java BFF 消费的 Phase 0 API：

```text
POST /agent-api/v1/conversations/{conversationId}/messages/stream
```

Java 调用 Agent 时必须传入 `X-Request-Id`。成功响应使用共享 SSE v1 契约；建流前非 2xx 响应使用共享 `StreamOpenError`，两者都不使用 Java `Result<T>`。
