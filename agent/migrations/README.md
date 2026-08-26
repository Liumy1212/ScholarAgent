# Alembic migrations

迁移只管理 Python Agent 的 MySQL schema。运行时从 `AIRESEARCHER_DB_*` 读取连接信息，迁移文件不包含凭据或运行数据。
