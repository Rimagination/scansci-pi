# 文献证据 RAG 项目方案

这份文档说明如何把 `ScanSci` 设计成一个面向论文写作的高精度文献问答与证据标注系统。当前工程实现仍保留 `scansci-html` 作为 HTML-first capture 层和兼容入口。

核心判断：

> 不要先让模型回答再补引用，而要先构造可验证的证据表，再基于证据表写答案，最后把每个事实性句子映射回 HTML 原文句子。

`scansci-html` 已经解决了一个很关键的底座问题：把用户合法可访问的论文保存成干净、离线可读的 HTML，并且不保存 PDF、cookie、token 或机构凭据。下一层应该把这些 HTML 当成规范化语料库，构建 evidence-first 的论文写作助手。

命名判断：

- `ScanSci` 是长期品牌和总命名空间，兼有 scan science / search science 的含义。
- `scansci-html` 是历史兼容入口，代表当前 capture 层的 HTML-only 边界，不应该限制后续证据检索、问答和综述写作。
- CLI 已保留 `scansci-html`，同时新增 `scansci` alias；后续用户心智应逐步迁移到 `scansci capture`、`scansci evidence`、`scansci ask`、`scansci review`、`scansci bench` 这类能力层。
- 详细命名体系见 [`docs/naming.zh.md`](naming.zh.md)：对外品牌先升级为 `ScanSci`，发行包、Python import、keyring service name 暂时保留 `scansci-html` / `scansci_html`，避免破坏旧脚本和已保存凭据。

## 命名体系建议

建议把命名拆成四层，而不是让 `scansci-html` 同时承担品牌、包名、功能边界和未来愿景：

1. 品牌层：`ScanSci`。这是长期名字，表达 scan science / search science，也能覆盖从原文获取到证据检索、问答验证、综述写作的完整工作流。
2. 兼容层：`scansci-html` / `scansci_html`。这是当前仓库、发行包和 Python import 的稳定名字，短期不要破坏；它只描述 capture 层的 HTML-first 起点。
3. 能力层：`capture`、`library`、`evidence`、`ask`、`verify`、`review`、`bench`。这些名字面向用户任务，不绑定某个算法。`RAG` 应该写在架构里，不建议作为对外产品名。
4. 产物层：`paper.html`、`paper.evidence.html`、`evidence.sqlite`、`evidence-spans.jsonl`、`reports/*.html`、`bench/gold_questions.jsonl`。文件名描述 artifact，命令名描述能力。

当前最稳路线是双轨：

- 用户文档、论文方案和新命令示例统一叫 `ScanSci` / `scansci`。
- 旧 CLI `scansci-html`、包名 `scansci-html`、import `scansci_html`、keyring service name 暂时不改。
- 等 API 稳定后，再新增轻量 `src/scansci/` facade，内部继续复用 `src/scansci_html/`；不要为了名字好看提前搬目录。
- 后续命令数量继续变多时，从扁平命令平滑迁移到分组命令，例如 `scansci evidence index`、`scansci evidence search`、`scansci review matrix`、`scansci bench run`，旧命令保留 alias。

不建议的命名包括：

- 把整个项目继续叫 `scansci-html`：会把证据检索、问答、综述写作误解成下载器附属功能。
- 新开 `scansci-rag`：RAG 是实现方式，不是研究者真正要完成的任务。
- 新开 `scansci-reviewer` 或 `scansci-litreview`：综述写作应该是 `ScanSci Review` 能力层，依赖上游 evidence store，而不是另一个平行项目。
- 在 `ask`、`review`、`bench` 这些层继续使用 `html` 命名：HTML 是证据载体，不是用户任务。

## 项目目标

1. 对本地 HTML 论文库进行高精度问答。
2. 面向论文写作，尤其是文献综述、研究背景、方法比较、证据整理。
3. 优先保证准确性，其次才是速度和成本。
4. 每个事实性回答句都能回到原始论文中的句子、段落、章节、DOI。
5. 证据不足时明确拒答或标记为 `insufficient evidence`。
6. 尽量复用 PaperQA2、Ai2 ScholarQA、OpenScholar、LlamaIndex 等现有工作，不重复造轮子。

## 非目标

- 不替代研究者的最终学术判断。
- 不从模型记忆中生成无证据文献综述。
- 不只依赖摘要回答全文问题。
- 不把 citation 当作装饰性脚注。
- 不保存机构登录态、密码、cookie、token 或任何凭据。

## 准确性优先于标注

论文写作场景中，标注只是结果。真正的系统质量取决于：

1. 是否找到了正确论文。
2. 是否找到了论文正文中的关键证据句。
3. 是否区分了支持、反驳、限制条件和背景信息。
4. 是否避免把相邻但不支持的文本拿来当引用。
5. 是否能在证据不足时拒答。
6. 是否能暴露冲突证据，而不是强行综合成单一结论。

因此本项目的核心中间产物不是答案，而是证据表。

## 资料依据表

下面这张表把本方案中的关键判断和外部资料中的对应依据对齐。这里的“原文短句”只作为定位线索；真正写论文或项目文档时，应该点击来源阅读上下文，而不是只依赖摘录。

