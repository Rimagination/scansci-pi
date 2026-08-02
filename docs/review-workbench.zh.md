# ScanSci Evidence Review Workbench

本文记录 grounded annotation、review matrix、transformation templates 和 evidence-bound 草稿之间的闭环。

对象层说明见 [`docs/notebook-object-model.zh.md`](notebook-object-model.zh.md)。`workspace.sqlite` 负责登记 Notebook、Source、Note、Layer 的身份和关系；`evidence.sqlite` 与 `annotation_layers.sqlite` 仍分别保存证据和软标注明细。

## 目标

ScanSci 的综述产物必须从可审计证据生成，而不是从 loose chunks 直接生成。当前工作流是：

```text
grounded annotation layer -> review matrix -> human review state -> transformation/report draft
```

默认只让 `supported` / `partial_support` 进入矩阵和展示层；`weak_candidate` 仍可保存在原始诊断数据中，但不会进入正式综述输出。用于最终产物的已确认状态是 `confirmed`、`approved`、`verified`。

## Evidence-Bound 综述矩阵

从 annotation layer SQLite 导出：

```powershell
python -m scansci_html.cli review-matrix `
  --layers annotation_layers.sqlite `
  --output review-matrix.csv `
  --format csv
```

从一个或多个 `ask` JSON 报告导出仍然兼容：

```powershell
python -m scansci_html.cli review-matrix `
  --report ask-report.json `
  --output review-matrix.html `
  --format html
```

矩阵保留 `layer_id`、`item_id`、`review_state`、`claim_text`、`exact_quote`、`paper`、`doi`、`section`、`publication_year`、`evidence_id`、`html_path`、`html_anchor` 和 `source_href`。这些字段足够把任何综述行追溯回原文锚点。

## 双向打通

人工审阅矩阵时，把 `review_state` 改成：

- `confirmed`：证据可用于报告、综述、术语表等产物。
- `rejected`：证据不应使用。
- `needs_evidence`：结论可能有价值，但当前证据不足。
- `unreviewed`：尚未审阅。

回写到软标注层：

```powershell
python -m scansci_html.cli review-apply `
  --layers annotation_layers.sqlite `
  --review reviewed-matrix.csv
```

回写后，`annotation-viewer` 和后续 `review-matrix --template ...` 会读取同一个 layer DB 中的审阅状态，不需要为每个问题生成新的 HTML 文件。

## Transformation 模板

已实现的模板：

- `glossary`：术语表/主题表。
- `timeline`：按年份排序的证据时间线。
- `methods`：方法/场景/证据对比表。
- `report`：从已确认证据生成综述草稿。

示例：

```powershell
python -m scansci_html.cli review-matrix `
  --layers annotation_layers.sqlite `
  --template glossary `
  --output glossary.md

python -m scansci_html.cli review-matrix `
  --layers annotation_layers.sqlite `
  --template timeline `
  --output timeline.md

python -m scansci_html.cli review-matrix `
  --layers annotation_layers.sqlite `
  --template methods `
  --output methods.md

python -m scansci_html.cli review-matrix `
  --layers annotation_layers.sqlite `
  --template report `
  --output review-draft.md
```

当输入行包含 `review_state` 时，模板默认只使用 `confirmed` / `approved` / `verified`。如果输入来自旧的 `ask` JSON 报告且没有审阅状态，模板会使用全部传入证据行。

## 推荐闭环

1. 用 `grounded-annotate --layer-db annotation_layers.sqlite` 把草稿或研究问题保存为软标注层。
2. 用 `annotation-viewer` 在干净原文上审阅证据。
3. 用 `review-matrix --layers ... --format csv` 导出审阅表。
4. 在 CSV 中确认或驳回证据，修改 `review_state`。
5. 用 `review-apply` 回写审阅状态。
6. 用 `review-matrix --template report|glossary|timeline|methods` 从已确认证据生成综述产物。

如果还没有本地 acceptance set，可以先运行：

```powershell
scansci bench acceptance `
  --db .\html-papers\evidence.sqlite `
  --output-dir .\bench\local-acceptance-workbench `
  --questions-per-type 2
```

这个 starter 会同时生成待人工确认的 gold 模板和 `review-draft.template.md`。前者用于 benchmark gate，后者用于 `scansci annotate ground` 跑通 grounded annotation -> annotation viewer -> review matrix 的审阅闭环。
