# Agent

AIResearcher 的 Python Agent API、RAG 与异步 Worker 目录。

## 职责

- 作为论文与 AI 数据的唯一事实来源。
- 管理论文文件、解析、索引、检索、会话、消息、引用和模型运行记录。
- 通过 `/agent-api/v1/**` 向 Java BFF 提供 REST 与 SSE。

## 当前状态

当前仅建立协作边界，尚未生成 Python 包或 Conda 环境。后续 Phase 0 Agent 任务将采用 Python 3.12、FastAPI、普通 application use case 和 FakeChatProvider，不引入 LangGraph。

开始修改前请阅读本目录的 `AGENTS.md` 与 [总体架构](../docs/architecture.md)。
