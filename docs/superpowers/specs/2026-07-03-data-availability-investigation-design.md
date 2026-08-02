# Research Data Availability Investigation Layer 设计

## 背景

`scansci-html` 已经从单纯 HTML 保存工具演进为 evidence-first 文献工具链：capture 层负责合法获取 clean HTML，evidence 层负责生成可引用证据，RAG 与 annotation 层负责问答、标注、审阅和报告。

下一步要补的是“科研数据可得性侦查”能力：用户不是只想问论文正文，而是要回答一组可复现研究问题：

- 论文使用或发布的数据在哪里。
- 哪些数据有公开文件，哪些只有图表、补充材料或联系路径。
- 哪些站点、样本、变量、年份、方法、尺度和数据门户被论文证据支持。
- 最终能否导出一张可审阅、可追踪 provenance 的数据可得性矩阵。

这个能力必须保持通用，不绑定任何私人研究任务、具体数据集或未公开项目。私有任务只能作为本地验证用例，不进入公开文档、fixture、提交记录或默认样例。

## 目标

新增一个通用的 `data-investigation` 应用层，服务“从论文到数据可得性证据链”的项目工作流。

第一阶段目标：

- 从 clean HTML 中抽取结构化参考文献，覆盖 DOI 与无 DOI 文献。
- 识别并登记 supplementary、source data、repository、dataset DOI、文件链接和数据可得性声明。
- 导出 `references.csv`、`references.jsonl`、`artifacts.csv`、`data_availability.csv`。
- 为领域实体抽取和最终矩阵保留 schema 扩展点。
- 所有输出都带 `source_html_path`、`source_anchor`、`quote_or_text`、`confidence`、`review_state`。

第二阶段目标：

- 支持项目级 workspace，把 seed paper、参考文献、实体表、附件清单、可得性判断和人工审阅状态放进同一个对象图。
- 支持站点、样本、变量、年份、时间尺度等实体模板，并允许用户自定义领域 schema。
- 支持别名解析、地理近邻或属性校验等 matcher，但 matcher 输出默认是待审候选。
- 导出 `availability_matrix.csv`，每一行都能回指证据。

非目标：

- 不绕过付费墙、登录、embargo、robots 或机构访问限制。
- 不保存账号密码、cookie、token、MCP 接入点或机构凭据。
- 不默认下载 PDF、CAJ、原始数据库文件或大体积附件。
- 不把私有研究任务、具体验证任务或未公开数据追索线索写进仓库。
- 不让 LLM 直接把未审抽取结果写成 confirmed truth。

## 架构位置

该能力属于现有应用层和 workspace 层，不改变 capture 与 evidence 的核心契约。

```text
clean HTML
  -> references extractor
  -> artifact collector
  -> data availability parser
  -> domain entity extractor
  -> evidence-bound review tables
  -> availability matrix
```

现有 `evidence.sqlite` 仍然服务句子级 QA 与 citation。数据可得性侦查需要额外索引 back matter，因为 clean HTML 契约会把 `references`、`data_availability`、`supplementary`、`source_data` 从普通 QA 证据中排除。这个排除对问答是正确的，但对数据追索需要并行的专门抽取器。

建议新增模块：

| 模块 | 作用 |
|---|---|
| `data_investigation.py` | 编排单篇或项目级数据侦查流程 |
| `references.py` | 结构化参考文献抽取，逐步替代或包住现有 `citations.py` |
| `artifacts.py` | supplementary/source data/repository/file link 识别与登记 |
| `data_availability.py` | 数据可得性声明解析与状态分类 |
| `domain_schema.py` | 通用实体 schema 与领域 profile 定义 |
| `entity_resolution.py` | 别名、坐标、属性、同名冲突等候选匹配 |
| `availability_matrix.py` | 证据矩阵构建与 CSV/JSONL 导出 |

`citations.py` 可以先保留为兼容 API，但新能力应输出更完整的 `ReferenceRecord`，而不是只输出 DOI candidate。

