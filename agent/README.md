# Agent

AIResearcher 的 Python Agent API、PDF 入库 Worker、检索、Rerank 和 DeepSeek Tool Calling
实现。Python 是论文文件与 AI 领域数据的唯一事实来源。

当前运行时使用仓库外的 `AIRESEARCHER_STORAGE_DIR`，支持单 PDF 上传/删除、MySQL 持久
任务、PyMuPDF 按页切块、BGE-M3 embedding、Qdrant、本地 reranker、原生 Tool Calling、
SSE 和引用校验。本地原件库扫描与排除/恢复仍处于契约已完成、实现待完成状态。

## 目录结构

| 路径 | 职责 |
| --- | --- |
| `src/airesearcher_agent/api/` | FastAPI 路由、DTO、PDF 与 SSE 适配 |
| `src/airesearcher_agent/application/` | 入库、论文和流式 Run 用例 |
| `src/airesearcher_agent/domain/` | 论文、问答和 SSE 领域模型 |
| `src/airesearcher_agent/ingestion/` | PDF 解析与按页切块 |
| `src/airesearcher_agent/persistence/` | SQLAlchemy 模型、数据库和仓储 |
| `src/airesearcher_agent/providers/` | DeepSeek 与测试 provider |
| `src/airesearcher_agent/retrieval/` | embedding、Qdrant、reranker 和工具 |
| `src/airesearcher_agent/worker/` | 带租约的后台入库 Worker |
| `migrations/` | Agent MySQL Alembic 迁移 |
| `tests/` | 单元、集成和契约测试 |

## 运行与检查

完整环境变量、首次安装和启动顺序见
[Windows 本地部署与运行](../docs/deployment.md)。

在仓库根目录启动 Agent API 或 Worker：

```powershell
conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app `
    --app-dir .\agent\src --host 127.0.0.1 --port 8000
conda run -n airesearcher-agent python -m airesearcher_agent.worker.main
```

在 `agent/` 下检查：

```powershell
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent python -m pytest
```

修改本模块前阅读 [Agent instructions](AGENTS.md) 和
[当前架构](../docs/architecture.md)。
