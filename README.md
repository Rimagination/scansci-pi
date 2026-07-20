# ScanSci Pi

ScanSci Pi 是 ScanSci 的独立桌面版本：保留现有证据、项目、任务、引用验证和交付物体系，将对话与科研工具循环替换为 Pi Agent SDK。

当前状态：`runnable MVP`。源项目 `D:\scansci-html` 未被修改；本项目使用独立的 `%LOCALAPPDATA%\ScanSciPi` 数据目录。

## 核心原则

- Pi 只负责模型会话、工具选择、流式输出和上下文压缩。
- Python ScanSci Core 继续拥有研究项目、证据库、任务状态和产物。
- 引用验证位于 Agent harness 之外，不能被模型绕过。
- 产品运行时禁用 Pi 默认的 `read`、`write`、`edit` 和 `bash` 工具，只开放 ScanSci 白名单工具。
- 先完成同模型 A/B 验证，再决定是否替换现有 ScanSci 的默认引擎。

## 运行与构建

```powershell
# 源码运行
$env:PYTHONPATH = "src"
python scripts/scansci_desktop_entry.py

# 构建独立 Windows 桌面程序
powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1 -Mode onedir -Name scanscipi
```

构建产物位于 `dist/scanscipi/scanscipi.exe`。构建会把 Pi sidecar 和 Node.js runtime 一起放进应用目录，使用者无需另装全局 Pi。
默认 MVP 包使用云端/兼容 API 模型；如需把体积很大的本地 Hugging Face/Torch 运行时也装入包内，可额外传入 `-IncludeLocalModels`。

Pi 只获得 `inspect_workspace`、本地证据检索、引用验证、DOI/期刊/论文发现、参考文献审计和演示大纲等 ScanSci 白名单工具；Pi 自带的 shell 与文件修改工具默认关闭。

## 文档

- [迁移实施计划](docs/implementation-plan.md)

## 来源

- 当前产品仓库：`D:\scansci-html`
- 独立实验仓库：`F:\AI\scansci-pi`
- Pi Agent：https://github.com/earendil-works/pi
