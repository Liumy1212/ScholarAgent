# Infrastructure

此目录只保存本地开发基础设施的可提交配置，不保存运行数据。

## 服务与数据边界

Compose 提供以下开发服务：

- MySQL `mysql:8.4.11`，只绑定 `127.0.0.1:3306`。
- Qdrant `qdrant/qdrant:v1.19.0`，只绑定 `127.0.0.1:6333/6334`。

MySQL 与 Qdrant 分别使用 Docker named volume `airesearcher_mysql_data` 和
`airesearcher_qdrant_data`。它们均不位于仓库；PDF、模型缓存和日志也必须保存在仓库外。
本地开发不使用 Redis。

## 准备本机环境

从仓库根目录复制模板并填写真实值。密码应使用不含空格的随机 URL-safe 字符串：

```powershell
Copy-Item .\.env.example .\.env
```

`.env` 已被 Git 忽略。Compose 通过 `--env-file .\.env` 读取它；Agent、Alembic、Java 和
React 不会自动加载该文件。启动应用前，可在对应父 PowerShell 中无回显地加载变量，同时排除
仅供 Compose 使用的 root 密码：

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

## 启动与迁移

在干净环境中启动两个服务，并等待 MySQL 显示为 `healthy`：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml config --quiet
docker compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql qdrant
docker compose --env-file .\.env -f .\infrastructure\compose.yaml ps
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
```

如果 Qdrant 已由其他容器提供，只启动 MySQL，避免争用 6333/6334：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml up -d mysql
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
docker compose --env-file .\.env -f .\infrastructure\compose.yaml stop mysql
docker compose --env-file .\.env -f .\infrastructure\compose.yaml down
```

删除 volume 会永久删除本机 Demo 数据，因此本仓库不提供自动删除命令，也不要默认使用
`down --volumes`。

Windows 上若本机 `MySQL80` 已占用 3306，应在管理员 PowerShell 中停止它并改为手动启动；
这不会删除本机 MySQL 数据：

```powershell
Stop-Service -Name MySQL80
Set-Service -Name MySQL80 -StartupType Manual
```

如需恢复本机 MySQL，先停止容器以释放 3306，再在管理员 PowerShell 中恢复服务：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml stop mysql
Set-Service -Name MySQL80 -StartupType Automatic
Start-Service -Name MySQL80
```

更多应用启动顺序见 [开发环境说明](../docs/development.md)。
