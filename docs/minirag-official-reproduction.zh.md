# MiniRAG 官方复现记录

日期：2026-06-29

## 当前状态

已在 `external/minirag-official` 拉取官方仓库 `HKUDS/MiniRAG`，并在官方仓库下创建隔离环境：

```powershell
cd <legacy-repo>\external\minirag-official
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install -r requirements.txt transformers torch nano-vectordb sentence-transformers
```

验证结果：

- `minirag` 可 import。
- `torch` 版本：`2.12.1+cpu`。
- `transformers` 版本：`5.12.1`。
- 官方 LiHua-World 数据已解压，包含 `442` 个 txt 文件。
- 当前 shell 未设置 `OPENAI_API_KEY` 和 `OPENAI_API_BASE`。
- 本机当前未发现可用的 `Ollama` 服务。

## 官方路线

官方 README 给出的复现入口是：

```powershell
python .\reproduce\Step_0_index.py
python .\reproduce\Step_1_QA.py
```

关键实现细节：

- `Step_0_index.py` 默认使用 `gpt_4o_mini_complete` 建索引，即实体/关系抽取依赖 OpenAI-compatible chat completion。
- `Step_1_QA.py` 默认使用 `hf_model_complete` 跑小语言模型答题。
- embedding 使用 `sentence-transformers/all-MiniLM-L6-v2`。
- 默认 `MiniRAG.tiktoken_model_name` 是 `gpt-4o-mini`，首次运行会触发 `tiktoken` 下载 `o200k_base` BPE；当前网络下这一下载曾被连接重置。

## ScanSci 小样本准备

为了先跑通小闭环，已添加脚本：

```powershell
python <legacy-repo>\scripts\prepare_minirag_lihua_sample.py `
  --official-root <legacy-repo>\external\minirag-official `
  --questions 5 `
  --distractors 10 `
  --output-name scansci-lihua-small
```

生成结果：

- 小样本路径：`<legacy-repo>\external\minirag-official\scansci-lihua-small`
- 问题数：`5`
- evidence 文档请求数：`13`
- evidence 文档找到数：`13`
- 总 txt 数：`23`
- query 文件：`scansci-lihua-small\qa\query_set.csv`

## ScanSci Wrapper

已添加 wrapper：

```powershell
<legacy-repo>\scripts\run_minirag_official_repro.py
```

用途：

- 复用官方 `MiniRAG` 类，不修改官方库。
- 显式传入 `workingdir/datapath/querypath/outputpath`。
- 支持 `--phase index|qa|both`。
- 支持 `--tiktoken-model gpt-4`，避免默认 `gpt-4o-mini` 首次下载 BPE 卡住。
- 在缺少 OpenAI 环境变量时早期失败，避免半途写坏运行目录。

## 下一步命令

先设置 OpenAI-compatible 环境变量。不要把 key 写入文档或代码。

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_API_BASE="https://api.openai.com/v1"
```

小样本 index：

```powershell
cd <legacy-repo>
external\minirag-official\.venv\Scripts\python.exe scripts\run_minirag_official_repro.py `
  --phase index `
  --official-root external\minirag-official `
  --model qwen `
  --llm-provider openai `
  --workingdir external\minirag-official\scansci-lihua-small\workdir-wrapper `
  --datapath external\minirag-official\scansci-lihua-small\data `
  --querypath external\minirag-official\scansci-lihua-small\qa\query_set.csv `
  --outputpath external\minirag-official\scansci-lihua-small\outputs\mini.csv `
  --question-limit 5 `
  --tiktoken-model gpt-4
```

小样本 QA 如果使用同一个 OpenAI-compatible 模型：

```powershell
external\minirag-official\.venv\Scripts\python.exe scripts\run_minirag_official_repro.py `
  --phase qa `
  --official-root external\minirag-official `
  --model qwen `
  --llm-provider openai `
  --qa-provider openai `
  --workingdir external\minirag-official\scansci-lihua-small\workdir-wrapper `
  --datapath external\minirag-official\scansci-lihua-small\data `
  --querypath external\minirag-official\scansci-lihua-small\qa\query_set.csv `
  --outputpath external\minirag-official\scansci-lihua-small\outputs\mini.csv `
  --question-limit 5 `
  --tiktoken-model gpt-4
```