## 对象模型

### InvestigationProject

项目级对象记录在 `workspace.sqlite` 或后续 `investigation.sqlite` 中。第一版可以先用文件目录 + manifest，等 schema 稳定后并入 workspace。

关键字段：

| 字段 | 含义 |
|---|---|
| `project_id` | 本地稳定 ID |
| `title` | 用户给项目的通用标题 |
| `root_path` | 项目目录 |
| `seed_sources` | 初始论文或文献集合 |
| `schema_profile` | 使用的领域 schema，如 `generic`, `ec_flux`, `clinical_trial` |
| `created_at` / `updated_at` | 本地时间戳 |
| `metadata_json` | 用户自定义元数据，不写凭据 |

### ReferenceRecord

参考文献抽取结果。支持 DOI 文献、无 DOI 英文文献、中文文献和不完整条目。

字段：

| 字段 | 含义 |
|---|---|
| `reference_id` | `source_doc_id + reference_anchor` 派生的稳定 ID |
| `source_doc_id` | 引用它的论文 |
| `source_html_path` | clean HTML 路径 |
| `source_anchor` | 参考文献条目锚点 |
| `raw_text` | 原始参考文献文本 |
| `doi` | 规范 DOI，可为空 |
| `title` | 题名候选 |
| `authors` | 作者字符串或 JSON list |
| `year` | 年份候选 |
| `venue` | 期刊/会议/数据库/出版社候选 |
| `language` | `en`, `zh`, `unknown` |
| `record_type` | `dataset_paper`, `station_study`, `method_paper`, `review`, `unknown` |
| `confidence` | 规则或模型置信度 |
| `review_state` | `unreviewed`, `confirmed`, `rejected`, `corrected` |

第一版只需要稳定抽取 `raw_text`、`doi`、`title/year` 的候选和 anchor。类型分类可先用规则词表与待审状态。

### ArtifactRecord

论文相关附件和外部数据对象登记。它记录“看到了什么、能不能访问、是否已下载元数据或小文件”，不默认下载大数据。

字段：

| 字段 | 含义 |
|---|---|
| `artifact_id` | 稳定 ID |
| `source_doc_id` | 所属论文 |
| `source_html_path` | clean HTML 路径 |
| `source_anchor` | 链接或声明所在锚点 |
| `label` | 页面显示文本 |
| `url` | 清洗后的 URL |
| `doi` | artifact 或 repository DOI，可为空 |
| `repository` | `figshare`, `zenodo`, `sciencedb`, `dryad`, `osf`, `publisher`, `unknown` |
| `artifact_type` | `supplementary_pdf`, `xlsx`, `zip`, `source_data`, `dataset_record`, `code`, `unknown` |
| `content_type` | HTTP Content-Type 或页面推断 |
| `size_bytes` | 可合法探测到时记录 |
| `license` | 页面可见 license 文本或 URL |
| `access_status` | `available`, `metadata_only`, `by_request`, `embargoed`, `paywalled`, `broken`, `unknown` |
| `downloaded_path` | 显式下载的小附件路径，可为空 |
| `checked_at` | 检查日期 |
| `review_state` | 人工审阅状态 |

附件采集应分两层：

- `discover`：只从 HTML 和公开页面识别链接、仓库、DOI、文件类型。
- `collect`：用户显式开启时下载小体积附件，并写入大小、hash、sheet/table 索引。

### DataAvailabilityRecord

每篇论文至少生成一条数据可得性判断。

字段：

| 字段 | 含义 |
|---|---|
| `availability_id` | 稳定 ID |
| `source_doc_id` | 论文 ID |
| `statement_text` | 数据可得性声明原文 |
| `source_html_path` | clean HTML 路径 |
| `source_anchor` | 声明锚点 |
| `availability_status` | `yes`, `no`, `by_request`, `contact_author`, `embargoed`, `not_applicable`, `unknown` |
| `repository` | 仓库或门户 |
| `url` | 数据链接 |
| `doi` | 数据 DOI |
| `license` | license 候选 |
| `files_available` | 是否观测到可下载文件 |
| `evidence_level` | `statement_only`, `metadata_page`, `file_listing`, `download_verified` |
| `confidence` | 置信度 |
| `review_state` | 人工审阅状态 |

