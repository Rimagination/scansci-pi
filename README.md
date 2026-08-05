# ScanSci

![ScanSci Pi product banner](assets/scansci-pi-banner.png)

ScanSci 是一款 evidence-first 科研工作台：围绕本地论文与合法可访问的学术来源，完成检索、证据提取、科研问答、综述写作和幻灯片生成，并让关键结论能够回到原文证据。

本仓库是统一产品的代码基线。Pi Agent SDK 负责模型会话、工具选择、流式输出、取消、恢复与上下文压缩；Python ScanSci Core 继续拥有项目、证据库、任务状态、引用验证和交付物。Pi 是内部运行时，不是第二个产品品牌。

## 公开测试版

Windows 安装包从 [GitHub Releases](https://github.com/Rimagination/scansci-pi/releases) 分发。安装前请核对发布页提供的 SHA-256；当前测试版尚未使用公开信任的代码签名证书，Windows 可能显示“未知发布者”或 SmartScreen 提示。

请勿在公开 Issue 中提交 API 密钥、Access Token、私有文档全文、未脱敏的聊天记录或诊断日志。

## 设计约束

- 干净的结构化 HTML 优先，PDF、OCR 与 MinerU 作为回退。
- 研究性结论必须通过 Agent 外部的引用门禁；证据不足时明确说明。
- 句子级引用紧跟对应陈述，并可回到来源、定位原文。
- Pi 只获得 ScanSci 白名单科研工具；内置 shell 和文件修改工具默认关闭。
- Deep Agents 仅保留为同模型、同证据、同工具的评测基线，不进入正式产品路径。
- 项目业务状态不存放在 Agent 框架会话中。

## 本地运行

```powershell
# Browser preview: always serves this checkout, even if another editable
# ScanSci installation exists on this computer.
python scripts/scansci_preview_entry.py --workspace workspace.sqlite --evidence-db html-papers/evidence.sqlite --host 127.0.0.1 --port 8781

# Native desktop shell from this checkout.
python scripts/scansci_desktop_entry.py
```

在浏览器打开前，可用 `python scripts/scansci_preview_entry.py --identity` 确认当前预览所用的代码目录；`/api/health` 也会返回相同的运行来源。

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

## Windows 构建

```powershell
python -m pip install -e ".[desktop,local-gpu,rerank]"
powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1 `
  -Mode onedir -PackageProfile full -Name ScanSci
```

构建会将 Pi sidecar、Node.js runtime 与本地检索推理运行时放入 ScanSci 应用目录，用户无需单独安装 Python、PyTorch 或全局 Pi。Qwen 检索权重在首次导入资料时从 ModelScope 国内源按需安装；`core` profile 仅用于同时提供独立运行时镜像的轻量渠道。

正式发布由 `scripts/release_gate.ps1` 驱动，发布合同位于 `config/release-gate.json`。迁移背景见 [统一实施计划](docs/implementation-plan.md)，原版产品与证据设计文档已迁入 `docs/`。

`release` 门禁还会编译 Inno Setup Windows 安装包，并在临时隔离目录中执行安装、已安装 EXE 诊断和卸载验证。公开分发仍需由发行方完成 Authenticode 签名、安全扫描和生产网关运维验收；详见 [发布工作流](docs/release-workflow.zh.md)。

## 兼容入口

Python 包仍保留 `scansci-html` 命令，供既有脚本继续使用；正式桌面入口和产品名称统一为 `ScanSci`。
