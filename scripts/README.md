# Scripts

本目录保存跨平台、可重复的开发与验证脚本。脚本优先调用项目 Wrapper 或隔离环境，不得静默
安装全局工具、修改 `PATH` 或污染 Conda `base`。

## 本地启动

`start-dev.ps1` 统一校验根目录 `.env`、工具和依赖，启动 MySQL/Qdrant、执行 Alembic，并在
独立终端启动 Agent API、Worker、Java BFF 和 React：

```powershell
.\scripts\start-dev.ps1 -CheckOnly
.\scripts\start-dev.ps1
```

完整说明见 [Windows 本地部署与启动](../docs/deployment.md)。

## Demo PDF

真实 Demo 验收使用运行时生成的两页中英文文本 PDF，不向仓库提交 PDF：

```powershell
conda run -n airesearcher-agent python .\scripts\generate_demo_pdf.py C:\path\outside\repository\airesearcher-demo.pdf
```

生成器拒绝把输出写进仓库；目标目录由调用者明确指定。
