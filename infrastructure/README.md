# Infrastructure

本目录只保存 AIResearcher 本地开发基础设施配置，不保存运行数据。

## 服务与数据边界

Docker Compose 提供：

- MySQL `mysql:8.4.11`，绑定 `127.0.0.1:3306`。
- Qdrant `qdrant/qdrant:v1.19.0`，绑定 `127.0.0.1:6333/6334`。
- named volume `airesearcher_mysql_data` 与 `airesearcher_qdrant_data`。

PDF 与模型缓存使用 `.env` 指定的仓库外目录。本地开发不使用 Redis，也不启动宿主机
MySQL 作为项目数据库。

## 启动与停止

环境要求、首次安装、`.env`、一键启动、健康验证、停止和端口冲突处理统一见
[Windows 本地部署与启动](../docs/deployment.md)。

普通 `docker compose down` 不删除 named volume。不要使用 `down --volumes`，除非明确要
永久删除本机 Demo 数据。MySQL 初始化变量只对空卷生效；修改 `.env` 不会自动轮换已有
数据库用户的密码。

只检查 Compose 配置时，从仓库根目录执行：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml config --quiet
```
