# 内测稳定性门禁

一次修复只有同时满足下面三层，才可以标记为“可发布”：

1. **运行身份**：预览和桌面端能证明自己实际加载的代码目录与 build id。
2. **用户链路**：自动验证证据问答、联网学术搜索、下载失败恢复、PPT 模板和健康端点。
3. **发布门禁**：针对性单测、完整单测、真实资料验收、打包健康检查和同一 build 的人工截图全部通过。

开发预览统一使用：

```powershell
python scripts/scansci_preview_entry.py --workspace workspace.sqlite --evidence-db html-papers/evidence.sqlite --host 127.0.0.1 --port 8781
```

先用以下命令确认运行来源；如果 `package_root` 不是当前仓库的 `src\\scansci_html`，不得继续验收：

```powershell
python scripts/scansci_preview_entry.py --identity
```

内测契约可独立运行：

```powershell
python scripts/verify_internal_beta.py --output .scansci-diagnostics/internal-beta-contracts.json
```

这份检查故意不依赖外网或模型余额；它验证软件自己的路由、证据、失败恢复和 UI 数据契约。真实外部来源仍由发布门禁中的真实资料验收负责，并要求失败时留下可重试的阶段和原因。
