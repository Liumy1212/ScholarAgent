# Windows 本地部署与运行

本文是 AIResearcher 当前唯一的完整本地运行说明，适用于 Windows 10/11 从源码首次部署和
后续再次运行。当前尚未提供 Linux/macOS 等价启动脚本，也没有全栈生产部署方案。

当前运行时使用 `AIRESEARCHER_PAPER_LIBRARY_DIR` 管理论文原件，默认值为仓库内被 Git
忽略的 `.private/paper-library`。扫描器实际递归遍历 `originals/`，网页/API 上传固定进入
`originals/uploads/`。三端已支持原件登记、扫描、状态筛选、手动入库、知识删除及兼容性
排除/恢复；以下步骤是本机端到端复验流程。

## 1. 环境与版本要求

| 工具或服务 | 要求 | 用途 |
| --- | --- | --- |
| Windows | Windows 10/11 | 当前支持的本地开发平台 |
| PowerShell | PowerShell 7，命令为 `pwsh` | 启动脚本和应用终端 |
| Git | 可使用 `git` 命令 | 验证本地原件库不会被提交 |
| Docker Desktop | 已启动，支持 Compose v2 | 运行 MySQL 与 Qdrant |
| Conda | Miniconda 或 Anaconda | 隔离 Python Agent 环境 |
| Python | 3.12 | Agent API、Worker 与 RAG |
| Java | JDK 21 | Spring Boot BFF |
| Node.js | 22.13.0 或更高 | React 工具链 |
| pnpm | 11.x | 前端依赖和脚本 |
| MySQL | Compose 固定 `mysql:8.4.11` | Agent 关系数据与任务 |
| Qdrant | Compose 固定 `qdrant/qdrant:v1.19.0` | chunk 向量 |

Java 使用仓库中的 Maven Wrapper，不需要全局安装 Maven。首次运行还需要：

- 可用的 DeepSeek API Key 和账户额度。
- 能访问 DeepSeek API 的网络。
- 能访问 Hugging Face 的网络，以下载 `BAAI/bge-m3` 和
  `BAAI/bge-reranker-v2-m3`。
- 足够的磁盘保存 Python/Java/Node 依赖和两个本地模型。
- 可选 CUDA GPU；`AIRESEARCHER_MODEL_DEVICE=auto` 会自动选择可用设备，CPU 也可以运行但
  首次建库和检索会更慢。

项目默认占用以下本机端口：

| 端口 | 服务 |
| --- | --- |
| `3306` | MySQL |
| `6333` | Qdrant HTTP |
| `6334` | Qdrant gRPC |
| `8000` | Python Agent API |
| `8080` | Java BFF |
| `5173` | React |

## 2. 首次部署

以下命令均从仓库根目录执行。先进入实际仓库路径，例如：

```powershell
Set-Location C:\path\to\AIResearcher
```

### 2.1 检查本机工具

```powershell
pwsh --version
docker version
docker compose version
conda --version
java -version
node --version
pnpm --version
```

确认：

- `docker version` 同时显示 Client 和 Server，只有 Client 通常表示 Docker daemon 未启动。
- `java -version` 指向 JDK 21，`JAVA_HOME` 没有指向其他 JDK。
- Node.js 不低于 22.13.0，pnpm 主版本为 11。

### 2.2 创建 Python 隔离环境

不要安装到 Conda `base`：

```powershell
conda create -n airesearcher-agent python=3.12 -y
conda run -n airesearcher-agent python -m pip install -e ".\agent[dev]"
```

验证核心依赖可以导入：

```powershell
conda run -n airesearcher-agent python -c "import airesearcher_agent, alembic, uvicorn"
```

### 2.3 安装前端依赖

```powershell
Set-Location .\frontend
pnpm install --frozen-lockfile
Set-Location ..
```

Java 第一次启动时 Maven Wrapper 会下载依赖到用户 Maven 缓存，无须预先安装 Maven。

### 2.4 创建本机配置

```powershell
Copy-Item .\.env.example .\.env
```

`.env` 已被 Git 忽略。不要提交、粘贴或打印其中的秘密。