`download_verified` 只表示工具在合法访问范围内确认文件可下，不表示数据内容完整或科学质量可靠。

### EntityObservation

领域实体抽取的统一记录。它不限定学科，但支持 profile。

字段：

| 字段 | 含义 |
|---|---|
| `entity_id` | 稳定 ID |
| `source_doc_id` | 来源论文 |
| `entity_type` | `site`, `sample`, `variable`, `year`, `method`, `instrument`, `repository`, `dataset` 等 |
| `canonical_name` | 规范名候选 |
| `surface_text` | 原文表述 |
| `aliases_json` | 别名候选 |
| `attributes_json` | 经纬度、年份、变量、时间尺度等 profile 字段 |
| `source_html_path` | clean HTML 路径 |
| `source_anchor` | 证据锚点 |
| `quote_snapshot` | 原文 quote |
| `confidence` | 置信度 |
| `review_state` | 人工审阅状态 |

领域 profile 只定义字段和词表，不把任何私人任务的实体清单提交到仓库。

### AvailabilityMatrixRow

最终矩阵是派生产物，不是权威原始库。每行必须能回指 ReferenceRecord、ArtifactRecord、DataAvailabilityRecord 或 EntityObservation。

通用字段：

| 字段 | 含义 |
|---|---|
| `subject` | 站点/样本/队列/区域/对象等通用主体 |
| `year` | 年份或时间范围 |
| `variable` | 变量或指标 |
| `resolution` | 时间/空间/实验尺度 |
| `value_available` | 论文或图表中是否有可恢复值 |
| `raw_data_available` | 原始或高分辨率数据是否可得 |
| `access_status` | 可得性状态 |
| `source` | 论文、仓库或附件 |
| `evidence_ids` | 证据记录 ID 列表 |
| `provenance` | `table`, `figure`, `supplement`, `repository`, `statement`, `author_contact` |
| `review_state` | 人工审阅状态 |

## CLI 设计

新增分层命令建议挂在 `scansci investigate` 下。也可以保留扁平别名，但文档优先使用分层命令。

### 初始化项目

```powershell
scansci investigate init `
  --project-dir .\data-investigation `
  --title "Research data availability review" `
  --schema-profile generic
```

输出：

- `investigation.manifest.json`
- `inputs/`
- `outputs/`
- `artifacts/`
- `review/`

### 抽取参考文献

```powershell
scansci investigate references `
  --html .\html-papers\paper.html `
  --output .\outputs\references.csv `
  --jsonl-output .\outputs\references.jsonl
```

第一版也应支持目录：

```powershell
scansci investigate references `
  --library-dir .\html-papers `
  --output .\outputs\references.csv `
  --jsonl-output .\outputs\references.jsonl
```

### 收集附件与外部数据对象

```powershell
scansci investigate artifacts `
  --library-dir .\html-papers `
  --output .\outputs\artifacts.csv `
  --jsonl-output .\outputs\artifacts.jsonl
```

显式下载小附件：

```powershell
scansci investigate artifacts `
  --library-dir .\html-papers `
  --output .\outputs\artifacts.csv `
  --download-small-files `
  --max-file-mb 25
```

下载策略：

- 默认只识别，不下载。
- 只下载用户已有合法访问下的 URL。
- 不保存请求头、cookie、token 或带凭据的临时 URL。
- 对 xlsx 只读取 workbook metadata、sheet 名、列名和前几行结构，不把大表内容塞进 manifest。
- 对 PDF 第一版只记录文件与可检索索引状态，表格抽取后置。

