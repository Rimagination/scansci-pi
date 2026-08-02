# NotebookLM-like 项目借鉴备忘录

调研日期：2026-07-02

官方产品复核：2026-07-22

本文记录从 GitHub 上类 NotebookLM 项目中可以吸收的设计优点。结论不是把 ScanSci 改成通用文档聊天工具，而是在保持 `HTML/evidence-first` 边界的前提下，借鉴它们在产品组织、证据交互和研究产物生成上的优点。

## 总体判断

ScanSci 应学习 NotebookLM-like 项目的“用户体验层”，不要照搬它们的通用 RAG 底座。

这些项目普遍擅长：

- 把资料组织成 notebook / source / note / chat。
- 支持多种输入源和多模型配置。
- 把问答、引用、笔记、报告、播客、PPT 等整合成一个研究工作台。
- 给用户可点击的来源和文档预览。

但它们多数仍是通用文档 RAG：上传 PDF/网页/文本，切块，embedding，聊天。ScanSci 的优势和约束更窄也更硬：面向学术文献，长期母本是 clean HTML / XML，核心中间物是 evidence span、quote、source anchor 和可验证证据表。

## 项目观察

| 项目 | 主要优点 | ScanSci 应吸收什么 | 不应照搬什么 |
|---|---|---|---|
| [Open Notebook](https://github.com/lfnovo/open-notebook) | 多 notebook、多 source、笔记、搜索、聊天、内容转换、播客、多模型、自托管/本地部署 | 借鉴 notebook/source/note/action 的产品组织；把综述、问答、标注、报告做成统一工作台 | 不把 ScanSci 变成泛内容管理器；不牺牲 evidence-first 证据链 |
| [SurfSense](https://github.com/MODSetter/SurfSense) | connector 同步、hybrid search、带引用聊天、报告生成、播客、PPT/视频、Obsidian/本地文件夹同步 | 借鉴 “deliverable studio”：综述报告、证据矩阵、导出格式、Obsidian/本地知识库同步 | 不优先做企业协作、Slack/Notion/Gmail 连接器；这些会稀释文献核心 |
| [Cite](https://github.com/feRpicoral/cite) | inline citation + 同步文档 viewer；点击引用后右侧文档滚动到精确区域并高亮 | 继续强化我们的 annotation viewer：citation 点击、source card、原文定位、软标注层切换 | 不依赖 PDF 页级坐标作为主坐标；ScanSci 仍以 HTML anchor 为主 |
| [Insights LM](https://github.com/theaiautomators/insights-lm-public) | 自托管、文档聊天、可验证引用、音频摘要，基于 Supabase/n8n 编排 | 借鉴“可验证引用 + 自动化工作流”的产品路径；后续可把批处理和导出接入工作流 | 不引入 n8n/Supabase 作为核心依赖 |
| [Notex](https://github.com/smallnest/notex) | 多源输入、问答、摘要、FAQ、学习指南、时间线、术语表、测验、思维导图、播客脚本 | 借鉴 transformation 库：从同一证据层生成 FAQ、术语表、时间线、比较表、综述提纲 | 不让生成物绕过 evidence table；每个事实性输出仍需证据 |
| [notebooklm-py](https://github.com/teng-lin/notebooklm-py) | 自动化真实 NotebookLM：批量导入、提问、生成报告/音频/表格/思维导图 | 作为外部对照和灵感来源；可用来观察 NotebookLM 的信息架构和产物类型 | 不依赖非官方 Google 内部 API 作为 ScanSci 核心路径 |
| [Podcastfy](https://github.com/souzatharsis/podcastfy) | 复刻 NotebookLM audio overview / podcast 功能 | 可作为“音频综述”模块的未来参考 | 音频不是当前文献证据质量的核心，应排在证据工作台之后 |

## 可吸收的产品模式

### 1. Notebook / Source / Note / Layer 四对象

当前 ScanSci 已有 `paper.html`、`evidence.sqlite`、`annotation_layers.sqlite`，但用户心智还偏命令行。可以借鉴 Open Notebook 的组织方式，把上层对象明确化：

| 对象 | ScanSci 对应物 | 作用 |
|---|---|---|
| Notebook | 学科文献库 / 项目库 | 一个研究主题下的文献集合、问题、综述产物 |
| Source | clean HTML/XML 论文 | 可信来源，不是随便上传的文件 |
| Evidence | `evidence.sqlite` 中的 span/table/caption | 机器可检索、可引用、可审计的最小证据 |
| Note | 人类笔记、综述草稿、问题清单 | 可被 grounded annotation 逐句校验 |
| Layer | `annotation_layers.sqlite` | 同一原文上的不同问题、综述角度、人工审阅结果 |

近期可落地：

- 在文档和 CLI 摘要中统一使用“文献库 / source / evidence / note / layer”术语。
- viewer 的标题区显示 notebook/source/layer 关系，而不只是文件路径。

### 2. Source-grounded viewer 是核心体验

Cite 和 SurfSense 都强调点击引用后打开源文档并定位。ScanSci 已经有 `annotation-viewer.html`，下一步应把它做得更像研究工作台：

- 左侧/主区：干净原文，默认不显示全局高亮。
- 右侧：当前问题或综述草稿的 source cards。
- 点击 citation：滚动到 `html_anchor`，只高亮当前证据。
- 切换 layer：同一原文换不同标注视角。
- 弱证据默认不展示，只显示 `supported` / `partial_support`。

这比“生成一份带满页角标的新 HTML”更接近 NotebookLM 的体验，也更符合学术证据审计。

### 2.1. 从 Cite 追加吸收的 citation 对象层

2026-07-02 进一步阅读 `feRpicoral/cite` 后，最值得吸收的不是它的 SaaS 技术栈，而是它把 citation fidelity 做成核心对象：

- `DocumentLocation` 不是普通 URL，而是 PDF bbox 或 HTML selector/offset。
- `MessageCitation` 保存引用编号、quote snapshot 和 chunk 关系。
- `CitationAudit` 单独保存审计 verdict、reasoning 和 confidence。
- agent state 记录 classify、decompose、retrieve、sufficiency 等 trace，便于重放和审计。

ScanSci 已落地本地化版本：`workspace.sqlite` 增加 `citation_records` 与 `citation_audits`。当前第一版 `source_location` 使用 `html_anchor`，未来可扩展到 DOM selector + char offset；机器审计和人工 `review_state` 分开，避免把模型判断误当成人工确认。

### 3. Deliverable Studio：产物从证据表生成

SurfSense 和 Open Notebook 的强项是把同一份资料转成报告、播客、PPT、笔记等产物。ScanSci 可以吸收这个思路，但必须约束为：

```text
evidence table -> review matrix -> grounded draft -> export
```

而不是：

```text
retrieved chunks -> LLM free generation -> pretty report
```

适合 ScanSci 的第一批产物：

- 证据矩阵：主题 / 方法 / 结果 / 限制 / 原文 quote / DOI / section。
- 综述提纲：每个小节绑定证据集合。
- 术语表：术语、定义、证据句、出现论文。
- 时间线：研究进展、年份、方法、证据。
- 对比表：方法、数据集、指标、优缺点、证据。

音频概览、PPT、视频可以后置，因为它们依赖前面的证据结构质量。

### 4. 多模型配置只服务组件角色

Open Notebook 和 SurfSense 都支持多模型。ScanSci 也需要多模型，但不能让“模型列表”主导架构。模型必须绑定角色：

| 角色 | 可替换组件 |
|---|---|
| embedding | dense recall |
| reranker | 证据排序 |
| LLM planner | query rewrite / multi-query |
| LLM synthesizer | 证据表到答案/综述 |
| verifier | claim-evidence 支持判断 |
| extractor | 实体、关系、实验设置、结果抽取 |

任何新模型都要说清楚替代哪个角色，并进入 benchmark 或 smoke test。不要因为模型大或新就替代 MiniLM-Rerank 这类强基线。

### 5. Local-first 和 self-hosted 是默认姿态

多个项目都强调 privacy-first / self-hosted / local-first。ScanSci 的本地边界更严格：

- 文献原文、证据库、标注层默认本地。
- API LLM 可用于生成和判断，但不能把凭据、cookie、机构登录态写入文档或日志。
- HTML/XML 是长期母本；PDF/Markdown 是 fallback 或导出，不作为核心证据链。

## 不应照搬的部分

- 不把上传任意文件作为主流程；ScanSci 先服务学术文献库。
- 不以 PDF 为主坐标系；PDF 只在没有 HTML/XML 时 fallback。
- 不把音频/PPT/视频放到证据质量之前。
- 不做企业协作和全连接器平台，除非文献库核心流程已稳定。
- 不展示弱证据 quote；弱候选只用于内部诊断。
- 不依赖非官方 NotebookLM API 作为核心能力。

## 近期落地清单

优先级从近到远：

1. 已落地：Notebook / Source / Note / Layer 作为 `workspace.sqlite` 正式对象。
2. 已落地：evidence-bound 综述矩阵导出，以及术语表、时间线、方法对比、报告草稿模板。
3. 已落地：grounded annotation 与 review matrix 双向打通，`review-apply` 可把人工审阅状态写回 layer。
4. 已落地：`CitationRecord / CitationAudit`，让 claim / citation / evidence / audit 成为稳定对象。
5. 继续完善 source-grounded viewer：点击 citation 后右侧 source card 与左侧原文同步，高亮当前证据，支持 layer 切换。
6. 后置考虑音频 overview / PPT：只从已确认 evidence matrix 生成，不从原始 chunks 直接生成。

## 对 ScanSci 的一句话定位

ScanSci 不应只是“开源 NotebookLM clone”。更准确的定位是：

> 面向学术文献库的 evidence-first NotebookLM：以 clean HTML/XML 为母本，以 evidence span 为证据坐标，以可验证引用、软标注和综述矩阵为核心体验。

## 2026-07-22：对 NotebookLM 官方能力的复核与落地

本次不再以第三方复刻项目推断 NotebookLM，而是以 Google 官方帮助文档和产品博客为准。对 ScanSci 写作最有价值的不是自由生成，而是以下闭环：

1. 用户可以明确勾选本轮使用的来源，模型回答受所选来源约束。
2. 回答中的行内引用可以显示原文摘录，并跳到来源中的对应位置。
3. 对同一来源集合，可以配置回答风格和篇幅，并转换为提纲、学习指南、FAQ 等不同产物。
4. 对话结果可以保存为可编辑笔记，再从笔记继续组织和导出。
5. 新来源发现应给出相关性说明，让用户先审阅，再纳入资料范围。

官方依据：

- [NotebookLM chat help](https://support.google.com/notebooklm/answer/16179559?hl=en)：来源勾选、引用悬停查看原文、点击跳转、回答风格与长度、保存回复为笔记。
- [Create and add notes](https://support.google.com/notebooklm/answer/16262519?hl=en-PH)：新建和编辑笔记、把回复保存为笔记、从笔记生成提纲和学习材料、导出。
- [Add or discover sources](https://support.google.com/notebooklm/answer/16215270?hl=en)：来源选择、来源指南、Discover Sources 与 Deep Research。
- [NotebookLM goes global](https://blog.google/innovation-and-ai/products/notebooklm-goes-global-support-for-websites-slides-fact-check/)：行内引用回到原文段落，以及 FAQ、Briefing Document、Study Guide 等产物。
- [Discover Sources](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-discover-sources/)：候选来源附相关性说明后供用户决定是否加入。

本轮 ScanSci Pi 已把这些特点映射为工程约束：

| NotebookLM 优点 | ScanSci Pi 落地方式 |
|---|---|
| 本轮来源选择 | 综述表单显式勾选 `source_doc_ids`；检索阶段的每条 query 都带相同文献过滤器 |
| Source-grounded | 正文只接收检索证据表，事实句逐句保存 `citation_ids` |
| 引用回跳 | 引用抽屉显示 exact quote，并通过 `doc_id + html_anchor` 定位本地 clean HTML |
| 风格与篇幅 | `writing_brief` 只控制读者、语气、篇幅和关注点，不得覆盖证据规则 |
| 保存为 Note | 完整 Markdown 综述保存为当前 notebook 的 `literature_review` note |
| 可验证 | 交付前校验未知引用、无引用事实句、来源覆盖与可读性；失败不伪装成成稿 |

与 NotebookLM 的边界仍然不同：ScanSci 不把“看起来相关”当作充分证据；本地嵌入和重排负责召回排序，写作模型只能在 exact quote 白名单内组织句子，最终引用仍需可回跳和可审计。
