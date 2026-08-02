# ScanSci 检索决策优化路线

建立日期：2026-06-23

这份文档把 `观点11：2026 ICLR RAG 前沿论文精读.md` 里对 ScanSci 有用的方向落到工程动作上。当前阶段的核心目标不是马上训练 RL agent，而是先把检索过程变成可观察、可评估、可替换的动作系统。

## 已找到的可复用代码

| 方向 | 代码/资料 | 复用判断 |
|---|---|---|
| HiPRAG：过程奖励、over-search / under-search | https://github.com/qualidea1217/HiPRAG | 适合借鉴 search/no-search 过程奖励、轨迹标签和 OSR/USR 指标；完整 RL 训练链路暂不搬进 ScanSci。 |
| Q-RAG：embedding 空间多步检索 | https://github.com/griver/Q-RAG | 适合后续研究“在候选证据空间中学习下一步检索”；当前先复用它的多步 retrieval/eval 组织方式，不直接训练 embedder。 |
| LinearRAG：relation-free graph | https://github.com/DEEP-PolyU/LinearRAG | 适合 ScanSci 的 HTML evidence store：实体-句子-段落图可以低成本试验；注意该仓库显示 GPL-3.0，若搬代码要先做许可证隔离。 |
| GraphRAG-Bench：GraphRAG 适用边界评估 | https://github.com/GraphRAG-Bench/GraphRAG-Benchmark | 适合复用评测分类思想：事实检索、复杂推理、上下文总结、开放生成；不作为默认 GraphRAG 实现。 |
| QAFD-RAG：query-aware graph traversal | https://github.com/Tarzanagh/QAFD-RAG | 适合等 relation-free graph 有结果后借鉴 query-aware edge weighting；当前不直接接图扩散算法。 |
| Interact-RAG：语料交互动作 | https://openreview.net/forum?id=yHUjWb6eMe | 暂未确认作者官方代码；可先按论文思想把 ScanSci 检索动作拆成 `semantic_search`、`exact_search`、`hybrid_search`、`fetch_parent_context`、`include/exclude_doc`。 |
| Interact-RAG 非官方工程参考 | https://github.com/NomaDamas/AutoRAG-Research | 适合参考 pipeline/plugin/evaluation 组织方式；不是作者官方实现，不能当论文复现依据。 |
| GRO-RAG：generation-aware rerank | https://openreview.net/forum?id=5zdubHFutd | 暂未找到作者官方代码；当前先做轻量 answer-aware rerank/证据充分性诊断，不实现梯度重排。 |

## 当前已落地：retrieval trace

本轮已给本地检索和外部 benchmark 增加检索 trace：

- `search_evidence_store(..., trace=[])` 会追加结构化事件。
- `search-v2 --trace-output trace.json` 会把单题检索 trace 写成 JSON，便于人工排查。
- `bench-external` 的逐题 details 会带 `retrieval_trace`、`retrieval_trace_summary`、`retrieved_route_counts`。
- 聚合指标会输出：
  - `retrieval_trace_questions`
  - `retrieval_search_calls`
  - `retrieval_queries`
  - `retrieval_fts_candidates`
  - `retrieval_dense_candidates`
  - `retrieval_unique_candidates`
  - `retrieval_reranked_candidates`
  - `retrieval_returned_hits`
  - `retrieval_route_counts`
  - `avg_*_per_question`

这些指标是 HiPRAG / DeepRAG / Interact-RAG 思路的地基。没有 trace，就无法判断某次提升到底来自更好的 query、dense 召回、FTS 精确匹配、reranker，还是仅仅扩大候选池。

## 当前已落地：错题 trace 诊断

`bench-mistakes` 已经能读取 details 里的 `retrieval_trace` 和 `retrieval_trace_summary`，并给失败样本自动补充诊断标签：

- `under_search`：候选或返回证据不足。
- `bad_query_variant`：query variants 没有增加有效候选。
- `wrong_route`：返回的是非 gold 证据，优先检查 FTS/dense/hybrid route 和 reranker。
- `wrong_scope`：检索 scope 可能排除了正确文档。
- `over_search`：已经部分找回后仍继续搜索，后续要用 stop rule 或过程奖励控制。

这一步不使用 blind benchmark 的 gold details；`bench-mistakes` 仍拒绝 blind details，避免错题集变成答案泄露通道。

## 下一步优先级

1. 建立可组合检索动作层：
   - `exact_search(term, filters)`
   - `semantic_search(query, k)`
   - `hybrid_search(query, sparse_weight, dense_weight)`
   - `fetch_parent_context(evidence_id)`
   - `include_doc(doc_id)`
   - `exclude_doc(doc_id)`
2. 先在 `bench-external` 的公开 benchmark 上比较；需要真实语料验收时，再加入本地 acceptance set：
   - 固定 single-query
   - query variants
   - exact + semantic hybrid
   - answer-aware rerank
3. 为 HTML context expansion 增加 `irrelevant_context_expansion` 诊断，区分“召回到了正确句子”和“扩展上下文把引用边界污染了”。
4. 只有当公开 benchmark 或本地 acceptance set 显示跨文档、多跳、实体关系题明显弱时，再试 LinearRAG 风格的 relation-free graph。

## 暂不做的事

- 暂不把 HiPRAG/Q-RAG 的 RL 训练链路搬进主项目。当前公开 benchmark 和本地 acceptance 覆盖还不够，容易过拟合单一路线。
- 暂不把 GraphRAG 作为默认升级路线。论文证据定位的第一瓶颈仍是召回、重排、quote extraction 和 citation verification。
- 暂不复制 GPL 代码进主代码库；有价值的算法先用独立实验脚本或干净重写方式验证。
