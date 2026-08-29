# ADR 0002：本地论文原件库

- 状态：已接受
- 日期：2026-08-29

## 背景

旧设计把上传 PDF 放在 `AIRESEARCHER_STORAGE_DIR` 指向的仓库外目录，并把论文硬删除作为
Web 操作。它不利于用户直接整理原件，也无法为未来 MCP 获取的论文提供统一、可审计的落盘
边界。论文原件、MySQL 元数据与 Qdrant 索引还需要明确区分生命周期。

## 决策

### 受控的 `.private/` 例外

论文原件库由 `AIRESEARCHER_PAPER_LIBRARY_DIR` 配置，默认值为相对仓库根目录解析的
`./.private/paper-library`：

```text
.private/paper-library/
├─ originals/
└─ .staging/
```

这是一项对“运行数据位于仓库外”规则的受控例外，不是允许提交运行数据。整个 `.private/`
必须被 Git 忽略，任何真实 PDF、研究数据、数据库、向量、模型、缓存和日志都不得进入 Git。
MySQL/Qdrant 仍使用仓库外 volume，模型缓存仍必须位于仓库外。

`originals/` 是用户可直接管理的论文原件目录；`.staging/` 只存尚未完成上传或下载校验的
临时文件，不参与扫描。API 不接受任意本机路径，只扫描配置目录。扫描必须防止路径穿越，
跳过隐藏目录、临时文件、符号链接与 Windows reparse point，并在哈希前后确认文件未变化。

### 登记、索引与排除

首版只支持文本型 PDF 和 Web 手动触发的后台扫描，不实现 OCR、多格式、启动扫描、目录监听
或定时扫描。上传与扫描复用同一登记逻辑：格式/大小/稳定性/SHA-256 校验完成后，从
`.staging/` 原子移动到 `originals/`，再登记论文并创建入库任务。

相同 SHA-256 只登记一次；移动或改名只更新 `libraryRelativePath`，不重新向量化。同一路径
变成不同内容时，旧论文标记 `REPLACED` 并为新内容创建记录；原件消失时标记 `MISSING`。
只有 `READY + AVAILABLE` 且 `searchable=true` 的论文可以参与检索。

论文硬删除 API 被移除，改为排除/恢复：排除保留原件、SHA-256 和最小登记信息，删除 chunk
与当前 Qdrant 向量并标记 `EXCLUDED`；扫描不会自动导回。恢复要求原件 `AVAILABLE` 并创建
新的入库任务。`MISSING`、`REPLACED` 和 `EXCLUDED` 均不得检索，前两者不得预览。

### 迁移与未来 MCP

旧 `AIRESEARCHER_STORAGE_DIR` 数据采用“用户显式重置并重新扫描”，不做自动迁移：先停止
服务并备份，把需要保留的 PDF 复制到 `originals/`，由用户明确重置 MySQL/Qdrant，运行新
Alembic migration 后在 Web 扫描。启动脚本、迁移和 Agent 都不得自动删除旧 storage、
数据库 volume、collection 或原件。

本次只冻结未来 MCP 的边界，不实现 MCP。MCP 获取的文件必须先写入 `.staging/`，完成来源
授权、格式、大小、稳定性和哈希校验后原子移动到 `originals/<provider>/`，再调用公共登记
服务；不得直接写 MySQL、Qdrant 或调用解析器内部实现。

## 影响

- 用户可以在项目旁直接整理原件，同时 Git 安全边界仍然明确。
- 浏览器继续只调用 Java，Java 只代理合同；Python 仍是论文与 AI 数据唯一事实来源。
- 未发布的 `DELETE /papers/{paperId}` 被替换，三端必须同步迁移到 exclusion API。
- 已有 `storage_path` 数据不能就地无损升级，需要按部署文档备份、显式重置并重新扫描。
- 本地绝对 `rootPath` 会返回给单用户本地 Web 以辅助管理，不应暴露到远程多用户部署。

