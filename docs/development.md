# 开发环境与多 Chat 工作流

## 1. 工具基线

当前应用基线：

| 区域 | 基线 |
| --- | --- |
| frontend | Node.js 22.13+、pnpm 11、React 19、Vite 7、TypeScript |
| backend | Java 21、Spring Boot 4、Maven Wrapper |
| agent | Python 3.12、独立 Conda 环境 `airesearcher-agent` |
| infrastructure | Docker Compose MySQL 8.4 + Qdrant 1.19；不使用 Redis |

仓库任务不得顺带安装全局工具、修改 `PATH` 或改变 Conda `base`。首次部署、环境变量、
一键启动、停止与排错统一见 [Windows 本地部署与启动](deployment.md)。

## 2. 当前基线与验证

v0.1 单篇论文 Demo 的真实纵向切片已经实现：React 只调用 Java BFF，Java 转发到 Python
Agent；Python 使用 MySQL、PyMuPDF、真实 BGE 模型、Qdrant、DeepSeek 原生 Tool Calling 和
SSE。`FakeChatProvider` 仅供无外部依赖测试使用。

仓库级检查：

```powershell
git status --short --branch
git diff --check
git ls-files
git check-ignore -v --no-index .env .private/paper-library/originals/example.pdf frontend/node_modules/example.js
```

分应用检查：

```powershell
Set-Location contracts
npm ci
npm run validate

Set-Location ..\frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build

Set-Location ..\backend
.\mvnw.cmd verify

Set-Location ..\agent
conda run -n airesearcher-agent ruff check .
conda run -n airesearcher-agent ruff format --check .
conda run -n airesearcher-agent mypy
conda run -n airesearcher-agent python -m pytest
```

依赖安装和检查应按子系统顺序执行，不要让多个包管理器进程并发写入同一个依赖目录。
`.env`、私有数据、PDF、数据库、向量、模型和日志必须被忽略；只有 `.env.example` 可以提交。

## 3. 多 Chat 原则

Codex 从仓库根到当前目录叠加 `AGENTS.md`，越接近工作目录的规则越具体。每个 Chat 应从目标目录的边界开始工作，并遵守根规则和最近的子目录规则。

本地 `main` 是唯一集成入口，GitHub 远端不是日常任务交换通道。仓库保留以下长期本地分支和 Worktree：

| 分支 | 固定所有权 |
| --- | --- |
| `codex/frontend` | `frontend/**` 的实现和模块测试 |
| `codex/backend` | `backend/**` 的实现和模块测试 |
| `codex/agent` | `agent/**` 的实现、迁移、Worker 和模块测试 |
| `codex/docs` | `contracts/**`、`docs/**`、全部 `README.md`、全部 `AGENTS.md` 和 `.env.example` |
| `codex/test` | 仅根级 `tests/**` 的跨端测试、回归门禁和验收资产 |

长期分支只提供稳定工作环境，不是第二套主干，也不能积压多个未集成任务。固定生命周期为：

1. 确认 Local checkout 位于干净的本地 `main`；本地 `main` 可以领先 `origin/main`。
2. 长期分支接受新任务前必须没有未集成提交，并在对应 Worktree 执行 `git merge --ff-only main`；失败时停止，不得 rebase、reset 或强制更新。
3. Prompt 明确写出唯一目标、允许和禁止修改的路径、依赖的契约提交以及验收命令。
4. 一个 Chat 只处理一个边界明确的任务，完成检查后只提交自己的文件，并交接分支名、提交 SHA、变更范围、验证结果和未运行检查。
5. Local 集成 Chat 始终停留在 `main`，审查后使用 `git merge --no-ff <branch>` 按依赖顺序逐个合并。
6. 合并并验证后，对应长期分支执行 `git merge --ff-only main`，恢复到最新已接受基线，之后才能接收下一项任务。
7. Codex 不执行 `git push`、不创建 PR、不修改远端设置、不 rebase、不 reset、不强制更新或重写共享历史。用户在合适里程碑统一上传本地 `main`。