#### 必须填写

| 变量 | 要求 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 替换为真实 API Key，不能保留模板占位符 |
| `AIRESEARCHER_DB_PASSWORD` | MySQL 应用用户随机密码 |
| `AIRESEARCHER_DB_ROOT_PASSWORD` | 与应用密码不同的 MySQL root 随机密码 |
| `AIRESEARCHER_PAPER_LIBRARY_DIR` | 必须位于仓库的 `.private/` 子目录并被 Git 忽略 |
| `AIRESEARCHER_MODEL_CACHE_DIR` | embedding/reranker 缓存，必须位于仓库外 |

可以用以下命令分别生成两个不同密码：

```powershell
([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')).Substring(0,48)
```

推荐保持模板中的受控相对路径；Windows 仓库外路径建议使用正斜杠：

```dotenv
AIRESEARCHER_PAPER_LIBRARY_DIR=.private/paper-library
AIRESEARCHER_MODEL_CACHE_DIR=C:/Users/your-name/.cache/airesearcher/models
```

正常启动会创建：

```text
.private/paper-library/
├─ originals/          用户管理的 PDF 原件
│  └─ uploads/         网页/API 上传的原件
└─ .staging/           上传校验与原子落盘暂存
```

`-CheckOnly` 不会创建这些目录。`AIRESEARCHER_STORAGE_DIR` 仅在旧数据迁移期间可选保留，
新上传不会再写入该目录。

#### 数据库与 Qdrant

| 变量 | 默认用途 |
| --- | --- |
| `AIRESEARCHER_DB_HOST` | `127.0.0.1` |
| `AIRESEARCHER_DB_PORT` | `3306` |
| `AIRESEARCHER_DB_NAME` | `airesearcher_agent` |
| `AIRESEARCHER_DB_USER` | `airesearcher` |
| `AIRESEARCHER_QDRANT_URL` | `http://127.0.0.1:6333` |
| `AIRESEARCHER_QDRANT_COLLECTION` | `airesearcher_chunks_v1` |

MySQL 初始化变量只在空 named volume 第一次创建时生效。修改 `.env` 不会自动修改已有
volume 内的账户或密码。

#### 模型与连接参数

| 变量 | 默认值或说明 |
| --- | --- |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` |
| `AIRESEARCHER_EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `AIRESEARCHER_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `AIRESEARCHER_MODEL_DEVICE` | `auto`，可改为 `cpu` |
| `AIRESEARCHER_VECTOR_SIZE` | `1024`，必须与 embedding 和 collection 一致 |
| `AIRESEARCHER_AGENT_BASE_URL` | Java 调用 Agent 的 `http://127.0.0.1:8000` |
| `AIRESEARCHER_AGENT_CONNECT_TIMEOUT` | Java 下游连接超时，默认 `2s` |
| `AIRESEARCHER_AGENT_OPEN_TIMEOUT` | Java 等待 SSE 建流超时，默认 `5s` |
| `AIRESEARCHER_SSE_EMITTER_TIMEOUT` | Java SSE emitter 超时，`0ms` 表示不由 emitter 主动超时 |
| `VITE_API_PROXY_TARGET` | Vite 代理目标 `http://127.0.0.1:8080` |

不要随意修改模型名或 `AIRESEARCHER_VECTOR_SIZE`。已有 Qdrant collection 的向量维度不会
随 `.env` 自动迁移。

### 2.5 只读启动检查

```powershell
.\scripts\start-dev.ps1 -CheckOnly
```

此命令会检查：

1. `.env` 语法、必填变量和占位符。
2. 两个数据库密码是否不同。
3. 原件库是否位于仓库的 `.private/` 子目录且确实被 Git 忽略，模型缓存是否位于仓库外。
4. PowerShell、Git、Docker、Conda、Java、Node.js、pnpm 和 Maven Wrapper。
5. Agent 与 Frontend 依赖。
6. Compose 配置。

`-CheckOnly` 不启动容器、执行迁移或创建运行目录。

### 2.6 一键启动

检查通过后执行：

```powershell
.\scripts\start-dev.ps1
```

脚本按以下顺序工作：