### 解析数据可得性

```powershell
scansci investigate availability `
  --library-dir .\html-papers `
  --artifacts .\outputs\artifacts.jsonl `
  --output .\outputs\data_availability.csv `
  --jsonl-output .\outputs\data_availability.jsonl
```

### 抽取领域实体

```powershell
scansci investigate entities `
  --library-dir .\html-papers `
  --schema-profile generic `
  --output .\outputs\entity_observations.csv `
  --jsonl-output .\outputs\entity_observations.jsonl
```

领域 profile 是可选输入：

```powershell
scansci investigate entities `
  --library-dir .\html-papers `
  --schema-profile .\profiles\custom-schema.json `
  --output .\outputs\entity_observations.csv
```

### 生成可得性矩阵

```powershell
scansci investigate matrix `
  --references .\outputs\references.jsonl `
  --artifacts .\outputs\artifacts.jsonl `
  --availability .\outputs\data_availability.jsonl `
  --entities .\outputs\entity_observations.jsonl `
  --output .\outputs\availability_matrix.csv `
  --jsonl-output .\outputs\availability_matrix.jsonl
```

矩阵生成默认保守：

- 没有证据的格子不填 confirmed。
- 冲突证据进入 `needs_review`。
- 只有声明没有文件列表时，`evidence_level=statement_only`。
- 从图表或文字推断出的值必须标注 provenance，不冒充原始数据。

## 抽取策略

### 参考文献

优先级：

1. 结构化 HTML：`section`、`ol/li`、`role=doc-biblioentry`、JATS 转换后的 ref list。
2. DOI 链接与 DOI 文本。
3. citation meta 与 schema.org JSON-LD。
4. 无 DOI 条目的启发式解析：年份、题名、作者、期刊。
5. 中文参考文献：中文标点、中文题名、英文刊名混排、缺 DOI title matching 候选。

不确定字段保留为空或候选，不造数据。

### Artifact 发现

识别来源：

- 链接文本：Supplementary Information、Source Data、Extended Data、Data availability、Supporting Information。
- URL 和域名：figshare、zenodo、dryad、osf、github、science data portals、publisher asset paths。
- 文件扩展名：xlsx、xls、csv、zip、pdf、docx、txt、nc、hdf、rds。
- DOI：数据 DOI、repository DOI、Crossref relation。
- Publisher XML/JATS 中的 supplementary-material 与 ext-link。

### 数据可得性解析

规则优先，模型后置：

- 明确公开：`available at`, `deposited in`, `can be accessed`, 数据 DOI。
- 按请求：`available from the corresponding author`, `upon reasonable request`。
- 限制：`embargo`, `restricted`, `not publicly available`, `privacy`, `license restrictions`。
- 不适用：`no datasets were generated or analysed`。
- 模糊：没有声明或声明与文件列表冲突，标 `unknown` 或 `needs_review`。

解析结果必须保留原文声明，不只保留标签。

### 领域 schema

内置 `generic` profile：

| 类型 | 字段 |
|---|---|
| `site` | name, alias, latitude, longitude, elevation, region, ecosystem_or_domain |
| `sample` | name, cohort, material, organism_or_domain, location |
| `variable` | name, unit, temporal_resolution, spatial_resolution |
| `method` | name, software, instrument, processing_step |
| `dataset` | name, doi, repository, license, access_status |
| `period` | start_year, end_year, date_range |

领域专用 profile 可以扩展这些字段，但不得在仓库默认 profile 中包含私人任务实体清单。

### Entity resolution

第一版只产生候选匹配：

- exact normalized name。
- case-folding、标点清洗、空格/连字符变体。
- 用户提供 alias table。
- 坐标距离或属性一致性校验。
- 同名冲突标记。

匹配状态：

- `candidate`
- `likely_match`
- `conflict`
- `confirmed`
- `rejected`

只有人工确认或显式规则确认后才进入矩阵的 canonical 维度。

## 数据存储与文件布局

推荐项目目录：

```text
data-investigation/
  investigation.manifest.json
  inputs/
    seed_sources.csv
    alias_table.csv
    schema-profile.json
  outputs/
    references.csv
    references.jsonl
    artifacts.csv
    artifacts.jsonl
    data_availability.csv
    data_availability.jsonl
    entity_observations.csv
    entity_observations.jsonl
    availability_matrix.csv
    availability_matrix.jsonl
  artifacts/
    downloaded/
    indexes/
  review/
    conflicts.csv
    corrections.csv
