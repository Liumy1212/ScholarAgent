# AIResearcher Frontend

单篇论文 Demo 的 React 客户端。知识库页提供单 PDF 上传、入库阶段轮询、失败重试、删除与浏览器原生 PDF 预览；问答页通过 Java BFF 接收 Tool 状态、SSE 正文和可跳页的引用。

## 环境

- Node.js 22.13+
- pnpm 11

## 本地开发

```bash
pnpm install --frozen-lockfile
pnpm dev
```

开发服务器默认把 `/api/**` 代理到 `http://localhost:8080`。如需修改 Java BFF 地址，可在启动命令中设置 `VITE_API_PROXY_TARGET`。

## 检查

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

浏览器仅调用相对路径 `/api/v1/**`，不会直连 Python。流式问答通过 `fetch` 发起 POST 并解析 SSE，不使用 `EventSource`；PDF 由浏览器原生阅读器打开，引用链接使用 `#page=<页码>`，不包含自定义 PDF Viewer。
