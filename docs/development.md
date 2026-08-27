# 开发环境与多 Chat 工作流

## 1. 工具基线

当前应用基线：

| 区域 | 基线 |
| --- | --- |
| frontend | Node.js 22.13+、pnpm 11、React 19、Vite 7、TypeScript |
| backend | Java 21、Spring Boot 4、Maven Wrapper |
| agent | Python 3.12、独立 Conda 环境 `airesearcher-agent` |
| infrastructure | Docker Compose MySQL 8.4 + Qdrant 1.19；不使用 Redis |

仓库任务不得顺带安装全局工具、修改 `PATH` 或改变 Conda `base`。Java 使用 Maven Wrapper；Python 使用独立环境；前端以仓库锁文件为准。

## 2. 当前基线

v0.1 单篇论文 Demo 的真实纵向切片已经实现：React 只调用 Java BFF，Java 转发到 Python Agent；Python 使用 MySQL、PyMuPDF、真实 BGE 模型、Qdrant、DeepSeek 原生 Tool Calling 和 SSE。`FakeChatProvider` 仅供不依赖外部服务的测试使用。

真实运行数据必须位于仓库外。根目录 `.env.example` 只是键名和占位值；复制得到的 `.env`
由 Compose 通过 `--env-file` 读取，但应用不会自动加载它。启动 Alembic、API 与 Worker 前，应在
各自父 shell 中无回显地加载应用变量，并排除 Compose 专用的
`AIRESEARCHER_DB_ROOT_PASSWORD`。完整命令和回退方式见
[Infrastructure](../infrastructure/README.md)。

本机启动顺序：

```powershell
# 1. 安装 Agent，并启动容器化 MySQL 与 Qdrant
conda run -n airesearcher-agent python -m pip install -e ".\agent[dev]"
docker compose --env-file .\.env -f .\infrastructure\compose.yaml config --quiet
docker compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql qdrant
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps

# 2. 在当前 PowerShell 中加载应用变量；不加载 MySQL root 密码
Get-Content -LiteralPath .\.env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2]
        if ($name -ne 'AIRESEARCHER_DB_ROOT_PASSWORD') {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

# 3. MySQL healthy 后更新 schema
Set-Location .\agent
conda run -n airesearcher-agent alembic upgrade head
Set-Location ..

# 4. 分别在四个已加载所需变量的终端启动 Agent API、Worker、Java BFF 与 React
conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app --app-dir .\agent\src --host 127.0.0.1 --port 8000
conda run -n airesearcher-agent python -m airesearcher_agent.worker.main

Set-Location .\backend
.\mvnw.cmd spring-boot:run

Set-Location .\frontend
pnpm dev
```

启动后浏览器访问 `http://127.0.0.1:5173`。首次入库和首次问答会把公开 BGE 模型下载到外部模型缓存；`auto` 设备策略优先 CUDA，单个模型显存不足时回退 CPU。

仓库级检查：

```powershell
git status --short --branch
git diff --check
git ls-files
git check-ignore -v --no-index .env .private/example.pdf agent/storage/example.db frontend/node_modules/example.js
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

`.env.example` 应保持可提交；`.env`、私有数据、PDF、数据库、向量、模型和日志必须被忽略。

## 3. 多 Chat 原则

Codex 从仓库根到当前目录叠加 `AGENTS.md`，越接近工作目录的规则越具体。每个 Chat 应从目标目录的边界开始工作，并遵守根规则和最近的子目录规则。

并行任务使用独立 Worktree，本地 `main` 是唯一集成入口，GitHub 远端不是日常任务交换通道：

1. 确认 Local checkout 位于干净的本地 `main`；本地 `main` 可以领先 `origin/main`。
2. 在 Codex 新 Chat 中选择 Worktree，并以最新本地 `main` 为起点，不以滞后的 `origin/main` 为起点。
3. Prompt 明确写出目标、允许修改的路径、禁止修改的共享路径和验收命令。
4. 一个 Chat 只处理一个边界明确的任务；不要在同一任务顺手修改另一个应用。
5. Worktree Chat 创建或使用 `codex/<task>` 本地分支，完成检查后只提交自己的文件；不得推送分支或创建 PR。
6. Worktree Chat 交接分支名、提交 SHA、变更范围和验证结果；不要让其他 Chat 依赖未提交文件。
7. Local 集成 Chat 始终停留在 `main`，检查任务分支后按依赖顺序逐个合并，不在 Local 检出仍由 Worktree 占用的任务分支。
8. 每次本地合并后运行相关检查；后续 Chat 必须从更新后的本地 `main` 新建或显式同步。
9. Codex 不执行任何 `git push`。用户在合适的里程碑统一把本地 `main` 上传到 GitHub。

本仓库不创建 `.worktreeinclude`，因此被忽略的 `.env` 和本地凭据不会作为项目配置被复制。未来每个 Worktree 应从对应 `.env.example` 独立配置本地环境。

## 4. 任务所有权

每个 Chat 的 Prompt 至少包含：

```text
目标：
允许修改：
禁止修改：
依赖的提交或契约版本：
必须运行的检查：
完成定义：
```

共享路径包括：

- `contracts/**`
- 根级配置和 `AGENTS.md`
- 跨应用开发脚本
- GitHub Actions 公共工作流

未明确获得共享路径所有权的 Chat 不得修改这些文件。

## 5. 契约先行顺序

任何跨进程接口按以下顺序推进：

1. 独立 contracts Chat 修改 OpenAPI、Schema、说明和示例并完成校验。
2. contracts Chat 提交本地任务分支，由 Local 集成 Chat 合入本地 `main`，记录契约版本或提交 SHA。
3. Agent、backend、frontend Chat 从包含该契约的本地 `main` 分别实现。
4. 集成 Chat 只处理跨端验证与必要的小型修复，不重新设计契约。

若实现发现契约问题，停止在该边界，返回 contracts 任务修订；不得由实现 Chat 私自改变 wire shape。

## 6. 本地提交、合并与发布

- 分支和提交信息使用英文，文档使用中文。
- Worktree Chat 在 `codex/<task>` 分支提交前，运行目标目录 `AGENTS.md` 指定的检查和 `git diff --check`。
- Worktree 交接说明必须列出本地分支、提交 SHA、变更范围、验证结果、未运行检查和兼容性影响。
- Local 集成 Chat 在 `main` 上先检查 `git status`、`git log main..<task-branch>` 和 `git diff --stat main...<task-branch>`，确认范围后使用 `git merge --no-ff <task-branch>` 串行合并。
- 合并冲突时不要猜测或在本地 `main` 临时重写设计；中止该次合并，报告冲突，并回到对应任务分支修复后再集成。
- 合并后运行受影响检查与 `git diff --check`，并报告本地 `main` 相对 `origin/main` 的领先提交数。
- Codex 不推送任何分支、不创建 PR、不修改远端设置。用户负责执行最终的 `git push origin main`。
- 在用户确认远端上传成功前保留本地任务分支；清理分支或 Worktree 需要用户明确授权。
- 不提交其他 Chat 的工作，不重写已共享历史。

官方参考：

- [OpenAI Docs：AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenAI Docs：Git Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)