| 本项目判断 | 资料原文短句 | 来源 | 落地方式 |
|---|---|---|---|
| NotebookLM 类体验的关键不是漂亮引用，而是 source grounding 和原文 quote。 | “grounded in your own documents”；“original quotes from your sources” | [Google NotebookLM 官方介绍](https://blog.google/innovation-and-ai/technology/ai/notebooklm-google-ai/) | `ask` 报告必须显示 evidence table、exact quote、source anchor；答案不能只给论文级引用。 |
| 科研问答必须先构建 evidence，再组织答案。 | “answer built around evidence” | [Ai2 ScholarQA 官方博客](https://allenai.org/blog/ai2-scholarqa) | pipeline 顺序固定为 retrieval -> rerank -> quote extraction -> evidence table -> answer。 |
| 文献综述型问题需要 quote extraction 和 outline/clustering，不适合一次性把 chunks 交给模型。 | “top re-ranked passages”；“select the most relevant quotes” | [Ai2 ScholarQA 官方博客](https://allenai.org/blog/ai2-scholarqa) | `ExtractedQuote` 作为答案前的强制中间产物；`review-matrix` 复用 quote 和 claim。 |
| 科学文献 RAG 需要处理检索、总结和矛盾检测。 | “information retrieval, summarization, and contradiction detection” | [PaperQA2 arXiv](https://arxiv.org/abs/2409.13740) | answer type 覆盖 `multi_paper_synthesis` 和 `conflict_evidence`，benchmark 不能只测事实题。 |
| 高精度系统需要 passage retrieval、reranking、自反馈或验证，而不只是向量召回。 | “retrievers and rerankers”；“self-feedback loop” | [OpenScholar Nature 论文](https://www.nature.com/articles/s41586-025-10072-4) | `search-v2` 保留 hybrid retrieval 和 reranker；后续 agentic retrieval 做 follow-up search。 |
| 引用质量要作为独立指标评估。 | “fluency, correctness, and citation quality” | [ALCE, ACL Anthology](https://aclanthology.org/2023.emnlp-main.398/) | benchmark 分开统计 answer accuracy、citation precision/recall/F1、unsupported-claim rate。 |
| claim 必须能被指定来源验证。 | “verified against an independent, provided source” | [AIS, ACL Anthology](https://aclanthology.org/2023.cl-4.2/) | `verify` 对每个 `AnswerClaim` 生成 `support_status`，不是只验证整段答案。 |
| RAG 本身不能消灭幻觉，仍可能产生 unsupported/contradictory claims。 | “unsupported or contradictory claims” | [RAGTruth, ACL Anthology](https://aclanthology.org/2024.acl-long.585/) | 即使 evidence 检索成功，也必须保留 claim-level verification 和拒答路径。 |
| HTML 适合作为证据标注载体，因为 Web annotation 本来就支持指向资源片段。 | “segments of timed multimedia resources”；“specific segment of the resource” | [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) | `paper.evidence.html` 中使用 `data-evidence-id` 和稳定 anchor 指向句子级 evidence span。 |
| JATS/XML 是学术文章更结构化的并行 canonical source。 | “XML elements and attributes for tagging journal articles” | [JATS NLM documentation](https://jats.nlm.nih.gov/) | 若 publisher XML 可得，保存为 `jats_xml_path`；否则以 rendered/raw/clean HTML 为主。 |
| PDF 解析工具很有价值，但它解决的是重建文档内容，不应覆盖已有 HTML/XML。 | “OCR, layout detection, and formula recognition” | [MinerU arXiv](https://arxiv.org/abs/2409.18839) | PDF -> MinerU/Marker/Docling 只作为 fallback，并保留页码、bbox、parser confidence 和原 PDF hash。 |
| LlamaIndex 这类工具能复用 citation 编号原型，但不足以覆盖科研级准确性。 | “retrieve relevant nodes”；“Add citations to the retrieved nodes” | [LlamaIndex CitationQueryEngine 文档](https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/) | 可借鉴 source numbering，但 ScanSci 需要额外的 evidence adequacy、gold benchmark、HTML anchor doctor。 |

## HTML 作为主证据载体

当前判断：支持把下载端抓取到的论文 HTML 作为本项目的主载体，尤其是面向机器查询、RAG、证据标注和人眼校对时。它比 `PDF -> Markdown` 更适合作为证据底座，因为 HTML 保留了 DOM 层级、章节结构、段落、图表说明、链接、公式容器、图片资源和页面锚点；这些信息正好是高精度证据定位需要的坐标系。

但这里的结论不是“只要 HTML，不要其他格式”，而是：

```text
publisher JATS/XML, if available
  + publisher rendered HTML or raw snapshot
  + clean HTML
  + evidence JSON/SQLite sidecar
  + HTML report/UI
```

也就是说，HTML 是最好的人机共同载体；JATS/XML 如果能拿到，应该作为更结构化的并行 canonical source；JSON/SQLite sidecar 是机器可信证据库；Markdown 只适合作为笔记、草稿或导出格式，不应该进入可信证据链。

推荐证据源优先级：

1. Publisher JATS/XML 或官方 full-text XML。
2. Publisher rendered HTML 和 raw DOM snapshot。
3. `scansci-html` 生成的 clean HTML。
4. PDF 加版面解析工具。
5. Markdown。

为什么不把 Markdown 当主载体：

- Markdown 很适合阅读笔记和写作草稿，但会丢失 DOM 层级、稳定锚点、复杂表格、图注关系、脚注链接、公式结构和补充材料链接。
- 对证据检索来说，`claim -> quote -> evidence_id -> source sentence` 这条链路需要稳定坐标，Markdown 很难长期稳定地承载这种坐标。
- 如果先把 HTML 或 PDF 转成 Markdown，再从 Markdown 做 RAG，系统会更容易把转换损耗误认为原文事实。

为什么 `PDF -> MinerU/Marker/Docling -> Markdown/JSON` 更适合作为 fallback：

- PDF 是排版成品，不是论文的语义源文件。解析器需要重建阅读顺序、表格、公式、图注和跨栏结构，这一步天然可能有损。
- MinerU 这类工具的价值很大，尤其是在没有 HTML/XML、只有 PDF 的场景中。但它们解决的是文档解析问题，不应替代已经能从下载端获得的 publisher HTML/XML。
- 如果必须使用 PDF 解析结果，应该保留 parser confidence、页码、bbox、原 PDF hash，并在报告里标记这类证据的来源等级低于 HTML/XML。

HTML 的关键优势不只是“可显示”，而是可以同时满足三类需求：

1. 机器查询：DOM 节点可以切成句子级 `EvidenceSpan`，并保存 section、anchor、offset、DOI、标题等元数据。
2. RAG 准确性：模型只接触经过检索和 quote extraction 验证的 evidence IDs，而不是无边界的大段文本。
3. 人眼校对：点击答案里的 citation 可以回到原文句子，高亮上下文，检查模型有没有过度概括或误引。

因此本项目的格式策略应该是：

- 原始 clean HTML 不轻易改动，作为离线阅读稿。
- 生成并排的 `paper.evidence.html`，插入句子级 span 和高亮锚点。
- 生成 `paper.evidence.json` 或 SQLite 记录，作为机器检索和校验的可信数据层。
- 生成最终 `report.html`，把 answer pane、evidence pane、source pane 放在一起，服务论文写作和人工复核。

这个设计也和 W3C Web Annotation 的方向一致：标注应该能指向资源中的具体片段，并能跨系统复用。对学术出版物来说，JATS/XML 也是重要参考，因为它本来就是面向期刊文章结构化建模的标准。因此最稳的路线不是在 HTML、XML、JSON、Markdown 中选一个万能格式，而是让它们分工：

| 格式 | 角色 |
|---|---|
| JATS/XML | 官方结构化全文源，若可得则优先保存 |
| Raw HTML snapshot | 下载端真实 DOM 证据，便于追溯清洗前状态 |
| Clean HTML | 人眼阅读和本地归档主文件 |
| Evidence HTML | 句子级高亮、跳转、校对界面 |
| SQLite/JSON | 检索、rerank、quote、claim verification 的机器层 |
| Markdown | 笔记、草稿、导出，不作为证据源 |

## 可直接参考和复用的项目

### PaperQA2

链接：

- [PaperQA2 代码](https://github.com/Future-House/paper-qa)
- [PaperQA2 论文](https://arxiv.org/html/2409.13740v1)
- [FutureHouse 工程博客](https://www.futurehouse.org/research/engineering-blog-journey-to-superhuman-performance-on-scientific-tasks)

可以借鉴：

- Agentic RAG，而不是固定检索一次就回答。
- 多轮 query expansion。
- LLM reranking 和 contextual summarization。
- citation traversal，也就是从相关论文继续沿参考文献或引用网络扩展。
- LitQA2 评测思想：问题答案在正文中，通常不在摘要里。

在本项目中的用法：

- 把 PaperQA2 作为 baseline 跑同一批问题。
- 复用它的高精度设计原则。
- 可以直接调用 `paper-qa` 包验证效果，但不要让它替代本项目的 HTML 证据坐标系。

### Ai2 ScholarQA

链接：

- [Ai2 ScholarQA 代码](https://github.com/allenai/ai2-scholarqa-lib)
- [Ai2 ScholarQA 论文](https://arxiv.org/abs/2504.10861)
- [Ai2 ScholarQA 博客](https://allenai.org/blog/ai2-scholarqa)

可以借鉴：

- 先检索 top-k passages。
- 再用 reranker 保留 top candidates。
- 再做 quote extraction。
- 再做 outline and clustering。
- 最后按 section 生成报告。

这是最贴近论文写作的流程，因为它不是直接把 chunks 扔给模型写文章，而是先抽取可用 quote，再组织成报告结构。

### OpenScholar

链接：

- [OpenScholar 代码](https://github.com/akariasai/openscholar)
- [OpenScholar arXiv HTML](https://ar5iv.labs.arxiv.org/html/2411.14199v1)
- [OpenScholar Nature 文章](https://www.nature.com/articles/s41586-025-10072-4)

可以借鉴：

- 面向科学文献训练或适配 retriever。
- bi-encoder 召回加 cross-encoder reranking。
- 多来源检索：自建语料库、Semantic Scholar API、学术网页检索。
- iterative self-feedback。
- citation verification。
- 用 citation accuracy 和 rubric score 同时评估，而不是只看答案流畅度。

在本项目中的用法：

- 不要一开始复制它的 4500 万论文库。
- 先把本地 HTML 论文库做扎实。
- 借鉴它的检索、重排、自反馈和验证流程。

### LlamaIndex CitationQueryEngine

链接：

- [LlamaIndex Build RAG with in-line citations](https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/)

可以借鉴：

- 把 source nodes 编号。
- 要求模型回答时引用编号。
- 从编号映射回 source nodes。

局限：

- 适合快速原型。
- 不足以保证论文写作级准确性。
- 它解决的是“引用格式”，不是完整的证据召回、quote extraction、claim verification。

### RAGTruth、ALCE、AIS

链接：

- [RAGTruth](https://aclanthology.org/2024.acl-long.585/)
- [ALCE](https://aclanthology.org/2023.emnlp-main.398/)
- [AIS](https://aclanthology.org/2023.cl-4.2/)

可以借鉴：

- RAG 仍然会产生 unsupported 或 contradictory claims。
- 引用评估要看 citation precision、citation recall、citation F1。
- 一个回答是否可信，要看 claim 是否可被指定来源验证。

## 推荐技术栈

### 现有项目继续保留

- `resolver`
- `official_sources`
- `fetchers`
- `browser`
- `publisher_recipes`
- `cleaner`
- `article_structure`
- `assets`
- `service`
- `cli`

这些是 HTML 论文库的底座，不要推翻。

### 新增库

解析与切句：

- `beautifulsoup4`
- `lxml`
- `pysbd` 或 `blingfire`
- 后续可接 `spacy`

检索：

- 本地 MVP：SQLite FTS5
- 高性能全文检索：Tantivy
- 向量索引：FAISS、Qdrant、Chroma 或 LanceDB

Embedding：

- 可选 OpenAI `text-embedding-3-large`
- 可选本地 `sentence-transformers`
- 必须做成 provider-pluggable

Reranker：

- `mixedbread-ai/mxbai-rerank-large-v1`
- `BAAI/bge-reranker-large`
- 或 hosted reranker

结构化输出：

- `pydantic`
- JSON schema

报告界面：

- 静态 HTML
- 少量 JavaScript
- 本地 source pane + evidence pane + answer pane

## 总体架构

```text
HTML/XML papers
  -> source normalization
  -> sentence/span anchoring
  -> evidence store
  -> hybrid retrieval
  -> cross-encoder reranking
  -> quote extraction
  -> evidence table
  -> answer synthesis
  -> claim verification
  -> HTML report with source highlighting
```

关键点：

- HTML 是主阅读、标注和人工校对载体；JATS/XML 若存在，是更结构化的并行 canonical source。
- Evidence JSON/SQLite 是机器可信数据层，不能只依赖渲染文本或 Markdown。
- 检索单位不是整篇论文，而是 sentence window。
- 生成单位不是自由文本，而是 claim。
- 引用单位不是 paper，而是 evidence span。
- UI 展示的不是普通脚注，而是 claim 到 evidence 的映射。

## 数据模型

### SourceDocument

论文级元数据。

```json
{
  "doc_id": "10.1038_s41586_...",
  "doi": "10.1038/s41586-...",
  "title": "...",
  "source_url": "https://...",
  "html_path": "html-papers/...",
  "raw_snapshot_path": "html-papers/raw-snapshots/...",
  "jats_xml_path": "html-papers/xml/...",
  "evidence_html_path": "html-papers/...",
  "publication_year": 2026,
  "journal": "Nature",
  "publisher": "Springer Nature",
  "capture_status": "success",
  "source_priority": "publisher_html",
  "structure_hash": "sha256:..."
}
```

### EvidenceSpan

句子级或子段落级证据。

```json
{
  "evidence_id": "doc123.s0042",
  "doc_id": "doc123",
  "section": "Results",
  "section_kind": "results",
  "block_id": "doc123:p0017",
  "sentence_index": 42,
  "text": "The treatment increased X by 18% compared with control.",
  "char_start": 10231,
  "char_end": 10292,
  "html_anchor": "s-doc123-0042",
  "metadata": {
    "doi": "10....",
    "title": "...",
    "year": 2026
  }
}
```

### EvidenceChunk

检索单位，通常是一个句子窗口。

```json
{
  "chunk_id": "doc123.c0017",
  "doc_id": "doc123",
  "evidence_ids": ["doc123.s0040", "doc123.s0041", "doc123.s0042"],
  "text": "... sentence window ...",
  "section": "Results",
  "token_count": 220
}
```

### ExtractedQuote

针对当前问题抽取出的精确证据。

```json
{
  "quote_id": "q0007",
  "question": "How does method A compare with method B?",
  "evidence_ids": ["doc123.s0042"],
  "exact_quote": "The treatment increased X by 18% compared with control.",
  "role": "supports",
  "claim_hint": "Method A improved X relative to control.",
  "confidence": 0.83
}
```

### AnswerClaim

回答中的事实性句子。

```json
{
  "claim_id": "c0012",
  "text": "Method A improved X relative to control in the cited trial.",
  "citation_quote_ids": ["q0007"],
  "support_status": "supported",
  "verification_score": 0.91
}
```

## HTML 证据锚点

索引时为每个证据句生成稳定锚点：

```html
<span
  id="s-doc123-0042"
  data-evidence-id="doc123.s0042"
  data-section-kind="results">
  The treatment increased X by 18% compared with control.
</span>
```

如果不希望改动原始 clean HTML，可以生成并排文件：

```text
paper.html
paper.evidence.html
paper.evidence.json
```

推荐做法：

- clean HTML 保持原始阅读稿。
- evidence HTML 保持阅读干净，只注入稳定 `evidence_id/html_anchor`；高亮由答案、问题或审阅 layer 按需叠加。
- evidence JSON/SQLite 作为系统可信数据源。

## 检索流程

### 1. Query Analysis

把用户问题解析成结构化查询：

- 核心概念。
- 实体、方法、数据集、物种、疾病、模型、指标。
- 问题类型：定义、比较、机制、证据表、矛盾、趋势、限制、综述。
- 可选过滤条件：年份、期刊、DOI、章节、领域。

LLM 在这里只负责生成查询结构，不回答问题。

### 2. Multi-Route Candidate Recall

同时跑多路召回：

1. SQLite FTS5 或 BM25。
2. Dense embedding search。
3. 标题、DOI、作者、期刊、年份、参考文献元数据检索。
4. Citation traversal。
5. 可选外部发现：Semantic Scholar、Crossref、OpenAlex、PubMed、arXiv。

外部发现只负责找论文。真正进入证据库前，仍然要通过 `scansci-html` 保存 HTML。

### 3. Reranking

用 cross-encoder 对候选 chunk 精排。

建议策略：

- 初召回保留 200 到 1000 个候选。
- rerank 后保留 top 50。
- 每篇论文最多保留 3 到 5 个 chunk，避免单篇论文霸榜。
- 文献综述问题要保留一定年份、方法、研究对象的多样性。

OpenScholar 的消融结果说明，去掉 reranking 会显著降低正确性和引用准确性。

### 4. Evidence Adequacy Check

在生成前判断：

- 是否覆盖了问题的所有子问题。
- 是否有相互冲突的证据。
- 是单篇论文问题还是多篇论文综合问题。
- 是否应该继续检索。
- 是否应该拒答。

这一步很重要。高精度系统必须允许“不够证据，不能回答”。

## Quote Extraction

借鉴 Ai2 ScholarQA：先抽 quote，再写答案。

当前状态：

- 已新增 `qa/quote_extractor.py`：提供 `ExtractedQuote`、`extract_quotes` 和 `validate_quotes`。
- 已新增 `qa/schemas.py`：用 Pydantic v2 定义 LLM quote、answer claim、claim verification 的结构化 schema，约束非空引用、bounded confidence 和固定 support status。
- 当前实现是 deterministic local extractor：从 reranked evidence hits 中选择带有 matched terms 的证据句，生成 exact quote；后续可以替换为 LLM quote extraction。
- 已新增 `extract_quotes_with_llm`：可注入 chat JSON client，使用结构化 prompt 从候选 evidence hits 中抽取 quote；仍复用 `validate_quotes` 强制检查 evidence_id 和 exact substring；已兼容数组输出和 `{"quotes": [...]}` 输出。
- 已新增 `llm.py`：提供 OpenAI-compatible JSON chat client，可通过 `SCANSCI_CHAT_BASE_URL`、`SCANSCI_CHAT_API_KEY`、`SCANSCI_CHAT_MODEL` 或 CLI 参数配置。
- `ask` CLI 已支持 `--quote-provider local|llm`；默认 local，只有显式选择 `llm` 时才调用 chat provider。
- `validate_quotes` 强制检查 `evidence_id` 必须存在，`exact_quote` 必须是 evidence text 的原文子串。
- 已新增 `qa/evidence_table.py`：把 quote 映射成可人工检查的 evidence table rows，保留论文标题、DOI、section、HTML path 和 anchor。

输入：

- 用户问题。
- reranked chunks。
- 每个 chunk 的 evidence IDs。

输出：

```json
[
  {
    "quote_id": "q001",
    "evidence_ids": ["docA.s0123"],
    "exact_quote": "...",
    "role": "supports",
    "claim_hint": "...",
    "confidence": 0.82
  }
]
```

约束：

- `evidence_id` 必须存在。
- quote 必须是原文子串，或指向具体 evidence span。
- 不能让模型发明 quote。
- 不能让模型引用未检索到的论文。

## Evidence Table

证据表是用户真正应该检查的中间产物。

建议列：

| Claim target | Stance | Exact quote | Paper | Section | Year | DOI | Confidence |
|---|---|---|---|---|---:|---|---:|

对论文写作来说，证据表往往比最终段落更有价值，因为它可以直接变成文献综述矩阵。

## Answer Synthesis

答案只能从 evidence table 写出。

当前状态：

- 已新增 `qa/synthesizer.py`：将 evidence table 转成 answer JSON，生成 `claim_id`、`text`、`quote_ids` 和初始 `support_status`。
- 已新增 `render/report.py`：生成静态 HTML answer report，包含 answer、limitations、evidence table、quote 链接和 source anchor。
- 已新增 `ask` CLI：串联 `search-v2 -> extract_quotes -> build_evidence_table -> synthesize_answer -> render_answer_report`。
- 当前 synthesizer 默认是 deterministic evidence-only 骨架；它不会从模型记忆写无证据综述。也可以通过 `--answer-provider llm` 启用 LLM synthesizer，并继续保持 JSON schema 和 quote 校验。
- 已新增 `synthesize_answer_with_llm`：可注入 chat JSON client 生成 claim JSON，但会拒绝 evidence table 之外的 quote_id。

规则：

1. 每个事实性句子必须引用 quote ID。
2. 证据冲突时必须说明冲突。
3. 保留范围和不确定性。
4. 不引用 evidence table 之外的论文。
5. 不因为论文主题相关就引用。
6. 复杂问题优先输出短段落加证据表。

输出先用 JSON，再渲染 HTML：

```json
{
  "answer": [
    {
      "claim_id": "c001",
      "text": "The strongest evidence suggests ...",
      "quote_ids": ["q001", "q004"]
    }
  ],
  "limitations": ["Only five papers in the local corpus address ..."],
  "followup_queries": ["..."]
}
```

## Claim Verification

答案生成后，逐句拆 claim 并核验。

当前状态：

- 已新增 `qa/verifier.py`：提供 `verify_answer_claims` 和 `verification_counts`。
- 已新增 `verify` CLI：读取 `ask` 生成的结构化 JSON，写出 verified JSON report。
- 当前 verifier 是 deterministic checker：根据 claim terms、绑定 quote text 和简单矛盾启发式判断 `supported`、`partially_supported`、`contradicted`、`unsupported`、`not_enough_information`。
- 已新增 `verify_answer_claims_with_llm`：可注入 chat JSON client 进行严格 entailment judge，并强制状态值必须属于既定 support status 集合；`ask` 和 `verify` CLI 均已支持 `--verification-provider local|llm`。
- 已新增 `apply_verification_policy`：验证后若没有任何 `supported` 或 `partially_supported` claim，则将 answer 标记为 `insufficient_evidence` 并记录 `verification_policy.action = "abstain"`；这提供了当前 MVP 的 regenerate-or-abstain 中的 abstain path。
- 后续可以继续接科学文本 NLI 或第二模型交叉验证，但保留当前 JSON 状态字段和报告结构。

核验方式：

1. 严格 entailment prompt 的 LLM judge。
2. 可选科学文本 NLI 模型。
3. 高风险输出使用第二模型交叉验证。
4. 对数字、实体、方法、数据集做精确匹配检查。

支持状态：

- `supported`
- `partially_supported`
- `contradicted`
- `unsupported`
- `not_enough_information`

处理策略：

- supported：保留。
- partially_supported：改写成更保守的句子。
- contradicted：改写为冲突证据描述。
- unsupported：删除、继续检索或标记证据不足。
- not_enough_information：拒答或给出后续检索建议。

## HTML 报告界面

当前状态：

- `render/report.py` 已生成静态 HTML report，包含 Answer、Evidence、Source 三个区域。
- Answer claim 使用 `details` 展示，带 claim-level citation、support status 和 verification score。
- Evidence table 保留 exact quote、paper、DOI、section、confidence 和 evidence source link。
- Source pane 使用本地 `*.evidence.html#anchor` iframe 展示对应 source sentence，支持人工跳回校对。
- 已新增 `review.py` 和 `review-matrix` CLI：可把一个或多个 `ask` JSON 报告中的 evidence table 导出为 CSV/JSON/HTML 综述证据矩阵，保留 query plan、retrieval filters、实际执行的 retrieval queries、evidence adequacy、claim、quote、paper、DOI、evidence ID、support status 和 source anchor；HTML 格式会把 evidence ID 链接回 `html_path#html_anchor`，适合写综述前人眼校对，也能在矩阵脱离原始 ask 报告后继续审计证据是如何被检索出来的。`--report` 可以重复传入，用来把多个问题或多个综述小主题的报告合并成一张矩阵；`--support-status`、`--question-type`、`--section-kind`、`--evidence-sufficient` 和 `--columns` 已支持导出前筛选与列设置。
- Citation 链接已带 `title` / `data-quote-preview` exact quote 预览；报告顶部已有 unsupported / not enough information claim toggle。
- 后续可继续增加更精细的前端交互，例如浏览器内筛选、列设置和多矩阵比较；CLI 级多报告合并、筛选和列设置已经可用。

报告分三栏：

1. Answer pane：回答段落，每句话带 claim-level citation。
2. Evidence pane：精确 quote、论文元数据、章节、支持状态、置信度。
3. Source pane：本地 HTML 原文，高亮对应 evidence span。

交互：

- hover citation 显示 exact quote。
- click citation 跳转到原文句子。
- click claim 展开 verification status。
- toggle unsupported 显示被删除或改写的 claim。
- export evidence table 为 CSV/JSON。

## CLI 设计

已实现命令。新文档优先使用 `scansci` 作为用户入口；`python -m scansci_html.cli ...` 继续作为开发和调试入口保留。

```powershell
scansci index-v2 `
  --library-dir .\html-papers `
  --db .\html-papers\evidence.sqlite `
  --jsonl-output .\html-papers\evidence-spans.jsonl `
  --inject-evidence-html
```

```powershell
scansci search-v2 `
  --db .\html-papers\evidence.sqlite `
  --query "What evidence supports X?" `
  --limit 10 `
  --per-document-limit 3
```

可选 cross-encoder reranking：

```powershell
scansci search-v2 `
  --db .\html-papers\evidence.sqlite `
  --query "What evidence supports X?" `
  --limit 10 `
  --initial-limit 200 `
  --reranker cross-encoder `
  --reranker-model BAAI/bge-reranker-large
```

```powershell
scansci ask `
  --db .\html-papers\evidence.sqlite `
  --question "What evidence supports X?" `
  --output .\reports\question-001.html `
  --json-output .\reports\question-001.json `
  --adequacy-profile auto `
  --min-quotes 1 `
  --min-documents 1
```

无标注开箱路径：如果只是想直接对本地 HTML 论文库提问，可用 `local-ask` 自动建库或复用已有 evidence store；gold set 只用于后续质检，不是提问前置条件。

```powershell
scansci local-ask `
  --library-dir .\html-papers `
  --db .\html-papers\evidence.sqlite `
  --question "What evidence supports X?" `
  --output .\reports\question-001.html `
  --json-output .\reports\question-001.json `
  --inject-evidence-html `
  --adequacy-profile auto
```

可选 LLM-backed quote / synthesis / verification：

```powershell
scansci ask `
  --db .\html-papers\evidence.sqlite `
  --question "What evidence supports X?" `
  --output .\reports\question-001.html `
  --json-output .\reports\question-001.json `
  --quote-provider llm `
  --answer-provider llm `
  --verification-provider llm `
  --chat-provider openai-compatible `
  --chat-base-url https://api.example.test/v1 `
  --chat-api-key $env:SCANSCI_CHAT_API_KEY `
  --chat-model your-json-capable-model
```

```powershell
scansci verify `
  --report .\reports\question-001.json `
  --output .\reports\question-001.verified.json
```

```powershell
scansci verify `
  --report .\reports\question-001.json `
  --output .\reports\question-001.verified.json `
  --verification-provider llm `
  --chat-provider openai-compatible
```

```powershell
scansci review-matrix `
  --report .\reports\question-001.json `
  --output .\reports\question-001.matrix.html `
  --format html
```

```powershell
scansci bench `
  --db .\html-papers\evidence.sqlite `
  --gold .\bench\gold_questions.jsonl `
  --min-retrieval-recall 0.8 `
  --min-citation-f1 0.8 `
  --min-answerable-evidence-adequacy 0.8 `
  --adequacy-profile auto `
  --min-quotes 1 `
  --min-documents 1 `
  --details-output .\bench\benchmark-details.json `
  --details-html-output .\bench\benchmark-details.html
```

```powershell
scansci bench-validate `
  --gold .\bench\gold_questions.jsonl `
  --db .\html-papers\evidence.sqlite `
  --min-questions 50 `
  --min-per-answer-type 10 `
  --require-answer-types single_paper_fact,single_paper_method,multi_paper_synthesis,conflict_evidence,unanswerable,numeric_extraction `
  --html-output .\bench\gold-validation.html
```

```powershell
scansci corpus-coverage --db .\html-papers\evidence.sqlite
```

```powershell
scansci bench-template `
  --db .\html-papers\evidence.sqlite `
  --output .\bench\gold_questions.template.jsonl `
  --html-output .\bench\gold_questions.template.html `
  --questions-per-type 10
```

```powershell
scansci bench-template-report `
  --template .\bench\gold_questions.template.jsonl `
  --output .\bench\gold_questions.template.html
```

```powershell
scansci bench-import qasper `
  --input .\external\qasper\qasper-dev-v0.3.json `
  --output .\bench\gold_questions.external.qasper.jsonl

scansci bench-import scifact `
  --claims .\external\scifact\data\claims_dev.jsonl `
  --corpus .\external\scifact\data\corpus.jsonl `
  --output .\bench\gold_questions.external.scifact.jsonl
```

```powershell
scansci bench-external qasper `
  --input .\external\qasper\qasper-dev-v0.3.json `
  --gold .\bench\gold_questions.external.qasper.jsonl `
  --db .\bench\qasper-external-evidence.sqlite `
  --k 20

scansci bench-external scifact `
  --corpus .\external\scifact\data\corpus.jsonl `
  --gold .\bench\gold_questions.external.scifact.jsonl `
  --db .\bench\scifact-external-evidence.sqlite `
  --k 20
```

```powershell
scansci discover `
  --provider openalex `
  --query "cortical activity language model" `
  --limit 10
```

```powershell
scansci references `
  --html .\html-papers\paper.html
```

## 推荐模块结构

```text
src/scansci_html/
  evidence.py              # 保留现有 block extraction，谨慎扩展
  evidence_spans.py        # 句子锚点和 span extraction
  evidence_store.py        # SQLite schema 和 JSONL import/export
  evidence_doctor.py       # evidence store -> HTML anchor link validation
  citations.py             # References/Bibliography DOI extraction
  discovery.py             # OpenAlex/Crossref/Semantic Scholar/PubMed discovery
  llm.py                   # OpenAI-compatible JSON chat client
  bench.py                 # benchmark metrics, gold template generation, quality gates
  bench_fetch.py           # public benchmark download/unpack helpers, currently BEIR
  bench_import.py          # public benchmark importers, currently QASPER, SciFact, and BEIR
  bench_external.py        # external benchmark retrieval scorer and temporary stores
  coverage.py              # corpus coverage summary for gold-set planning
  review.py                # literature-review evidence matrix export
  embeddings.py            # embedding provider interface
  retrieval.py             # 保留现有 lexical search，增加 hybrid interface
  rerankers.py             # reranker interface, local lexical reranker, optional cross-encoder
  qa/
    schemas.py            # Pydantic schemas for LLM JSON outputs
    query_planner.py       # 查询分解和 metadata filters
    quote_extractor.py     # 精确 quote JSON extraction
    evidence_table.py      # 证据表
    synthesizer.py         # evidence-only answer generation
    verifier.py            # claim-level support checks
    agent.py               # retrieve-check-refine 编排
  render/
    report.py              # HTML report renderer
    gold_template.py       # gold-question annotation HTML report renderer
```

## 实施阶段

### Phase 1：句子级 Evidence Store

当前状态：

- 已新增 `evidence_spans.py`：从 clean HTML 提取句子级 `EvidenceSpan`，生成稳定 `evidence_id`、`html_anchor`、section metadata 和 block metadata。
- 已新增 `evidence_store.py`：写入 SQLite evidence store 和 FTS5 表，并支持 JSONL 导出。
- EvidenceSpan 和 SQLite evidence store 已新增 `publication_year`：从 article data attributes、citation/date meta tags 或 `<time>` 标签读取年份；旧库缺列时检索会兼容为 unknown，重新 `index-v2` 后可得到可过滤的年份元数据。
- 已新增 `index-v2` CLI：保留旧 `index` 命令，同时支持 `--inject-evidence-html` 生成并排的 `*.evidence.html`，不覆盖原始 clean HTML；生成 sidecar 时，`evidence_spans.html_path` 指向带句子锚点的 `*.evidence.html`，`source_documents` 同时保留原始 clean HTML 和 sidecar 路径；同一 DOI/source-derived `doc_id` 在一个 library root 中重复出现时，只索引第一份并用 `duplicate_documents_skipped` 计数，避免重复抓取目录把同一篇论文误算成多个 source documents；`_rejected_preview`、`raw-snapshots`、`*_files` 等浏览器保存资源目录会被跳过。
- 已新增 `evidence_doctor.py` 和 `evidence-doctor` CLI：检查每条 evidence span 的 `html_path#html_anchor` 是否存在，并验证 sidecar HTML 上的 `data-evidence-id` 是否和 SQLite 中的 `evidence_id` 一致；链接损坏时返回非零 exit code。
- 已增加 Nature、Science、Wiley 风格样例测试，覆盖 span extraction、sidecar HTML、SQLite FTS5、JSONL export 和 CLI 入口。
- EvidenceSpan 已覆盖 paragraph、figure caption、table row；table row 在 sidecar HTML 中保留原始单元格结构并给 `<tr>` 添加 evidence anchor；heading 解析已支持子标题继承父 section kind，例如 `Results and Discussion -> 2.1 ...` 会保留为 results/discussion 语境；References、作者单位、funding、data availability、rights、supplementary/source data 等非证据 back matter 不再进入 QA evidence store。
- 当前 `html-papers` 已实际跑通 `index-v2 --inject-evidence-html`：得到 72 个唯一 source documents、15,575 条 evidence spans、72 个 sidecar HTML，并跳过 95 个重复 `doc_id`；`evidence-doctor` 已验证 15,575 个 `html_path#html_anchor` 全部存在且 `data-evidence-id` 匹配；磁盘 sidecar 与 SQLite 引用已对齐为 72/72/0 orphan。

交付：

- 从现有 clean HTML 中提取 `EvidenceSpan`。
- 生成稳定 `evidence_id` 和 `html_anchor`。
- SQLite FTS5 存储。
- JSONL 导出。
- publication year metadata。
- evidence link doctor。
- 覆盖 Nature、Science、Wiley 样例的测试。

验收：

- 每个段落和图注能映射到有序句子。
- evidence ID 能跳回本地 HTML 原文位置。
- `evidence-doctor` 能证明每个入库锚点可打开并匹配 `data-evidence-id`。
- `publication_year` 能从常见 HTML 元数据进入 evidence span、SQLite 和 JSONL。
- 现有 `index` 命令不被破坏，或新增 `index-v2`。

### Phase 2：Hybrid Retrieval 与 Reranking

当前状态：

- 已在 `retrieval.py` 新增 `search_evidence_store`，面向 `index-v2` 生成的 SQLite evidence store 检索句子级证据。
- 已新增 `embeddings.py`：提供 deterministic hashing embedding fallback 和 OpenAI-compatible embedding provider，可用 CLI 参数或 `SCANSCI_EMBEDDING_*` 环境变量配置。
- 已新增 `rerankers.py`：提供 `LexicalReranker`、`CrossEncoderReranker`、`build_reranker` 和小型 reranker interface；`cross-encoder` provider 使用可选 `sentence-transformers`，只有显式选择时才加载。
- 已新增 `search-v2` CLI：支持 `--db`、`--limit`、`--initial-limit`、`--per-document-limit`、`--year-min`、`--section-kind`、`--embedding-provider`、`--reranker`、`--reranker-model`、`--reranker-batch-size`。
- 当前已经支持 FTS5 召回、dense fallback、候选合并、去重、publication-year metadata filter、section-kind metadata filter、重排和每篇论文候选数量上限。显式 `--year-min` 会排除未知年份文档，避免把没有年份证据的论文误当作满足时间条件；`--section-kind` 可重复传入，用于限定 Methods、Results、Discussion 等文章区域。

交付：

- FTS/BM25 检索。
- Dense embedding 检索。
- 候选合并和去重。
- Cross-encoder reranking。
- Metadata filters，包括 `publication_year >= year_min` 和 `section_kind in (...)`。
- 每篇论文的候选数量上限。

验收：

- 搜索结果包含 evidence ID、原文、章节、DOI、标题。
- reranked output 可检查。
- `since/after YEAR` 这类时间条件能过滤掉旧年份或未知年份文档。
- 方法、结果、讨论等明确章节限定能过滤掉其他 section 的证据句。
- 小型 gold set 上能测 retrieval recall。

### Phase 3：Quote Extraction

当前状态：

- 已新增 `qa/schemas.py`：用 Pydantic v2 定义 `ExtractedQuoteSchema`、`AnswerPayloadSchema`、`ClaimVerificationPayloadSchema` 等结构化输出 schema。
- 已新增 `qa/quote_extractor.py`：提供本地 quote extraction 和 LLM quote extraction 两条路径。
- 本地路径会从 reranked evidence hits 中选择 exact quote；LLM 路径要求模型只使用给定 `evidence_id`，并返回结构化 JSON。
- 已实现 `validate_quotes`：每个 quote 必须引用已知 `evidence_id`，且 `exact_quote` 必须是对应 evidence text 的精确子串，否则直接报错。
- 已新增 `qa/evidence_table.py`：把 quote 和 evidence metadata 合并成可审计 evidence table，保留 paper、section、DOI、html path、html anchor、stance、confidence 等字段。

交付：

- 结构化 quote extraction prompt。
- Pydantic schema。
- exact substring 或 evidence ID 校验。
- Evidence table renderer。

验收：

- 不存在的 evidence ID 会被拒绝。
- 模型不能发明原文 quote。
- 用户能在答案生成前检查证据表。

### Phase 4：Evidence-Only Answer Generation

当前状态：

- 已新增 `qa/synthesizer.py`：提供本地 evidence-only answer synthesis 和 LLM answer synthesis 两条路径。
- 本地路径只从 evidence table 的 `claim_target` 和 `quote_id` 生成 claims；没有 evidence table 时返回 `insufficient_evidence`。
- LLM 路径要求模型只基于 evidence table 写 concise claims，每个 claim 必须绑定已知 `quote_id`；引用 evidence table 之外的 quote ID 会被拒绝。
- 已新增 `render/report.py`：生成 HTML answer report，包含 Retrieval Audit、Answer、Limitations、Evidence table 和 Source pane。
- HTML report 中 citation 链接到 quote row，并通过 `title`/`data-quote-preview` 保留 exact quote preview；source pane 使用 `*.evidence.html#html_anchor` 指回本地证据句，保证人工校对时打开的是带句子级标注的页面。
- Retrieval Audit 会展示 question type、metadata filters、实际执行的 retrieval queries、evidence adequacy、quote count、min quotes、document count、min documents 和 follow-up reason，便于人工判断答案是否建立在足够且正确约束的检索过程上。

交付：

- Answer JSON schema。
- Claim IDs 和 Quote IDs。
- HTML answer renderer。
- Retrieval audit renderer。
- Insufficient evidence path。

验收：

- 每个事实性句子都有 quote IDs。
- citations 不包含 evidence table 之外的来源。
- HTML report 能展示 query plan、filters、retrieval queries 和 adequacy 判断。
- 冲突证据会被展示，而不是被抹平。

### Phase 5：Claim Verification

当前状态：

- 已新增 `qa/verifier.py`：提供本地 claim verification 和 LLM claim verification 两条路径。
- 本地 verifier 会检查 claim 绑定的 quote，输出 `supported`、`partially_supported`、`contradicted`、`unsupported`、`not_enough_information` 等状态和 verification score。
- LLM verifier 使用结构化 JSON schema，并限制 support status 只能来自允许集合。
- 已新增 `apply_verification_policy`：当没有任何 supported 或 partially supported claim 时，自动把结果转为 `insufficient_evidence`，避免无证据答案继续流入报告。
- `verify` CLI 可对已有 ask JSON report 重新执行 verification，并输出 verification counts。

交付：

- Claim splitter。
- Citation support verifier。
- Regenerate-or-abstain loop。
- Verification report。

验收：

- unsupported claim 会被删除、改写或标记。
- HTML report 显示 verification status。
- gold examples 上能测 citation precision、recall、F1。

### Phase 6：Agentic Retrieval

当前状态：

- 已新增 `qa/query_planner.py`：把问题解析成 question type、core terms、简单年份过滤、简单 section-kind 过滤和 follow-up query candidates；`ask` 已把 `year_min` 与 `section_kinds` filters 传给初次检索和 follow-up 检索。当前只有明确方法类问题会自动限定到 Methods，避免普通比较题被过窄过滤。
- 已新增 `qa/agent.py`：提供 `answer_question`，串联 `plan_query -> search_evidence_store -> extract_quotes -> build_evidence_table -> synthesize_answer -> verify_answer_claims`。
- 已新增 `assess_evidence_adequacy`：根据 quote 数量和来源文档多样性判断证据是否足够，并给出 follow-up reason；`ask` CLI 已暴露 `--adequacy-profile`、`--min-quotes` 和 `--min-documents`，并把策略与阈值写入 adequacy JSON、HTML Retrieval Audit 和 review matrix。`auto` profile 会把 comparison、conflict、synthesis 这类多证据问题提升到至少 2 条 quote / 2 个 source documents；`manual` profile 则严格使用传入阈值。
- `ask` CLI 已改为调用 agent orchestration，默认输出带 verification 的结构化结果，并记录实际执行的 `retrieval_queries`。
- 当初次检索后的 quote adequacy 不足时，agent 会按 `query_plan.followup_queries` 继续检索、合并 evidence hits、重新抽取 quote 并重新评估 adequacy；证据足够后停止。
- 当所有 follow-up 后 evidence adequacy 仍不足时，agent 会保留 evidence table 供人工审查，但不再进入 answer synthesis / LLM / verifier 生成事实 claim；最终 answer 标记为 `insufficient_evidence`，并在 limitations 中写明 adequacy gate 失败原因。
- 已新增 `discovery.py` 和 `discover` CLI：支持 OpenAlex、Crossref、Semantic Scholar、PubMed 的候选论文发现。Discovery 只返回候选元数据，真正入库仍必须通过现有 HTML capture pipeline。
- 已新增 `citations.py` 和 `references` CLI：从已保存 HTML 的 References/Bibliography 区域抽取 DOI 候选，保留来源 HTML path、anchor 和 reference text，作为本地 citation traversal 原语。
- 外部 discovery 和 citation traversal 仍只返回候选元数据，真正进入证据库仍必须通过 HTML capture pipeline。

交付：

- Query planner 可发起 follow-up searches。
- Query planner 的年份和 section-kind filters 会真正约束检索结果。
- Evidence adequacy check。
- Citation traversal。
- Semantic Scholar/OpenAlex/PubMed discovery hook。

验收：

- 多论文问题 recall 提升。
- agent 在证据足够或明显不足时停止。
- 外部发现的论文仍通过现有 HTML pipeline 入库。

### Phase 7：Benchmark 与质量门

当前状态：

- 已新增 `bench.py`：读取 gold questions JSONL，并基于 `gold_evidence_ids` 评估本地 evidence-first pipeline。
- 已新增 `bench` CLI：支持 `--db`、`--gold`、`--k`、`--min-retrieval-recall`、`--min-all-gold-retrieval-recall`、`--min-gold-evidence-recall`、`--min-citation-f1`、`--min-answerable-evidence-adequacy`、`--adequacy-profile`、`--min-quotes`、`--min-documents`、`--details-output`、`--details-html-output`。
- 已新增 `bench-validate` CLI：校验 gold JSONL 的字段、重复 `question_id`、answerable/unanswerable 与 `gold_evidence_ids` 的一致性、最小题量、answer type 覆盖率、每类 answer type 最小题量，并拒绝仍带 `annotation_status: "todo"` 的未完成模板行；传入 `--db` 时还会验证每个 `gold_evidence_id` 是否存在于当前 evidence store，防止手写 ID 错误或语料版本漂移；同时会做 answer-type 证据充分性检查，例如 `multi_paper_synthesis` 和 `conflict_evidence` 至少需要 2 条 gold evidence 且来自 2 个 source documents，`numeric_extraction` 至少需要一条包含数字的 gold evidence text；`--html-output` 会把 schema 问题、缺失 evidence ID、题型覆盖缺口和 gold evidence adequacy 问题渲染成 HTML 修订报告，并按 `question_id` 分组生成页内锚点，每个问题卡片包含 answer type、annotation status、question text 和 gold evidence IDs；报告还包含 `completed_rows`、`incomplete_rows`、`empty_question_rows` 和 status counts 等 annotation progress，并把 template 的 suggested 字段带入问题卡片；在传入 `--db` 时，每条已找到的 gold evidence 还会展开为来源卡片，包含 title、DOI、section、转义后的证据原文和可点击的 `html_path#html_anchor` 链接，便于逐题回到 HTML 原文校对；validation payload 和 HTML report 还会输出 `gold_evidence_coverage`，统计当前有效 gold evidence references、unique evidence spans、source document counts、section kind counts 和 block type counts，用来检查最终 gold set 是否被少数论文或少数正文区域垄断。
- `bench-validate` 现在还会把答案准确性判分点作为正式 gold row 的门槛：可回答题至少需要一个 `required_points`，不可回答题至少需要一个 `forbidden_points`；`annotation_status: "todo"` 的模板行仍只作为人工待办，不会因为空判分点额外刷屏。这样 benchmark 的 `answer_accuracy` 不只是“有没有引用”，而是能检查答案是否覆盖了人工定义的关键事实、限制或禁答条件。
- `bench-validate` 还会输出非致命的 `gold_evidence_quality_warnings`：当人工已验证的 `multi_paper_synthesis` 或 `conflict_evidence` gold rows 仍包含 figure-caption-like evidence（包括 `block_type=caption`，或文本明显像 `Fig.` / `Figure` / `Representative panels`）时，它会在 JSON 和 HTML validation report 中提示人工复核，但不会单独让 validation 失败；真正失败的仍是字段、覆盖率、ID 缺失和 answer-type 证据充分性问题。
- 已新增 `coverage.py` 和 `corpus-coverage` CLI：输出 evidence store 的文档数、证据句数、section kind、block type 和逐文档摘要，用于规划真实 gold 标注的 corpus coverage。
- 已新增 `bench-template` CLI：从 `evidence.sqlite` 生成待人工标注的 `gold_questions.template.jsonl`，按 answer type 抽取候选证据，保留 `candidate_evidence`、候选 `gold_evidence_ids`、空 `question` 和 `annotation_status: "todo"`；每条 `candidate_evidence` 现在也保留 `doc_id`，便于审计同一篇论文是否过度贡献候选；同时生成 `suggested_question`、`suggested_required_points`、`suggested_forbidden_points` 作为人工改写起点，但这些建议字段不会填充最终 `question`，也不会绕过人工审批；可用 `--html-output` 同时生成 HTML 人工校对页。单证据类型候选会按文档轮转取样，并优先选择 Results / Methods / Discussion 等正文 section，Abstract 只作为 fallback，避免同一篇论文或摘要句垄断事实、方法和数值抽取模板；多证据 pair 生成已用 term postings 和 per-doc candidate cap 优化，并跳过 figure-caption-like rows，避免长图注泛词主导跨论文配对；生成 payload 和 HTML worksheet 顶部都会显示 `template_coverage` 摘要，包括 candidate evidence references、unique evidence spans、source document counts、section kind counts 和 block type counts；当前真实库 `--questions-per-type 10` 可在数秒内完成。
- 已新增 `render/gold_template.py` 和 `bench-template-report` CLI：可把已有模板或标注中间稿重新渲染为 HTML worksheet，候选证据链接会指回 `html_path#html_anchor`。
- 已新增 `bench_fetch.py` 和 `bench-fetch` CLI：`bench-fetch beir --dataset-name climate-fever --output-dir .\external\beir` 可按 BEIR 官方公开 zip URL 下载并安全解包，同时输出 `corpus_path`、`queries_path`、`qrels_paths` 和下一步 `bench-import` 命令；下载器会检查 zip member 是否越过输出目录，避免恶意 zip 写到外部路径。已新增 `bench_import.py` 和 `bench-import` CLI：`bench-import qasper` 可把本地 QASPER JSON/JSONL 转成 `bench/gold_questions.external.qasper.jsonl`，兼容官方 raw release 的顶层 paper-id mapping、`qas` 列表，以及 Hugging Face-style 的 `qas.question` / `qas.question_id` / `qas.answers` 字段，并优先使用句子级 `highlighted_evidence`，没有时回退到段落级 `evidence`；`bench-import scifact` 可把 SciFact 的 `claims_*.jsonl` 与 `corpus.jsonl` 转成 claim verification benchmark，使用 claim label 和 abstract sentence rationale，且保留 `id: 0` 这类合法 ID；`bench-import beir` 可把标准 BEIR `corpus.jsonl`、`queries.jsonl`、`qrels.tsv` 转成 document-level retrieval benchmark，适合 Climate-FEVER 这类 BEIR 子集。三个导入器都会写入 `annotation_status: "imported"`、`external_source` 和 `candidate_evidence`，但 evidence ID 是 `qasper:` / `scifact:` / 自定义 BEIR dataset 前缀开头的外部合成 ID，不是本地 `html_path#html_anchor`；它们是论文式公开 benchmark 主线，应与本地 acceptance set 分开报告。
- 已新增 `bench_external.py` 和 `bench-external` CLI：可根据 imported QASPER/SciFact/BEIR gold rows 临时构建外部 evidence store，并只评估检索层是否在 top-k 命中 gold evidence IDs；它复用当前本地 FTS + hashing dense + lexical rerank 口径，已加入 SQLite `external_embedding_cache` 持久化本地 hashing vectors，并用 `--initial-limit` / `--dense-limit` 控制进入 rerank 的候选数，避免全库 dense 正分候选膨胀。QASPER 默认 `--scope gold-docs`，因为 QASPER 问题绑定到单篇论文；SciFact 默认 `--scope corpus`，因为 claim verification 本身是语料级证据检索；BEIR 默认 `--scope corpus`，因为 qrels 是语料级 document relevance。为避免作弊，QASPER external store 现在只索引 raw `full_text` spans，不再把 imported highlighted evidence 作为 searchable span 注入；评分时通过 `external_gold_evidence_map` 把 synthetic gold evidence ID 映射到 raw span ID。BEIR external store 按 qrels 的 document-level 标注把每个文档建成一个 evidence span，例如 `climate-fever:doc-id.s0001`，适合先衡量“找不找得到相关文档”，不能直接当成句子级 citation 指标。当前全量 local-hash 基线为：QASPER dev 1005 题、883 个有 gold evidence 的可回答问题，在 faithful paper-scoped 口径下 `retrieval_recall_at_k=0.629672`、`all_gold_retrieval_recall_at_k=0.471121`、`gold_evidence_recall_at_k=0.485149`，涉及 281 篇外部文档、45160 条 raw spans、0 条 gold spans、1139 条 mapped gold evidence、174 条 unmapped gold evidence；同一 QASPER 若强行 `--scope corpus`，旧对照为 `retrieval_recall_at_k=0.187995`、`all_gold_retrieval_recall_at_k=0.137033`、`gold_evidence_recall_at_k=0.140899`，说明此前低分主要混入了错误的跨论文文档定位难度。使用本地已缓存的 `sentence-transformers/all-MiniLM-L6-v2` 且离线运行时，QASPER `--scope gold-docs --k 20` 为 `retrieval_recall_at_k=0.673839`，`--k 50` 为 `0.842582`，`--k 100` 达到 `0.915062`，但 `all_gold_retrieval_recall_at_k=0.802945`、`gold_evidence_recall_at_k=0.827113`，这只能说明 question-level retrieval 达到 90% 阶段目标，不能冒充最终答案正确率。SciFact dev 300 题、188 个有 gold evidence 的可回答 claim，在 corpus scope 下 `retrieval_recall_at_k=0.664894`、`all_gold_retrieval_recall_at_k=0.409574`、`gold_evidence_recall_at_k=0.480874`，涉及 5183 篇外部文档、45952 条 spans。抽样 QASPER failures 显示，部分 top retrieved raw sentences 实际能回答问题但不是 QASPER highlighted gold evidence ID，因此 exact gold ID recall 对 RAG citation 可用性偏严格；后续应增加 semantic-evidence adequacy 诊断，不能只看 exact highlighted sentence 命中。
- CI sample gate 已加入 `evidence-doctor`，确保 benchmark 前先检查 evidence store 到 HTML anchor 的链路没有断。
- 当前指标包括 retrieval recall@k、all-gold retrieval recall@k、gold evidence recall@k、answer accuracy、citation precision、citation recall、citation F1、answerable evidence adequacy rate、unsupported-claim rate、abstention accuracy。`retrieval_recall_at_k` 表示问题级任一 gold evidence 命中；`all_gold_retrieval_recall_at_k` 要求一个问题的全部 gold evidence 都在 top-k 中；`gold_evidence_recall_at_k` 则按 evidence ID 计算整体召回；`answerable_evidence_adequacy_rate` 表示可回答 gold 问题中最终通过证据充分性门槛的比例。
- 使用 `bench --details-output .\bench\benchmark-details.json` 时，会额外写出逐题诊断：每题的 gold evidence、top-k retrieved evidence、retrieved gold evidence、missing gold evidence、quoted evidence、cited gold evidence、missing cited gold evidence、evidence adequacy 阈值与结果、answer point match 和 claim support counts；`--details-html-output .\bench\benchmark-details.html` 会把同一批诊断渲染成 HTML 人工校对页。本地 acceptance set 失败时，先看这些 details 定位是检索没召回、quote/citation 没选中，证据充分性门槛不合适，还是答案合成/验证出了问题。`--adequacy-profile auto` 在 benchmark 中还会读取人工 gold 的 `answer_type`：`multi_paper_synthesis` 与 `conflict_evidence` 会提升到至少 2 条 quote / 2 个 source documents，即使问题文本本身没有明显的综合或冲突提示词。
- 阈值参数会在指标低于要求时返回非零 exit code，已经可以作为最小质量门；本地 acceptance set 必须由人工校准，不能把 `bench-template` 产物直接当作真值。
- 已新增 `bench/sample_library` 和 `bench/gold_questions.sample.jsonl`，覆盖一个可回答事实题、一个不可回答题、一个冲突证据题。
- 已新增 `.github/workflows/tests.yml`：在 GitHub Actions 上安装 package，运行 `python -m pytest tests -q`，然后基于 sample library 构建 evidence store，执行 `scansci bench-validate` 和 `scansci bench` gate。
- 当前真实 `html-papers` coverage 显示：72 个文档、15,575 条 spans，其中 `abstract` 478、`introduction` 682、`methods` 5,368、`results` 1,846、`discussion` 1,260、`conclusion` 210、`other` 5,731、`references` 0；上一轮 `other` 16,404 / `references` 3,131 / `methods` 89 / `results` 52 的问题已经通过 section 继承、back matter 排除、资源页过滤和 decimal/subscript sentence split 修复显著改善。剩余 `other` 主要来自没有标准 IMRaD heading 的综述/观点类文章、Science 简短页面和少量 publisher-specific 小节；如果要做本地 acceptance set，仍应先抽样校对。
- 已在真实库上生成 `bench/gold_questions.template.jsonl` 和 `bench/gold_questions.template.html`：共 60 行，6 类 answer type 各 10 行，60 行都有 `suggested_question`，50 个 answerable 行有 `suggested_required_points`，10 个 unanswerable 行有 `suggested_forbidden_points`，`missing_answer_types` 为空；当前 `template_coverage` 为 candidate evidence references=70、unique evidence spans=41、source documents=23，section kinds 为 `methods=10`、`results=60`，block types 为 `paragraph=70`；multi/conflict 候选已过滤明显图注样式文本，当前模板中这些 pair 的候选 evidence 未命中 `^Fig\.|^Figure|panels show|Representative panels` 抽查模式；`bench-validate --db .\html-papers\evidence.sqlite --min-questions 50 --min-per-answer-type 10 --html-output .\bench\gold-validation.template.html` 预期返回失败，因为 `question` 仍为空且 `annotation_status` 是 `todo`，但 `missing_gold_evidence_ids` 为空、`underrepresented_answer_types` 为空、`gold_evidence_adequacy_issues` 为空，annotation progress 明确显示 `completed_rows=0`、`incomplete_rows=60`、`empty_question_rows=60`、`status_counts=todo=60`；这说明候选 evidence ID 与当前库一致、starter 已达到 50 到 100 题人工 gold set 的规模起点，且 multi/conflict/numeric 的候选证据结构满足最低要求；HTML validation report 可直接作为带原文来源链接和建议草稿的人工修订清单。

- 最新刷新验证结果：`bench-validate --db .\html-papers\evidence.sqlite --min-questions 50 --min-per-answer-type 10 --html-output .\bench\gold-validation.template.html` 当前为 `passed=false`、`questions=60`、`completed_rows=0`、`incomplete_rows=60`、`missing_answer_types=0`、`underrepresented_answer_types=0`、`missing_gold_evidence_ids=0`、`gold_evidence_adequacy_issues=0`、`gold_evidence_quality_warnings=0`、`gold_evidence_coverage.gold_evidence_references=70`、`unique_evidence_spans=41`、`source_documents=23`、`section_kind_counts=methods=10, results=60`、`block_type_counts=paragraph=70`、`issues=120`；`evidence-doctor --db .\html-papers\evidence.sqlite` 为 `passed=true`，共 72 个 HTML sidecar、15575 个 spans、缺失文件/锚点/ID mismatch 均为 0。

交付：

- 本地 benchmark JSONL。
- gold annotation template JSONL。
- gold annotation HTML review report。
- imported public benchmark JSONL and retrieval-only external benchmark stores。
- per-question benchmark diagnostics JSON。
- 指标：retrieval recall、all-gold retrieval recall、gold evidence recall、answer accuracy、citation F1、unsupported-claim rate、abstention accuracy。
- 回归测试。
- evidence link doctor gate。

验收：

- 降低任一 gold evidence 召回、全部 gold evidence 召回或 citation F1 的改动不能静默通过。
- 损坏 `html_path#html_anchor` 或 `data-evidence-id` 的改动不能静默通过。
- benchmark gate 失败时，`--details-output` 能指出每道题缺失的 gold evidence ID 和未引用的 gold evidence ID。
- sample benchmark 包含可回答和不可回答问题。
- sample benchmark 包含冲突证据问题。

## Benchmark 设计

先复现论文式公开 benchmark；如果需要验证真实学科库可用性，再做本地 acceptance set。推荐流程是：

0. 公开数据集先走外部层：下载 QASPER 后运行 `scansci bench-import qasper --input .\external\qasper\qasper-dev-v0.3.json --output .\bench\gold_questions.external.qasper.jsonl`；下载 SciFact 后运行 `scansci bench-import scifact --claims .\external\scifact\data\claims_dev.jsonl --corpus .\external\scifact\data\corpus.jsonl --output .\bench\gold_questions.external.scifact.jsonl`；BEIR/Climate-FEVER 这类 BEIR 格式数据先运行 `scansci bench-fetch beir --dataset-name climate-fever --output-dir .\external\beir`，再运行 `scansci bench-import beir --corpus .\external\beir\climate-fever\corpus.jsonl --queries .\external\beir\climate-fever\queries.jsonl --qrels .\external\beir\climate-fever\qrels\test.tsv --dataset-name climate-fever --output .\bench\gold_questions.external.climate-fever.jsonl`。随后用 `scansci bench-external qasper --input .\external\qasper\qasper-dev-v0.3.json --gold .\bench\gold_questions.external.qasper.jsonl --db .\bench\qasper-external-evidence.sqlite --k 20`、`scansci bench-external scifact --corpus .\external\scifact\data\corpus.jsonl --gold .\bench\gold_questions.external.scifact.jsonl --db .\bench\scifact-external-evidence.sqlite --k 20` 和 `scansci bench-external beir --corpus .\external\beir\climate-fever\corpus.jsonl --gold .\bench\gold_questions.external.climate-fever.jsonl --db .\bench\climate-fever-external-evidence.sqlite --dataset-name climate-fever --k 20` 跑全量检索基线；快速调试时再加 `--limit 100`。这一步用于复现公开 evidence QA / claim verification / document retrieval 的检索层，帮助校准召回和证据定位算法，但这些 rows 的 evidence ID 不在本地 `evidence.sqlite` 中，不能混入正式本地 gold；`bench-external` 目前也不评估答案合成、citation F1 或 unsupported-claim，只评估 retrieval。注意 QASPER 的 faithful 口径是 `--scope gold-docs`，因为每个问题绑定论文全文；`--scope corpus` 只是额外压力测试，不能用来代表 QASPER evidence retrieval 能力。BEIR/Climate-FEVER 的 qrels 是 document-level，适合作为相关文档召回基线，不等价于句子级引用准确率。
1. 可选本地验收：先运行 `scansci corpus-coverage --db .\html-papers\evidence.sqlite`，确认语料里 Methods、Results、Discussion、table row、caption 等证据类型是否足够。
2. 再运行 `scansci bench-template --db .\html-papers\evidence.sqlite --output .\bench\gold_questions.template.jsonl --html-output .\bench\gold_questions.template.html --questions-per-type 10`，得到 60 行待人工标注模板和 HTML 校对页。
3. 人工打开 HTML 校对页，逐行检查候选证据是否真的回答问题；必要时用 `scansci bench-template-report --template .\bench\gold_questions.template.jsonl --output .\bench\gold_questions.template.html` 重新渲染中间稿。
4. 在 JSONL 中逐行改写 `question`，保留或调整 `gold_evidence_ids`，补充 `required_points` 和 `forbidden_points`，把 `annotation_status` 改成 `done`、`verified` 或 `approved`。可回答题至少要有一个 `required_points`，不可回答题至少要有一个 `forbidden_points`；这些字段是答案准确性的人工 rubric，不是装饰性备注。
5. 把通过人工校对的文件另存为 `bench/gold_questions.local.jsonl`，再用 `bench-validate --db .\html-papers\evidence.sqlite --min-questions 10 --html-output .\bench\gold-validation.html` 校验题量、字段、answer_type 覆盖、answerable/unanswerable 一致性、answer-type 证据充分性、答案准确性判分点，以及 gold evidence IDs 是否真的存在于当前证据库；若要把它升级为长期质量门，再提高到 50 到 100 题和每类最小题量。若失败，优先打开 HTML validation report 修正对应行。
6. 只有通过校验的 `gold_questions.jsonl` 才能进入 `bench` 和 CI gate；正式跑 gate 时建议加 `--details-output .\bench\benchmark-details.json`，失败后先按逐题诊断里的 `missing_gold_evidence_ids` 和 `missing_cited_gold_evidence_ids` 定位问题。

`bench-template` 产物不是 gold truth。它的 `question` 故意留空，`annotation_status` 标为 `todo`，目的是降低人工标注成本，而不是让机器替代真值标注。`bench-import` / `bench-external` 继承公开数据集的人工标注，是论文式公开 benchmark 主线；经过本地 HTML 链接校验和人工批准的 `bench/gold_questions.local.jsonl` 只代表 ScanSci 当前语料的 acceptance 结果，不能和公开榜单混排。

类型：

- 单篇论文事实：答案在一个句子里。
- 单篇论文方法细节：答案在 Methods 或 Results，不在摘要。
- 多篇论文综合：需要比较多篇论文。
- 冲突证据：不同论文结论相反或互相限制。
- 不可回答：语料库里没有足够支持。
- 数值抽取：样本量、效应量、p 值、日期、比例。

Gold annotation 示例：

```json
{
  "question_id": "q001",
  "question": "...",
  "answer_type": "multi_paper_synthesis",
  "gold_evidence_ids": ["doc1.s0032", "doc7.s0111"],
  "required_points": [
    "A improves X in setting Y",
    "B has lower cost but weaker evidence"
  ],
  "forbidden_points": [
    "Do not claim clinical efficacy; only animal data is present"
  ],
  "answerable": true
}
```

## 最小可用版本

MVP 必须完成：

- sentence evidence store。
- FTS + dense retrieval。
- reranker。
- quote extraction。
- evidence-only answer。
- claim verification。
- HTML report。

暂缓：

- 大规模外部论文库。
- 复杂前端。
- PDF 坐标级定位。
- 全自动文献推荐。

## 关键风险

| 风险 | 缓解 |
|---|---|
| 关键证据没被召回 | 多路检索、更大的候选池、reranking、query expansion |
| 模型引用了相邻但不支持的文本 | evidence ID 校验和 claim-level verification |
| 答案过度概括 | evidence-only synthesis 和 limitation 字段 |
| 引用太多影响阅读 | 回答保持简洁，完整证据放展开表 |
| 本地语料库不完整 | 标注 corpus coverage，必要时触发外部发现 |
| 表格和图片里有关键事实 | 已支持 figure caption 和 table row；OCR 仍作为后续增强 |
| 长上下文模型忽略证据 | 先 quote extraction，不直接 dump 大量 chunks |
| citation traversal 带来低质量论文 | 元数据过滤、撤稿检查、谨慎使用 citation count |

## 开发顺序建议

1. 先做 `evidence_spans.py` 和 `evidence_store.py`。
2. 再做 `index-v2` 和本地 evidence SQLite。
3. 加 FTS 检索，保证基础可用。
4. 加 embedding 和 reranker。
5. 加 quote extraction。
6. 加 evidence table。
7. 加 answer synthesis。
8. 加 claim verification。
9. 加 HTML report。
10. 最后加 agentic retrieval 和外部发现。

## 参考资料

- [PaperQA2 论文](https://arxiv.org/html/2409.13740v1)
- [PaperQA2 代码](https://github.com/Future-House/paper-qa)
- [FutureHouse 工程博客](https://www.futurehouse.org/research/engineering-blog-journey-to-superhuman-performance-on-scientific-tasks)
- [OpenScholar arXiv HTML](https://ar5iv.labs.arxiv.org/html/2411.14199v1)
- [OpenScholar Nature 文章](https://www.nature.com/articles/s41586-025-10072-4)
- [OpenScholar 代码](https://github.com/akariasai/openscholar)
- [Google NotebookLM 官方介绍](https://blog.google/innovation-and-ai/technology/ai/notebooklm-google-ai/)
- [Ai2 ScholarQA 论文](https://arxiv.org/abs/2504.10861)
- [Ai2 ScholarQA 博客](https://allenai.org/blog/ai2-scholarqa)
- [Ai2 ScholarQA 代码](https://github.com/allenai/ai2-scholarqa-lib)
- [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/)
- [NISO JATS](https://www.niso.org/standards-committees/jats)
- [JATS NLM documentation](https://jats.nlm.nih.gov/)
- [MinerU](https://github.com/opendatalab/MinerU)
- [MinerU arXiv](https://arxiv.org/abs/2409.18839)
- [ALCE citation evaluation](https://aclanthology.org/2023.emnlp-main.398/)
- [AIS attribution framework](https://aclanthology.org/2023.cl-4.2/)
- [RAGTruth](https://aclanthology.org/2024.acl-long.585/)
- [Self-RAG](https://arxiv.org/abs/2310.11511)
- [Corrective RAG](https://arxiv.org/abs/2401.15884)
- [LlamaIndex inline citations](https://developers.llamaindex.ai/python/examples/workflow/citation_query_engine/)
- [Google Check Grounding with RAG](https://docs.cloud.google.com/generative-ai-app-builder/docs/check-grounding)
