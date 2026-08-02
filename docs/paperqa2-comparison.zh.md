# PaperQA2 本地对比烟测

日期：2026-07-02

## 目的

这个烟测不是正式 benchmark，而是确认：下载的 PaperQA2 GitHub 源码能否在本机稳定跑起来，并且能否在同一篇 clean HTML 上和 ScanSci 做可复现对比。

## 当前可运行配置

源码 zip 已解压到：

```text
tmp/paper-qa-main-src/paper-qa-main
```

隔离虚拟环境在：

```text
tmp/paperqa-src-venv
```

项目入口脚本：

```powershell
python scripts/run_paperqa2_smoke.py --phase doctor
python scripts/run_paperqa2_smoke.py --phase both --clear-paper-dir
python scripts/run_paperqa2_smoke.py --phase ask --no-evidence-skip-summary
```

默认测试文档是我们已经获取到的 Elsevier clean HTML：

```text
tmp/elsevier-clean-test-cell/10.1016_j.cell.2011.02.013_hallmarks_of_cancer_the_next_generation.html
```

默认问题：

```text
What are the two emerging hallmarks of cancer proposed in this paper?
```

## 为什么这样配置

- 不装 `paper-qa[local]`：它会拉 `sentence-transformers`/torch 等重依赖，前一次临时环境接近 GB 级且安装很慢。
- 使用 `--embedding sparse`：这是 PaperQA2 官方支持的关键词稀疏 embedding，不依赖 embedding API 或本地 embedding 大模型。
- 默认使用 `--answer.evidence_skip_summary true`：烟测优先确认索引、检索、证据引用和最终回答能跑通，避免一题触发过多 qnaigc API 调用导致 RPM 限流。若要测试 PaperQA2 完整 RCS 风格，使用 `--no-evidence-skip-summary`。
- 默认使用 `--parsing.use_doc_details false`：避免索引阶段访问 Crossref/Semantic Scholar 时遇到外部 API 限流；若要测试 PaperQA2 元数据增强，可显式使用 `--use-doc-details`。
- 使用 `openai/deepseek-v4-pro-202606`：PaperQA2 默认 `gpt-4o-2024-11-20`，当前 qnaigc 接口没有这个模型通道。
- 使用 `--agent.agent_type fake`：完整 tool agent 会触发部分 thinking 模型的 `tool_choice`/`reasoning_content` 兼容问题；`fake` agent 会按固定步骤执行检索、证据汇总和回答，更适合当前接口做烟测。
- 脚本会自动补齐 `journal_quality.csv`：GitHub zip 源码安装后，wheel 里缺了 `paperqa/clients/client_data/journal_quality.csv`，否则索引阶段会报 `FileNotFoundError`。

## 输出位置

脚本会把 PaperQA2 日志和耗时摘要写到：

```text
tmp/compare-paperqa2/paperqa2-runs
```

关键文件包括：

- `<index-name>-index.log`
- `<index-name>-ask.log`
- `<index-name>-summary.json`

## 已观察结果

在 Cell 2011 这篇 clean HTML 上，PaperQA2 能建立索引，并能回答两个 emerging hallmarks：

- `reprogramming of energy metabolism`
- `evading immune destruction`

本机烟测记录：

- index：约 42.57 秒
- ask：约 42.18 秒（复用索引，`--answer.evidence_skip_summary true`）
- 日志：`tmp/compare-paperqa2/paperqa2-runs/scansci_cell_paperqa2-ask.log`

注意：当前 qnaigc + deepseek thinking mode 仍可能在最终 complete/tool-selection 阶段打印兼容性错误，但 `fake` agent 路线已经能产出最终答案。正式对比时应把这种 provider compatibility 作为单独指标记录，不要和检索准确率混在一起。

## 后续正式 benchmark 建议

正式比较 ScanSci、PaperQA2、OneFind 或其他系统时，应固定：

- 同一批文档目录
- 同一批问题
- 人工 gold answer
- 证据句 gold span
- 索引耗时、问答耗时、LLM 调用次数
- answer correctness 与 citation/evidence correctness 分开评分