1. 再次校验配置、原件库边界、Git 忽略规则、工具和项目依赖。
2. 创建原件库的 `originals/` 与 `.staging/`。
3. 确认 Agent、Java 和 React 端口未被占用。
4. 启动 MySQL 与 Qdrant，并等待健康检查。
5. 执行 `alembic upgrade head`。
6. 分别打开 Agent API、Worker、Java BFF 和 React 的 PowerShell 终端。

启动命令可以从任意当前目录调用，也可以显式指定其他环境文件：

```powershell
C:\path\to\AIResearcher\scripts\start-dev.ps1 -EnvFile C:\private\airesearcher.env
```

首次处理论文时会下载并加载 embedding 与 reranker 模型，耗时取决于网络、磁盘和计算设备。
观察 Worker 终端确认下载和入库进度，不要在此时重复启动多个 Worker。

## 3. 验证首次部署

### 3.1 服务健康

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8080/api/v1/library
Invoke-RestMethod http://127.0.0.1:8080/api/v1/papers
Invoke-WebRequest http://127.0.0.1:5173 -UseBasicParsing
```

Compose 中 MySQL 应显示 `healthy`，Qdrant 健康端点应返回成功。

### 3.2 原件库与 RAG 冒烟

先在仓库外生成合成 PDF，再复制到原件库；生成器会拒绝直接写入仓库：

```powershell
$demoPdf = Join-Path $env:TEMP 'airesearcher-demo.pdf'
conda run -n airesearcher-agent python .\scripts\generate_demo_pdf.py $demoPdf
New-Item -ItemType Directory .\.private\paper-library\originals\smoke -Force
Copy-Item -LiteralPath $demoPdf -Destination .\.private\paper-library\originals\smoke\demo.pdf
```

随后通过 React 页面和 Java API 执行以下闭环：

1. 在页面上传一份唯一命名的合成 PDF，确认响应路径位于 `uploads/`，磁盘原件存在，页面
   立即显示“尚未存入知识库”。
2. 将另一份唯一命名的合成 PDF 复制到 `originals/` 的测试子目录，点击“扫描文件夹”，轮询
   `scanId` 到 `SUCCEEDED`，确认新原件出现且未自动创建入库任务。
3. 分别请求不带筛选、`libraryState=NOT_INGESTED`、`ORIGINAL_MISSING` 和 `INGESTED` 的列表，
   核对每页 `items`、`total` 与分页边界。
4. 对单篇调用 `POST /api/v1/library/files/{libraryFileId}/ingestion`，等待任务和 Paper 到
   `READY`，确认它进入“已存入知识库”筛选并可在 Chat 中检索与引用。
5. 将已入库的测试 PDF 移出 `originals/` 后再次扫描，确认行变为 `MISSING`、Paper/chunk/向量
   没有被扫描自动删除，但该 Paper 立即退出 Chat 可检索范围。
6. 对缺失行调用 `DELETE /api/v1/papers/{paperId}`，确认 Paper、任务、chunk、向量和缺失登记
   被清理。
7. 对另一篇原件仍存在的已入库测试论文调用同一删除接口，确认 PDF 仍在、原件行回到
   `AVAILABLE + NOT_INGESTED`。
8. 对活动任务验证 `409 PAPER_BUSY`；若模拟 Qdrant 故障，确认返回可重试错误、Paper 保持
   不可检索、原件不受影响，服务恢复后重复删除可完成。

复验只能使用合成或用户明确有权处理的论文；测试文件使用唯一名称，且不得通过清空数据库、
Qdrant volume 或原件目录来准备环境。知识删除不等于原件删除：它只清理数据库知识对象和向量，
不会删除或移动任何仍存在的 PDF。

上述闭环已经用仓库外生成的两份合成 PDF 完成全栈验收，覆盖上传、扫描、三类筛选、入库、
Chat 检索与页码引用、原件缺失同步，以及缺失/可用两种状态下的知识删除边界。

## 4. 后续再次运行

已有 `.env`、依赖和 named volume 时：

1. 启动 Docker Desktop，等待 daemon 可用。
2. 确认 `3306`、`6333`、`6334`、`8000`、`8080`、`5173` 没有被其他程序占用。
3. 如果 `.env`、依赖、JDK、Node、Docker 或项目代码发生变化，先运行：

   ```powershell
   .\scripts\start-dev.ps1 -CheckOnly
   ```

4. 启动：

   ```powershell
   .\scripts\start-dev.ps1
   ```

脚本每次都会执行幂等的 `alembic upgrade head`。普通停止不会删除 MySQL/Qdrant named
volume，也不会删除 `AIRESEARCHER_PAPER_LIBRARY_DIR` 中的原件或模型缓存。

若只有单个应用代码发生变化，可以在对应应用终端按 `Ctrl+C` 后重新运行该应用命令；
不需要重建 MySQL、Qdrant 或其他应用。

## 5. 正常停止

在 Agent API、Worker、Java 和 React 四个应用终端中分别按 `Ctrl+C`。确认应用退出后，从
仓库根目录停止基础设施：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml down
```

