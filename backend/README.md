# Backend

AIResearcher 的 Java Web Backend/BFF 目录。

## 职责

- 对 React 提供 `/api/v1/**` REST 与 SSE 接口。
- 处理请求校验、统一响应、错误映射、请求追踪与 Agent DTO 转换。
- 通过 AgentClient 调用 Python，不承担 PDF、RAG、Prompt 或模型逻辑。

## 当前状态

Demo Backend/BFF 采用 Java 21、Spring Boot 4、Spring MVC、WebClient、JDK HttpClient 和 Maven Wrapper。当前提供：

- `ChatController -> ChatService -> AgentSseClient` 流式问答链路。
- `PaperController -> AgentPaperClient/AgentFileClient` 上传、列表、详情、任务、重试、删除和 PDF 代理链路。
- `Result<T>`、`PageResult<T>`、`ResultCode` 与全局异常处理。
- `X-Request-Id` 接收、生成、响应和下游转发。
- Agent 建流错误映射、SSE 事件代理、建流后 `run.failed` 终止和浏览器断开取消。
- PDF 成功与错误均不使用 `Result<T>`；Range、Content-Range、Content-Length、Content-Type、Accept-Ranges 和 ETag 会保留。

本模块不包含数据库、Mapper、RAG、Prompt 或模型逻辑。

## 本地验证

只使用仓库内 Maven Wrapper，不需要安装全局 Maven：

```powershell
.\mvnw.cmd verify
```

若受限环境无法访问默认 Maven 缓存：

```powershell
.\mvnw.cmd "-Dmaven.repo.local=C:\Users\your-name\.m2\repository" verify
```

在 macOS 或 Linux 使用：

```bash
./mvnw verify
```

默认 Agent 地址为 `http://localhost:8000`。可以使用以下环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AIRESEARCHER_AGENT_BASE_URL` | `http://localhost:8000` | Agent 服务根地址 |
| `AIRESEARCHER_AGENT_CONNECT_TIMEOUT` | `2s` | 下游连接超时 |
| `AIRESEARCHER_AGENT_OPEN_TIMEOUT` | `5s` | 等待 Agent 建流超时 |
| `AIRESEARCHER_SSE_EMITTER_TIMEOUT` | `0ms` | 浏览器 SSE 超时，`0ms` 表示不设置超时 |

启动 Java BFF（默认端口 8080）：

```powershell
.\mvnw.cmd spring-boot:run
```

Web API 入口为：

```text
POST   /api/v1/papers
GET    /api/v1/papers
GET    /api/v1/papers/{paperId}
GET    /api/v1/papers/{paperId}/file
DELETE /api/v1/papers/{paperId}
GET    /api/v1/ingestion-jobs/{jobId}
POST   /api/v1/ingestion-jobs/{jobId}/retry
POST /api/v1/conversations/{conversationId}/messages/stream
```

开始修改前请阅读本目录的 `AGENTS.md` 与 [总体架构](../docs/architecture.md)。