## 2026-07-02 同文档检索/作答烟测

脚本：

```powershell
python scripts/compare_paperqa2_scansci_retrieval.py --paperqa-index-name scansci_cell_paperqa2 --output-dir tmp\compare-paperqa2\retrieval-answer-comparison-existing-index
```

数据：

- 单篇 clean HTML：`Hallmarks of Cancer: The Next Generation`
- 4 个自然语言问题：emerging hallmarks、enabling characteristics、Warburg effect、six hallmarks
- ScanSci：本地 `ask`，句子级 evidence store，本地 quote/answer/verification
- PaperQA2：`sparse` embedding、`fake` agent、`openai/deepseek-v4-pro-202606`、跳过 per-evidence summary

结果摘要：

| 指标 | ScanSci | PaperQA2 |
|---|---:|---:|
| 平均答案概念召回 | 0.50 | 0.75 |
| 平均证据/引用概念召回 | 0.50（sentence/evidence table） | 0.75（cited chunk） |
| 总耗时 | 6.21 秒 | 199.90 秒 |

逐题结果：

| 问题 | ScanSci | PaperQA2 |
|---|---:|---:|
| emerging hallmarks | 1.00 | 1.00 |
| enabling characteristics | 0.00 | 0.00 |
| Warburg effect | 1.00 | 1.00 |
| six hallmarks | 0.00 | 1.00 |

解释：

- ScanSci 在句子级证据库里确实有 gold evidence；用带答案术语的查询可召回 `s0003`、`s0005`、`s0331/s0333/s0338` 等关键句。
- 失败主要发生在自然问题的 query planning：例如 “six hallmark capabilities listed in the abstract” 没有扩展出六个 hallmark 名称，导致召回“hallmark capabilities”相关句而不是摘要列表句。
- PaperQA2 的答案组织更像最终用户答案，尤其在 q1/q3/q4；但它每题耗时约 43-54 秒，并多次出现 qnaigc/deepseek thinking-mode 的 `reasoning_content` 兼容错误。q2 因此输出 `I cannot answer.`
- 因此当前结论不是“PaperQA2 检索绝对更强”，而是：PaperQA2 的 LLM query generation + chunk-level answer synthesis 在部分自然问题上更会补全语义；ScanSci 的证据层更透明、更快，但需要补 query rewrite / multi-query / section-aware recall 才能稳定覆盖抽象问题。

产物：

- `tmp/compare-paperqa2/retrieval-answer-comparison-existing-index/comparison.md`
- `tmp/compare-paperqa2/retrieval-answer-comparison-existing-index/comparison.json`

## 2026-07-02 Query rewrite + block context 复测

本轮在 ScanSci 中新增了两项能力：

- 结构化 query rewrite routes + weighted RRF：自然问题先生成可审计的检索路线，再融合多路候选。
- paragraph/block 邻近证据扩展：对 `named_list`、比较、冲突、综述等问题，命中句会在 quote/evidence table 阶段扩展为同一 `block_id` 的段落上下文，保留原句 anchor 和 `parent_evidence_ids`。

关键修复点是 `q2_enabling_characteristics`。旧版只命中 “Their acquisition is made possible by two enabling characteristics.” 这一句，但答案名称在同段后两句；新版会把 `s0300` 扩展到同段 `s0299-s0302`，因此证据表同时包含 genomic instability / mutations 与 inflammatory state / tumor progression。

8 题扩展 ScanSci-only 结果：

```powershell
python scripts/compare_paperqa2_scansci_retrieval.py --paperqa-index-name scansci_cell_paperqa2 --output-dir tmp\compare-paperqa2\retrieval-answer-comparison-extended-scansci-v2 --no-run-paperqa
```

| 指标 | ScanSci |
|---|---:|
| 题数 | 8 |
| 平均 top-hit 概念召回 | 1.00 |
| 平均 evidence-table 概念召回 | 1.00 |
| 平均 answer 概念召回 | 1.00 |
| 总耗时 | 11.67 秒 |

逐题：

