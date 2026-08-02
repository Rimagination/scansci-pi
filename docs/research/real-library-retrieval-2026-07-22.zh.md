# 真实文献库证据检索验证（2026-07-22）

## 结论

本地神经检索值得进入正式流程，但必须以持久向量缓存和级联重排方式使用。在同一真实文献切片、同一金标、同一 `k=10` 下，`BAAI/bge-small-en-v1.5` + `cross-encoder/ms-marco-MiniLM-L6-v2` 将 Evidence Recall@10 从 75.00% 提升到 91.67%；模型和向量缓存常驻后的平均每题时间从 0.19 秒增至 2.67 秒。

这证明神经模型改善了证据召回，但没有自动改善本地模板答案的内容完整性：两组 `answer_accuracy` 都是 41.67%。因此检索与 NotebookLM 式写作必须保持两个独立、可分别验收的阶段。

## 数据与金标

- 原始库：`<legacy-repo>\html-papers\evidence.sqlite`
- 规模：72 篇真实论文，15,575 个 evidence spans。
- 金标：[real_library_gold_v1.jsonl](../../bench/real_library_gold_v1.jsonl)
- 题目：13 题；12 题可回答，1 题不可回答；覆盖事实、方法、数值抽取和因果陷阱。
- 精确金标：12 个经过原文核对的 evidence IDs，来自 Nature、Science 和 Global Change Biology 等真实文献。
- 可重复切片：12 篇、2,325 个 spans，其中 8 篇含金标，4 篇为跨学科干扰文献。基线和神经方案使用完全相同的切片。

完整 72 篇库另外跑了哈希 + 词法基线，Recall@10 同样为 75.00%，说明切片没有人为抬高该基线的召回率。

## 对照配置

| 项目 | 快速基线 | 本地神经方案 |
|---|---|---|
| Dense recall | `hashing-v1`, 128 维 | `BAAI/bge-small-en-v1.5`, 384 维 |
| Rerank | 本地词法 | 词法预排 Top 60 → `ms-marco-MiniLM-L6-v2` |
| 向量后端 | sqlite-vec 持久缓存 | sqlite-vec 按模型身份持久缓存 |
| 最大序列 | 不适用 | 128（本次测试） |
| 设备 | CPU | CPU；CUDA 不可用 |
| 检索深度 | `k=10` | `k=10` |

## 结果

| 指标 | 哈希 + 词法（暖） | BGE + MiniLM（冷缓存） | BGE + MiniLM（暖缓存） |
|---|---:|---:|---:|
| Evidence Recall@10 | 75.00% | 91.67% | 91.67% |
| All-gold Recall@10 | 75.00% | 91.67% | 91.67% |
| Citation recall | 75.00% | 91.67% | 91.67% |
| Citation precision | 9.38% | 13.25% | 13.25% |
| Citation F1 | 16.67% | 23.16% | 23.16% |
| Answer accuracy | 41.67% | 41.67% | 41.67% |
| 错误因果题拒答 | 100% | 100% | 100% |
| 验证通过率 | 100% | 100% | 100% |
| Unsupported claim rate | 0% | 0% | 0% |
| 13 题 wall time | 2.43 s | 69.27 s | 34.71 s |
| 平均每题 wall time | 0.19 s | 5.33 s | 2.67 s |

冷缓存相对暖缓存多 34.56 秒，用于给 2,325 个真实片段建立 BGE 向量。两个模型从本地磁盘加载约再需 18 秒；该时间不包含在 `run_benchmark` 的 wall time 中。桌面运行时会复用模型实例和 sqlite-vec 缓存，所以正常连续提问应参考暖缓存列。

神经方案剩余的唯一 gold miss 是 `real005`（语言产生过程中不同神经元表征的细粒度语言属性）。后续优化应针对该类“摘要相邻句/属性枚举”问题增加邻句召回或更好的 query rewrite，而不是盲目增大重排候选。

## 新发现并已修正的问题

### 1. 神经向量此前没有持久化

旧实现只缓存 hashing vectors，正式综述的每个章节查询可能重复对资料库做神经编码。现在任何声明稳定 `cache_key` 的本地 embedding provider 都进入按模型隔离的 sqlite-vec 表，按文本 SHA-256 增量失效；来源过滤也会复用缓存，而不会删除其他来源的向量。

