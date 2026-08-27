# Agent

AIResearcher 的 Python Agent API、PDF 入库 Worker、检索、Rerank 和 DeepSeek Tool Calling
实现。Python 是论文文件与 AI 领域数据的唯一事实来源。

## 当前能力

- 单 PDF 上传、SHA-256 去重、列表、详情、删除和支持 Range 的文件读取。
- MySQL 持久任务、租约 Worker、PyMuPDF 按页切片和失败重试。
- `BAAI/bge-m3` embedding、Qdrant 检索与 `BAAI/bge-reranker-v2-m3` 本地重排。
- DeepSeek 原生 Tool Calling、只读工具白名单、SSE、引用校验及 Run/消息/引用持久化。

`FakeChatProvider` 仅用于无外部依赖测试，不参与默认运行时。PDF、模型、缓存、数据库、向量、
日志和密钥必须保存在 Git 之外；运行目录边界由配置校验强制执行。

## 运行与检查

环境准备、`.env` 和一键启动统一见
[Windows 本地部署与启动](../docs/deployment.md)。

在 `agent/` 下运行质量检查：

```powershell
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent python -m pytest
```

修改本模块前还应阅读 [Agent instructions](AGENTS.md) 与
[总体架构](../docs/architecture.md)。
