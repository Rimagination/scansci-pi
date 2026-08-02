# ScanSci 错题集（Quality Ledger）

建立日期：2026-06-21

## 目的

这个错题集不是普通开发日志，而是 ScanSci 的质量记忆层。它记录我们在论文获取、证据检索、RAG 回答、引用标注、benchmark 和人工校对中已经犯过的错、暴露的短板、踩过的坑，以及对应的复现方式、根因、修复办法和回归保护。

目标很明确：

1. 每一次失败都能被定位到具体证据，而不是只留下“效果不好”的印象。
2. 每一次修复都能转化成测试、benchmark、人工 gold set 或工程约束。
3. 项目长期演进时，后来的人能知道哪些路已经试过、为什么不能只看表面指标。
4. 让 ScanSci 形成“知错能改”的闭环：发现问题 -> 记录问题 -> 修复问题 -> 防止复发 -> 重新评测。

## 文件分工

- 人读主文档：`docs/mistake-ledger.zh.md`
- 机器可追加记录：`bench/mistake_cases.jsonl`
- 新记录模板：`bench/mistake_cases.template.jsonl`
- 相关 benchmark 详情：`bench/*details*.json`
- 真实论文人工 gold set：未来建议放在 `bench/gold_questions.local.*.jsonl`

## 什么必须进入错题集

以下情况一律记录：

- benchmark 指标显著低于预期，例如 QASPER evidence recall 很低。
- 某个问题没有找回正确证据，或者证据排序明显错误。
- 回答内容看似正确，但引用句不能支撑该 claim。
- exact quote、HTML anchor、evidence id、source link 任一环节错位。
- 下载/清洗阶段误把摘要页、预览页、参考文献页当成正文。
- PDF/Markdown 转换导致结构、表格、图注、段落边界或引用定位丢失。
- 公开 benchmark 存在数据泄露、scope 降难度或过拟合风险。
- 某个模型、参数或 pipeline 看起来提升指标，但其实不可复现、不可扩展或成本过高。
- 人工校对发现“系统答案能骗过粗看，但经不起原文核对”。

不需要记录：

- 一次性拼写错误。
- 已经被普通单元测试覆盖、且没有方法学价值的小 bug。
- 没有复现信息、没有证据链接、没有行动项的泛泛吐槽。

## 标准结构

每条错题必须至少包含这些字段：

```json
{
  "id": "SS-AREA-YYYYMMDD-SHORT-NAME",
  "created_at": "YYYY-MM-DD",
  "updated_at": "YYYY-MM-DD",
  "status": "open | in_progress | fixed | regression_guarded | accepted_risk",
  "severity": "P0 | P1 | P2 | P3",
  "area": "capture | evidence | ask | verify | review | bench | docs | performance",
  "failure_type": "retrieval_miss | wrong_ranking | wrong_route | bad_query_variant | under_search | over_search | wrong_scope | unsupported_answer | citation_mismatch | data_leakage_risk | benchmark_bias | performance_bottleneck | capture_false_positive | format_loss | process_gap",
  "title": "一句话说明问题",
  "symptom": "我们看到了什么坏现象",
  "evidence": ["能复现或证明问题的文件、命令、指标、样例"],
  "root_cause": "当前最可信的根因判断",
  "fix": "已经做了什么，或者准备怎么做",
  "regression_guard": "如何防止复发：测试、benchmark、gold set、人工流程或工程约束",
  "next_action": "下一步最小行动",
  "links": ["相关详情文件或文档"]
}
```

状态定义：

- `open`：问题明确，但还没有修复。
- `in_progress`：正在修。
- `fixed`：已经修复，但还没有形成稳定回归保护。
- `regression_guarded`：已经有测试、benchmark 或人工流程防止复发。
- `accepted_risk`：短期接受风险，但必须写清楚原因和边界。

严重度定义：

- `P0`：会导致错误论文证据、错误引用、错误结论，必须优先处理。
- `P1`：影响核心可信度或评测可信度。
- `P2`：影响性能、体验、可维护性，暂不直接破坏答案正确性。
- `P3`：文档、命名、流程等改进项。

