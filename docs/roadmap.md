# AIResearcher v0.1 路线图

## 1. 版本目标与原则

- 前端开发版本：`0.1.0-dev.0`。
- Java 开发版本：`0.1.0-SNAPSHOT`。
- Python 开发版本：`0.1.0.dev0`。
- M0～M4 全部通过验收后发布 `v0.1.0`。
- 实施优先级固定为：**小而完整 > 大而没做完**。
- 每个里程碑必须形成可单独演示的纵向切片；当前里程碑未通过验收前，不提前建设后续能力。

v0.1 的唯一核心闭环是：

```text
上传单篇 PDF → 后台解析与建库 → Web 预览
→ 用户提问 → LLM 原生 Tool Calling
→ 向量检索 → Rerank → 流式回答
→ 展示并跳转到论文页码引用
```

## 2. 当前状态

M0～M3 的单篇论文纵向切片已经实现，M4 的本地真实环境 Demo 验收已经通过；发布加固与 CI 仍在后续范围内：

```text
React → Java BFF → Python Agent → MySQL / PyMuPDF / BGE-M3 / Qdrant
      ← Java SSE 转发 ← DeepSeek Tool Calling / 本地 Rerank / 引用校验
```

当前已有：

- Agent/Web OpenAPI、SSE v1 Schema、合法与非法示例及契约校验。
- FastAPI 论文 API、MySQL/Alembic、带租约 Worker、PyMuPDF 按页切块、真实 BGE embedding、Qdrant 和本地 Rerank。
- DeepSeek `deepseek-v4-flash` 原生 Tool Calling、只读工具白名单、最多三轮、Run/Tool/引用快照持久化和引用校验。
- Spring MVC BFF 的论文/PDF/SSE 代理、请求追踪、取消、错误映射和 PDF Range 语义。
- React 上传/入库状态/重试/删除/原生 PDF 预览，以及 Tool 状态、流式正文和可跳页引用。
- `FakeChatProvider` 仅保留为无外部依赖的契约测试替身，不参与默认运行时。
- Docker Compose MySQL 8.4 与 Qdrant 1.19、named volume 持久化、Alembic 迁移和完整启动/回退说明。

本地验收已经确认：

- 从 Web 上传运行时生成的两页中英文文本 PDF，Worker 完成解析、BGE-M3 embedding、Qdrant 写入并将论文置为 `READY`。
- 浏览器原生预览与 PDF Range 请求有效；DeepSeek 实际调用 `knowledge_base_search`，Qdrant 召回和本地 Rerank 后通过 SSE 返回答案，引用可跳转到正确页码。
- `document_lookup` 元数据问题和不调用工具的普通问题均完成真实 DeepSeek 冒烟。
- MySQL 容器重启后仍保持 Alembic head、论文、任务和 chunk，证明 named volume 持久化有效。
- contracts、frontend、backend、agent 全量自动门禁、敏感文件检查和 `git diff --check` 已通过。

M4 后续工作：

- 继续补齐尚未覆盖的失败组合、运行可观测性和面向日常使用的恢复操作。
- 在独立任务中建设可重复 CI；CI 不是本地 Demo 闭环的运行时依赖。
- 完成发布复核后再标记 `v0.1.0`，不得仅依据一次本地验收提前发布。

## 3. M0：关闭 Phase 0 基线

目标是冻结可靠的开发基线，不继续扩展 Fake 功能。

交付：

1. 校准 README、架构和开发文档，使其与已经落地的三端代码一致。
2. 顺序运行契约、frontend、backend、agent 的现有检查，修复真实失败并记录环境依赖。
3. 增加一个不依赖 MySQL、Qdrant、真实模型或 Docker 的 React → Java → Fake Agent 冒烟测试。
4. 建立分应用 CI，复用各子系统已有的 lint、类型检查和测试命令。

验收：

- 三个应用可以分别启动。
- 浏览器只通过 Java 获得 Fake SSE 文本与引用。
- 正常、失败和中断流符合共享 SSE 契约。
- 所有自动检查可从干净环境重复执行。

## 4. M1：单篇论文上传、建库和查看