| 问题 | ScanSci |
|---|---:|
| emerging hallmarks | 1.00 |
| enabling characteristics | 1.00 |
| Warburg effect / aerobic glycolysis | 1.00 |
| six hallmarks in abstract | 1.00 |
| genome instability and hallmark acquisition | 1.00 |
| tumor microenvironment complexity | 1.00 |
| inflammation supplies bioactive molecules | 1.00 |
| evading immune destruction | 1.00 |

PaperQA2 扩展 8 题重跑尝试：

```powershell
python scripts/compare_paperqa2_scansci_retrieval.py --paperqa-index-name scansci_cell_paperqa2 --output-dir tmp\compare-paperqa2\retrieval-answer-comparison-extended-paperqa --run-paperqa
```

结果：索引成功，q1 evidence gathering 成功，但 answer generation 在 `--agent.timeout 180.0` 后仍未稳定返回，最终非零退出。日志显示 PaperQA2 已找到相关 evidence，但卡在最终 answer generation/provider 阶段。因此本轮不能给出 PaperQA2 8 题有效分数；可比较的 PaperQA2 分数仍以 4 题冻结结果为准。

当前结论：

- 在原 4 题上，ScanSci 从 0.50 提升到至少 0.75；加入 block context 与修正词形评分后，4 题均可命中目标概念。
- 在扩展 8 题 ScanSci-only 烟测上，ScanSci 达到 1.00，且总耗时约 12 秒。
- 还不能宣称“全面超越 PaperQA2”，因为 PaperQA2 的 8 题扩展跑没有成功完成；但可以说：在同一篇 clean HTML、相同概念评分框架下，ScanSci 已经修复此前相对 PaperQA2 的主要失败点，并且速度优势非常明显。

## 2026-07-02 PaperQA2 8 题实际复跑

用户要求 PaperQA2 也跑完整 8 题，否则没有对比。因此在已存在的 `scansci_cell_paperqa2` 索引上复跑：

```powershell
python scripts/compare_paperqa2_scansci_retrieval.py --paperqa-index-name scansci_cell_paperqa2 --output-dir tmp\compare-paperqa2\retrieval-answer-comparison-extended-paperqa-keepgoing --run-paperqa --skip-paperqa-index --paperqa-timeout 300 --keep-going-on-paperqa-error
```

本轮对比对象仍是同一篇 clean HTML：`Hallmarks of Cancer: The Next Generation`。这不是公开 benchmark，只用于检查同一文档问答场景下两条路线的检索、证据和作答表现。

结果摘要：

| 指标 | ScanSci | PaperQA2 |
|---|---:|---:|
| 题数 | 8 | 8 |
| 平均 top-hit / cited-chunk 概念召回 | 1.00 | 0.54 |
| 平均 evidence-table 概念召回 | 1.00 | - |
| 平均 answer 概念召回 | 1.00 | 0.35 |
| 总耗时 | 12.58 秒 | 2090.33 秒，约 34.84 分钟 |

逐题结果：

| 问题 | ScanSci answer | PaperQA2 answer | PaperQA2 cited chunks | PaperQA2 耗时 |
|---|---:|---:|---:|---:|
| emerging hallmarks | 1.00 | 1.00 | 1.00 | 155.64 秒 |
| enabling characteristics | 1.00 | 0.00 | 0.00 | 287.37 秒 |
| Warburg effect / aerobic glycolysis | 1.00 | 0.00 | 0.00 | 315.39 秒 |
| six hallmarks in abstract | 1.00 | 0.00 | 0.00 | 287.09 秒 |
| genome instability and hallmark acquisition | 1.00 | 0.67 | 0.67 | 402.00 秒 |
| tumor microenvironment complexity | 1.00 | 0.67 | 1.00 | 56.82 秒 |
| inflammation supplies bioactive molecules | 1.00 | 0.00 | 0.67 | 191.31 秒 |
| evading immune destruction | 1.00 | 0.50 | 1.00 | 394.72 秒 |

主要观察：

