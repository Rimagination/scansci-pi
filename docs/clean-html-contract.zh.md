# Clean HTML 契约

本文定义 ScanSci capture 层的统一输出契约。不同出版社、数据库、XML/JATS/API、浏览器或 `paper-fetch-provider` 可以有不同获取配方，但它们最后都必须产出同一种可索引、可审计、可引用的 clean HTML。

## 核心判断

ScanSci 采用的是：

```text
一套统一 clean HTML 契约 + 多个来源/出版社配方
```

不是：

```text
每个出版社一种最终 HTML 格式
```

来源配方负责解决“怎么拿到正文”和“怎么把来源结构转成统一结构”。统一契约负责决定“什么才算可以进入本地文献库和 evidence store”。

## 目标产物

成功保存的主产物是一个离线可读的 `.html` 文件。它应满足：

- 保存的是可合法访问的论文正文，不是 PDF、Markdown、cookie、token、登录态或下载缓存。
- 人可以直接打开阅读。
- 机器可以稳定抽取句子级证据、表格行、图表 caption 和来源元数据。
- 同一篇文章后续可以被 `index-v2`、`evidence-doctor`、`search-v2`、`ask`、`review-matrix` 和 `bench` 复用。

默认不要求每篇论文都保存 PDF、Markdown、原始 provider 缓存或全部图片资产。图片可按当前 `fetch` 默认策略本地化，也可用 `--no-download-assets` 保留远程 URL。

## 最小结构

clean HTML 必须尽量归一成：

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Paper title</title>
  </head>
  <body>
    <article class="paper"
      data-doi="10.xxxx/example"
      data-source-url="https://publisher.example/article"
      data-publication-year="2026">
      <h1>Paper title</h1>
      <section>
        <h2>Abstract</h2>
        <p>...</p>
      </section>
      <section>
        <h2>Results</h2>
        <p id="results-p1">...</p>
      </section>
    </article>
  </body>
</html>
```

`article.paper` 是首选根。`extract_evidence_spans()` 会优先读取 `article.paper`，退化时才读取普通 `article` 或 `body`。

## 元数据

应尽量提供：

- `data-doi`：规范 DOI。用于稳定 `doc_id`。
- `data-source-url`：实际来源页面或 provider landing page。用于追溯。
- `data-publication-year`：能确定年份时写入。用于 `--year-min` 等过滤。
- `<title>` 或 `<h1>`：文献标题。
- citation/date meta：如 `citation_title`、`citation_doi`、`citation_publication_date`。不是必须，但有助于结构恢复。

如果 DOI 缺失，`evidence_spans` 会用 `data-source-url` 或文件名生成 `doc_id`。这可以工作，但不如 DOI 稳定。

## 允许内容块

证据抽取层当前稳定读取这些块：

- `p`：段落，会按句子切分。
- `figcaption` / `caption`：图表 caption，作为一个证据块。
- `tr`：表格行，作为一个证据块。
- `h1`-`h6`：章节层级和 section kind 判断。

因此，配方转换时要优先保留这些语义标签，而不是把所有正文塞进一个长 `div`、`pre` 或 Markdown 字符串。

推荐：

```html
<section>
  <h2>Methods</h2>
  <p>...</p>
  <table>
    <thead>...</thead>
    <tbody>
      <tr><td>...</td></tr>
    </tbody>
  </table>
  <figure>
    <figcaption>...</figcaption>
  </figure>
</section>
```

不推荐：

```html
<div>## Methods

All paragraphs and tables copied as raw markdown...</div>
```

## 章节语义

章节名会被归一为 `section_kind`。当前内容证据优先包括：

- `abstract`
- `introduction`
- `methods`
- `results`
- `discussion`
- `conclusion`

当前非证据 back matter 会被跳过：

- `references`
- `authors`
- `contributions`
- `acknowledgements`
- `funding`
- `data_availability`
- `declarations`
- `article_metadata`
- `supplementary`
- `source_data`

因此，配方应保留真实章节标题，不要把所有内容统一改成 `Body`。如果 XML/JATS 有明确 section kind，可以用接近原文的标题映射到 `h2/h3`。

## 表格与图注

表格最好保留为 HTML 表格：

- `table`
- `thead`
- `tbody`
- `tr`
- `th`
- `td`

`evidence_spans` 会把 `tr` 当作 `table_row` 证据。表格如果只有图片或复杂排版，也至少应保留 caption，让系统能检索到表格说明。

图像不一定必须下载，但图注应保留：

```html
<figure>
  <figcaption>Figure 1. Treatment increased biomass under drought.</figcaption>
