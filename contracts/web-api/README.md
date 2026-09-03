# Web API contract

`web-openapi-v1.yaml` 是 Java BFF 由 React 消费的已接受目标契约。阶段 1.4 的本地原件库
基线已由 Java 和 React 接入并通过合成 PDF 全栈冒烟；`libraryState`、`originalsPath`、
知识删除和上传 MIME 语义已经由 Java 与 React 消费，并通过模块测试及本轮全栈验收。

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
DELETE /api/v1/papers/{paperId}
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

`GET /library/files` 可选 `libraryState`，枚举和筛选分页语义与 Agent 契约完全一致；Java
只能校验并原样转发。`LibraryInfo.originalsPath` 必须透传扫描器实际遍历目录。
`DELETE /papers/{paperId}` 只删除知识、任务、chunk 和向量，保留所有仍存在的 PDF；
`404 PAPER_NOT_FOUND` 与 `409 PAPER_BUSY` 保持下游状态和 code，Agent 的 Qdrant/数据库
`503` 映射为 Web `502 AGENT_UNAVAILABLE`，协议错误和超时分别映射为 `502 AGENT_ERROR`
与 `504 AGENT_TIMEOUT`。上传接受 PDF、octet-stream 或未提供 MIME，但仍校验 `.pdf`、
50 MB 上限和 `%PDF-` 签名。exclusion/restore 继续作为兼容接口保留。
