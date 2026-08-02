# ScanSci 统一迁移状态

更新时间：2026-07-22

## 目标

最终只保留一个对外产品 `ScanSci`。`<repo>` 作为有 25 个提交历史的物理代码基线，吸收 `<legacy-repo>` 的缺失能力；Pi Agent 是正式候选运行时，Deep Agents 只用于冻结条件下的对照评测。

## 已完成

1. 在 `<migration-snapshots>\20260722-082457` 建立了迁移前快照：
   - `scansci-html-source.zip`：原版源代码、测试、配置与文档，SHA256 `64CA87DDCA6C0642E9767E0D1BC990F41A6299BB7376F4A6C325E93DA1511B9D`；
   - `scansci-pi-history.bundle`：Pi 仓库完整 Git 历史，SHA256 `7E6B617FCF6C0B299FA12BB7CF73A8DB6EA7014E8217F7B73FA217818FA9DE81`；
   - `scansci-pi-head.zip`：Pi 当前 HEAD，SHA256 `19F045DF935EA9AB36EEFF3C8DD04E1034803CC9EAF2F6377A6A0FE0759DEF54`；
   - `scansci-pi-working.patch`：Pi 迁移前已跟踪未提交修改，SHA256 `8D017A7E1F730913C015DD07F4E6FFD0A2F8441265ACBF6B5AD2E11A26857B23`；
   - Pi 的 6 个未跟踪评测文件另存于 `scansci-pi-untracked/`。
2. 文件级审计得到 177 个完全相同文件、42 个内容冲突文件、64 个原版独有文件、6 个 Pi 独有文件。
3. 64 个原版独有文件已单向迁入，包括：
   - 发布合同、发布门禁、CI、桌面打包与冻结工具；
   - 独立本地 Transformers runtime 组件；
   - GLM gateway 服务源码；
   - 原版证据、引用、Notebook、评测与产品治理文档；
   - 对应测试。
4. 发布/打包冲突域已人工合并：保留 Pi sidecar 和内嵌 Node runtime，同时恢复原版的 `core/full` profile、依赖键缓存、`build_id`、本地 runtime manifest 和分阶段发布门禁。
5. Python 核心冲突采用行为契约判定，不做无意义的文本拼接：
   - 统一仓库测试：627 项通过；
   - 原版完整测试在统一仓库 Python 源码上运行：551 项通过；
   - 原版仅有的 3 个独特测试行为也单独通过。
   因此核心 Python 实现保留 Pi 分支版本；它满足原版契约并额外拥有逐句引用、会话归档、Pi 会话恢复等能力。
6. 对外品牌已统一为 `ScanSci`：README、Python 项目名、Node 包名、窗口标题、页面品牌和 Agent 自我描述不再把 Pi 当作第二个产品。`scansci-html` CLI 只作为兼容入口保留。
7. Deep Agents 相关依赖已移入 `evaluation` 可选依赖，正式产品依赖只保留 Pi 运行路径。
8. 已实现保守数据合并器 `src/scansci_html/data_migration.py` 与命令行入口 `scripts/migrate_scansci_data.py`：
   - 支持 inspect、dry-run、SQLite 在线备份、逐文件 SHA256、表级 `INSERT OR IGNORE`、设置合并和路径重写；
   - 冲突文件归档到 `.scansci-migration/original-conflicts`；
   - 切换前保留 `ScanSci.pre-unification-<时间戳>`，且不修改旧 `ScanSciPi` 根；
   - 在真实数据完整副本 `<migration-validation>\20260722-084925` 上排演通过，最终得到 3 个 research run、11 个 stage、4 个 tool call、3 个 artifact、6 条 message、1 个 notebook、3 个 source 和 9 条 evidence link；SQLite integrity 与外键检查均通过。
