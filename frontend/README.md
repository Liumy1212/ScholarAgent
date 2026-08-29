# Frontend

AIResearcher 的 React 19 浏览器客户端。当前提供单 PDF 上传、入库状态与重试、删除、原生
PDF 预览，以及工具状态、SSE 回答和页码引用。

浏览器只调用 Java 的 `/api/v1/**`。本地论文原件库的扫描和排除/恢复已经进入 Web API
契约，但尚未进入当前 UI，状态见 [路线图阶段 1.4](../docs/roadmap.md)。

## 目录结构

| 路径 | 职责 |
| --- | --- |
| `src/api/` | REST DTO、请求封装、错误处理和 SSE 解析 |
| `src/chat/` | 问答流状态与状态转换 |
| `src/pages/` | 知识库页、问答页及页面测试 |
| `src/test/` | Vitest/Testing Library 公共测试配置 |
| `src/App.tsx` | 应用页面与导航入口 |
| `src/main.tsx` | React 挂载入口 |
| `src/styles.css` | 当前全局样式 |

## 开发命令

首次依赖安装：

```powershell
pnpm install --frozen-lockfile
```

在 `frontend/` 下运行：

```powershell
pnpm dev
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

完整环境准备与服务启动见 [Windows 本地部署与运行](../docs/deployment.md)。修改本模块前
阅读 [Frontend instructions](AGENTS.md) 和 [当前架构](../docs/architecture.md)。