目标是先完成“上传一篇真实论文并在 Web 端看到它”的可用闭环。

交付：

1. 在 Agent API 和 Web API 契约中先定义单文件上传、论文列表与详情、PDF 文件、删除、入库任务查询和失败重试。
2. Java 只负责浏览器请求校验、DTO 转换、错误映射和 Agent API/文件流代理，不创建论文或任务数据库。
3. Python 使用 MySQL 持久化 `Paper`、`IngestionJob` 和 `Chunk`；PDF 保存在配置指定的仓库外目录。
4. Python Worker 使用 MySQL 任务表和租约领取任务，支持过期任务恢复、有限重试和幂等执行；v0.1 不使用 Redis Streams。
5. 使用 SHA-256 去重、PyMuPDF 解析文本、按页切分 chunk、本地 embedding 和 Qdrant 建索引；chunk 不跨页，仅 `READY` 论文参与检索。
6. Web 知识库页面展示论文、入库阶段、失败原因、重试和删除；详情页使用浏览器原生 PDF 预览，并支持 HTTP Range 转发。

入库任务状态：

- 任务状态：`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`。
- 执行阶段：`PARSING`、`CHUNKING`、`EMBEDDING`、`INDEXING`。
- 论文状态：`PROCESSING`、`READY`、`FAILED`。

验收：

- 上传一篇不超过 50 MB、500 页的文本型 PDF 后，Web 可观察任务从排队到 `READY`。
- 解析失败不会产生可检索论文，并向用户展示稳定错误码和可操作说明。
- 成功入库后可在站内预览 PDF；重复上传不会创建第二份论文或向量。
- 删除论文会清理当前文件、记录和向量。

## 5. M2：可独立验证的 Retrieval 与 Rerank

目标是先把检索质量做成可测试能力，再接入 Agent。

交付：

1. 实现只读工具 `knowledge_base_search(query, paperIds?, topK)`：默认从 Qdrant 召回 20 个候选 chunk，再由本地 reranker 选择前 5 个证据。
2. 实现只读工具 `document_lookup(query)`：按 paper ID、标题、作者或年份查询论文元数据，不把整篇 PDF 放入模型上下文。
3. 默认 embedding 使用 `BAAI/bge-m3`，默认 reranker 使用 `BAAI/bge-reranker-v2-m3`；模型名称、设备和批大小均通过配置替换。
4. 每条检索证据必须携带 `citationId`、paper ID、标题、页码、原文 quote 和 chunk ID；这些字段是回答引用的唯一事实来源。
5. 检索前从 MySQL 取得允许参与检索的 `READY` paper ID，并作为 Qdrant 过滤条件，避免半成品索引泄露到结果中。

验收：

- 使用运行时生成的中英文合成论文验证跨语言查询。
- 固定查询可以验证向量召回和 Rerank 两个阶段，并确认最终证据顺序。
- 每条证据都能回溯到真实论文、页码、chunk 和原文；删除或未就绪论文不会被返回。

## 6. M3：真正的 Tool Calling Agent

目标是让 LLM 自主选择工具，而不是由代码中的问题分类器伪装成 Agent。

Agent 路径：

```text
用户问题
  ↓
支持 Tool Calling 的 LLM
  ├─ 知识库内容 → knowledge_base_search
  ├─ 论文元数据 → document_lookup
  └─ 普通问题   → 不调用工具
  ↓
工具结果回传 LLM
  ↓
流式回答 + 已验证 Citation
```

交付：

1. 定义统一 `LlmProvider` 和模型原生 Tool Calling 消息类型，DeepSeek 外部 API 为 v0.1 唯一默认 Provider。
2. 使用 `deepseek-v4-flash` 的原生 Tool Calling；不使用问题分类器、Ollama 兼容模式或伪造工具调用。
3. Agent 最多执行 3 轮工具调用；工具名必须来自白名单，参数使用 Pydantic 校验，单次调用受超时和结果大小限制。
4. PDF、工具输出和用户输入均视为不可信内容，不能增加工具权限、改变系统规则或请求隐藏推理。
5. Python 持久化 `Conversation`、`Message`、`AgentRun`、`ToolCall` 和 citation 快照；Java 保持无业务持久化。
6. SSE 保留现有事件并增加 `tool.status`，向 Web 提供工具名、调用 ID、`started/completed/failed` 状态和用户安全说明；不传输思维链。
7. `run.completed` 返回最终回答模式；模型只能引用本轮工具结果中的 citation ID，无法映射的引用不得输出为论文证据。
8. Web 为每次页面会话生成稳定 conversation ID，并流式显示 Agent 状态、回答和论文引用；会话管理 UI 延后。