## RAG 错题的额外字段

如果错题来自问答或证据检索，建议额外补充：

```json
{
  "question": "用户问题或 benchmark question",
  "gold_evidence": ["正确 evidence id 或原文 quote"],
  "predicted_evidence": ["系统找回的 evidence id 或 quote"],
  "answer_expected": "应回答什么",
  "answer_actual": "系统实际回答什么",
  "retrieval_queries": ["实际执行过的 query 或 query variant"],
  "retrieved_route_counts": {"fts": 0, "dense": 0, "query-1": 0},
  "retrieval_trace_summary": {
    "search_calls": 0,
    "queries": 0,
    "fts_candidates": 0,
    "dense_candidates": 0,
    "unique_candidates": 0,
    "reranked_candidates": 0,
    "returned_hits": 0
  },
  "metric_before": {"retrieval_at_20": 0.0, "evidence_recall_at_20": 0.0},
  "metric_after": {"retrieval_at_20": 0.0, "evidence_recall_at_20": 0.0}
}
```

## 自动诊断标签

`bench-mistakes` 会在 details 包含 `retrieval_trace` 或 `retrieval_trace_summary` 时自动补充检索诊断标签。没有 trace 的历史结果保持旧分类，不强行猜测根因。

- `under_search`：候选数或返回结果为 0，说明 reranker 没有机会看到 gold evidence。
- `bad_query_variant`：执行了多个 query variant，但后续 query 没有贡献候选或命中路线，优先检查 query 改写。
- `wrong_route`：系统返回了证据，但没有任何 mapped gold evidence，说明 dense/FTS/hybrid route 或 reranker 指向了干扰证据。
- `wrong_scope`：检索 scope 过窄或为空，可能把正确文档排除在检索范围外。
- `over_search`：已经找回部分 gold evidence 后仍继续发起额外搜索，后续需要加 stop rule 或过程奖励。

这些标签不是最终判决，而是排查优先级。真正修复前仍要看原文、gold evidence、retrieval trace 和返回证据。

## 首批错题

这些记录来自 2026-06-20 至 2026-06-21 的证据 RAG 建设和 QASPER / SciFact benchmark。

### SS-BENCH-20260621-QASPER-LOW-BASELINE

状态：`fixed`

严重度：`P1`

问题：QASPER 在 embedding-only 链路下 evidence recall 偏低，说明“只做向量召回”不足以支撑论文证据问答。

现象：

- QASPER MiniLM embedding-only，`k=20`，evidence recall 约 `0.527037`。
- QASPER Qwen3 embedding-only，`k=20`，evidence recall 约 `0.538462`。
- 换更强 embedding 有提升，但幅度有限。

根因判断：

- QASPER 问题经常需要跨段落、方法、结果、实验设置理解，单向量相似度容易召回语义相近但不能直接支撑答案的句子。
- 证据检索不能只看 first-stage retrieval，需要第二阶段 cross-encoder reranker。

已经采取的改进：

- 接入 `Qwen/Qwen3-Embedding-0.6B`。
- 接入 `Qwen/Qwen3-Reranker-0.6B` cross-encoder reranker。
- 以 `initial_limit=20`、`dense_limit=20` 完整重跑 QASPER gold-docs。

改进后结果：

- QASPER Qwen3 embedding + Qwen3 reranker：`retrieval@20=0.773499`，`all-gold@20=0.625142`，`evidence recall@20=0.635187`。

回归保护：

- 保留 `bench/qasper-external-details.qwen3-reranker.full.k20.candidate20.json`。
- 后续把 QASPER 加入固定开发校准集，但不能作为最终真实性证明。

下一步：

- 在 reranker score cache 完成后，补跑 `candidate=50/100/200`。

### SS-BENCH-20260621-SCIFACT-RERANKER-GAIN

状态：`fixed`

严重度：`P1`

