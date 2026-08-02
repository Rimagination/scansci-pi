# MiniRAG qwen/qwen3.7-max 追加复现记录

Date: 2026-06-30

本次目标是从当前 OpenAI-compatible endpoint 支持的模型中，挑一个较新的旗舰模型做 MiniRAG 官方路线小样本复现。`/models` 列表中 `qwen/qwen3.7-plus` 更新，但 chat probe 返回 400；`qwen/qwen3.7-max` probe 可用，因此先实跑它。

## Run

```text
sample=external\minirag-official\scansci-lihua-small
questions=5
txt_files=23
chunks=24
insert_mode=batch
llm_provider=openai
qa_provider=openai
openai_model=qwen/qwen3.7-max
entity_gleaning=0
llm_max_async=1
openai_min_interval=25
offline_tokenizer_fallback=true
```

## Index

- Workdir: `external\minirag-official\scansci-lihua-small\workdir-qwen3.7-max-5q-batch-rpm25`
- Graph: `44` entities, `60` relationships
- HTTP status: no 429 observed
- Approximate wall time: `~28m`

## QA And Score

- Answer CSV: `external\minirag-official\scansci-lihua-small\outputs\qwen3.7-max-5q-batch-rpm25.csv`
- Score report: `bench\lihua-small-qwen3.7-max-5q.md`
- QA time: `7m54s`
- Accuracy: `3/5 = 0.600`
- Correct: Q1, Q4, Q5
- Incorrect: Q2, Q3

Q2 was answered `No` because the model treated the Star Wars event as Li Hua asking Wolfgang, while the gold label is `Yes`. Q3 was answered `No` because the model focused on whether Li Hua agreed when Wolfgang first asked, while the gold label counts a later agreement after the first ask as `Yes`.

## Current Recommendation

On this 5-question LiHua-World sample, `qwen3-30b-a3b` remains the better next candidate: it scored `5/5`, while `qwen/qwen3.7-max` scored `3/5` and was slower in both indexing and QA. The latest flagship model name did not translate into better MiniRAG performance on this small temporal-reasoning sample.

The official comparison table is in `bench\lihua-small-model-comparison.md`.
