# ScanSci Evidence Retrieval Leaderboard

建立日期：2026-06-23

## 目的

这个 leaderboard 用来像 LLM 评测表一样横向比较不同证据检索链路，而不是凭感觉判断“复杂 RAG 是否更好”。

它的原则是：

1. 同一组 benchmark、scope、k、题量下才排名。
2. 默认按 `gold_evidence_recall_at_k` 排序，因为论文写作最关心具体证据是否找回。
3. 同时保留 `retrieval_recall_at_k` 和 `all_gold_retrieval_recall_at_k`，防止只看一个指标。
4. 公开 benchmark 是论文式验证的默认主线；真实 HTML gold set 是可选的本地验收层，必须单独报告。
5. FTS-only、简单 RAG、大模型 embedding、大模型 reranker、未来 ColBERT/graph/agent 链路都可以进入同一套表，但不能跨不可比组乱排。

## 生成当前榜单

```powershell
scansci bench-leaderboard `
  --details bench\qasper-external-details.qwen3-reranker.full.k20.candidate20.json bench\qasper-external-details.qwen3-reranker.full.k20.candidate50.json bench\qasper-external-details.qwen3-reranker.full.k20.candidate100.json bench\qasper-external-details.qwen3-reranker.full.k20.candidate200.json bench\scifact-external-details.qwen3-reranker.full.k20.candidate20.json bench\scifact-external-details.qwen3-reranker.full.k20.candidate50.json bench\scifact-external-details.qwen3-reranker.full.k20.candidate100.json bench\scifact-external-details.qwen3-reranker.full.k20.candidate200.json `
  --labels QASPER-Qwen3-c20,QASPER-Qwen3-c50,QASPER-Qwen3-c100,QASPER-Qwen3-c200,SciFact-Qwen3-c20,SciFact-Qwen3-c50,SciFact-Qwen3-c100,SciFact-Qwen3-c200 `
  --output bench\evidence_retrieval_leaderboard.json `
  --csv-output bench\evidence_retrieval_leaderboard.csv `
  --markdown-output bench\evidence_retrieval_leaderboard.md `
  --html-output bench\evidence_retrieval_leaderboard.html `
  --chart-output bench\evidence_retrieval_leaderboard_chart.html
```

当前项目已经生成：

- `bench/evidence_retrieval_leaderboard.json`
- `bench/evidence_retrieval_leaderboard.csv`
- `bench/evidence_retrieval_leaderboard.md`
- `bench/evidence_retrieval_leaderboard.html`
- `bench/evidence_retrieval_leaderboard_chart.html`

## 比较组

`bench-leaderboard` 会自动生成 `comparison_group`：

```text
{dataset}/{scope}/k{k}/q{questions}
```

例如：

- `qasper/gold-docs/k20/q1005`
- `scifact/corpus/k20/q300`
- `qasper/gold-docs/k20/q50`

rank 只在同一个 `comparison_group` 内有效。这样可以避免 `SciFact smoke50` 因为样本小而在全局表里误导性地排到第一。

## 加入新模型

新模型或新链路只需要先产出 benchmark details JSON，再追加到 leaderboard：

```powershell
scansci bench-leaderboard `
  --details OLD.json NEW_MODEL.json `
  --labels Old,NewModel `
  --markdown-output bench\evidence_retrieval_leaderboard.md
```

建议所有新跑分记录：

- 数据集：QASPER / SciFact / BEIR 子集（如 Climate-FEVER）/ 可选 local HTML acceptance set。
- scope：`gold-docs` / `corpus` / `full-library`。
- k：例如 `20`。
- candidate pool：`initial_limit`、`dense_limit`。
- embedding provider/model。
- reranker provider/model 或 `reranker_score_cache_name`。
- trace 指标：`retrieval_trace_summary`、候选数、route counts。
- 成本：耗时、显存、cache 命中率，后续需要继续补全。

## 接入 BEIR / Climate-FEVER

