# Web API contracts

`web-openapi-v1.yaml` 定义 Java BFF 由 React 消费的 Phase 0 API：

```text
POST /api/v1/conversations/{conversationId}/messages/stream
```

浏览器可以传入 `X-Request-Id`；缺失时 Java 必须生成并向 Agent 转发。成功响应使用共享 SSE v1 契约；建流前非 2xx 响应使用共享 `StreamOpenError`，两者都不使用普通 JSON API 的 `Result<T>`。