```

CSV 面向人工审阅，JSONL 面向稳定机器接口。SQLite 可以在第二阶段加入：

```text
investigation.sqlite
  reference_records
  artifact_records
  data_availability_records
  entity_observations
  entity_matches
  matrix_rows
  review_events
```

## 合规与隐私

文档、日志、fixture 和提交必须遵守：

- 不写账号密码、cookie、token、临时签名 URL、MCP 接入点或机构凭据。
- 不提交私人研究任务名、未公开站点清单、手工追索路径或用户身份线索。
- 对私有项目只使用本地目录和本地 manifest。
- 对付费墙和 embargo 数据只记录状态、声明、联系人路径或仓库元数据。
- 下载动作必须由用户显式开启，并限制文件大小。
- 报告中区分“声明可得”“元数据页可见”“文件列表可见”“文件下载已验证”。

## 测试策略

P0 测试：

- Nature/Springer 风格参考文献 DOM：抽 DOI、anchor、raw text。
- 无 DOI 英文文献：抽题名、年份候选。
- 中文参考文献：保留中文题名和 raw text，不因缺 DOI 丢弃。
- Supplementary/source data 链接：识别 artifact type、URL、label。
- Data availability 声明：分类 public/by request/embargo/no data/unknown。
- CSV/JSONL 字段稳定性。
- 不把正文里的 DOI 误当参考文献 DOI。
- 不把带 `token=`、`invoice=`、`nonce=` 的 URL 写入输出。

P1 测试：

- xlsx 小附件 sheet/column metadata。
- repository metadata page parser。
- alias table 匹配与冲突检测。
- matrix 行保留证据 ID 和 provenance。

## 迁移路线

### P0

- 新增 `ReferenceRecord`，增强现有 `references` 能力。
- 新增 artifact discovery，不默认下载。
- 新增 data availability parser。
- CLI 输出 `references.csv/jsonl`、`artifacts.csv/jsonl`、`data_availability.csv/jsonl`。
- README 增加简短入口，详细说明留在本设计文档或后续用户指南。

### P1

- 新增 `investigate init` 项目目录。
- 新增 generic domain schema 与 entity observations。
- 新增 alias table matcher。
- 新增 `availability_matrix.csv/jsonl`。
- 加入 review 状态和 conflict export。

### P2

- SQLite investigation store。
- 更多 repository adapter。
- PDF/figure digitization task queue。
- Web review UI。
- 用户自定义 schema/profile 的验证器。

## 验收标准

第一版完成时，用户可以在不暴露私人任务信息的前提下，对任意一批 clean HTML 运行：

```powershell
scansci investigate references --library-dir .\html-papers --output .\outputs\references.csv
scansci investigate artifacts --library-dir .\html-papers --output .\outputs\artifacts.csv
scansci investigate availability --library-dir .\html-papers --output .\outputs\data_availability.csv
```

并得到：

- 每条参考文献有原文、来源论文、anchor、DOI 或无 DOI 候选字段。
- 每个附件/外部数据对象有 URL、类型、访问状态和检查时间。
- 每篇论文有结构化数据可得性判断和原文声明。
- 所有行默认 `review_state=unreviewed`。
- 输出不包含凭据、临时 token 或私人项目线索。

第二版完成时，用户可以把这些记录合成为一个可审阅矩阵，并追踪每个格子的 evidence provenance。