BEIR 格式公开集统一走 `bench-import beir` 和 `bench-external beir`。这条链路按 qrels 的 document-level 标注评估“能否找回相关文档”，不把它伪装成句子级 citation benchmark。

以 Climate-FEVER 为例：

```powershell
scansci bench-fetch beir `
  --dataset-name climate-fever `
  --output-dir .\external\beir

scansci bench-import beir `
  --corpus .\external\beir\climate-fever\corpus.jsonl `
  --queries .\external\beir\climate-fever\queries.jsonl `
  --qrels .\external\beir\climate-fever\qrels\test.tsv `
  --dataset-name climate-fever `
  --output .\bench\gold_questions.external.climate-fever.jsonl

scansci bench-external beir `
  --corpus .\external\beir\climate-fever\corpus.jsonl `
  --gold .\bench\gold_questions.external.climate-fever.jsonl `
  --db .\bench\climate-fever-external-evidence.sqlite `
  --dataset-name climate-fever `
  --k 20 `
  --scope corpus `
  --details-output .\bench\climate-fever-external-details.json
```

如果使用 BEIR 的 `test.tsv` 只是开发调参，建议仍写成 `dev` 或 `calibration` 口径；如果想保留真正盲测，应在导入时用 `--benchmark-split blind`，并避免把逐题 details 写入错题集。

## 解读约束

- `retrieval_recall_at_k`：问题级指标，只要某个 gold evidence 被命中就算命中。
- `all_gold_retrieval_recall_at_k`：问题级指标，要求该问题全部 gold evidence 都命中。
- `gold_evidence_recall_at_k`：证据 ID 级指标，是当前默认排序指标。
- 公开 QASPER/SciFact/BEIR 可能存在训练数据泄露或过拟合风险，适合作为论文式公开对比和开发校准。
- local HTML gold/acceptance set 只能证明特定本地语料的可用性；它应和公开 benchmark 分开解释。

## 2026-06-24 OpenScholar_Reranker 跑分记录

本轮加入 `OpenSciLM/OpenScholar_Reranker`，链路为 `Qwen/Qwen3-Embedding-0.6B` 召回 + `OpenScholar_Reranker` cross-encoder 重排，统一使用 `k=20`、`initial_limit=200`、`dense_limit=200`。BEIR 类数据集使用 Qwen3 embedding 的 `max_seq_length=512` 版本索引。

输出文件：
- `bench/benchmark_performance.public-full-matrix-openscholar.json`
- `bench/benchmark_performance.public-full-matrix-openscholar.csv`
- `bench/benchmark_performance.public-full-matrix-openscholar.md`
- `bench/benchmark_performance.public-full-matrix-openscholar.html`
- `bench/benchmark_performance.public-full-matrix-openscholar.chart.html`
- 稳定查看入口同步为 `bench/evidence_retrieval_leaderboard_chart.html`

核心结果（主指标为 `gold_evidence_recall_at_k`）：

| 数据集 | Qwen3+OpenScholar | MiniLM-Rerank | Qwen3-Hybrid | OpenScholar 单题耗时 |
|---|---:|---:|---:|---:|
| QASPER | 0.624524 | 0.621478 | 0.538462 | 2.301s |
| SciFact | 0.833333 | 0.838798 | 0.551913 | 3.179s |
| NFCorpus | 0.073699 | 0.093076 | 0.074915 | 8.771s |
| TREC-COVID | 0.033032 | 0.030965 | 0.022413 | 12.562s |
| SciDocs | 0.202922 | 0.234578 | 0.129464 | 7.100s |

结论：OpenScholar_Reranker 不是全面默认最优。它在 QASPER 和 TREC-COVID 上略优于 MiniLM-Rerank，在 SciFact 接近但略低于 MiniLM，在 NFCorpus 和 SciDocs 上低于 MiniLM；同时耗时显著更高。当前建议把它作为“高精度可选重排器”或二级 cascade reranker，而不是默认全量替换 MiniLM-Rerank。
