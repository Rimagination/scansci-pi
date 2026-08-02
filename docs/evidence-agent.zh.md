# ScanSci Evidence Agent

## Control Plane / Runtime / Worker

当前推荐模式是 `Codex-supervised Runtime`：

- `control_plane.type=codex`：Codex 或用户所在的主力大模型负责理解目标、判断风险、给出监督说明。
- `runtime=ScanSci Evidence Agent`：只负责编排 typed actions、执行安全内部命令、记录 manifest。
- `worker_model.role=action_decider`：本地小模型只从 `allowed_actions` 里选择 `action_id`，不是 orchestrator。

`agent run` 的 manifest 会记录 `control_plane`、`autonomy`、`worker_model` 和 `events`。这些字段比自然语言总结更重要，因为它们决定后续 Codex 插件、独立工作台或自动化系统如何复盘一次运行。

## Autonomy Levels

| level | 含义 | 默认场景 |
|---|---|---|
| `L0` | 只建议，不进入执行循环 | 纯咨询 |
| `L1` | dry-run，只写 manifest | `agent run` 默认 |
| `L2` | 执行安全内部动作，人审门槛强制保留 | `agent run --execute` |
| `L3` | 高成本或高风险动作前请求确认 | 后续扩展 |
| `L4` | 定时/无人值守，但必须有预算、权限和人审门槛 | 后续扩展 |

不要把 `L4` 当成近期目标。ScanSci 现阶段应该长期停在 `L1-L2`，先把可审计性和失败复盘做扎实。

Evidence Agent 是 ScanSci 的本地小模型 harness。它不是自由聊天机器人，也不是让模型生成 shell 的执行器；它的核心循环是：

```text
observe -> assemble compact workspace context -> decide allowed action -> act -> record manifest -> observe
```

## 边界

- `observe` 只读取本地事实：`evidence.sqlite`、acceptance workbench manifest、`workspace.sqlite`、annotation layers。
- `decide` 可以交给本地 OpenAI-compatible 小模型，但模型只能从 `allowed_actions` 里选择一个 `action_id`。
- `act` 只执行带有内部 `argv` 的安全 ScanSci 命令；模型不能发明命令。
- `review_acceptance_gold` 这类动作带有 `requires_human=true`，即使使用 `--execute` 也会停在人审门槛。
- 每次运行都会返回 run manifest；传入 `--run-output` 时会写入 JSON 文件，便于审计和复盘。

## 命令

```powershell
scansci agent status --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
scansci agent next --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
scansci agent plan --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
```

默认 dry-run：

```powershell
scansci agent run `
  --db .\html-papers\evidence.sqlite `
  --acceptance-dir .\bench\local-acceptance-workbench `
  --control-plane codex `
  --supervisor-note "Codex supervised this dry-run." `
  --run-output .\bench\agent-runs\latest.json
```

允许执行安全内部动作：

```powershell
scansci agent run `
  --db .\html-papers\evidence.sqlite `
  --acceptance-dir .\bench\local-acceptance-workbench `
  --execute `
  --max-steps 3 `
  --run-output .\bench\agent-runs\latest.json
```

接本地小模型，例如 Ollama 或 LM Studio 的 OpenAI-compatible endpoint：

```powershell
scansci agent run `
  --db .\html-papers\evidence.sqlite `
  --acceptance-dir .\bench\local-acceptance-workbench `
  --local-model-base-url http://localhost:11434/v1 `
  --local-model qwen2.5:7b `
  --run-output .\bench\agent-runs\latest.json
```

如果模型返回的 `action_id` 不在允许列表中，Agent 会回退到确定性策略，并在 manifest 里记录 `model_invalid_fallback`。

## Workspace-first

当前版本先把工作区收敛成三个可审计阶段：

| workspace | 作用 | 自动化边界 |
|---|---|---|
| `evidence` | 建立或修复 evidence store | 可自动执行内部 ScanSci 命令 |
| `acceptance` | 创建 workbench、提示人审、验证 local gold | 创建和验证可自动化；人工审阅不可自动越过 |
| `benchmark` | 在 gold 通过后运行本地 benchmark | 可自动执行内部 ScanSci 命令 |

后续 Codex 插件或独立工作台应该优先消费 `agent plan` 和 `agent run` 的 JSON，而不是重新推断项目状态。