该命令停止并移除 Compose 容器，但保留 named volume。下一次执行启动脚本会重新创建容器并
复用数据。

永久删除 volume、storage 或模型缓存不属于普通停止流程。需要清空数据时必须先备份、确认
精确目标和影响，再由用户单独执行；本项目不会把危险清理命令放入启动或停止脚本。

## 6. 手动启动附录

一键脚本是推荐入口。只有需要单独调试服务或定位启动失败时才使用以下流程。

### 6.1 在当前 PowerShell 加载 `.env`

以下代码跳过空行和注释，按第一个 `=` 分割变量，并且不打印值：

```powershell
Get-Content -LiteralPath .\.env | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) {
        return
    }
    $name, $value = $line -split '=', 2
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}
```

每个新开的应用终端都需要从仓库根目录加载一次 `.env`，或者从已经加载环境变量的父
PowerShell 启动子进程。不要使用会把全部环境变量输出到终端或日志的命令。

### 6.2 启动基础设施

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql qdrant
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps
```

等待 MySQL 显示 `healthy`，并验证 Qdrant：

```powershell
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
```

### 6.3 执行数据库迁移

在已加载 `.env` 的终端中：

```powershell
Set-Location .\agent
conda run -n airesearcher-agent alembic upgrade head
Set-Location ..
```

### 6.4 分别启动四个应用

每项使用独立 PowerShell，并先加载 `.env`。

Agent API，从仓库根目录运行：

```powershell
conda run -n airesearcher-agent python -m uvicorn airesearcher_agent.main:app `
    --app-dir .\agent\src --host 127.0.0.1 --port 8000
```

Worker，从仓库根目录运行：

```powershell
conda run -n airesearcher-agent python -m airesearcher_agent.worker.main
```

Java BFF：

```powershell
Set-Location .\backend
.\mvnw.cmd spring-boot:run
```

React：

```powershell
Set-Location .\frontend
pnpm dev
```

推荐启动顺序为 Agent API、Worker、Java、React。单独重启一个应用时只在对应终端按
`Ctrl+C` 并重跑命令；数据库迁移只需在 schema 或迁移文件变化后重新执行。

## 7. 数据位置与备份边界

| 数据 | 默认或配置位置 | 普通 `down` 是否保留 |
| --- | --- | --- |
| PDF 原件 | `AIRESEARCHER_PAPER_LIBRARY_DIR/originals/`；网页上传位于其 `uploads/` 子目录 | 是 |
| 上传暂存 | `AIRESEARCHER_PAPER_LIBRARY_DIR/.staging/` | 是 |
| embedding/reranker | `AIRESEARCHER_MODEL_CACHE_DIR` | 是 |
| MySQL | `airesearcher_mysql_data` named volume | 是 |
| Qdrant | `airesearcher_qdrant_data` named volume | 是 |
| 本机配置 | 根目录 `.env` | 是 |

备份至少需要覆盖原件库、MySQL 和 Qdrant。只备份数据库而不备份 PDF，或只备份 PDF
而不保留数据库/向量，都不能完整恢复当前知识库。