问题：SciFact claim verification 对证据排序敏感，embedding-only 召回不足。

现象：

- SciFact Qwen3 embedding-only：`retrieval@20=0.723404`，`all-gold@20=0.478723`，`evidence recall@20=0.551913`。
- local hash baseline 更低：`retrieval@20=0.664894`，`all-gold@20=0.409574`，`evidence recall@20=0.480874`。

根因判断：

- SciFact 的 claim 与证据句常常是语义等价但表达不同，第一阶段召回会混入大量主题相关但论证关系不够直接的句子。

已经采取的改进：

- 使用 Qwen3 reranker 对候选证据重新排序。

改进后结果：

- SciFact Qwen3 embedding + Qwen3 reranker：`retrieval@20=0.920213`，`all-gold@20=0.792553`，`evidence recall@20=0.825137`。

回归保护：

- 保留 `bench/scifact-external-details.qwen3-reranker.full.k20.candidate20.json`。

下一步：

- 引入 label-level verification 评测，不只看 evidence recall。

### SS-PERF-20260621-RERANKER-NO-SCORE-CACHE

状态：`regression_guarded`

严重度：`P2`

问题：Qwen3 reranker 对大候选集重排成本太高，默认 `candidate=200` 和 `candidate=50` 的完整重跑耗时不可接受。

现象：

- SciFact full default candidate 运行超过 20 分钟未完成，被停止。
- SciFact candidate50 也超过 10 分钟未完成，被停止。
- candidate20 可以完成，但不能代表最终上限。

根因判断：

- 当前链路已经有 text embedding cache 和 query embedding cache，但还没有 reranker score cache。
- reranker 每次都重复计算 `(query, candidate_span)` 对的 cross-encoder 分数。
- 没有按 question checkpoint/resume，长任务中断后重跑成本高。

已经采取的改进：

- 暂时用 `initial_limit=20`、`dense_limit=20` 跑通完整链路。
- 实现 `external_reranker_score_cache` SQLite 分数缓存，缓存 `(query_hash, evidence_id, reranker_name, candidate_text_hash)` 的重排分数。
- 实现 `--checkpoint` JSONL 逐题断点续跑，完成一题就落盘，中断后可跳过已完成问题。
- 增加 `--reranker-cache-name`，CLI 在 cross-encoder 模式下也会自动生成 provider/model 缓存名。

回归保护：

- 把 candidate20 结果标注为“bounded rerank run”，不能宣传成 full candidate 上限。
- 新增测试覆盖跨运行复用 reranker score cache。
- 新增测试覆盖 benchmark 中断后从 checkpoint 跳过已完成问题。

下一步：

- 重跑 candidate50/100/200，记录耗时和指标边际收益。

### SS-BENCH-20260621-GOLD-DOC-SCOPE-BIAS

状态：`accepted_risk`

严重度：`P1`

问题：QASPER 当前主要跑 `gold-docs` scope，已经给定正确论文，只评测“论文内证据检索”，不能等价于真实文献库检索。

现象：

- QASPER gold-docs 适合测试 evidence finding。
- 但真实 ScanSci 场景还需要先从 library 中找对论文，再从论文中找对证据。

根因判断：

- gold-docs scope 是合理的中间评测，但如果不清楚标注，会造成能力夸大。

已经采取的改进：

- 在结果解释中明确区分 `gold-docs`、`corpus`、`full-library`。

回归保护：

- 任何 benchmark 报告必须写出 `scope`、`k`、`initial_limit`、`dense_limit`、`model`。

下一步：

- 先补公开 benchmark / 论文协议下的 full-library 或 corpus-level 检索评测。
- 如需验证真实业务可用性，再建立小规模本地 HTML acceptance set，并与公开 benchmark 分开报告。

### SS-EVAL-20260621-PUBLIC-BENCHMARK-LEAKAGE

状态：`open`

严重度：`P1`

问题：QASPER 和 SciFact 是公开数据集，现代 embedding / reranker 模型可能在预训练或后训练阶段见过，公开 benchmark 结果不能单独证明真实论文库能力。