</figure>
```

## 属性与噪声

cleaner 会删除或弱化这些噪声：

- `script`
- `style`
- `noscript`
- `svg`
- `canvas`
- `iframe`
- `form`
- `nav`
- `footer`
- `header`
- `aside`
- `button`
- `input`
- `select`
- `textarea`

通用 HTML 清洗只保留少量属性：

- 全局：`id`、`lang`
- `a`：`href`、`title`
- `img`：`src`、`alt`、`title`、`width`、`height`
- `table`：`summary`
- `th` / `td`：`colspan`、`rowspan`、`scope`
- `ol`：`start`

来源配方不应依赖 publisher 原始 class 名作为下游检索依据。class 可以帮助上游抓取，但保存后的证据契约依赖语义标签和 `data-*` 元数据。

## 全文判定

clean HTML 不能只看 HTTP 200、标题、摘要、长文本或参考文献数量。保存前必须通过全文形态检查。

常见阻断信号：

- 正文短于 `min_text_length`。
- 页面包含 access/paywall markers，且没有正文形态。
- `subscription preview`。
- Science/AAAS 页面仍是 access gate 或 references collapsed 状态。
- Wiley abstract page 被误抓为全文页。
- 页面有登录、机构选择、购买、租赁、推荐文章等信号但缺少 body sections。

`article_structure.blocking_warnings()` 当前会阻断：

- 有 access gate marker 但没有 body sections。
- 有 collapsed references marker。

保存结果必须能解释结构证据：`SaveResult.structure` 会报告 section count、body/endmatter presence、figure/image/table/reference counts、access markers 和 collapsed-reference markers。

## 统一来源链

默认 `fetch` / `batch` 不要求用户选择配方。source chain 负责依次尝试：

1. `pmc-jats`
2. `elsevier-xml`，有 Elsevier key 时启用
3. `crossref-fulltext-xml`
4. `wiley-full-xml`，有 Wiley TDM token 时启用
5. `springer-openaccess-jats`，有 Springer Nature key 时启用
6. `paper-fetch-provider`
7. 普通 publisher HTML preflight
8. 可见浏览器 / auth browser fallback

各来源的输出都应走同一条 `FetchResponse -> CleanHtmlRenderer / structured HTML -> save_clean_html -> index-v2` 语义边界。

## 来源配方边界

来源配方可以不同，最终契约必须相同。

配方可以做：

- DOI/URL/title 解析。
- publisher route 选择。
- 官方 XML/JATS/API 获取。
- 浏览器页面准备，例如展开 collapsed references。
- XML/JATS/ArticleModel 到 HTML 的结构转换。
- 表格、图注、章节、引用的语义恢复。

配方不应做：

- 绕过 access control。
- 默认下载 PDF 作为主产物。
- 把 Markdown 当作 source of truth。
- 保存账号、密码、cookie、token、机构凭据。
- 让下游 evidence store 依赖 publisher 专属 class 名。
- 把摘要页、参考文献页、登录页伪装成全文。

## Paper-Fetch Provider 的定位

`paper-fetch-provider` 借用 paper-fetch-skill 的 provider route 和 `ArticleModel` 转换经验，但在 ScanSci 内部它只是一个 source fetcher。

它的职责：

- 调用 paper-fetch runtime 获取 `ArticleModel`。
- 把 metadata、sections、assets captions、references 转成 ScanSci clean HTML 契约。
- 默认 `artifact-mode=none`、`asset-profile=none`，避免落下大体积中间产物。
- 如果只得到 `abstract_only` 或 `metadata_only`，抛出 unavailable，让主流程继续尝试下一条路径。

它不负责：

- 替代 `fetch` / `batch`。
- 替代 evidence store、retrieval、rerank、ask、review。
- 引入另一个独立文件格式作为下游检索标准。

## 验收清单

新增来源或出版社配方时，至少检查：

- 是否产出 `<article class="paper">`。
- 是否保留标题、DOI、source URL、publication year。
- 是否有真实 body sections，不只是 abstract/back matter。
- `extract_article_structure()` 是否显示 `has_body=true`。
- access markers 是否不会被误判为全文。
- references collapsed 控件是否已展开或被阻断。
- `extract_evidence_spans()` 是否能抽出 `paragraph`、`caption` 或 `table_row`。
- `index-v2 --inject-evidence-html` 后 `evidence-doctor` 是否通过。
- 同一 DOI 重复文件是否不会污染多文档证据计数。
- 不保存 PDF、Markdown、cookie、token 或机构凭据作为默认主产物。

推荐回归命令：

```powershell
pytest tests -q
```

对具体文献库：

```powershell
scansci index-v2 `
  --library-dir .\html-papers `
  --db .\html-papers\evidence.sqlite `
  --inject-evidence-html

scansci evidence-doctor --db .\html-papers\evidence.sqlite
```

## 代码位置

- `src/scansci_html/cleaner.py`：通用 HTML 清洗和全文可用性初判。
- `src/scansci_html/article_structure.py`：结构摘要与阻断 warning。
- `src/scansci_html/evidence_spans.py`：句子级证据抽取契约。
- `src/scansci_html/official_sources.py`：官方 XML/JATS/API source chain。
- `src/scansci_html/paper_fetch_source.py`：paper-fetch `ArticleModel` 到统一 HTML 契约的转换。
- `src/scansci_html/service.py`：source fetchers、HTTP/browser fallback、保存与 snapshot 编排。