9. Pi 正式运行路径已补齐并验证：真实取消、JSONL 持久会话、sidecar 重启恢复、原生上下文压缩，以及托管文本网关到 Pi 工具协议的严格适配。`build_verified_answer` 被定义为终结工具，成功结果持久化后结束本回合，不再依赖第二次无意义的模型收尾。

## 当前验证证据

- 迁入发布/本地 runtime 测试：15 项通过。
- Pi/Deep 相关回归：22 项通过；Pi 与通用 Agent 相关回归：35 项通过。
- Pi sidecar：`npm run build:pi-runtime` 构建成功。
- PowerShell 构建、打包和发布脚本：语法解析通过。
- `targeted` 发布门禁：110 项测试与前端语法检查通过，报告位于 `.scansci-diagnostics/release-gates/0.2.0+merge-targeted/release-report.json`。
- `source` 发布门禁完整通过：110 项针对性测试、627 项全量测试、前端语法、双正式模型验证和真实知识库 E2E 全部通过；报告位于 `.scansci-diagnostics/release-gates/0.2.0+merge-source-pi-terminal-20260722-0935/release-report.json`。
- 正式 `glm-4.7-flash` 已真实经过 `pi-agent-sdk` 工具循环并调用 `build_verified_answer`；引用验证通过且包含证据阅读器链接。独立证据位于 `.scansci-diagnostics/knowledge-e2e-pi-glm-terminal-2.json`。

## 尚未自动执行的高风险步骤

### 本机数据目录合并

本机同时存在两套真实数据，不能直接覆盖：

- `%LOCALAPPDATA%\ScanSci\workspace.sqlite`：278,528 字节，2 个 research run、6 条 run message；
- `%LOCALAPPDATA%\ScanSciPi\workspace.sqlite`：17,584,128 字节，1 个 notebook、3 个 source、1 个 research run，并有独立 evidence library 与 `.scansci-pi-agent` 持久会话。

合并器和完整副本排演已经通过，但真实切换尚未执行。当前 `scanscipi.exe` 及其 Pi sidecar 仍在运行并占用真实数据根；代码继续使用现有 `ScanSciPi` 数据根，避免运行中迁移造成会话或 SQLite 写入竞争。关闭桌面程序后应先重新检查进程，再执行 `python scripts/migrate_scansci_data.py --apply`；只有迁移报告通过后才能把默认数据根、更新目录和 Windows AppUserModelID 切到 `ScanSci`。

### 发布与评测

- 尚未生成新的正式 Windows EXE，也未做真实桌面视觉验收；源码级 `source` 门禁已经通过。
- 24 个任务 × 3 次 × 2 架构的冻结基准已生成独立工作区/证据快照，并记录模型、证据 SHA、任务 SHA、实现 SHA、同一 9 工具集合、温度和限速策略。
- GitHub Models 在本轮第一对任务即返回 `UserByModelByDay` 日配额耗尽，重置前无法产生有效新样本；断点为 `bench/pi-deep-ab-github-24x3-final.jsonl`，错误槽位会在续跑时重试。
- 托管 GLM 1×1 预检无基础设施错误，但两种架构都没有主动调用规定工具，不能替代正式 A/B；本机 OpenAI 环境密钥则返回 401。故完整 144 个有效运行仍未完成，当前不能宣布 Pi 或 Deep 的任务成功率胜者。

## 下一阶段顺序

1. 用户关闭正在运行的 ScanSci Pi 后，重新检查进程，执行真实数据合并与校验，再把默认数据根切到 `ScanSci`。
2. 构建唯一 `ScanSci.exe`，对真实 EXE 执行诊断、健康检查、进程存活和人工视觉验收。
3. GitHub Models 配额重置或提供有效的正式工具模型凭据后，从冻结断点续跑 24×3 A/B；完成前不宣布最终架构胜者。
4. 根据成功率、错误引用、token 成本代理、延迟与恢复能力决定正式 Agent 路径；失败架构只保留评测适配层。
5. 最后再重命名物理目录并归档 `<legacy-repo>`；在此之前不删除任何原仓库。