现象：

- Qwen3 模型在公开 benchmark 上表现提升明显。
- 但无法确认模型训练语料是否包含 benchmark 样本。

根因判断：

- 公开 benchmark 适合发现 pipeline 问题，不适合作为唯一可信度证明。

已经采取的改进：

- 把 QASPER / SciFact 定位为开发校准集，而不是最终宣传指标。

回归保护：

- 对外报告必须区分公开 benchmark、合成/LLM judge、人工抽检和本地 acceptance set，不能把任一层单独包装成完整真实能力证明。

下一步：

- 优先复现公开数据集和论文协议；如要验证本地语料可用性，再从真实 `html-papers` 中抽样做小规模 acceptance set。
- 如果本地 acceptance set 扩展到质量门，保留一部分 holdout，不参与调参。

### SS-CAPTURE-20260620-HTML-SAVED-NOT-FULLTEXT

状态：`regression_guarded`

严重度：`P0`

问题：不能把“HTML 下载成功”误认为“论文正文完整保存成功”。

现象：

- 期刊页面可能返回 HTTP 200、标题、摘要、参考文献或预览内容，但并没有可用正文。
- Nature / Science / Wiley / Elsevier 等站点存在订阅入口、折叠参考文献、预览页、授权状态混杂等情况。

根因判断：

- 论文 capture 的成败应该由 article structure 和正文证据判断，而不是由 HTTP 状态码、标题存在或页面长度判断。

已经采取的改进：

- 增加 `article_structure` 层，检查 body/endmatter、section headings、figures、references、access markers。
- 对 access-gate text 但无正文结构的页面拒绝保存为 full text。
- Science 折叠 references 未展开时阻断保存。

回归保护：

- 结构 gate 已写入架构文档。
- 相关逻辑由测试覆盖。

下一步：

- 对每个 publisher recipe 维护最小结构验收样例。

### SS-EVIDENCE-20260621-CONTEXT-VS-QUOTE

状态：`fixed`

严重度：`P0`

问题：为了提升阅读上下文而扩大 evidence context 时，不能把扩大后的 block 当成 exact quote；否则引用标注会变粗，甚至把不支持 claim 的邻近句也算进去。

现象：

- 证据检索需要 block context 才能让模型理解段落。
- 但论文写作引用需要句子级 exact quote 和可定位 anchor。

根因判断：

- retrieval context 和 citation quote 是两种不同产物，不能混用。

已经采取的改进：

- 新链路使用 `context_mode=block` 展示父块上下文。
- exact quote 仍然使用 `span_text`。
- evidence table/report 区分上下文显示与句子级引用。

回归保护：

- 对 citation/evidence span 相关测试保持覆盖。

下一步：

- 在人工校对界面明确显示：命中句、上下文、source anchor 三者的边界。

### SS-FORMAT-20260621-HTML-FIRST-NOT-MARKDOWN

状态：`accepted_risk`

严重度：`P1`

问题：PDF 转 Markdown 或纯 Markdown 作为证据载体会损失论文结构和可定位性，不适合作为 ScanSci 的主证据格式。

现象：

- PDF 解析可能丢失段落顺序、表格结构、图注、公式、引用锚点和 publisher metadata。
- Markdown 易读，但不是论文原文结构的忠实载体。

根因判断：

- 机器检索、RAG、引用标注和人眼校对都需要稳定 anchor、DOM structure、section hierarchy 和原文上下文。

当前决策：

- ScanSci 采用 HTML-first：下载端尽量保留 publisher HTML / official XML 可提供的信息。
- Markdown 可以作为派生阅读视图，但不能作为 evidence source of truth。

回归保护：

- evidence id、HTML anchor、`.evidence.html` sidecar 和 SQLite span store 共同构成证据定位层。

下一步：

- 对 official XML/JATS 作为 sidecar 的价值继续评估；HTML 仍是人眼校对优先载体。

## 每次 benchmark 后的记录流程

