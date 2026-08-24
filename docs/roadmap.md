# AIResearcher Phase 0～3 路线图

## 版本策略

- 前端开发版本：`0.1.0-dev.0`。
- Java 开发版本：`0.1.0-SNAPSHOT`。
- Python 开发版本：`0.1.0.dev0`。
- Phase 0～3 全部通过 Demo 验收后发布 `v0.1.0`。

## 当前里程碑：协作基线

- 初始化 Git、根配置、目录和中文文档。
- 建立根与 frontend/backend/agent/contracts 分层 `AGENTS.md`。
- 建立多 Chat Worktree、任务所有权和契约先行规则。
- 不创建应用代码、运行时契约、CI 或基础设施实例。

## Phase 0：可运行工程骨架

目标是完成不依赖 Docker、数据库、向量库或真实模型的最小竖切：

```text
React -> Java BFF -> Python Fake SSE -> Java 透传 -> React 展示
```

交付：

1. contracts Chat 定义最小 Agent/Web OpenAPI、SSE v1 Schema、说明与示例，并加入契约校验。
2. agent Chat 创建 FastAPI、普通 application use case、`ChatProvider` 与确定性的 `FakeChatProvider`。
3. backend Chat 创建 Spring MVC BFF、`Result<T>`、请求追踪、AgentClient 与 SSE 代理。
4. frontend Chat 创建知识库占位页、问答页、POST SSE parser 与完成/失败/中断状态。
5. ci/smoke Chat 添加分应用 CI 和不依赖 Docker 的端到端 SSE 冒烟测试。

验收：

- 三个应用可以分别启动。
- React 只通过 Java 显示 Fake SSE 文本与引用。
- Java 保留 SSE 事件名称、ID、序号和 JSON envelope。
- 正常和失败流均只有一个契约规定的终止事件。
- Agent 不可用时 Java 返回统一错误。
- 所有检查通过且仓库不包含敏感或运行数据。

## Phase 1：论文知识库

- 一次上传多篇文本型 PDF，单文件默认限制 50 MB、500 页。
- 使用 SHA-256 去重，提取并允许修改标题、作者、年份和页数。
- 使用持久 ingestion job、Redis Streams Worker、PyMuPDF、MySQL 和 Qdrant。
- 展示状态和失败原因，支持删除、重新解析和重建索引。
- 新索引验证成功后原子切换；失败时旧索引继续提供检索。
- 使用 10 篇可提取文本的 AI/计算机论文验收，不支持 OCR。

## Phase 2：全库 RAG

- 创建、列出和切换持久会话。
- 检索整个默认知识库，SSE 返回答案和页码引用。
- 保存消息、实际模型、Prompt 版本、论文范围和引用快照。
- 校验证据的 paper ID、page、section、quote 和 chunk ID。
- 在 UI 中区分论文证据与未由知识库支持的模型常识。

## Phase 3：论文范围过滤与 v0.1

- 在问答页增加 READY 论文多选器。
- 空选择表示全库，非空选择严格限定所选 paper ID。
- 完成三端联调、失败场景和完整 Demo 验收。
- 通过全部门禁后发布并标记 `v0.1.0`。

## 后续方向

Phase 4 以后依次引入研究工作区与 arXiv、研究缺口和创新候选、受预算和审批约束的实验闭环，以及 Markdown/LaTeX 论文写作。长期科研流程出现持久执行和人工审批需求时，再通过 ADR 评估 LangGraph。
