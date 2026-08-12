# 证据问答质量门禁

ScanSci 的证据问答采用“检索—证据—主张—引用”分层，不把“检索到了文本”当成答案正确。

## 运行时门禁

1. 检索结果先剔除参考文献、书目信息和元数据行。
2. 对综述、比较、冲突和机制问题，优先排序摘要、结果、讨论和结论；没有可靠章节标注时仍保留 `other` 作为回退。
3. 主题判定采用分级结果，而不是单一布尔开关：具体术语和语义重排信号都充分时为 `answerable`；只有少量词汇重合、但重排分数有希望时为 `needs_review`，允许生成带警告的证据答案；补充检索后仍没有主题证据时才输出 `not_enough_information`。只有“影响、研究、结果、发电”等泛化词重合时，才直接拒答。
4. 多分面问题由查询计划生成 `required_facets`。证据覆盖不完整时允许生成已支持部分，但结果必须标记 `answer_completeness=partial` 并列出 `missing_facets`。
5. 每条主张仍需绑定已验证的精确 quote、证据 ID 和 HTML 锚点；引用完整性还要检查所有 required facets 是否被引用覆盖。

综述或比较问题只有一个来源时，系统把“资料范围不足”标为 `needs_review` 并展示已支持内容；冲突问题仍要求来源多样性，因为单一来源不能证明存在冲突。

主题分数记录在 `adequacy.topical_relevance` 中，包括 `score`、`lexical_score`、`semantic_score` 和 `status`。`needs_review` 不是放宽引用门禁：主张仍须通过逐条引用、来源锚点和支持状态核验。

分面覆盖允许保守的词形和短语变体（例如 `soil carbon storage` 与 `soil organic carbon stocks`），但只把它作为检索完整性信号；最终答案仍必须引用覆盖对应分面。后续可用本地人工 gold 集校准 `needs_review` 的阈值，不能凭单次运行结果把阈值永久写死。

## Gold 问题集

本地 gold JSONL 可以为多分面问题增加：

```json
{
  "required_facets": [
    {"id": "微气候", "terms": ["微气候"]},
    {"id": "植被群落", "terms": ["植被群落"]}
  ]
}
```

`answerable=false` 的问题必须保留拒答标注；不能用“没有生成主张”冒充正确答案。建议每类问题保留人工核验的支持证据和必要回答点。

## 增强评测

`bench --benchmark-mode enhanced` 在原有 retrieval/citation 指标之外报告：

- `answer_completeness_rate`：可回答问题中，必要回答点和分面是否完整；
- `facet_coverage`：检索/回答覆盖的必要分面比例；
- `context_precision`：返回上下文中 gold 证据的比例；
- `reference_contamination_rate`：参考文献或元数据行混入候选的比例；
- `abstention_precision` / `abstention_recall`：拒答是否只用于无证据问题。

这些指标分别对应科学问答中的答案完整性、引用质量、检索噪声和拒答校准；不要只用单一平均分判断系统质量。公开方法参考：[QASPER](https://aclanthology.org/2021.naacl-main.365/)、[SciFact](https://aclanthology.org/2020.emnlp-main.609/)、[ALCE](https://aclanthology.org/2023.emnlp-main.398/)、[RAGChecker](https://arxiv.org/abs/2408.08067) 和 [ARES](https://arxiv.org/abs/2311.09476)。
