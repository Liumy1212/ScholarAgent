# Scripts

此目录保存跨平台、可重复的开发与验证脚本。

脚本应优先调用项目自带的 Wrapper 或隔离环境，不得静默安装全局工具、修改 `PATH`、污染 Conda `base`，也不得写入仓库外的未授权位置。

真实 Demo 验收使用运行时生成的两页中英文文本 PDF，不向仓库提交 PDF：

```powershell
conda run -n airesearcher-agent python .\scripts\generate_demo_pdf.py C:\path\outside\repository\airesearcher-demo.pdf
```

生成器拒绝把输出写进仓库；目标目录由调用者明确指定。