完整 LiHua-World 官方路线需要把 `--datapath` 改回：

```text
external\minirag-official\dataset\LiHua-World\data\LiHua-World
```

并把 `--querypath` 改回：

```text
external\minirag-official\dataset\LiHua-World\qa\query_set.csv
```

## 当前阻塞

官方 index 路线需要可用的 OpenAI-compatible chat completion。当前 shell 没有：

- `OPENAI_API_KEY`
- `OPENAI_API_BASE`

在没有这两个环境变量时，wrapper 已验证会早期退出：

```text
MiniRAG official OpenAI path requires environment variables: OPENAI_API_KEY, OPENAI_API_BASE.
```

## 2026-06-29 Smoke Test

已使用本地配置的 OpenAI-compatible endpoint 跑通 1 题 micro smoke test。

模型：

```text
qwen-turbo
```

命令要点：

```powershell
external\minirag-official\.venv\Scripts\python.exe scripts\run_minirag_official_repro.py `
  --phase both `
  --official-root external\minirag-official `
  --model qwen `
  --llm-provider openai `
  --qa-provider openai `
  --openai-model qwen-turbo `
  --workingdir external\minirag-official\scansci-lihua-micro\workdir-qwen-turbo `
  --datapath external\minirag-official\scansci-lihua-micro\data `
  --querypath external\minirag-official\scansci-lihua-micro\qa\query_set.csv `
  --outputpath external\minirag-official\scansci-lihua-micro\outputs\qwen-turbo-mini.csv `
  --question-limit 1 `
  --tiktoken-model gpt-4 `
  --offline-tokenizer-fallback `
  --llm-max-async 1 `
  --entity-gleaning 0 `
  --openai-min-interval 25
```

结果：

- micro 样本：`1` 个问题、`2` 个 evidence txt。
- 建图完成：`graph_chunk_entity_relation.graphml` 已生成。
- 运行日志显示最终图包含 `17` 个节点、`21` 条边。
- QA 输出：`external\minirag-official\scansci-lihua-micro\outputs\qwen-turbo-mini.csv`
- Gold Answer：`Yes`
- MiniRAG answer：判断为 Yes，并引用 AdamSmith 先通知 Li Hua 维护安排、随后 TirionFordring 宣布天气导致施工延期。

注意：

- 这不是论文严格复现数值，只是官方代码路径的最小闭环 smoke test。
- 使用了 `--offline-tokenizer-fallback`，因为当前网络无法下载 `tiktoken` 的 `cl100k_base.tiktoken` / `o200k_base.tiktoken`。
- 使用了 `--entity-gleaning 0` 和 `--openai-min-interval 25`，因为 `qwen-turbo` 直接跑 5 题时触发过 RPM 429。

## 复现口径

建议分三步：

1. 小样本烟测：5 题、23 个 txt，验证 index + QA 走通。
2. LiHua-World 全量复现：442 个 txt，全量 query_set。
3. 对齐论文表格：固定模型、prompt、temperature、评估器和 answer scoring，再报告 accuracy/error rate。

## 2026-06-29 5 题小样本复现

使用 `qwen-turbo` 跑通 `scansci-lihua-small`：5 个问题、13 个 evidence txt、10 个 distractor txt，共 23 个 txt。

本次使用 wrapper 的 `--insert-mode batch`。原因是官方 `reproduce/Step_0_index.py` 逐文件调用 `rag.insert(f.read())`，在当前 MiniRAG 实现里会对已 processed 的累计 chunks 反复做实体/关系抽取；5 题样本跑到第 7 个 txt 时已经明显呈现二次增长。`MiniRAG.insert` 原生支持 `list[str]`，所以 batch 模式不修改官方源码，只把 23 个 txt 一次性传入，避免重复抽取。