## 8. 从旧 PDF storage 迁移

迁移不会自动移动或删除任何文件，也不会自动清理数据库或向量。开始前必须停止四个应用，
并分别备份旧 `AIRESEARCHER_STORAGE_DIR`、MySQL 和 Qdrant。

1. 在现有 `.env` 中新增 `AIRESEARCHER_PAPER_LIBRARY_DIR=.private/paper-library`；迁移验证完成前
   保留原 `AIRESEARCHER_STORAGE_DIR`。
2. 运行 `start-dev.ps1 -CheckOnly`，确认新目录边界与 Git 忽略规则通过。
3. 正常启动一次，让 Alembic 升级到最新 schema 并创建 `originals/`、`.staging/`。
4. 使用 `Copy-Item` 把需要保留的旧 PDF 复制到 `originals/` 下自选子目录；不要使用移动或
   删除命令，也不要复制旧上传临时文件。
5. 创建并完成一次扫描。扫描会按 SHA-256 把复制原件关联到既有 Paper，不重新创建 Paper、
   入库任务、chunk 或向量。
6. 核对原件数量、相对路径、Paper 关联和抽样 PDF 预览。没有匹配到可用原件的旧论文显示为
   `MISSING` 且不可检索；不要在未查明原因前删除其旧文件或数据库记录。
7. 只有备份和关联验证都完成后，才可从日常配置中移除可选的
   `AIRESEARCHER_STORAGE_DIR`。本项目不会删除旧目录。

## 9. 常见问题

### 原件库路径校验失败

保持 `AIRESEARCHER_PAPER_LIBRARY_DIR=.private/paper-library`，并确认仓库根 `.gitignore` 仍
包含 `/.private/`。不要把原件库改到仓库其他目录，也不要强制添加其中的 PDF。

### API Key 或密码仍是占位符

编辑 `.env`，替换 `DEEPSEEK_API_KEY` 和两个数据库密码。两个数据库密码必须不同，启动
脚本不会输出其值。

### Docker Desktop 未启动

运行 `docker version`。只有 Client 信息、连接管道失败或找不到 Server 通常表示 daemon
尚未就绪。启动 Docker Desktop 后重试。

### 找不到 Conda 环境或 Agent 依赖

重新执行首次部署中的 Conda 创建和 `pip install -e ".\agent[dev]"`。不要安装到 Conda
`base`，也不要通过修改全局 `PATH` 绕过问题。

### Frontend 依赖缺失

```powershell
Set-Location .\frontend
pnpm install --frozen-lockfile
Set-Location ..
```

### 端口被占用

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 3306,6333,6334,8000,8080,5173 |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

停止旧的项目进程或冲突服务后重试。不要为了释放端口删除数据库数据。

### MySQL 账户或密码错误

先确认 MySQL 容器为 `healthy`。MySQL 初始化密码只在空 volume 第一次创建时生效；修改
`.env` 不会自动轮换已有账户。恢复原密码或使用明确的 MySQL 管理流程轮换，不要直接删除
volume 排错。

### 首次模型下载或加载失败

确认 Hugging Face 网络、仓库外模型缓存目录、磁盘空间和目录写权限。GPU 显存不足时可将
`AIRESEARCHER_MODEL_DEVICE` 改为 `cpu`；CPU 会更慢，但不应切换为 Fake 运行数据。

### Qdrant collection 维度不匹配

确认 embedding 模型与 `AIRESEARCHER_VECTOR_SIZE` 没有在已有 collection 上被单独修改。
索引迁移必须作为明确任务处理，启动脚本不会自动删除或重建 collection。

### DeepSeek 请求失败

检查 API Key、账户额度、`DEEPSEEK_BASE_URL`、模型名和网络。真实运行失败不会自动切换到
`FakeChatProvider`。

### 服务启动但 Web 无法访问

按顺序检查 React 终端、Java BFF、Agent API、MySQL 和 Qdrant。确认
`VITE_API_PROXY_TARGET` 指向 Java，`AIRESEARCHER_AGENT_BASE_URL` 指向 Agent，并查看各终端
中同一请求 ID 的错误信息。
