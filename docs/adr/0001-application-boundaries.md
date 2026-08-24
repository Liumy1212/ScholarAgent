# ADR 0001：React、Java BFF 与 Python Agent 的应用边界

- 状态：Accepted
- 日期：2026-08-24

## 背景

AIResearcher 同时需要浏览器产品界面、稳定的 Web API，以及快速演进的论文解析、RAG 和科研 Agent 能力。若三者共享实现或数据所有权，前端会直接依赖 AI 内部结构，Java 和 Python 会出现重复论文表与不一致状态，长期实验能力也难以隔离。

## 决策

仓库采用三个独立应用：

1. React frontend 负责浏览器交互，只调用 Java `/api/v1/**`。
2. Java backend 作为 BFF，负责 Web DTO、校验、统一错误、请求追踪和 Agent REST/SSE 代理。
3. Python Agent 负责论文与 AI 领域数据、文件、解析、索引、检索、Prompt、模型和后台任务，通过 `/agent-api/v1/**` 服务 Java。

跨应用 wire format 由 `contracts/` 管理。Python 是 Agent API 实现方，Java 是 Agent API 消费者和 Web API 实现方，React 是 Web API 消费者。

基础设施配置与运行数据分离：仓库提交 Compose、迁移和模板，数据库、PDF、向量、模型和密钥保存在 Git 之外。

## 结果

正面结果：

- 三个应用可独立启动、测试和演进。
- 浏览器不会接触模型凭据或 Agent 内部 API。
- 论文和 AI 数据只有一个事实来源。
- 契约任务可以先行，三端可在独立 Worktree 中并行实现。

代价：

- Java 需要显式维护 Web DTO、Agent DTO 和转换。
- SSE 代理必须正确处理取消、超时以及流建立前后的不同错误。
- 契约修改需要跨应用兼容性检查，不能在实现中临时改变字段。

## 被拒绝的方案

- **React 直接调用 Python**：绕过统一 Web API、错误处理和请求追踪，并扩大 Agent 暴露面。
- **Java 与 Python 各自保存论文数据**：制造双事实源、同步和删除一致性问题。
- **Java 承担 RAG/Prompt**：模糊 BFF 与 AI 系统边界，阻碍 Python 侧快速演进。
- **Phase 0 即引入 LangGraph**：普通最小竖切不需要持久图执行，会增加依赖与调试成本。
