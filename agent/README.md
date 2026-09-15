# Agent

AIResearcher 的 Python Agent API、PDF 入库 Worker、检索、Rerank 和 DeepSeek Tool Calling
实现。Python 是论文文件与 AI 领域数据的唯一事实来源。

当前运行时使用 `AIRESEARCHER_PAPER_LIBRARY_DIR` 管理 PDF 原件，支持只登记上传、分页
清单与 `libraryState` 筛选、后台扫描、逐篇手动入库、只删除知识并保留 PDF 原件、
排除/恢复、可持久化逻辑知识库与成员关系、三类问答范围快照、MySQL 持久任务、
PyMuPDF 章节感知页内切块、DeepSeek 逐 Chunk 上下文化、
BGE-M3/Qdrant 与按论文版本缓存倒排索引的 BM25 双路召回、RRF 融合、本地 reranker、原生 Tool Calling、SSE 和引用校验。生成的
上下文只进入检索文本，引用 quote 始终保留论文原文。扫描会清理没有知识关联的缺失或替换登记，并保留仍
关联知识的缺失状态。旧
`AIRESEARCHER_STORAGE_DIR` 仅保留迁移期兼容读取。

PDF 直接存放在配置的论文目录中，网页上传与手动放入使用同一位置；仅 `.staging/` 用于
上传暂存。扫描递归覆盖任意子目录，但文件夹没有知识库语义，也不会因创建知识库而移动原件。

## 目录结构

| 路径 | 职责 |
| --- | --- |
| `src/airesearcher_agent/api/` | FastAPI 路由、DTO、PDF 与 SSE 适配 |
| `src/airesearcher_agent/application/` | 入库、论文和流式 Run 用例 |
| `src/airesearcher_agent/domain/` | 论文、问答和 SSE 领域模型 |
| `src/airesearcher_agent/ingestion/` | PDF 结构解析、页内切块与检索上下文模型 |
| `src/airesearcher_agent/persistence/` | SQLAlchemy 模型、数据库和仓储 |
| `src/airesearcher_agent/providers/` | DeepSeek 与测试 provider |
| `src/airesearcher_agent/retrieval/` | embedding、Qdrant、BM25、RRF、reranker 和工具 |
| `src/airesearcher_agent/evaluation/` | Dense/Hybrid 离线对照、Recall@20、MRR 和来源追踪评测 |
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

完成数据库迁移、生成合成 PDF 并按标题 `Aurora Bamboo Calibration Study` 入库后，可运行：

```powershell
conda run -n airesearcher-agent python -m airesearcher_agent.evaluation.main `
    --require-hybrid-improvement
```

命令从根目录 `.env` 读取本地运行配置，对固定中英文问题分别执行 Dense 与 Hybrid top-20
检索，输出 Recall@20、MRR、差值和证据来源完整率；不会输出论文原文或修改数据库。

修改本模块前阅读 [Agent instructions](AGENTS.md) 和
[当前架构](../docs/architecture.md)。