关键参数：

```text
openai_model=qwen-turbo
llm_provider=openai
qa_provider=openai
insert_mode=batch
entity_gleaning=0
llm_max_async=1
openai_min_interval=25
offline_tokenizer_fallback=true
```

索引结果：

- workdir：`external\minirag-official\scansci-lihua-small\workdir-qwen-turbo-5q-batch-rpm25`
- 输入：`23` 个 txt，切成 `24` 个 chunks。
- 图：`45` 个实体节点、`63` 条关系边。
- 输出文件包括 `graph_chunk_entity_relation.graphml`、`vdb_chunks.json`、`vdb_entities.json`、`vdb_relationships.json`。
- index 期间配置的 chat completion endpoint 均返回 HTTP 200，未再触发 429。

QA 结果：

- 输出：`external\minirag-official\scansci-lihua-small\outputs\qwen-turbo-5q-batch-rpm25.csv`
- 5 个 gold answer 都是 `Yes`。
- 人工严格判定：`3/5`。
- 正确：Q1、Q3、Q4。
- 错误：Q2、Q5，模型把时间先后关系答成否定。

观察：

- 主要失败点不是检索系统没跑起来，而是多跳时间顺序判断。
- 本机负载不高，主要成本在远程 LLM 的建图抽取和答题请求。
- 如果扩大到全量 LiHua-World，应优先继续使用 batch insert，并先做更明确的 answer scorer，否则全量官方逐文件 loop 成本会非常高。

## 2026-06-30 Answer Scorer

已添加本地评分脚本：

```powershell
python scripts\score_lihua_answers.py `
  --input external\minirag-official\scansci-lihua-small\outputs\qwen-turbo-5q-batch-rpm25.csv `
  --query-csv external\minirag-official\scansci-lihua-small\qa\query_set.csv `
  --answer-column minirag `
  --output-prefix bench\lihua-small-qwen-turbo-5q
```

脚本输出：

- `bench\lihua-small-qwen-turbo-5q.json`
- `bench\lihua-small-qwen-turbo-5q.csv`
- `bench\lihua-small-qwen-turbo-5q.md`

当前 scorer 是本地启发式版本，不调用额外 LLM。它会把答案归类为 `yes/no/insufficient/unknown/error`，并对 LiHua-World 的 Yes/No/Insufficient gold answer 计算 accuracy。

5 题结果：

- total：`5`
- correct：`3`
- incorrect：`2`
- accuracy：`0.600`
- Q2、Q5 被判为错误；两题模型答案都明确给出否定判断，与 gold answer `Yes` 不一致。

下一步模型对比时，统一使用同一 scorer 和同一输出前缀命名：

```text
bench\lihua-small-{model-name}-5q.*
```

## 2026-06-30 5 题模型对比

已用同一 5 题样本、同一 batch index 口径、同一 scorer 对比：

| Model | Correct | Total | Accuracy | Notes |
|---|---:|---:|---:|---|
| `qwen-turbo` | 3 | 5 | 0.600 | Q2、Q5 时间顺序题答成 `No` |
| `qwen3-30b-a3b` | 5 | 5 | 1.000 | 修复了 Q2、Q5，5 题全对 |

详细报告：

```text
bench\lihua-small-model-comparison.md
```

相关输出：

- `bench\lihua-small-qwen-turbo-5q.md`
- `bench\lihua-small-qwen3-30b-a3b-5q.md`
- `external\minirag-official\scansci-lihua-small\outputs\qwen-turbo-5q-batch-rpm25.csv`
- `external\minirag-official\scansci-lihua-small\outputs\qwen3-30b-a3b-5q-batch-rpm25.csv`

结论：

- 这个 5 题样本上，`qwen3-30b-a3b` 明显优于 `qwen-turbo`。
- `qwen3-30b-a3b` 更慢，但没有触发 429。
- 下一步建议扩大到 `20-50` 题，优先使用 `qwen3-30b-a3b`，再按需要加入 `deepseek-v3` 对比。