本仓库不创建 `.worktreeinclude`，因此被忽略的 `.env` 和本地凭据不会作为项目配置被复制。未来每个 Worktree 应从对应 `.env.example` 独立配置本地环境。

## 4. 临时功能分支与任务所有权

跨子系统、共享契约或共享根配置的功能使用临时分支族，每个切片由独立 Chat 和 Worktree 负责：

```text
codex/feature/<feature>-docs
codex/feature/<feature>-agent
codex/feature/<feature>-backend
codex/feature/<feature>-frontend
codex/feature/<feature>-runtime
codex/feature/<feature>-test
```

只创建功能实际需要的切片。所有临时分支都从最新已接受的本地 `main` 创建，不从长期分支或其他临时切片派生。契约切片先完成并合入 `main`；Agent、backend、frontend 等消费者再从包含该契约提交的 `main` 建立切片。一个临时分支只能由一个 Chat 使用，不能依赖其他 Chat 的未提交文件。

每个 Chat 的 Prompt 至少包含：

```text
目标：
允许修改：
禁止修改：
依赖的提交或契约版本：
必须运行的检查：
完成定义：
```

长期所有权之外的根启动脚本、`.gitignore`、基础设施和公共自动化没有默认长期所有者；需要修改时建立边界明确的临时 `runtime` 切片。共享路径包括：

- `contracts/**`
- 根级配置和 `AGENTS.md`
- 跨应用开发脚本
- GitHub Actions 公共工作流

未明确获得共享路径所有权的 Chat 不得修改这些文件。模块实现 Chat 必须同步维护模块内部测试；`codex/test` 和临时 `-test` 切片只修改根级 `tests/**`，发现模块缺陷时记录复现信息并退回对应实现 Chat，不能直接修补模块代码。

## 5. 契约先行顺序

任何跨进程接口按以下顺序推进：

1. `codex/docs` 或临时 `-docs` Chat 独占修改 OpenAPI、Schema、说明和示例并完成校验。
2. 文档与契约 Chat 提交本地任务分支，由 Local 集成 Chat 合入本地 `main`，记录契约版本或提交 SHA。
3. Agent、backend、frontend Chat 从包含该契约的本地 `main` 分别实现。
4. 集成 Chat 只处理跨端验证与必要的小型修复，不重新设计契约。

若实现发现契约问题，停止在该边界，返回 contracts 任务修订；不得由实现 Chat 私自改变 wire shape。

## 6. 本地提交、合并与发布

- 分支和提交信息使用英文，文档使用中文。
- Worktree Chat 在长期分支或 `codex/feature/<feature>-<slice>` 临时分支提交前，运行目标目录 `AGENTS.md` 指定的检查和 `git diff --check`。
- Worktree 交接说明必须列出本地分支、提交 SHA、变更范围、验证结果、未运行检查和兼容性影响。
- Local 集成 Chat 在 `main` 上先检查 `git status`、`git log main..<task-branch>` 和 `git diff --stat main...<task-branch>`，确认范围后使用 `git merge --no-ff <task-branch>` 串行合并。
- 合并冲突时不要猜测或在本地 `main` 临时重写设计；中止该次合并，报告冲突，并回到对应任务分支修复后再集成。
- 合并后运行受影响检查与 `git diff --check`，并报告本地 `main` 相对 `origin/main` 的领先提交数。
- Codex 不推送任何分支、不创建 PR、不修改远端设置。用户负责执行最终的 `git push origin main`。
- 长期分支和 Worktree 持续保留；在用户确认远端上传成功前保留临时功能分支。清理任何分支或 Worktree 都需要用户明确授权。
- 不提交其他 Chat 的工作，不重写已共享历史。

官方参考：

- [OpenAI Docs：AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenAI Docs：Git Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)
