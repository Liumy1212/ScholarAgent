# Contracts

AIResearcher 单篇论文 Demo 三端共享的机器可读接口契约。

| 路径 | 使用关系 |
| --- | --- |
| `agent-api/agent-openapi-v1.yaml` | Python 实现，Java 消费 |
| `web-api/web-openapi-v1.yaml` | Java 实现，React 消费 |
| `sse/v1/` | Java、Python、React 共享的 SSE v1 Schema、规则与夹具 |
| `validation/` | OpenAPI、JSON Schema、示例和跨事件语义校验 |

## 校验

要求 Node.js 20 或更高版本。依赖只安装到本目录，不需要或允许全局安装：

```powershell
cd contracts
npm ci
npm run validate
```

`npm run validate` 会校验两个 OpenAPI 文档、论文与入库任务路径、REST DTO 跨 BFF 一致性、`Result<T>`/PDF/SSE 边界、Range 响应头、全部 `*.schema.json`、每种事件的合法示例、`StreamOpenError` 示例、完整成功/失败 SSE 流，并确认非法事件和非法流确实被拒绝。

所有修改必须遵守本目录的 `AGENTS.md`。
