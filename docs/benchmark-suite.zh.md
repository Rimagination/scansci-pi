# ScanSci Benchmark Suite 设计

建立日期：2026-06-23

## 一句话原则

ScanSci 的 benchmark 不能只展示“某一次 Qwen3 跑分”。它应该像公开 LLM / IR / RAG benchmark 一样，固定任务、固定方法、固定指标，然后横向比较普通 RAG、hybrid RAG、reranker RAG、agentic RAG 和未来的 graph/late-interaction 方法。

图表只是最后一层展示。真正重要的是：哪些实验可以放在同一张图里，哪些只能作为 smoke test 或开发校准，哪些指标代表准确性，哪些指标代表成本。

## 资料依据

- BEIR 把信息检索评测做成多数据集、多检索架构的横向比较，并强调 BM25、dense、sparse、reranking、late interaction 等方法在效果和计算成本上的差异；这说明 ScanSci 不能只跑一个 embedding 模型。[BEIR paper](https://arxiv.org/abs/2104.08663), [BEIR code](https://github.com/beir-cellar/beir)
- RAGAS 把 RAG 评估拆成检索上下文质量、生成忠实性和答案相关性等维度；这说明 ScanSci 不能只看 retrieval recall，也要看 answer/citation/faithfulness。[RAGAS paper](https://arxiv.org/abs/2309.15217)
- ALCE 把带引用生成分成 fluency、correctness、citation quality；这和 ScanSci 的“证据回答 + 精确引用 + 人眼校对”目标一致。[ALCE paper/code](https://github.com/princeton-nlp/ALCE)
- RAGTruth 面向 RAG 场景标注 hallucination，提醒我们必须单独统计 unsupported claims，而不是只看答案是否流畅。[RAGTruth paper](https://aclanthology.org/2024.acl-long.585/)

## 评测层级

### Layer A：公开校准集

用途：快速发现检索算法、query 策略和 reranker 是否明显退化。

数据集：

- QASPER：论文内 question answering，适合测“给定正确论文后，能不能找到证据句”。
- SciFact：语料级 claim verification，适合测“给定科学 claim，能不能找到支持/反驳证据”。
- BEIR / Climate-FEVER：document-level retrieval，适合测“能不能找到相关文档”，不能冒充句子级 citation benchmark。
- SciERC / ScienceIE：科学实体与关系抽取，适合测 Task / Method / Dataset / Metric / Material 等结构化信息，不能和 QA/retrieval 分数混排。
- 当前 `entity-candidates` 的 `regex` / `scientific-ngram` 只应视为候选召回烟测。2026-07-01 的 ScienceIE test 结果显示，默认 regex untyped F1 约 0.129；宽召回 n-gram 可以把 recall 推到约 0.396，但 precision 约 0.061。第一版本地模型 baseline 已接入：`ml6team/keyphrase-extraction-distilbert-inspec` 在 labelled test 上 untyped F1 约 0.372，`score >= 0.6` 后配合 ScienceIE train gold 训练的 char-logreg type classifier，typed F1 约 0.253；后续若要接近论文强模型，仍需要 SciBERT/PL-Marker/PURE 类 sequence tagging 或官方 scorer 对齐。

限制：

- 公开集可能被现代模型训练见过，适合做论文式公开对比和开发校准，但不能单独夸大成真实本地文献库能力。
- QASPER 的 faithful 默认口径是 `scope=gold-docs`；`scope=corpus` 是额外压力测试。
- smoke50 只能用于健康检查，不和 full-dev 结果同图排名。

### Layer B：可选本地 HTML acceptance set

用途：在公开 benchmark 稳定后，检查 ScanSci 对某个用户真实论文库的可用性。它是工程验收和回归测试，不替代论文式公开 benchmark。

规模：

- 起步可以是 10 到 20 题抽检；需要长期作为质量门时再扩展到 50 到 100 题。
- 每题必须能回到本地 HTML 的 `html_path#anchor`。
- 每题必须标注 `answer_type`、`answerable`、`gold_evidence_ids`、`required_points` 或 `forbidden_points`。

推荐覆盖：

- `single_paper_fact`：单篇事实。
- `single_paper_method`：方法细节。
- `numeric_extraction`：数值、表格、结果句。
- `multi_paper_synthesis`：多篇综合。
- `conflict_evidence`：证据冲突。
- `unanswerable`：库内无证据时正确拒答。

推荐先用 `bench-acceptance` 生成一个本地人工审阅工作台，而不是手写空白 gold 文件：

```powershell
scansci bench acceptance `
  --db .\html-papers\evidence.sqlite `
  --output-dir .\bench\local-acceptance-workbench `
  --questions-per-type 2 `
  --answer-types single_paper_fact,single_paper_method,numeric_extraction,multi_paper_synthesis,conflict_evidence,unanswerable `
  --min-questions 12 `
  --require-answer-types single_paper_fact,single_paper_method,numeric_extraction,multi_paper_synthesis,conflict_evidence,unanswerable `
  --min-per-answer-type 2
```

该命令会生成 `gold_questions.template.jsonl`、HTML 审阅页、validation 报告、`review-draft.template.md`、`README.zh.md` 和 manifest。生成的题默认仍是 `annotation_status=todo`，必须由人工填写问题、核对证据、补齐 required/forbidden points，并改成 `verified` 或 `approved` 后，才能作为正式 benchmark gold。

如果不确定当前项目该走哪一步，可以先运行确定性的 Evidence Agent。它只读取本地证据库和 workbench manifest，不调用大模型：

```powershell
scansci agent status --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
scansci agent next --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
scansci agent plan --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench
scansci agent run --db .\html-papers\evidence.sqlite --acceptance-dir .\bench\local-acceptance-workbench --run-output .\bench\agent-runs\latest.json
```

### Layer C：真实压力测试

用途：测系统在用户真正会用的场景里是否稳。

场景：

- 全库几百到上千篇 HTML。
- 跨论文主题检索。
- 方法/结果/表格/figure caption 混合证据。
- 多轮 query planning。
- 明确限制年份、物种、生态环境、实验条件或研究区。

## 方法矩阵

同一 benchmark 至少应该比较这些方法。每条方法都要有稳定 `method_id`，不要只写模型名。

| method_id | 方法名 | 说明 | 当前状态 |
|---|---|---|---|
| `lexical_fts` | 普通 lexical RAG | FTS/BM25 式文本检索，top-k evidence 直接进入 quote/answer | 需要补 full-dev 跑分 |
| `local_hash_hybrid` | 当前轻量 baseline | FTS + local-hash dense fallback + lexical rerank | 已有部分结果 |
| `dense_minilm` | 小模型 dense RAG | `sentence-transformers/all-MiniLM-L6-v2` | 曾跑过，需要纳入 leaderboard |
| `hybrid_minilm_rerank` | 小模型 hybrid + rerank | MiniLM embedding + MiniLM cross-encoder | 本地 benchmark preset 已有 |
| `hybrid_bge_rerank` | BGE baseline | `BAAI/bge-small-en-v1.5` + `BAAI/bge-reranker-base` | 本地 benchmark preset 已有，外部需跑 |
| `hybrid_qwen3` | Qwen3 embedding | `Qwen/Qwen3-Embedding-0.6B`，无 reranker | 已有部分 QASPER/SciFact 对照 |
| `hybrid_qwen3_rerank` | Qwen3 embedding + Qwen3 reranker | 当前最强公开检索链路 | 已进入 leaderboard |
| `context_parent_window` | 上下文扩展 RAG | 召回 evidence sentence 后补父段落/相邻句 | 待实现/待测 |
| `agentic_followup` | 多步检索 RAG | query planning、follow-up search、adequacy gate | answer pipeline 已有雏形，需系统评测 |
| `graph_or_late_interaction` | Graph / ColBERT 类 | 用于长文档、多跳、实体关系或 late interaction | 实验层，不能替代当前主线 |

## 指标矩阵

### 准确性

| 指标 | 含义 | 适用层 |
|---|---|---|
| `retrieval_recall_at_k` | 可回答题中，top-k 至少命中一个 gold evidence 的比例 | A/B/C |
| `all_gold_retrieval_recall_at_k` | 可回答题中，top-k 找回全部 gold evidence 的比例 | A/B |
| `gold_evidence_recall_at_k` | evidence ID 级别召回率，当前默认排序指标 | A/B |
| `ndcg_at_k` | 排名敏感的文档相关性指标 | BEIR 类 |
| `mrr_at_k` | 第一个相关证据出现得有多靠前 | A/B/C |
| `answer_accuracy` | 答案是否覆盖人工定义的 required/forbidden points | B/C |

### 引用与忠实性

| 指标 | 含义 | 适用层 |
|---|---|---|
| `citation_precision` | 引用的证据中有多少是真正 gold/supporting evidence | B/C |
| `citation_recall` | gold evidence 中有多少被答案引用 | B/C |
| `citation_f1` | citation precision/recall 的综合 | B/C |
| `unsupported_claim_rate` | 答案 claims 中无证据支持的比例 | B/C |
| `answerable_evidence_adequacy_rate` | 可回答题是否满足 quote/source 充分性门槛 | B/C |
| `abstention_accuracy` | 不可回答题是否正确拒答 | B/C |

### 效率与成本

| 指标 | 含义 | 为什么重要 |
|---|---|---|
| `wall_time_seconds` | 整次 benchmark 用时 | 判断是否可日常运行 |
| `avg_wall_time_seconds_per_question` | 单题平均耗时 | 比较复杂 RAG 是否值得 |
| `avg_search_calls_per_question` | 每题检索调用数 | 识别 over-search |
| `avg_fts_candidates_per_question` | 每题 FTS 候选数 | 衡量 lexical recall 成本 |
| `avg_dense_candidates_per_question` | 每题 dense 候选数 | 衡量 dense 检索成本 |
| `avg_reranked_candidates_per_question` | 每题进入 reranker 的候选数 | reranker 成本核心指标 |
| `embedding_cache_hit_rate` | embedding cache 命中率 | 区分冷启动和热缓存 |
| `reranker_score_cache_hit_rate` | reranker score cache 命中率 | 解释重跑速度 |
| `peak_vram_mb` | GPU 峰值显存 | 大模型/ColBERT 必须报 |
| `estimated_cost_usd` | hosted API 成本 | 远程模型必须报 |

当前代码已经有 cache、candidate、trace 相关字段；下一步应补 `wall_time_seconds`、每题耗时、可选 GPU/成本记录。

### 鲁棒性与可信度

| 指标 | 含义 |
|---|---|
| `benchmark_split` | `dev` / `calibration` / `blind`，避免把调参集当盲测 |
| `scope` | `gold-docs` / `corpus` / `full-library`，避免混淆任务难度 |
| `answer_type` breakdown | 分题型报告，避免平均分掩盖 numeric/conflict 弱点 |
| `section_kind` breakdown | 方法、结果、讨论、表格、caption 分层 |
| `leakage_risk` | public benchmark、local blind、manual gold 的风险级别 |

## 可比性规则

只有满足以下条件，才允许放进同一张柱状图：

1. 同一数据集。
2. 同一 split。
3. 同一 scope。
4. 同一 k。
5. 同一题量。
6. 同一候选预算口径，例如 `initial_limit` / `dense_limit`。
7. 同一评分目标，例如 sentence-level evidence recall 不能和 document-level BEIR recall 混排。

如果不满足，应单独成图，或者在图中明确标成 `not comparable`。

## 推荐图表

### 图 1：Evidence Retrieval Accuracy

横轴：QASPER full-dev、SciFact full-dev、Climate-FEVER dev、可选本地 HTML acceptance set。

颜色/柱子：`lexical_fts`、`dense_minilm`、`hybrid_bge_rerank`、`hybrid_qwen3`、`hybrid_qwen3_rerank`、`agentic_followup`。

主指标：`gold_evidence_recall_at_k`。BEIR 类用 `ndcg_at_k` 或 document recall 单独成图。

### 图 2：Answer Grounding Quality

横轴：本地 HTML acceptance set 的题型。

柱子：各方法。

指标：`citation_f1`、`unsupported_claim_rate`、`abstention_accuracy`。`unsupported_claim_rate` 越低越好，不能和越高越好的指标混在同一 y 轴。

### 图 3：Efficiency / Cost

横轴：方法。

指标：

- 单题平均耗时。
- 每题搜索次数。
- 每题 rerank 候选数。
- cache hit rate。
- 可选 GPU 显存和 API 成本。

这个图用来回答“复杂 RAG 是否值得”。如果准确率只涨 1 个百分点但耗时涨 10 倍，就不应作为默认链路。

## 当前项目状态

已经有：

- QASPER / SciFact / BEIR import。
- QASPER / SciFact / BEIR external retrieval scorer。
- SciERC / ScienceIE import。
- `ie-bench` 实体抽取 precision/recall/F1 scorer。
- Qwen3 embedding + Qwen3 reranker 的 QASPER/SciFact full-dev 结果。
- FTS smoke50 结果。
- 本地 `bench` 的 answer/citation/abstention 指标。
- `bench-leaderboard` 表格和 SVG/HTML 分组柱状图。
- retrieval trace、candidate counts、cache stats。

还缺：

- full-dev `lexical_fts` 基线。
- full-dev MiniLM / BGE / E5 / GTE 等方法。
- SciERC / ScienceIE 的强实体抽取 baseline 与关系抽取 scorer。
- `wall_time_seconds` 与单题耗时。
- 可选本地 HTML acceptance set。
- answer-level 多方法 leaderboard。
- 图表对 `not run` 和 `not comparable` 的显式标注。

## 下一步执行顺序

1. 给 `bench` 和 `bench-external` details 增加 wall-time 字段。
2. 把 `bench-leaderboard` 的 chart 改成只展示完整可比矩阵，缺失值明确标为 `not run`。
3. 先补 full-dev 低成本基线：`lexical_fts`、`dense_minilm`、`hybrid_minilm_rerank`。
4. 再补强模型：BGE/E5/GTE/Qwen3。
5. 生成 Accuracy / Grounding / Efficiency 三张图。
6. 如果需要真实语料验收，再把本地 HTML acceptance set 接进同一协议，但单独标成 `local-html`，不和公开集混淆。
