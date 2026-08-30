# Web API contract

`web-openapi-v1.yaml` 是 Java BFF 由 React 消费的已接受目标契约。Java 已实现本地原件库
相关接口，React 已消费这些接口，并已通过合成 PDF 全栈冒烟。完成状态与后续范围以
[路线图阶段 1.4](../../docs/roadmap.md)为准。

```text
GET    /api/v1/library
GET    /api/v1/library/files
POST   /api/v1/library/files
GET    /api/v1/library/files/{libraryFileId}/file
POST   /api/v1/library/files/{libraryFileId}/ingestion
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

浏览器可以传入 `X-Request-Id`；缺失时 Java 必须生成并向 Agent 转发。普通 JSON API 使用
`Result<T>`；PDF、SSE 和 `StreamOpenError` 不包装。Java 必须保留下游 PDF 的 Range、
`Content-Range`、`Content-Length`、`Content-Type`、`Accept-Ranges` 和 `ETag`。

创建扫描保持 Agent 的 `202`，活动扫描冲突映射为
`409 LIBRARY_SCAN_ACTIVE`。浏览器不得传入任意本机路径，只能触发配置好的原件库扫描。
原件上传和扫描只登记 `LibraryFile`；浏览器需要逐篇调用 `ingestion` 才会进入知识库。
兼容性 `POST /papers` 暂时保留并标记为 deprecated，新页面不应继续调用。
