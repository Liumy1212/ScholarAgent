# AIResearcher Frontend

单篇论文 Demo 的 React 19 客户端。知识库页提供 PDF 上传、原件库手动扫描、入库状态、
排除/恢复和浏览器原生预览；问答页展示工具状态、SSE 正文和可跳页引用。

浏览器仅调用 Java 的相对路径 `/api/v1/**`，不会直连 Python。POST SSE 使用 `fetch` 解析，
PDF 引用链接使用 `#page=<页码>`。

## 运行与检查

完整环境、首次依赖安装和一键启动见
[Windows 本地部署与启动](../docs/deployment.md)。

在 `frontend/` 下验证：

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

修改本模块前还应阅读 [Frontend instructions](AGENTS.md) 与
[总体架构](../docs/architecture.md)。
