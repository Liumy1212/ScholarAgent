# Infrastructure

本目录只保存 AIResearcher 本地开发基础设施配置，不保存运行数据。

## 当前内容

| 路径 | 职责 |
| --- | --- |
| `compose.yaml` | MySQL 8.4.11、Qdrant 1.19.0、健康检查和 named volume |

Compose 仅绑定本机地址：

- MySQL：`127.0.0.1:3306`
- Qdrant HTTP/gRPC：`127.0.0.1:6333/6334`
- MySQL volume：`airesearcher_mysql_data`
- Qdrant volume：`airesearcher_qdrant_data`

PDF 原件库由 `.env` 指向仓库内被 Git 忽略的 `.private/` 子目录，模型缓存位于仓库外。
当前不使用 Redis，也不使用宿主机 MySQL 服务作为项目数据库。

## 配置检查

从仓库根目录运行：

```powershell
docker compose --env-file .\.env -f .\infrastructure\compose.yaml config --quiet
```

首次部署、启动、停止、健康验证和密码/volume 注意事项见
[Windows 本地部署与运行](../docs/deployment.md)。普通 `down` 保留 named volume；永久数据
清理不属于日常基础设施操作。
