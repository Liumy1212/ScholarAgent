# Agent

AIResearcher 的 Python Agent API、PDF 入库 Worker、检索、Rerank 和 DeepSeek Tool Calling 实现。Python 是论文文件与 AI 领域数据的唯一事实来源。

## Demo 能力

- `/agent-api/v1/papers`：单 PDF 上传、SHA-256 去重、列表、详情、删除和支持 Range 的文件读取。
- `/agent-api/v1/ingestion-jobs/**`：任务状态、阶段与有限重试。
- PyMuPDF 按页解析文本；chunk 不跨页，保留确定性的 chunk/vector ID、页码和 quote。
- MySQL + SQLAlchemy + Alembic；Worker 使用任务表、`SKIP LOCKED` 和数据库租约。
- `BAAI/bge-m3` 生成 1024 维归一化向量，Qdrant 保存向量；`BAAI/bge-reranker-v2-m3` 本地重排。
- DeepSeek `deepseek-v4-flash` 原生 Tool Calling，只允许 `knowledge_base_search` 与 `document_lookup` 两个只读工具，最多三轮。
- SSE 只输出正文、引用、用户安全的 `tool.status` 和终止状态，不输出隐藏推理。

`FakeChatProvider` 仅用于无外部依赖的契约单元测试，默认运行时始终使用真实数据库、Qdrant、本地模型和 DeepSeek Provider。

## 配置与数据边界

所有设置从进程环境读取。根目录 [`.env.example`](../.env.example) 只列键名和占位值，应用不会自动读取 `.env`。至少要设置 DeepSeek、MySQL、Qdrant 和外部存储目录变量。`AIRESEARCHER_DB_ROOT_PASSWORD` 只供 Compose 初始化 MySQL，Agent 和 Alembic 始终使用应用账户。

`AIRESEARCHER_STORAGE_DIR` 与 `AIRESEARCHER_MODEL_CACHE_DIR` 必须位于仓库外；应用会拒绝仓库内路径。PDF、模型、缓存、数据库、向量和日志不得提交。

## 安装、迁移与启动

从仓库根目录使用隔离环境，不修改 Conda `base`。先按
[Infrastructure](../infrastructure/README.md) 创建未跟踪的 `.env`、启动 MySQL，并在当前
PowerShell 中加载应用变量；等待 MySQL 显示为 `healthy` 后再运行迁移：

```powershell
conda run -n airesearcher-agent python -m pip install -e ".\agent[dev]"
docker compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps mysql

Set-Location .\agent
conda run -n airesearcher-agent alembic upgrade head
Set-Location ..
```

启动 Agent API（终端 1）：

```powershell
conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app --app-dir .\agent\src --host 127.0.0.1 --port 8000
```

启动 Worker（终端 2）：

```powershell
conda run -n airesearcher-agent python -m airesearcher_agent.worker.main
```

Worker 第一次处理论文时会把公开模型下载到外部缓存。`AIRESEARCHER_MODEL_DEVICE=auto` 优先 CUDA；CUDA 显存不足时单个模型会安全回退 CPU，不会以 Fake 结果代替。

## 检查

在 `agent/` 下运行：

```powershell
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent python -m pytest
```

开始修改前请阅读本目录的 `AGENTS.md` 与 [总体架构](../docs/architecture.md)。
