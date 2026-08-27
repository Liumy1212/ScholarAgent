# Windows 本地部署与启动

本文是 AIResearcher 当前唯一的本地运行入口。适用于从源码在 Windows 上开发和体验
v0.1 Demo；当前版本尚未提供全栈 Docker 生产部署。

## 1. 环境要求

| 工具 | 要求 | 用途 |
| --- | --- | --- |
| Windows | Windows 10/11 | 当前支持的本地开发平台 |
| PowerShell | PowerShell 7，命令为 `pwsh` | 一键启动和独立服务终端 |
| Docker Desktop | 已启动，支持 `docker compose` | MySQL 8.4 与 Qdrant 1.19 |
| Conda | Miniconda 或 Anaconda | 隔离 Python Agent 环境 |
| Python | 3.12 | Agent API、Worker、RAG |
| Java | JDK 21 | Spring Boot BFF |
| Node.js | 22.13 或更高 | React 开发服务器 |
| pnpm | 11.x | 前端依赖与脚本 |

Java 使用仓库内 Maven Wrapper，不需要全局 Maven。先确认基础命令可用：

```powershell
pwsh --version
docker version
conda --version
java -version
node --version
pnpm --version
```

Docker Desktop 必须已经运行。公开的 BGE embedding 与 reranker 模型会在首次入库、检索时下载，
需要可访问 Hugging Face 的网络和足够磁盘空间；CUDA 可选，`auto` 会优先使用 GPU，并在单个
模型显存不足时回退 CPU。

## 2. 首次准备

以下命令均从仓库根目录执行。创建独立 Python 3.12 环境并安装 Agent：

```powershell
conda create -n airesearcher-agent python=3.12 -y
conda run -n airesearcher-agent python -m pip install -e ".\agent[dev]"
```

安装前端依赖：

```powershell
Set-Location .\frontend
pnpm install --frozen-lockfile
Set-Location ..
```

Java 第一次启动时 Maven Wrapper 会把依赖下载到用户 Maven 缓存，无须提前安装。

### 创建本机配置

```powershell
Copy-Item .\.env.example .\.env
```

`.env` 已被 Git 忽略。必须修改：

| 变量 | 填写要求 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 真实 DeepSeek API Key，不得保留模板占位符 |
| `AIRESEARCHER_DB_PASSWORD` | MySQL 应用用户随机密码 |
| `AIRESEARCHER_DB_ROOT_PASSWORD` | 与应用密码不同的 MySQL root 随机密码 |
| `AIRESEARCHER_STORAGE_DIR` | 仓库外 PDF/上传目录 |
| `AIRESEARCHER_MODEL_CACHE_DIR` | 仓库外模型缓存目录 |

可以用以下命令生成密码，每执行一次生成一个新值：

```powershell
([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')).Substring(0,48)
```

Windows 路径建议写成正斜杠，例如：

```dotenv
AIRESEARCHER_STORAGE_DIR=C:/Users/your-name/.airesearcher/storage
AIRESEARCHER_MODEL_CACHE_DIR=C:/Users/your-name/.cache/airesearcher/models
```

其余地址、端口、模型名和向量维度可保持模板默认值。MySQL 初始化变量只在 named volume
第一次创建时生效；已有卷不会因为修改 `.env` 自动更改账户密码。

## 3. 日常启动

先做不产生运行时变更的检查：

```powershell
.\scripts\start-dev.ps1 -CheckOnly
```

检查通过后，一条命令启动完整环境：

```powershell
.\scripts\start-dev.ps1
```

脚本会：

1. 校验 `.env`、工具版本和项目依赖，不输出秘密。
2. 启动 MySQL 与 Qdrant，并等待健康。
3. 执行 Alembic `upgrade head`。
4. 打开 Agent API、Worker、Java BFF 和 React 四个独立 PowerShell 终端。

脚本可从任意当前目录调用；需要使用其他配置文件时可显式传入：

```powershell
D:\AIResearcher\scripts\start-dev.ps1 -EnvFile D:\private\airesearcher.env
```

启动完成后访问 <http://127.0.0.1:5173>。首次处理论文可能需要较长时间下载和加载
`BAAI/bge-m3` 与 `BAAI/bge-reranker-v2-m3`，Worker 终端会显示进度。

## 4. 验证服务

```powershell
# Compose 状态；mysql 应显示 healthy
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps

# Qdrant
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing

# Agent API
Invoke-RestMethod http://127.0.0.1:8000/health

# Java BFF 论文列表代理
Invoke-RestMethod http://127.0.0.1:8080/api/v1/papers
```

最终在 Web 上传一篇文本型 PDF，等待状态进入 `READY`，再提出与论文相关的问题；正常情况
下页面会显示检索、重排状态、流式回答和可跳转页码引用。

## 5. 停止与数据位置

在四个应用终端中分别按 `Ctrl+C`。随后从仓库根目录停止基础设施：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml down
```

`down` 不删除数据。MySQL 与 Qdrant 分别保存在 Docker named volume
`airesearcher_mysql_data`、`airesearcher_qdrant_data`；PDF 与模型缓存在 `.env` 指定的仓库
外目录。不要使用 `down --volumes`，除非明确要永久删除本机 Demo 数据。

## 6. 常见问题

### 脚本提示 API Key 仍是占位符

编辑根目录 `.env`，替换 `DEEPSEEK_API_KEY=replace-with-your-deepseek-api-key`。脚本不会
接受占位符，也不会把 Key 打印到终端。

### Docker 不可用

先启动 Docker Desktop，再运行 `docker version`。只有 Client 信息而没有 Server 信息通常
表示 daemon 尚未就绪。

### 找不到 Conda 环境或 Agent 依赖

重新执行“首次准备”中的 Conda 创建和 `pip install -e` 命令；不要安装到 Conda `base`。

### 3306、6333、6334、8000、8080 或 5173 被占用

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 3306,6333,6334,8000,8080,5173 |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

停止旧的项目进程或冲突服务后重试。本机 `MySQL80` 占用 3306 时，可在管理员 PowerShell
中暂时停止该服务；不要删除其数据。

### Alembic 报账户或连接错误

先确认 MySQL 为 `healthy`。若 named volume 已用旧密码初始化，修改 `.env` 不会更新卷内
账户；应恢复原密码或通过 MySQL 管理命令显式轮换，不要为了排错直接删除 volume。

### 首次模型下载或加载失败

确认模型缓存目录可写、位于仓库外且磁盘充足，并检查 Hugging Face 网络访问。GPU 显存不足
可把 `AIRESEARCHER_MODEL_DEVICE` 改为 `cpu`；CPU 模式会更慢，但不应改用 Fake 数据。

### DeepSeek 请求失败

检查 API Key、账户额度、`DEEPSEEK_BASE_URL` 和网络。模型调用失败不会自动切换到
`FakeChatProvider`。

## 7. 开发检查

契约、前端、Java 和 Agent 的完整检查命令，以及多 Chat/Worktree 协作规则，见
[开发流程](development.md)。
