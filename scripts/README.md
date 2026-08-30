# Scripts

本目录保存可重复的开发辅助脚本。脚本调用项目 Wrapper 或隔离环境，不静默安装全局工具、
修改 `PATH`、清理数据库或污染 Conda `base`。

## 当前脚本

| 路径 | 职责 |
| --- | --- |
| `start-dev.ps1` | Windows 环境检查、一键启动基础设施和四个应用 |
| `generate_demo_pdf.py` | 在仓库外生成可再分发的两页中英文冒烟 PDF |

### 启动

```powershell
.\scripts\start-dev.ps1 -CheckOnly
.\scripts\start-dev.ps1
```

脚本读取根目录 `.env`，要求 `AIRESEARCHER_PAPER_LIBRARY_DIR` 位于仓库内被 Git 忽略的
`.private/` 子目录，并要求模型缓存位于仓库外。`-CheckOnly` 只验证边界，不创建目录；
正常启动会准备 `originals/` 与 `.staging/`。
完整环境、首次部署、再次运行、停止和手动启动见
[Windows 本地部署与运行](../docs/deployment.md)。

### 生成合成 PDF

```powershell
conda run -n airesearcher-agent python .\scripts\generate_demo_pdf.py `
    C:\path\outside\repository\airesearcher-demo.pdf
```

生成器拒绝把输出写入仓库。目标目录必须由调用者明确指定。
