# Query Rewrite 专项调研与 ScanSci 强化方案

日期：2026-07-02

## 结论先行

ScanSci 现在最该补的不是更大的 reranker，而是一个可审计、可缓存、可评测的 query rewrite/query transformation 层。更适合我们的默认路线是：

```text
用户问题
-> 轻量 query router
-> 结构化 query rewrite plan
-> 多查询 hybrid retrieval
-> RRF 融合
-> 单次 cross-encoder rerank
-> evidence adequacy gate
-> 必要时再做一次 follow-up rewrite
```

这条路线比 PaperQA2 式全 agent 搜索更可控，也比当前单查询检索更稳。它符合近两年论文和主流 RAG 框架的共同方向：先把用户自然语言问题翻译成检索器更容易命中的若干查询，再用融合和重排控制噪声。

## 已落地状态

2026-07-02 已把这条路线落到代码：

- `src/scansci_html/qa/query_planner.py`：新增结构化 `routes`、`answer_type`、`expected_answer_count`、`language`、`section_hints` 和中英文术语路由；保留旧 `query_variants` 字段兼容旧报告。
- `src/scansci_html/query_fusion.py`：新增 weighted RRF 融合，记录 `rrf_score`、`fusion_routes`、`route_ranks` 和命中的 `retrieval_queries`。
- `src/scansci_html/qa/agent.py`：多 query 时先用本地 lexical/hybrid 召回，再 RRF 融合；如果配置了强 reranker，只对融合候选精排一次；对列表/比较/冲突/综述类问题，会把命中句扩展到同一 paragraph/block 的邻近证据，避免答案名称落在相邻句时漏召回。
- `src/scansci_html/bench_external.py`：QASPER/SciFact/BEIR external benchmark 使用同一 query rewrite 路线；checkpoint hash 纳入 `deterministic_query_rewrite_plan_v1_rrf`，避免旧结果混用。
- 已补测试：中文 query rewrite、multi-query 下强 reranker 只调用一次、external benchmark multi-query synonym recovery。

当前默认实现是“确定性 rewrite + RRF”，不默认生成 HyDE/pseudo-answer，也不把具体答案词硬编码进扩展词。LLM rewrite 仍应作为下一层可缓存增强，而不是基础依赖。

## 改造前的短板

改造前 `src/scansci_html/qa/query_planner.py` 主要做规则化 core terms、年份过滤、少量 section hint 和 follow-up query。`src/scansci_html/qa/agent.py` 会把原问题和 `query_variants` 送入 retrieval，但默认数量有限，且没有 LLM 语义扩展、HyDE、问题分解、RRF 融合、section-aware answer type 约束。

这解释了 PaperQA2 对比里的失败：

- “six hallmark capabilities listed in the abstract” 没有被改写成摘要里的列举句检索问题，也没有推断 answer type 是 list。
- “two enabling characteristics” 没有生成 `genome instability and mutation`、`tumor-promoting inflammation` 这类潜在术语查询。
- gold evidence 在库里，但自然问题和论文术语之间存在 vocabulary mismatch。

## 顶会论文怎么做

