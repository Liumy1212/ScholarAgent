# Backend

AIResearcher 的 Java Web Backend/BFF 目录。

## 职责

- 对 React 提供 `/api/v1/**` REST 与 SSE 接口。
- 处理请求校验、统一响应、错误映射、请求追踪与 Agent DTO 转换。
- 通过 AgentClient 调用 Python，不承担 PDF、RAG、Prompt 或模型逻辑。

## 当前状态

当前仅建立协作边界，尚未生成 Spring Boot 工程。后续 Phase 0 后端任务将采用 Java 21、Spring Boot 4、Spring MVC、WebClient 和 Maven Wrapper。

开始修改前请阅读本目录的 `AGENTS.md` 与 [总体架构](../docs/architecture.md)。
