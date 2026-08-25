# Agent

AIResearcher 的 Python Agent API、RAG 与异步 Worker 目录。

## 职责

- 作为论文与 AI 数据的唯一事实来源。
- 管理论文文件、解析、索引、检索、会话、消息、引用和模型运行记录。
- 通过 `/agent-api/v1/**` 向 Java BFF 提供 REST 与 SSE。

## Phase 0 实现

当前目录提供 Python 3.12 FastAPI 应用，调用链为 API route -> application use case ->
`ChatProvider`。默认 `FakeChatProvider` 不访问网络或真实模型，会确定性地产生模拟文本和引用。

唯一端点严格实现共享契约：

```text
POST /agent-api/v1/conversations/{conversationId}/messages/stream
```

请求正文必须包含 `content` 和 `paperIds`，并通过 `X-Request-Id` 传递请求追踪标识。
空 `paperIds` 产生默认合成引用，非空列表为每个指定 ID 产生一条合成引用。将 `content`
精确设为 `__FAKE_PROVIDER_FAILURE__` 可稳定模拟建流后的 provider 失败。

## 本地开发

使用隔离环境，不修改 Conda `base`：

```powershell
conda create -n airesearcher-agent python=3.12 pip -y
conda run -n airesearcher-agent python -m pip install -e ".\agent[dev]"
conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app --app-dir agent/src
```

在 `agent/` 下运行全部检查：

```powershell
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent pytest
```

开始修改前请阅读本目录的 `AGENTS.md` 与 [总体架构](../docs/architecture.md)。
