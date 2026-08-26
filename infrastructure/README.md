# Infrastructure

此目录只保存本地开发基础设施的可提交配置，不保存运行数据。

## Qdrant

Demo 固定使用 `qdrant/qdrant:v1.19.0`。从仓库根目录启动：

```powershell
docker compose -f .\infrastructure\compose.yaml up -d qdrant
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
```

停止容器但保留 named volume：

```powershell
docker compose -f .\infrastructure\compose.yaml down
```

`airesearcher_qdrant_data` 是 Docker 管理的 named volume，不位于仓库。删除 volume 会永久删除本机 Demo 向量，因此本仓库不提供自动删除命令。

## MySQL

Demo 使用本机现有 MySQL `127.0.0.1:3306`，不在 Compose 中重复启动 MySQL，也不引入 Redis。连接参数由仓库根目录 [`.env.example`](../.env.example) 列出；真实密码只放在进程环境或未跟踪的 `.env` 中。

数据库创建和用户授权属于本机管理员操作。完成后由 Alembic 创建应用表：

```powershell
Set-Location .\agent
conda run -n airesearcher-agent alembic upgrade head
```

PDF、MySQL 数据、Qdrant volume、模型缓存和日志均不得进入 Git。
