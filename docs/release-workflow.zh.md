# ScanSci 收敛式开发与发布门禁

> 发布渠道分级：`beta` 生成受邀内测包；`release` 生成正式候选包并执行人工桌面验收。当前发布契约暂不把代码签名作为阻塞条件；若未来启用签名，应通过独立的 release 配置和发布机凭据显式打开，不把凭据写入仓库。

这套流程解决两个问题：开发期间不要每改一点就完整打包；交付时也不能再用源码测试、浏览器预览或“进程启动了”冒充 EXE 验收。

## 1. 开工前只允许一个 P0

当前任务写在 `config/release-scope.json`：

- `p0_objective`：本轮唯一目标；
- `acceptance`：可观察、可复核的验收项；
- `non_goals`：本轮明确不做的内容。

目标或验收项变化时必须修改该文件。门禁会记录它的 SHA256；修改后不得沿用旧构建的测试证据。

## 2. 三层门禁，不重复做最贵的工作

日常修改先跑针对性门禁：

```powershell
.\scripts\release_gate.ps1 -Profile targeted
```

它只跑与桌面、对话、模型、Skill、资料库、幻灯片和门禁直接相关的测试，以及前端语法检查。失败时停止，不运行完整测试、真实模型或打包。

准备候选版本时跑源码门禁：

```powershell
.\scripts\release_gate.ps1 -Profile source
```

执行顺序固定为：针对性测试 → 完整测试 → ScanSci 框架内双模型与 Skill → 真实本地知识库。上一层失败，下一层不会运行。

如果刚刚已经通过 `targeted`，可以晋级原报告，避免重复针对性测试：

```powershell
.\scripts\release_gate.ps1 `
  -Profile source `
  -PromoteReport "<targeted 的 release-report.json>"
```

正式交付时运行：

```powershell
.\scripts\release_gate.ps1 -Profile release
```

如果 `source` 已通过，正式构建应晋级该报告，不重复完整测试、双模型和知识库：

```powershell
.\scripts\release_gate.ps1 `
  -Profile release `
  -PromoteReport "<source 的 release-report.json>"
```

它在源码门禁之后只构建一次，并继续检查包完整性、Windows 安装包、隔离目录中的安装→运行诊断→卸载、运行时诊断、正式 EXE `/api/health` 和桌面进程存活。每次输出到唯一目录：

```text
releases\0.2.0+<build_id>\
  ScanSci\ScanSci.exe
  update\ScanSci-<version>-windows-x64.zip
  update\ScanSci-<version>-windows-x64.zip.blockmap
  update\stable.json
  installer\ScanSci-<version>-windows-x64-setup.exe
  installer\installer-manifest.json
  diagnostics\
  visual-evidence\
  release-report.json
```

正式门禁强制 clean build；直接调用 `build_desktop.ps1` 的开发构建默认保留以 `build_id` 隔离的 PyInstaller 缓存。不同构建不共享 `dist`、workpath、specpath 或 metadata 目录。

## 3. EXE 人工验收不能被自动测试替代

自动门禁通过后，如果缺少桌面证据，命令以退出码 `2` 停在 `awaiting_visual_evidence`，而不是错误宣称发布完成。它会生成：

```text
visual-evidence\visual-evidence.json
```

必须启动报告中记录的同一个 `ExecutablePath`，逐项验证并保留三张真实桌面截图：

- `home.png`：首页布局；
- `chat.png`：Enter、点击发送、回答及参考文献栏规则；
- `maximized.png`：最大化后任务栏仍可见。

把对应检查改为 `true` 后，用原报告续跑：

```powershell
.\scripts\release_gate.ps1 `
  -Profile release `
  -ResumeReport "<legacy-repo>\releases\0.2.0+<build_id>\release-report.json"
```

晋级仅在 `contract_sha256`、`scope_sha256` 和发布相关源码指纹 `source_sha256` 均未变化时成立；任一代码、安装器或契约发生变化，门禁拒绝复用。续跑会复用已通过步骤和同一个 EXE，不再重新跑模型、知识库或 20 分钟打包。只有 `release-report.json` 最终为 `passed`，才可以说“已交付候选”。

### 公开发布还需独立满足的条件

门禁的 `passed` 证明候选包可构建、安装、运行、卸载并完成桌面验收；它不替代外部发布权限。公开分发前还必须完成：

