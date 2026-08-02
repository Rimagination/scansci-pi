# CitationRecord / CitationAudit 对象模型

调研 `feRpicoral/cite` 后，ScanSci 把“可点击引用”提升为正式对象，而不是只把 `[1]` 当成渲染时的装饰。目标是让每个事实性 claim 都能追踪到：

- 用户原句或综述句子。
- 证据 quote 快照。
- `evidence_id`、`doc_id` 和 HTML anchor。
- 当前机器审计结论。
- 人工审阅状态。

## 存储位置

```text
workspace.sqlite
  citation_records   -> claim / citation / evidence 的稳定绑定
  citation_audits    -> 机器或人工审计工具对 citation 的 verdict
```

`citation_records` 不替代 `evidence.sqlite`。它只保存引用对象所需的快照和索引；原始证据文本、文献元数据和 HTML 锚点仍来自 evidence store 与 clean HTML。

## CitationRecord

每条 `CitationRecord` 对应一个 layer item，也就是“某个 Note/claim 被某条 evidence 支持”的绑定。

关键字段：

| 字段 | 含义 |
|---|---|
| `citation_record_id` | workspace 内稳定 citation 对象 ID |
| `notebook_id` | 所属研究项目 |
| `note_id` | 所属问题、笔记或综述草稿 |
| `layer_object_id` | 所属软标注层对象 |
| `annotation_layer_id` | `annotation_layers.sqlite` 中的 layer id |
| `segment_id` | 草稿或笔记中的句子/claim id |
| `citation_marker` | 面向读者的引用编号，如 `1` |
| `claim_text` | 被证据支持的句子 |
| `evidence_id` / `doc_id` | 回指证据库和论文 |
| `quote_snapshot` | 生成引用时冻结的原文 quote |
| `source_location` | 当前第一版为 `html_anchor`，包含 `html_path`、`html_anchor`、`source_href` |
| `support_status` | 机器初筛支持状态，只同步 `supported` / `partial_support` |
| `review_state` | 人工审阅状态，默认 `unreviewed` |

弱证据不会进入默认 citation 记录，因为面向读者的引用必须可审计。

## CitationAudit

`CitationAudit` 与 `review_state` 分开保存：

- `CitationAudit`：机器或审计工具的 verdict，例如 `supported`、`unsupported`、`needs_review`。
- `review_state`：人的确认、驳回、批准或待审状态。

这样后续可以让 LLM judge、规则校验、人工审阅共存，而不会把“模型判断”误当成“人确认”。

## CLI

挂载 annotation layer 时会自动同步 citation records：

```powershell
python -m scansci_html.cli notebook attach-layer `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --layers annotation_layers.sqlite `
  --layer-id graph_rag_question `
  --note-id note_graph_rag
```

查看当前 Notebook 的 citation 对象：

```powershell
python -m scansci_html.cli notebook citations `
  --workspace workspace.sqlite `
  --notebook-id rag_review
```

可以按 Note 或 layer object 过滤：

```powershell
python -m scansci_html.cli notebook citations `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --note-id note_graph_rag
```

## 与 Cite 的关系

Cite 的强项是把 inline citation、文档 viewer、源位置和 citation audit 做成一条闭环。ScanSci 吸收这条产品逻辑，但保持自己的技术边界：

- ScanSci 以 clean HTML/XML 和 evidence span 为主坐标，不把 PDF bbox 作为默认坐标。
- ScanSci 的 citation 对象落在本地 `workspace.sqlite`，不依赖 Supabase/Prisma/Next.js。
- ScanSci 的 citation 从 annotation layer / review matrix 出发，服务学术综述、实体抽取和证据审阅，而不是泛文档聊天。

