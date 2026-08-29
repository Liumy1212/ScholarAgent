# Contracts

AIResearcher 的 Agent API、浏览器 Web API 和 SSE 共享机器可读契约。

契约采用 contract-first：它们可以先于 Python、Java 和 React 实现被接受。当前契约已经
定义本地论文原件库扫描与排除/恢复，但三端消费者仍使用现有单 PDF 上传/删除流程。实现状态
以 [路线图阶段 1.4](../docs/roadmap.md)为准，契约存在不等于功能已经上线。

## 目录结构

| 路径 | 使用关系 |
| --- | --- |
| `agent-api/agent-openapi-v1.yaml` | Python 实现，Java 消费 |
| `web-api/web-openapi-v1.yaml` | Java 实现，React 消费 |
| `sse/v1/` | 三端共享的 SSE v1 Schema、规则和夹具 |
| `validation/` | OpenAPI、JSON Schema、示例和跨事件语义校验 |

Agent API 使用 `/agent-api/v1/**`，浏览器 Web API 使用 `/api/v1/**`。Java 普通 JSON
响应使用 `Result<T>`，Agent 使用直接 DTO；PDF、SSE 和健康检查保持各自协议语义。

## 校验

要求 Node.js 20 或更高版本。依赖只安装到本目录：

```powershell
npm ci
npm run validate
```

校验覆盖两份 OpenAPI、JSON Schema、有效/无效事件、完整成功/失败流、DTO 对应关系、
分页与冲突语义，以及 `Result<T>`、PDF Range 和 SSE 边界。

修改前阅读 [Contract instructions](AGENTS.md)。
