# 本地论文原件库多 Chat 提示词

本文提供可直接复制的任务提示词。仓库长期保留 `codex/frontend`、`codex/backend`、
`codex/agent`、`codex/docs`、`codex/test` 五个分支和 Worktree；当前跨子系统功能使用
`codex/feature/paper-library-<slice>` 临时分支族。`main` 是唯一集成入口。

固定顺序为：docs/contracts 先合入 `main`；agent、backend、frontend、runtime 从包含合同提交
的 `main` 建立并行切片；实现全部合入后才创建 test；最后由 Local 集成。所有 Chat 均不得
push、创建 PR、rebase、reset、强制更新、修改远端或删除分支/Worktree。

## 1. Docs 与 Contracts Chat

```text
你负责 AIResearcher“本地论文原件库”的合同与文档切片。

分支：codex/feature/paper-library-docs
长期所有者：codex/docs
基线：从最新已接受的本地 main 创建独立 Worktree。

开始前阅读根 AGENTS.md、contracts/AGENTS.md、README.md、docs/architecture.md、
docs/roadmap.md，并检查 git status。

允许修改：contracts/**、docs/**、受影响的 README.md/AGENTS.md、.env.example。
禁止修改：agent/backend/frontend 源码与测试、scripts/**、infrastructure/**、tests/**。

目标：
- 定义 .private/paper-library/originals、.staging 和 AIRESEARCHER_PAPER_LIBRARY_DIR。
- 同步 Agent/Web OpenAPI：library、扫描任务/分页扫描项、paper exclusion。
- 移除未发布 DELETE /papers/{paperId}，增加 Paper 原件状态、EXCLUDED 与 searchable。
- 保持 Agent 直接 DTO、Web Result<T>、PDF Range 与 SSE 非 Result 边界。
- 更新验证器、示例、架构、路线图、部署文档和 ADR；说明重置再扫描及未来 MCP 边界。

检查：
Set-Location contracts
npm ci
npm run validate
Set-Location ..
git diff --check

只提交授权文件，提交信息使用英文。交接分支、SHA、文件范围、检查结果、公共接口及兼容性
影响。不得 push 或创建 PR。合同提交合入 main 前，消费者 Chat 不得开始实现。
```

## 2. Agent Chat

```text
你负责 AIResearcher“本地论文原件库”的 Python Agent 切片。

分支：codex/feature/paper-library-agent
长期所有者：codex/agent
依赖：必须从已包含合同提交 <CONTRACT_COMMIT_SHA> 的最新本地 main 创建独立 Worktree。

开始前阅读根 AGENTS.md、agent/AGENTS.md 和已合入的 Agent OpenAPI；检查 git status。不得改变
wire shape，发现合同问题时停止并退回 docs/contracts Chat。

允许修改：agent/**（实现、Alembic migration、Worker、模块测试）。
禁止修改：contracts/**、docs/**、所有 README/AGENTS、backend/**、frontend/**、scripts/**、
.env.example、tests/**。

实现配置和安全目录解析、originals/.staging、后台扫描任务/租约/恢复、PDF 递归扫描与稳定性
检查、SHA-256 去重、移动/MISSING/REPLACED/EXCLUDED、上传与扫描共用登记器、原子落盘、
排除/恢复、READY+AVAILABLE 检索过滤和安全 PDF 读取。只新增迁移，不自动删除或搬迁旧数据；
不实现 OCR、多格式、监听、定时扫描或 MCP。行为变化必须同步模块测试。

检查：
Set-Location agent
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent python -m pytest
Set-Location ..
git diff --check

只提交 agent/**。交接分支、SHA、依赖合同 SHA、迁移/旧数据要求、检查结果和未运行项。不得
push 或创建 PR。
```

## 3. Backend Chat

```text
你负责 AIResearcher“本地论文原件库”的 Java BFF 切片。

分支：codex/feature/paper-library-backend
长期所有者：codex/backend
依赖：必须从已包含合同提交 <CONTRACT_COMMIT_SHA> 的最新本地 main 创建独立 Worktree。

阅读根 AGENTS.md、backend/AGENTS.md 和两份 OpenAPI，检查 git status。不得修改合同；发现
wire shape 问题时退回 docs/contracts Chat。

允许修改：backend/**（实现和模块测试）。
禁止修改：contracts/**、docs/**、README/AGENTS、agent/**、frontend/**、scripts/**、tests/**。

按 Controller -> Service -> AgentClient 代理 library/scans/exclusion，DTO 严格匹配合同；普通
JSON 继续使用 Result<T>，保留扫描 202、活动扫描 409 与 X-Request-Id。移除旧浏览器硬删除
入口，PDF Range 和 SSE 行为不变。Java 不读取本地目录、不解析 PDF、不创建论文持久化。

检查：
Set-Location backend
.\mvnw.cmd verify
Set-Location ..
git diff --check

只提交 backend/**。交接分支、SHA、合同 SHA、检查结果和兼容性影响。不得 push 或创建 PR。
```

## 4. Frontend Chat