- 当前不把代码签名作为本轮阻塞条件；若发布方已有证书，可额外签署并复核 Authenticode，但未签名状态必须在渠道说明中明确；
- 完成同一候选的安全扫描与高风险问题处置；
- 由网关维护者确认生产凭据、限流、监控与故障响应可用；
- 发布不可变下载地址、SHA256、版本说明和回滚方案。
- 将安装器、完整 Windows ZIP 和 `.zip.blockmap` 上传到同一个不可变版本标签，再最后上传 `stable.json`；不得只发布安装器却让应用指向不存在的更新清单；
- 上传完成后必须运行 `scripts/verify_update_channel.py`，确认公开清单版本、资产大小与 SHA256 一致。HTTP Range 可用时走差分；不可用时必须明确验证完整包回退仍然可达。

没有这些外部证据时，只能称为“已验证的发布候选”；代码签名缺失本身不会阻塞本轮候选构建，但不得隐瞒。

## 4. 计划预览与报告

不执行任何命令，只检查契约并查看将运行的步骤：

```powershell
.\scripts\release_gate.ps1 -Profile release -PlanOnly
```

计划报告只写入 `.scansci-diagnostics\release-gate-plans`，不会在 `releases` 下制造一个没有 EXE 的空候选目录。

`release-report.json` 记录：

- `scope_sha256`、`contract_sha256` 与 `source_sha256`；
- 每一步的命令、开始/结束时间、耗时、退出码与日志；
- 正式 EXE 的绝对路径、`build_id`、大小、文件数和 SHA256；
- 安装包路径、SHA256、大小、签名状态，以及安装、运行、卸载验证结果；
- 双模型、Skill、知识库、运行时和桌面证据路径；
- `planned`、`running`、`failed`、`awaiting_visual_evidence` 或 `passed` 状态。

报告和日志不得包含 API Key。密钥只保留在既有服务端 Secret / 系统凭据链路中。

## 5. 什么时候才运行完整测试

- 产品代码尚在快速迭代：只跑 `targeted`。
- 针对性门禁稳定且准备候选版本：跑 `source`。
- `source` 已通过且确实要交付 EXE：跑一次 `release`。
- 只补桌面截图或人工勾选：用 `-ResumeReport`，不重新打包。

任何“顺便优化”先写入下一轮候选，不并入当前 P0。OpenCode 仅在某个明确问题缺少设计依据时查相应模块，不做全量迁移。

## 6. 受邀内测包（无需购买证书）

`beta` 仍用于受邀内测，`release` 用于正式候选；两者都不要求本轮购买代码签名证书：

```powershell
.\scripts\release_gate.ps1 `
  -Profile beta `
  -PromoteReport ".scansci-diagnostics\release-gates\0.2.0+<source-build-id>\release-report.json" `
  -BuildId "beta-20260729"
```

`beta` 会复用同一源代码指纹已通过的 source 测试证据，并自动完成：干净构建、包完整性、未签名 Inno 安装包、安装/启动/卸载、运行时诊断、健康检查和桌面进程存活检查。

交付目录为：

```text
internal-beta-releases\0.2.0+<build-id>\
  installer\ScanSci-0.2.0-windows-x64-setup.exe
  beta-delivery\SHA256SUMS.txt
  beta-delivery\BETA-README.zh-CN.md
  beta-delivery\BETA-FEEDBACK-TEMPLATE.md
  beta-delivery\beta-distribution.json
  release-report.json
```

`BETA-README.zh-CN.md` 会明确说明“未签名、仅限受邀测试”、Windows 可能出现的未知发布者提示、SHA-256 校验方式、卸载方式及反馈时禁止提交的敏感数据。`beta-distribution.json` 绑定被实际安装验收过的安装包 SHA-256；只有它与 `release-report.json` 同时为 `passed`，才可发给受邀测试者。

## 7. 可选的代码签名发布机准备

如果后续需要启用签名，可在独立发布机上显式配置以下条件；当前 `config/release-gate.json` 将 `signature_required` 设为 `false`，未配置时不会失败：

- 安装在当前用户 `CurrentUser\\My` 证书库中的、未过期且可访问私钥的 Authenticode 代码签名证书；
- Windows SDK 或 Visual Studio 提供的 `SignTool.exe`；
- 由发布运维方提供的 HTTPS RFC 3161 时间戳服务地址。

在发布机的受控环境中设置（不要写入仓库、日志或安装包）：

```powershell
$env:SCANSCI_SIGNING_CERT_THUMBPRINT = "<40 位证书指纹>"
$env:SCANSCI_TIMESTAMP_URL = "https://<timestamp-service>"
```

门禁会先签署并验证 `ScanSci.exe`，再构建、签署并验证安装包；隔离安装验收还会再次验证安装目录内的 `ScanSci.exe`。安装器清单记录两个文件的签名状态和 SHA256，但不记录证书指纹、私钥或时间戳地址。