| 方法 | 代表论文 | 做法 | 对 ScanSci 的启发 |
|---|---|---|---|
| Query rewrite | [Rewrite-Retrieve-Read, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.322.pdf) | 先用 LLM 改写查询，再检索，再阅读；还尝试训练小 rewriter 对齐 frozen retriever/reader。 | 我们可以先用 API LLM 做 JSON rewrite，再把缓存数据积累成小模型训练集。 |
| Query expansion | [Query2doc, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.585/) | LLM 生成 pseudo document，把它和原查询拼起来，提升 sparse/dense retrieval。 | 对“术语不一致”的问题很有用，但要防止扩展太长导致噪声。 |
| HyDE | [HyDE, ACL 2023](https://aclanthology.org/2023.acl-long.99/) | 先生成 hypothetical document，再用它的 embedding 做检索。 | 适合短问题和事实问答；开放式综述问题默认不用，因为 LlamaIndex 文档也提示 HyDE 可能让开放问题偏向假设答案。 |
| Iterative retrieval | [IRCoT, ACL 2023](https://aclanthology.org/2023.acl-long.557/)；[Iter-RetGen, EMNLP Findings 2023](https://aclanthology.org/2023.findings-emnlp.620/) | 用中间推理/生成内容继续指导下一轮检索。 | 适合多跳问题；对我们应作为 evidence adequacy 失败后的 follow-up，而不是每题默认跑多轮。 |
| Query generation blending | [BlendFilter, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.58/) | 混合原查询、内部知识、外部检索信号生成查询，并过滤噪声知识。 | 我们可以用第一轮检索的 heading/abstract/top sentences 反过来生成第二轮查询。 |
| Reranker feedback | [RaFe, EMNLP Findings 2024](https://aclanthology.org/2024.findings-emnlp.49.pdf) | 用公开 reranker 给 query rewrite 提供无标注反馈。 | 我们已有 MiniLM/Qwen3/OpenScholar reranker，可以用“重写后 top-k 是否更像 gold evidence”做离线反馈。 |
| Adaptive routing | [Adaptive-RAG, NAACL 2024](https://aclanthology.org/2024.naacl-long.389/)；[UniRAG, ACL 2025](https://aclanthology.org/2025.acl-long.693/)；[Q-PRM, EMNLP Findings 2025](https://aclanthology.org/2025.findings-emnlp.817.pdf) | 不同复杂度问题选择不同增强策略；UniRAG 把 paraphrase、expansion、abstraction 统一建模。 | 关键：不要每题都上最贵流程。简单事实题直接检索；抽象/多跳/列表题才扩展。 |
| Knowledge-aware expansion | [KAR, NAACL 2025](https://aclanthology.org/2025.naacl-long.216/) | 用知识图谱/关系约束避免只做语义相似扩展。 | 对学科文献库，关系可以来自 section、citation、entity、method、dataset、指标。 |
| Question decomposition | [Question Decomposition for RAG, ACL SRW 2025](https://aclanthology.org/2025.acl-srw.32/) | 把复杂问题拆成子问题，分别检索，合并候选，再 cross-encoder rerank。 | 对比较题、机制题、综述矩阵题很适合。 |

## GitHub 和主流框架怎么做

| 项目/框架 | 相关实现 | 观察 |
|---|---|---|
| LangChain | 官方 retrieval 文档把 Hybrid RAG 拆成 query enhancement、retrieval validation、answer validation，并说明 query enhancement 包括 rewrite、多变体和 expansion。[docs](https://docs.langchain.com/oss/python/langchain/retrieval) | 框架层面已经把 query enhancement 视为 Hybrid RAG 的核心步骤。 |
| LlamaIndex | Query transformations 支持 HyDE、sub-question decomposition；QueryFusionRetriever 支持生成多个查询，并用 reciprocal rerank fusion 合并 BM25/vector 结果。[query transformations](https://developers.llamaindex.ai/python/framework/optimizing/advanced_retrieval/query_transformations/), [RRF retriever](https://developers.llamaindex.ai/python/framework/integrations/retrievers/reciprocal_rerank_fusion/) | 这和我们要做的“多查询 + hybrid + RRF + rerank”高度一致。 |
| Haystack | `QueryExpander` 用 LLM 生成 JSON `queries`，要求保持原问题语言、换词、同义词、相关术语，并默认包含原查询。[source](https://raw.githubusercontent.com/deepset-ai/haystack/main/haystack/components/query/query_expander.py) | 对中文适配很有参考价值：保留输入语言，同时可生成英文科学术语查询。 |
| PaperQA2 | README 明确使用 LLM-generated keyword query 搜索论文，gather evidence 时做 contextual summarization/re-score；agent 可用不同措辞继续 gather evidence。[README](https://github.com/Future-House/paper-qa) | PaperQA2 的强项是 agentic evidence gathering，但它慢。我们应吸收“不同措辞 gather evidence”，不照搬全 agent 成本。 |
| Elasticsearch / LlamaIndex RRF | RRF 将多个不同 relevance indicator 的结果集合并，不要求分数同尺度，默认 `rank_constant=60`。[Elastic docs](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) | 我们当前 dense/FTS/reranker 分数尺度不同，RRF 是非常合适的融合层。 |

## 对 ScanSci 的具体设计

### 1. QueryRewritePlan 对象

建议新增正式对象，而不是让 `query_variants` 只是字符串数组：

```json
{
  "original_query": "What are the two enabling characteristics proposed in the paper?",
  "language": "en",
  "intent": "list",
  "answer_type": "named_list",
  "section_hints": ["abstract", "section_heading", "discussion"],
  "routes": [
    {
      "label": "original",
      "query": "two enabling characteristics proposed paper",
      "retrieval": ["bm25", "dense"],
      "weight": 1.0
    },
    {
      "label": "terminology_expansion",
      "query": "enabling characteristics genome instability mutation tumor-promoting inflammation",
      "retrieval": ["bm25", "dense"],
      "weight": 1.0
    },
    {
      "label": "section_heading",
      "query": "An enabling characteristic genome instability inflammation",
      "retrieval": ["bm25"],
      "weight": 0.8
    },
    {
      "label": "hyde_answer",
      "query": "The two enabling characteristics are genome instability and mutation, and tumor-promoting inflammation.",
      "retrieval": ["dense"],
      "weight": 0.6
    }
  ],
  "followup_policy": {
    "trigger": "answer_type=list and distinct_items_found < expected_count",
    "max_rounds": 1
  }
}
```

### 2. 默认只做一次 LLM rewrite

为了避免 PaperQA2 那种 5 题都很慢的情况，默认每题只允许一次 rewrite LLM 调用，并缓存：

- cache key：问题文本 + corpus fingerprint + prompt version。
- 输出必须是 JSON，不能直接回答用户问题。
- 每个 route 都记录 label，方便 benchmark 追踪是哪一路召回 gold evidence。

### 3. 检索融合方式

建议每个 route 同时跑：

- BM25/FTS：抓术语和精确短语。
- Dense embedding：抓语义近似。
- Section-aware filter/boost：abstract、methods、results、discussion、figure/table caption。

然后使用 RRF 合并所有 route 的候选，再对合并后的 top 100/200 做一次 cross-encoder rerank。不要对每个 query 都单独 rerank，否则成本会线性膨胀。

### 4. 中文适配

中文问题不应直接只用中文检索英文论文。rewriter 应输出：

- `display_query_zh`：给用户看的中文意图。
- `search_queries_en`：英文科学术语查询。
- `bilingual_terms`：中文术语、英文术语、缩写。
- `answer_language`：默认中文回答，但 evidence quote 保持原文。

例如：

```json
{
  "display_query_zh": "论文提出的两个 enabling characteristics 是什么？",
  "search_queries_en": [
    "two enabling characteristics genome instability mutation tumor-promoting inflammation",
    "emerging hallmark enabling characteristic cancer genome instability inflammation"
  ],
  "bilingual_terms": [
    {"zh": "基因组不稳定性和突变", "en": "genome instability and mutation"},
    {"zh": "促肿瘤炎症", "en": "tumor-promoting inflammation"}
  ]
}
```

### 5. Evidence adequacy 驱动 follow-up

第一次 retrieval 后，不要马上让 LLM 作答。先检查：

- list 问题是否找到了足够数量的 distinct items。
- comparison 问题是否覆盖双方实体。
- synthesis 问题是否覆盖多个 paper/doc。
- 引用句是否来自强证据 section，而不是只来自泛泛背景句。

如果失败，只做一次 follow-up rewrite。follow-up 的输入包括：原问题、top hit heading、top hit text、缺失的 answer slots。

## 推荐优先级

1. 先实现 deterministic router：识别 list/comparison/method/mechanism/synthesis、section hints、expected count。
2. 实现 LLM JSON rewriter：生成 3-5 个 routes，支持中文问题转英文术语检索。
3. 实现 RRF fusion：把多 query、多 retriever 结果合并成统一候选池。
4. 只对融合后的候选做一次 rerank：先 MiniLM，必要时 Qwen3/OpenScholar cascade。
5. 用现有 benchmark 加一个 `query_rewrite` 维度：记录 recall@k、gold evidence recall、耗时、rewrite cache hit、每题检索次数。
6. 在 Hallmarks 4 问、SciFact、QASPER、HotpotQA 小样本上做 ablation：单查询 vs rule rewrite vs LLM rewrite vs HyDE vs decomposition。

## 不建议默认采用的做法

- 不建议每题都跑完整 agentic retrieval。它像 PaperQA2 一样强，但不适合几千篇文献上的日常交互。
- 不建议默认 HyDE。HyDE 对事实题有效，但对开放式综述可能把系统带向 LLM 假设出来的答案。
- 不建议只做 paraphrase。学术文献检索真正缺的是术语、section、实体关系、answer type，不只是换句话说。
- 不建议把 query rewrite 和 final answer 混成一个 prompt。rewrite 只服务检索，应保持可审计和可评测。

## 我认为的“当下最好做法”

对 ScanSci 这种个人本地文献库，最优不是单一论文方法，而是组合：

```text
Adaptive query routing
+ LLM structured query rewrite
+ bilingual terminology expansion
+ section-aware hybrid retrieval
+ RRF fusion
+ one-pass rerank
+ evidence adequacy follow-up
```

这套方法吸收了 Query2doc/HyDE/Rewrite-Retrieve-Read/IRCoT/UniRAG 的优点，但把成本压在可接受范围内。它也能解释我们当前和 PaperQA2 的差距：PaperQA2 会主动换措辞找证据，而 ScanSci 现在只是把自然问题粗略切成词。
