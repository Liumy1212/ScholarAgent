# Backend

AIResearcher 的 Java Web Backend/BFF。React 只通过本应用访问 Python Agent；本模块没有论文
数据库、PDF 解析、RAG、Prompt 或模型逻辑。

当前实现代理原件库信息、服务端状态筛选、只登记上传、手动入库、扫描、扫描项、知识删除、
排除/恢复、PDF Range 和流式问答，并暂时保留旧单篇论文接口。`originalsPath` 直接透传
Agent 的实际扫描目录；知识删除只代理 Agent，不在 Java 删除 PDF、数据库记录或向量。
React 是否已消费这些接口以[路线图阶段 1.4](../docs/roadmap.md)为准。

## 目录结构

| 路径 | 职责 |
| --- | --- |
| `src/main/java/dev/airesearcher/backend/common/` | `Result<T>`、错误与请求 ID |
| `src/main/java/dev/airesearcher/backend/integration/agent/` | Python Agent client 与下游 DTO |
| `src/main/java/dev/airesearcher/backend/library/` | 原件库、扫描与知识库生命周期 Web API |
| `src/main/java/dev/airesearcher/backend/paper/` | 论文、入库和 PDF Web API |
| `src/main/java/dev/airesearcher/backend/chat/` | POST SSE 控制、状态与下游取消 |
| `src/main/resources/application.properties` | Agent 地址与超时配置 |
| `src/test/` | Controller、client、SSE、取消和契约测试 |

## 运行与检查

默认 Agent 地址为 `http://127.0.0.1:8000`。完整环境启动见
[Windows 本地部署与运行](../docs/deployment.md)。

在 `backend/` 下运行：

```powershell
.\mvnw.cmd spring-boot:run
.\mvnw.cmd verify
```

修改本模块前阅读 [Backend instructions](AGENTS.md) 和
[当前架构](../docs/architecture.md)。