验收：

- 知识库问题会产生真实 `knowledge_base_search` 工具调用和论文证据。
- 文档信息问题会产生真实 `document_lookup` 工具调用。
- 普通问题不调用工具，并明确标记为未使用知识库证据。
- DeepSeek 通过知识库、文档元数据和无工具三类真实 Tool Calling 冒烟测试。
- 引用只能是检索工具返回证据的子集，并可跳转到 PDF 对应页。

## 7. M4：v0.1 完整性与发布

目标是把成功路径升级为可以日常使用和重复部署的版本。

交付：

1. 完成无文本 PDF、加密或损坏 PDF、重复上传、Worker 中断、MySQL/Qdrant/LLM 不可用、工具失败和 SSE 中断的用户可见状态。
2. 完成 Agent 运行和入库任务的超时、取消、重试、日志关联和请求追踪。
3. 使用运行时生成的合成 PDF 建立三端端到端测试，不向仓库提交真实或测试 PDF 文件。
4. 提供使用 Docker Compose MySQL 与 Qdrant 启动 Python API/Worker、Java 和 React 的说明，以及 DeepSeek 冒烟步骤。
5. 接入 CI，并执行契约、单元、集成、端到端和敏感文件门禁。

发布验收：

1. 从空环境启动所有必需服务。
2. 上传一篇文本型 PDF 并等待其进入 `READY`。
3. 在 Web 中查看论文详情和 PDF。
4. 提出知识库问题并观察真实工具调用、检索和 Rerank 状态。
5. 接收流式回答并从引用跳转到正确页码。
6. 使用 DeepSeek 完成知识库、文档元数据和无工具三类问题冒烟。
7. 所有自动门禁通过后发布并标记 `v0.1.0`。

## 8. v0.1 公共契约增量

在 `contracts/` 中先定义并验证以下能力，再由 Python、Java 和 React 顺序消费：

```text
POST   /papers
GET    /papers
GET    /papers/{paperId}
GET    /papers/{paperId}/file
DELETE /papers/{paperId}

GET    /ingestion-jobs/{jobId}
POST   /ingestion-jobs/{jobId}/retry

POST   /conversations
GET    /conversations
GET    /conversations/{conversationId}/messages
POST   /conversations/{conversationId}/messages/stream
```

- 浏览器端路径统一位于 `/api/v1/**`，Agent 端路径统一位于 `/agent-api/v1/**`。
- 普通 JSON API 使用 Java `Result<T>`；SSE、PDF 文件和健康检查不包装该结构。
- PDF 文件端点需要保留 `Range`、`Content-Range`、`Content-Length`、`ETag` 和内容类型等必要语义。
- SSE v1 增加 `tool.status`，并扩展 `run.completed` payload；Schema、OpenAPI、示例、非法夹具和三端测试必须一起更新。

## 9. 明确延后项

v0.1 固定为单用户、本地优先、单默认知识库。以下能力不进入 M0～M4：

- 登录、租户、多用户授权和 Java 业务数据库。
- 批量上传、OCR、arXiv 导入、人工笔记和自定义 PDF 阅读器。
- 多知识库、标签、元数据编辑和 READY 论文多选器。
- 重新解析、全库重建、索引版本原子切换和零停机索引迁移。
- Redis Streams、LangGraph、研究工作区、实验闭环和论文写作。
- Ollama 或其他本地 LLM Provider；如有真实离线需求，后续通过独立契约和验收引入。

当单机 MySQL Worker 的吞吐或恢复能力成为真实瓶颈时，再通过基准和 ADR 评估 Redis Streams；当科研流程出现持久执行、人工审批和可恢复图状态时，再评估 LangGraph。