### 2. 正式综述此前没有传入本地模型

`retrieve_review_evidence` 现在接收并向每个 section query 传递真实 embedding provider 和 reranker；Deep、Pi 和 provider-neutral evidence 路径使用同一个本地证据栈，并在结果中记录真实模型身份或明确 fallback 原因。

### 3. 直接重排全部候选在 CPU 上不划算

正式运行时改为词法预排 Top 60，再进入 MiniLM cross-encoder。它保留了 91.67% 的 Recall@10，同时把暖缓存 13 题测试控制在 34.71 秒。直接对全部候选做 cross-encoder 的试验因 CPU 延迟过高被排除出正式方案。

### 4. 相似来源不能拼成因果证据

错误题把“superconducting qubits”和“Amazonian tree mortality”分别召回到不同文献。新增关系门禁要求因果两端至少在同一来源中共同出现，否则标记证据不足。该题的 abstention accuracy 从 0% 修正为 100%。

### 5. 测试环境曾错误加载旧仓库

本机 editable 安装仍指向 `<legacy-repo>`。所有纳入本报告的结果均显式设置 `PYTHONPATH=<repo>\src`；在发现路径污染前产生的运行结果全部作废，没有混入表格。

## 继续优化复测

针对唯一漏检 `real005`，检索器现在只在“属性、特征、机制、因素、组成”等列举型问题上做有界的一跳邻句扩展。相邻答案句进入重排时临时携带引导句上下文，但最终返回、引用和回跳仍使用答案句自己的 `evidence_id`、原文与锚点。这样避免了把整段文字挂在错误句级 ID 上，也没有扰动 `real007` 等普通事实题。

同一 12 篇、2,325 spans、同一金标与 `k=10` 的最终暖缓存复测结果：

| 指标 | 优化前 | 最终复测 |
|---|---:|---:|
| Evidence Recall@10 | 91.67% | **100.00%** |
| Citation recall | 91.67% | **100.00%** |
| Citation precision | 13.25% | 13.33% |
| Citation F1 | 23.16% | 23.53% |
| Answer accuracy（本地模板） | 41.67% | 33.33% |
| 错误因果题拒答 | 100% | 100% |
| Citation verification pass rate | 100% | 100% |
| Unsupported claim rate | 0% | 0% |
| 13 题 wall time | 34.71 s | 34.75 s |

`answer_accuracy` 的下降再次说明，本地确定性模板不能代表 NotebookLM 式正式写作质量；它仍保留为离线兜底。正式正文继续使用来源白名单内的写作模型与句级引用核验。检索层的提升则由 12/12 可回答题全部命中和 0 unsupported claim 独立确认。

大资料库导入后的首次神经向量构建也已迁入持久任务：UI 可见批次进度，可在批次边界协作取消；每批写入 sqlite-vec 后立即提交。恢复时按模型身份与文本 SHA-256 复用已完成向量，只补剩余行。小于 1 MB 的资料库仍走 hashing 快路径，不创建无意义的模型预热任务。

## 对产品的决定

1. 真实资料库默认使用本地 BGE + MiniLM 级联；小于 1 MB 的测试或微型资料库保留 hashing + lexical 快路径。
2. 模型身份、fallback、最大序列和重排候选上限写入 `retrieval_runtime`，不能把 fallback 宣称为神经模型成功。
3. 首次缓存构建已迁到“导入/索引任务”：显示持久进度，支持取消、应用重启后的继续和增量复用；正常导入后的首次查询不再承担整库冷构建成本。
4. 不用 `answer_accuracy` 掩盖检索提升：NotebookLM 式正文必须由证据白名单内的正式写作模型生成，再经过句级 citation 校验。

## 验证边界

- 13 题仍属于小型工程验收集，不足以声称跨学科普适领先。
- 本轮是 CPU 桌面环境；GPU 和更大模型需要另建同金标对照，不应混入当前延迟结论。
- Citation precision 偏低，说明当前 quote selector 会保留较多非 gold 但表面相关的证据；后续应优化 quote pruning。
- 本轮没有把写作模型的文风质量混进检索指标。写作阶段单独通过来源范围、句级引用、原文回跳和保存为笔记验收。