```text
你负责 AIResearcher“本地论文原件库”的 React 切片。

分支：codex/feature/paper-library-frontend
长期所有者：codex/frontend
依赖：必须从已包含合同提交 <CONTRACT_COMMIT_SHA> 的最新本地 main 创建独立 Worktree。

阅读根 AGENTS.md、frontend/AGENTS.md 和 Web OpenAPI，检查 git status。不得改变合同；浏览器
只能调用 /api/v1/**。

允许修改：frontend/**（实现和模块测试）。
禁止修改：contracts/**、docs/**、README/AGENTS、agent/**、backend/**、scripts/**、tests/**。

展示原件库路径、支持格式、最近扫描；创建扫描并轮询终态；展示统计与失败项；分别呈现
sourceStatus、status、searchable；MISSING/REPLACED 禁止预览和问答；将删除改为保留原件的
“移出知识库”，为 EXCLUDED 提供重新加入；上传文案说明本地落盘。覆盖 loading、empty、
error、disabled、轮询、排除/恢复和无障碍测试。

检查：
Set-Location frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
Set-Location ..
git diff --check

只提交 frontend/**。交接分支、SHA、合同 SHA 和检查结果。不得 push 或创建 PR。
```

## 5. Runtime Chat

```text
你负责 AIResearcher“本地论文原件库”的共享运行配置切片。

分支：codex/feature/paper-library-runtime
依赖：必须从已包含合同提交 <CONTRACT_COMMIT_SHA> 的最新本地 main 创建独立 Worktree。

阅读根 AGENTS.md、已接受 ADR 和部署文档，检查 git status。

允许修改：scripts/start-dev.ps1、仅在现有规则不足时修改 .gitignore、必要的 infrastructure
开发配置。
禁止修改：.env.example、contracts/**、docs/**、README/AGENTS、agent/**、backend/**、
frontend/**、tests/**。

让启动校验识别 AIRESEARCHER_PAPER_LIBRARY_DIR，并只允许仓库内受控 .private 边界；不放宽
其他运行数据规则。移除旧 storage 启动依赖；CheckOnly 不创建/删除数据；正常启动不得删除
旧文件、volume、collection 或原件；验证 .private/paper-library/**/*.pdf 被忽略且不输出秘密。

检查：
.\scripts\start-dev.ps1 -CheckOnly
git check-ignore -v --no-index .private/paper-library/originals/example.pdf
git diff --check

只提交授权路径。交接分支、SHA、合同 SHA、检查结果和未运行项。不得 push 或创建 PR。
```

## 6. Test Chat

```text
你负责 AIResearcher“本地论文原件库”的仓库级测试与验收切片。

分支：codex/feature/paper-library-test
长期所有者：codex/test
依赖：docs、agent、backend、frontend、runtime 切片必须已全部合入最新本地 main，之后才创建
本 Worktree。

阅读根 AGENTS.md、合同、ADR 和测试说明，检查 git status。

允许修改：tests/**。
禁止修改：frontend/**、backend/**、agent/**、contracts/**、docs/**、scripts/**、
.env.example、.gitignore 及模块内部测试。

在 tests/e2e 运行时生成合成 PDF，不提交 PDF；只通过 Java /api/v1/** 验证扫描、去重、移动、
READY+AVAILABLE、预览、排除、恢复和 MISSING。区分无外部依赖门禁与需要 MySQL/Qdrant/
模型的冒烟；不调用真实 DeepSeek，不自动清理用户数据库、volume、collection 或原件。发现
模块缺陷只记录复现并退回所属实现 Chat，不能跨边界修补。

运行新建仓库级门禁、git diff --check，并确认 git ls-files 不含 PDF、数据库、向量或秘密。
只提交 tests/**。交接分支、SHA、自动检查、未运行冒烟及原因。不得 push 或创建 PR。
```

## 7. Local 集成 Chat

```text
你是 AIResearcher Local 集成 Chat，必须停留在本地 main。不得 push、创建 PR、修改远端、
重写历史、删除分支/Worktree 或自动重置数据库、Qdrant、旧 storage 或论文原件。

合同先行及合并顺序：
1. codex/feature/paper-library-docs
2. codex/feature/paper-library-agent
3. codex/feature/paper-library-backend
4. codex/feature/paper-library-frontend
5. codex/feature/paper-library-runtime
6. codex/feature/paper-library-test

消费者分支必须声明第 1 步的合同 SHA；test 只能在 1-5 全部合入后建立。每次合并前检查
git status --short --branch、git log main..<branch>、git diff --stat main...<branch> 和完整 diff，
然后使用 git merge --no-ff <branch> 串行合并。冲突时中止并退回所属 Chat，不在 main 猜测。

最终依次运行 contracts npm run validate、Agent Ruff/format/mypy/pytest、backend mvnw verify、
frontend lint/typecheck/test/build、tests/** 门禁、git diff --check、Git 忽略与敏感文件检查。
需要真实服务或数据重置的验收必须停下并由用户明确执行，或使用独立可丢弃环境。

集成完成后把 codex/frontend、codex/backend、codex/agent、codex/docs、codex/test 分别以
git merge --ff-only main 同步到最终 main。报告每个合并提交、全部检查、未运行项、兼容性、
旧数据人工迁移步骤及 main 相对 origin/main 的领先提交数。不得删除任何分支或 Worktree。
```
