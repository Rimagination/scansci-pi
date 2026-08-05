# Agent Harness P0–P2 落地说明

本轮把 Reasonix 中值得借鉴的治理能力落到 ScanSci 现有 Pi 主循环上，Pi 仍是生产主 harness；PydanticAI、OpenAI Agents SDK 和 LangGraph 继续保持可选适配，不会在启动时强制导入。

## P0：运行可观测性与上下文治理

- 每个 Pi run manifest 保存脱敏的 `prefix_shape`，只记录组件 hash，不保存系统提示词、工具结果或密钥。
- `sessionStats` 和 manifest 记录 `cacheReadTokens`、`cacheWriteTokens`、命中率、上下文 breakdown 与 prefix hash，便于定位缓存失效。
- 在 Pi 首次 prompt、恢复 continuation 和手动 compact 前，旧 tool result 会被替换成小型可重跑提示；最近两轮结果保留。
- 能力诊断默认静态、只读，不启动 MCP、不访问网络：

```powershell
scansci doctor capabilities --root . --json
```

## P1：任务契约与恢复

- `TaskContract` 明确目标、输出格式、约束、必需证据、允许工具、暂停策略和成功标准，并随 run manifest 保存。
- `edit_section` / `edit_slide` 在工作区内写入前自动创建文件级 checkpoint，返回 `checkpoint_id`。
- 可手动操作 checkpoint：

```powershell
scansci checkpoint create --root . --file reports/draft.md --label "before edit"
scansci checkpoint list --root .
scansci checkpoint restore --root . --id <checkpoint_id> --mode code
```

## P2：子 Agent 隔离

在 `.scansci/subagents/*.json` 声明 profile；`write_paths` 必须是工作区内且互不重叠的路径。调度器会按 profile 并发上限和路径冲突生成确定性批次，重叠写入直接进入诊断错误，不会静默并行。

```json
{
  "name": "literature-scout",
  "description": "只读文献侦察",
  "tools": ["discover_papers", "search_web"],
  "effort": "medium",
  "write_paths": [],
  "max_concurrency": 2
}
```

相关实现集中在 `prefix_diagnostics.py`、`context_policy.py`、`capability_doctor.py`、`task_contract.py`、`checkpoints.py` 和 `subagent_profiles.py`，并通过 Pi runtime、CLI、manifest 和编辑工具接线。