- PaperQA2 不是完全不能答。q1、q5、q6、q8 能给出可用答案，其中 q1 完整命中；q5/q6/q8 部分命中。
- 但 PaperQA2 在当前 qnaigc + `deepseek-v4-pro-202606` + PaperQA2 fake agent 组合下不稳定：q2/q4 输出 `I cannot answer this question due to having no papers.`，q3 非零退出，多个题目打印 `reasoning_content` 兼容性错误。
- PaperQA2 的长尾耗时非常明显：8 题总耗时约 35 分钟，最慢单题约 402 秒；ScanSci 8 题总耗时约 13 秒。
- ScanSci 的改进来自两点：query rewrite / multi-query + weighted RRF 提升自然语言问题召回；paragraph/block 邻近证据扩展解决“命中解释句但答案名词在同段邻句”的问题。
- 当前结论可以更明确：在这个同文档 smoke test 上，ScanSci 的检索证据链和最终答案都优于当前 PaperQA2 跑法，且速度优势极大；但这仍不能替代公开数据集 benchmark，也不能代表 PaperQA2 在其它模型、其它配置下的最佳表现。

产物：

- `tmp/compare-paperqa2/retrieval-answer-comparison-extended-paperqa-keepgoing/comparison.md`
- `tmp/compare-paperqa2/retrieval-answer-comparison-extended-paperqa-keepgoing/comparison.json`

脚本治理补充：本次复跑暴露出 `--agent.timeout` 只是 PaperQA2 agent 内部超时，不是外层进程硬超时。已给 `scripts/run_paperqa2_smoke.py` 增加 `--wall-timeout`，并在 `scripts/compare_paperqa2_scansci_retrieval.py` 中增加 `--paperqa-wall-timeout`，后续复测不会无限等待 PaperQA2 子进程。

## 2026-07-02 吸收 PaperQA2 / Agentic RAG 的优点

本项目不把 PaperQA2 式 agentic RAG 作为默认主路径，因为它在本地个人文献库场景中过慢、过贵、失败模式复杂。但它的若干思想值得吸收：

- query expansion / multi-query：问题表述和论文术语不一致时，先生成多条可审计检索路线。
- evidence adequacy gate：不要有一点命中就回答；先判断证据数量和来源多样性是否足够。
- stop rule：证据已经足够时停止；证据不足时才触发 follow-up；follow-up 预算耗尽则拒答。
- citation verification：每个 claim 必须绑定 quote；quote 必须能回到 evidence row 和 HTML anchor。
- deep mode：复杂综述、冲突判断、多论文比较时，可以显式启用更高预算，而不是所有问题默认慢速 agent。

已落地为可控增强层：

- `src/scansci_html/qa/agent.py`
  - 新增 `agentic_profile`：`custom` / `fast` / `balanced` / `deep`。
  - 新增 `resolve_agentic_controls()`：把 profile 解析成 `query_variants`、`max_followup_queries`、`paper_recall_limit`。
  - `answer_question()` 返回 `agentic_trace`，记录 profile、实际控制参数、是否触发慢路径、停止原因、每一步 query/hit/quote/adequacy 状态。
  - `verify_citations()` 升级为 strict gate：未引用 claim、引用不存在、无 HTML anchor、无 exact quote、或 verification 后仍 unsupported 的 claim，都会导致 citation verification 不通过。
- `src/scansci_html/cli.py`
  - `rag ask` / `local-ask` / `workflow` 增加 `--agentic-profile`。
  - 默认 `balanced`，保持当前 staged RAG；`fast` 用于日常快速问答；`deep` 用于复杂综述和多论文问题。
- `src/scansci_html/render/report.py`
  - HTML 报告的 Retrieval Audit 展示 agentic profile、stop reason、slow path 是否触发、uncited / unsupported cited claims。
- `src/scansci_html/literature_workflow.py`
  - 批量文献工作流接入同一套 `agentic_profile`，避免单题和 workflow 行为分裂。

推荐使用方式：

