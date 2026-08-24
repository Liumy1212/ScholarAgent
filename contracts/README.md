# Contracts

AIResearcher 三端共享的机器可读接口契约。

| 目录 | 使用关系 |
| --- | --- |
| `agent-api/` | Python 实现，Java 消费 |
| `web-api/` | Java 实现，React 消费 |

当前仅保留目录边界，尚未创建 OpenAPI 或 SSE Schema。契约必须由独立 Chat 先行定义并合入，依赖它的三端任务再基于更新后的 `main` 开始。

所有修改必须遵守本目录的 `AGENTS.md`。
