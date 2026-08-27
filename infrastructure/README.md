# Infrastructure

此目录只保存本地开发基础设施的可提交配置，不保存运行数据。

## 服务与数据边界

Compose 提供以下开发服务：

- MySQL `mysql:8.4.11`，只绑定 `127.0.0.1:3306`。
- Qdrant `qdrant/qdrant:v1.19.0`，只绑定 `127.0.0.1:6333/6334`。

MySQL 与 Qdrant 分别使用 Docker named volume `airesearcher_mysql_data` 和
`airesearcher_qdrant_data`。它们均不位于仓库；PDF、模型缓存和日志也必须保存在仓库外。
开发环境默认使用这里定义的容器 MySQL，不启动宿主机 MySQL；本地开发不使用 Redis。

## 准备本机环境

从仓库根目录复制模板并填写真实值。密码应使用不含空格的随机 URL-safe 字符串：

```powershell
Copy-Item .\.env.example .\.env
```

`.env` 已被 Git 忽略。Compose 通过 `--env-file .\.env` 读取它；Agent、Alembic、Java 和
React 不会自动加载该文件。启动 Alembic、Agent API 或 Worker 前，可在对应父 PowerShell 中
无回显地加载应用变量，同时排除仅供 Compose 使用的 root 密码：

```powershell
Get-Content -LiteralPath .\.env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2]
        if ($name -ne 'AIRESEARCHER_DB_ROOT_PASSWORD') {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}
```

上述代码块必须在每个将要启动 Alembic、Agent API 或 Worker 的父 PowerShell 中执行；一个
终端内设置的进程环境变量不会自动传给后来独立打开的终端。Java 和 React 不需要数据库变量；
若不使用默认地址，只向各自进程设置 `AIRESEARCHER_AGENT_*` 或
`VITE_API_PROXY_TARGET` 等本应用需要的变量。

## 定位 Docker CLI

以下命令只为当前 PowerShell 定位 Docker CLI，不会修改全局 `PATH`。如果 `docker` 已经可用，
会直接复用现有命令；否则依次检查 Docker Desktop 常见的当前用户和系统安装位置：

```powershell
$DockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$DockerCli = if ($DockerCommand) {
    $DockerCommand.Source
} else {
    @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $DockerCli) {
    throw '未找到 Docker CLI；请先确认 Docker Desktop 已启动。'
}
```

## 启动与迁移

在干净环境中启动两个服务，并等待 MySQL 显示为 `healthy`：

```powershell
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml config --quiet
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql qdrant
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml ps
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
```

如果 Qdrant 已由其他容器提供，只启动 MySQL，避免争用 6333/6334：

```powershell
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml ps mysql
```

官方 MySQL 镜像只负责在空卷中创建数据库和应用用户；业务表始终由 Alembic 创建。先在同一
PowerShell 中按上一节加载应用变量，再执行：

```powershell
Set-Location .\agent
conda run -n airesearcher-agent alembic upgrade head
conda run -n airesearcher-agent alembic current
Set-Location ..
```

`MYSQL_DATABASE`、`MYSQL_USER` 和密码等初始化变量只对空数据卷生效。修改 `.env` 不会自动
修改已有卷内的账户或密码；需要轮换时应通过 MySQL 管理命令显式处理。

## 停止、持久化与回退

停止单个服务或删除 Compose 容器不会删除 named volume：

```powershell
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml stop mysql
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml down
```

删除 volume 会永久删除本机 Demo 数据，因此本仓库不提供自动删除命令，也不要默认使用
`down --volumes`。

Windows 上若本机 `MySQL80` 已占用 3306，应在管理员 PowerShell 中停止它并改为手动启动；
这不会删除本机 MySQL 数据：

```powershell
Stop-Service -Name MySQL80
Set-Service -Name MySQL80 -StartupType Manual
Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
```

最后一条命令无输出表示当前没有进程监听 3306；确认端口释放后再启动容器 MySQL。

如需恢复本机 MySQL，先停止容器以释放 3306，再在管理员 PowerShell 中恢复服务：

```powershell
& $DockerCli compose --env-file .\.env -f .\infrastructure\compose.yaml stop mysql
Set-Service -Name MySQL80 -StartupType Automatic
Start-Service -Name MySQL80
```

更多应用启动顺序见 [开发环境说明](../docs/development.md)。