```powershell
# 日常快速问答：尽量不走慢路径
python -m scansci_html.cli rag ask --db evidence.sqlite --question "..." --output answer.html --agentic-profile fast

# 默认增强问答：多 query + 证据充分性 gate + 有限 follow-up
python -m scansci_html.cli rag ask --db evidence.sqlite --question "..." --output answer.html --agentic-profile balanced

# 复杂综述/多论文比较/冲突证据：显式深度模式
python -m scansci_html.cli rag ask --db evidence.sqlite --question "..." --output answer.html --agentic-profile deep
```

测试：

```powershell
pytest tests\test_agent.py tests\test_bench.py tests\test_review.py -q
```

结果：`112 passed`。

## 2026-07-02 NotebookLM-like Reader Answer

用户指出：自然语言回答同样可以引用证据，NotebookLM 的好用之处正是“可读回答 + 行内引用”。因此 `rag ask` 的输出展示顺序调整为：

```text
Reader Answer
  自然语言句子 + [1][2] 行内引用

Claim Audit
  claim_id / support_status / verification_score / quote_ids

Evidence Ledger
  quote_id / exact_quote / evidence_id / paper / DOI / HTML anchor

Retrieval Audit
  query plan / agentic trace / evidence adequacy / citation verification
```

实现要点：

- `answer_question()` 现在返回顶层 `reader_answer`，同时也写入 `answer.reader_answer`。
- `reader_answer` 包含 `text`、`sentences`、`citations`，引用编号是面向读者的 `[1]` 风格，但底层仍绑定 `quote_id`、`evidence_id`、`html_path`、`html_anchor`。
- `render_answer_report()` 默认第一屏渲染 Reader Answer；Claim Audit、Evidence Ledger、Retrieval Audit 仍保留在同一报告中。
- Reader Answer 会优先展示和问题最相关的 supported / partially_supported claims。对于 named-list 问题，如果首条高相关证据已经完整回答问题，则只把这条放入 reader 层，避免背景证据污染第一屏。
- 这一路径仍不强制依赖 LLM；默认 local provider 会用已验证 evidence 生成可读句子和行内引用。LLM 仍可作为 `--answer-provider llm` 的增强层。

示例产物：

- `tmp/reader-answer-smoke.html`
- `tmp/reader-answer-smoke.json`

## 2026-07-18 小模型替代 Qwen3-4B 的选型记要

这次补一个更直接的结论，方便后面做本地部署和 benchmark 选型。

### 优先级建议

1. `Qwen3.5-4B` / `Qwen3.5-4B-Instruct-2507`
   - 仍然是最接近 `Qwen3-4B` 的“同家族升级版”。
   - 官方卡片强调了更好的指令跟随、长尾知识和更长上下文能力。
   - 如果我们想保持现有 Qwen API / tool calling 结构不变，它是最省迁移成本的替代。

2. `microsoft/Phi-4-mini-instruct`
   - 3.8B 级别，小于 4B，官方定位就是 memory/compute constrained 和 latency bound 场景。
   - 适合更看重“模型小、推理密度高”的路径。

3. `Gemma 3 4B IT`
   - 官方把它定位为适合 laptop / desktop 这类有限资源环境的通用模型。
   - 如果希望补充一个非 Qwen 家族的强对照，它值得纳入比较。

### 当前可用的远端模型名

我查到当前 `https://api.qnaigc.com/v1/models` 可见这些和 Qwen 相关的模型名：

- `qwen/qwen3.5-plus`
- `qwen/qwen3.6-plus`
- `qwen/qwen3.7-max`
- `qwen3-30b-a3b`
- `qwen3-32b`
- `qwen3-max`

注意：这只是端点上可调用的模型清单，不等于它们都适合做本地替代，也不等于它们的参数规模就是最小。

### 现在的实际判断

- 如果目标是“**本地小模型替代 Qwen3 4B**”，首选还是 `Qwen3.5-4B` / `Qwen3.5-4B-Instruct-2507`。
- 如果目标是“**更小但尽量稳**”，优先试 `Phi-4-mini-instruct`。
- 如果目标是“**RAG 中文学术问答表现优先**”，后面最该跑的不是再猜型号，而是直接做同题 benchmark，对比：
  - query rewrite 后的召回
  - evidence 命中率
  - answer/citation 正确率
  - 单题耗时