1. 运行 benchmark，保存 details JSON。
2. 找出所有失败样本：没有召回 gold evidence、排序低、证据不完整、unmapped gold evidence。
3. 把典型失败写入 `bench/mistake_cases.jsonl`。
4. 如果是系统性问题，在本文件补充一条复盘。
5. 修复后记录 before/after 指标。
6. 为问题补上测试、benchmark gate 或人工校对规则。

## 每次本地 acceptance set 校对后的记录流程

1. 对每个错误答案标注 `failure_type`。
2. 把用户问题、正确证据、系统证据、错误答案、正确答案写入 JSONL。
3. 区分三种错误：
   - 没找回正确论文。
   - 找到论文但没找回正确证据。
   - 找到证据但回答或引用解释错。
4. 优先修 P0/P1。
5. 不把 holdout gold set 反复用于调参。

## 对外表述约束

当引用 benchmark 成绩时必须同时说明：

- 使用的数据集。
- 使用的 scope。
- 使用的模型。
- `k`、`initial_limit`、`dense_limit`。
- 是否使用 reranker。
- 是否可能存在公开 benchmark 数据泄露或过拟合风险。
- 是否包含公开 benchmark、合成/LLM judge、人工抽检或本地 acceptance set；这些层是否分开报告。

一句话原则：

> 公开 benchmark 是论文式验证主线；本地 HTML acceptance set 只证明特定语料的可用性，必须分开报告。

### SS-MODEL-20260624-OPEN-SCHOLAR-NOT-DEFAULT

状态：`accepted_risk`

严重度：`P1`

问题：学术专用 reranker 看起来更贴近论文场景，但在公开 benchmark 上不一定比轻量 reranker 更好；如果直接把它设为默认链路，可能得到更慢、并不更准的系统。

现象：
- `Qwen3 embedding + OpenScholar_Reranker` 在 QASPER 上略高于 MiniLM-Rerank：0.624524 vs 0.621478。
- 在 TREC-COVID 上略高于 MiniLM-Rerank：0.033032 vs 0.030965。
- 在 SciFact 上略低于 MiniLM-Rerank：0.833333 vs 0.838798。
- 在 NFCorpus 和 SciDocs 上明显低于 MiniLM-Rerank：0.073699 vs 0.093076；0.202922 vs 0.234578。
- 计算成本显著更高：OpenScholar 单题耗时约 2.30s 到 12.56s，远高于 MiniLM-Rerank 的同类运行。

根因判断：
- cross-encoder reranker 的领域适配不等于所有检索任务的排序适配。
- 文档级 BEIR 任务、句子级证据任务、医学/科学问答任务的相关性定义不同，单一 reranker 很难全胜。
- 当前候选池为 `initial_limit=200`、`dense_limit=200`，OpenScholar 需要对大量 `(query, candidate)` 对打分，成本直接放大。

已经采取的改进：
- 完整跑通 5 个公开测试集、每集 7 种方法的新 full matrix。
- 新图和表保存到 `bench/benchmark_performance.public-full-matrix-openscholar.*`，稳定图入口同步为 `bench/evidence_retrieval_leaderboard_chart.html`。
- 将 OpenScholar 定位为可选高精度 reranker，而不是默认主链路。

回归保护：
- 新模型必须进入同一套 full matrix，而不能只看单一测试集。
- 图表必须同时保留准确性和效率指标；如果收益很小但耗时大幅增加，不应设为默认。
- 默认链路选型优先看公开 benchmark 的平均表现、失败类型和效率；本地 HTML acceptance set 用于真实语料验收，单独报告。

下一步：
- 实现 cascade rerank：先用轻量 reranker 排前 50，再让 OpenScholar 只重排 top-N，测试是否保留收益并降低成本。
- 增加半精度/量化加载选项，但必须单独标记为新的运行配置，避免与本次 fp32 结果混淆。
- 如需要真实语料验收，再在本地 HTML acceptance set 上复测 OpenScholar，判断它是否对本地论文证据定位有独特价值。
