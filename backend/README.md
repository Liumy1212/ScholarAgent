# Backend

AIResearcher 的 Java Web Backend/BFF。React 只通过本应用访问 Python Agent。

## 当前能力

- 向浏览器提供 `/api/v1/**` REST 与 SSE。
- `Controller -> Service -> AgentClient` 的论文、PDF 和流式问答代理。
- Web 请求校验、`Result<T>`、错误映射、请求追踪和下游取消。
- PDF Range 语义及 SSE 事件、ID、顺序和终止状态透传。

本模块没有数据库、Mapper、PDF 解析、RAG、Prompt 或模型逻辑。默认 Agent 地址为
`http://127.0.0.1:8000`。

## 运行与检查

完整环境和一键启动见
[Windows 本地部署与启动](../docs/deployment.md)。

本模块使用 Java 21 和仓库内 Maven Wrapper；在 `backend/` 下验证：

```powershell
.\mvnw.cmd verify
```

修改本模块前还应阅读 [Backend instructions](AGENTS.md) 与
[总体架构](../docs/architecture.md)。
