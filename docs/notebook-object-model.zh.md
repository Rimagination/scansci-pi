# Notebook / Source / Note / Layer 对象模型

ScanSci 现在把 Notebook、Source、Note、Layer 作为正式对象记录在 `workspace.sqlite` 中。这个库不替代现有证据库，而是记录对象身份和关系：

```text
workspace.sqlite
  notebooks
  sources          -> 指向 evidence.sqlite / clean HTML
  notes            -> 研究问题、草稿、人工笔记
  layers           -> 指向 annotation_layers.sqlite 中的软标注层
  layer_sources    -> Layer 命中了哪些 Source
  citation_records -> Note/Layer 中每条可引用证据
  citation_audits  -> 对 citation 的机器审计结果
```

## 四类对象

| 对象 | 作用 | 长期保存在哪里 |
|---|---|---|
| Notebook | 一个研究主题、学科库或综述项目 | `workspace.sqlite:notebooks` |
| Source | 可信论文来源，通常是 clean HTML/XML 转换后的 HTML | `evidence.sqlite:source_documents`，并同步到 `workspace.sqlite:sources` |
| Note | 人的研究笔记、问题、综述草稿、待验证观点 | `workspace.sqlite:notes` |
| Layer | 某个 Note/问题在 Source 上形成的软标注层 | `annotation_layers.sqlite`，并登记到 `workspace.sqlite:layers` |
| CitationRecord | 某个 claim 与某条 evidence 的可点击引用绑定 | `workspace.sqlite:citation_records` |
| CitationAudit | 机器或审计工具对 citation 的独立 verdict | `workspace.sqlite:citation_audits` |

`workspace.sqlite` 只保存对象索引、路径和关系；证据 span 仍在 `evidence.sqlite`，逐句标注仍在 `annotation_layers.sqlite`。
Citation 的详细规则见 [`docs/citation-object-model.zh.md`](citation-object-model.zh.md)。

## CLI

创建或更新 Notebook：

```powershell
python -m scansci_html.cli notebook init `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --title "RAG 文献综述"
```

从 evidence store 同步 Source：

```powershell
python -m scansci_html.cli notebook sync-sources `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --evidence-db evidence.sqlite
```

登记 Note：

```powershell
python -m scansci_html.cli notebook add-note `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --title "GraphRAG 是否适合个人文献综述" `
  --text "GraphRAG 在多跳关系综述中有优势，但可能太慢。"
```

把已有 annotation layer 挂到 Notebook/Note：

```powershell
python -m scansci_html.cli notebook attach-layer `
  --workspace workspace.sqlite `
  --notebook-id rag_review `
  --layers annotation_layers.sqlite `
  --layer-id graph_rag_question `
  --note-id note_graph_rag
```

挂载 layer 时会自动同步 `supported` / `partial_support` citation records。查看 citation 对象：

```powershell
python -m scansci_html.cli notebook citations `
  --workspace workspace.sqlite `
  --notebook-id rag_review
```

查看工作台对象关系：

```powershell
python -m scansci_html.cli notebook summary `
  --workspace workspace.sqlite `
  --notebook-id rag_review
```

## Grounded Annotation 自动登记

`grounded-annotate` 现在可以直接写入 workspace：

```powershell
python -m scansci_html.cli grounded-annotate `
  --db evidence.sqlite `
  --text "GraphRAG 适合关系密集型综述，但成本较高。" `
  --layer-db annotation_layers.sqlite `
  --layer-id graph_rag_question `
  --layer-name "GraphRAG 成本判断" `
  --workspace workspace.sqlite `
  --notebook-id rag_review
```

如果没有传 `--note-id`，CLI 会自动创建一个 `grounded_draft` Note，并把新 Layer 挂到这个 Note 上。Layer 命中的 `doc_id` 会进入 `layer_sources`，因此可以追踪“这个问题用到了哪些论文”。

## 推荐工作流

1. `notebook init`：创建研究主题。
2. `index-v2`：从 clean HTML 生成 `evidence.sqlite`。
3. `notebook sync-sources`：把论文 Source 登记到 Notebook。
4. `notebook add-note` 或 `grounded-annotate --workspace`：登记问题/草稿。
5. `annotation-viewer`：在同一份 Source 上切换 Layer 做审阅。
6. `notebook citations`：查看 claim / citation / evidence 的稳定绑定。
7. `review-matrix --layers`：导出证据矩阵。
8. `review-apply`：把人工审阅状态回写到 Layer。
9. `review-matrix --template report|glossary|timeline|methods`：从已确认证据生成产物。

这样项目不再是散落的文件和命令，而是稳定对象图：

```text
Notebook
  -> Sources
  -> Notes
  -> Layers
  -> CitationRecords / CitationAudits
  -> Review Matrix / Transformations / Drafts
```
