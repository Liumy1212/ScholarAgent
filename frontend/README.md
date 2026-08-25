# AIResearcher Frontend

Phase 0 React 客户端，提供知识库占位页和基于 Java BFF 的流式问答页。

## 环境

- Node.js 22.13+
- pnpm 11

## 本地开发

```bash
pnpm install
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

浏览器仅调用相对路径 `/api/v1/**`，流式问答通过 `fetch` 发起 POST 并解析 SSE，不使用 `EventSource`。
