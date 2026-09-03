# Frontend

AIResearcher 的 React 19 浏览器客户端。当前提供统一原件清单、只登记 PDF 上传、目录扫描、
服务端原件/知识状态筛选、逐篇手动入库、状态与重试、只删除知识、原件 PDF 预览，以及工具
状态、SSE 回答和页码引用。兼容性的排除/恢复请求封装仍保留，但知识库页面不再将其作为
删除流程。

浏览器只调用 Java 的 `/api/v1/**`，不读取本地目录；页面展示 Agent 经 Java 返回的实际
`originalsPath`。Chat 只列出 `searchable=true` 的论文，浏览器不提供原件硬删除。完整三端验收状态见
[路线图阶段 1.4](../docs/roadmap.md)。

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
