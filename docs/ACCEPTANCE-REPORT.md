# ScanSci Pi 交付验收报告

验收时间：2026-07-21（Asia/Shanghai）  
项目目录：`F:\AI\scansci-pi`  
原项目：`D:\scansci-html`（本项目独立创建，本次实现未向原项目写入代码）

## 交付结论

`scanscipi.exe` 已形成可运行的科研 Agent 最小闭环，并完成以下真实验收：开源论文下载、知识库导入、本地 RAG、NotebookLM 式带证据问答、中文综述、科学问题梳理、可编辑 PPTX 生成和桌面 UI 启动。

最终默认模型为内置 `glm-4.7-flash`。模型服务发生 429/502 波动时，流式接口会自动重试；正式 Skill 输出还会经过完整性门控。科学问题卡若含未经审定的统计公式或系数方向，本地质量层会保留模型收束出的题目与核心问题，并换成保守的强推断框架，不会把看似专业但内部矛盾的草稿标记为完成。

内置 `Qwen/Qwen2.5-7B-Instruct` 可用于基础备用对话，但本轮对复杂中文科研卡片的质量不稳定，因此不作为综述、科学问题卡和 PPT 叙事的验收模型；这些任务应使用默认 GLM。

## 最终构建

- EXE：`F:\AI\scansci-pi\dist\scanscipi\scanscipi.exe`
- 版本：`0.2.0`
- build id：`20260721-193445`
- build commit：`7bf19dd`
- EXE 大小：49,314,659 bytes（47.03 MiB）
- Pi runtime：`0.80.10`
- 打包诊断：`ok=true`、`frozen=true`；桌面资源、Pi sidecar 和所需 Python 模块均存在
- 源码回归：`594 passed, 5 warnings`，耗时 145.76 秒

## 验收矩阵

| 能力 | 结果 | 实测证据 |
| --- | --- | --- |
| 最终 EXE 启动与诊断 | 通过 | `/api/health` 返回 `status=ok`、`build_id=20260721-193445`、`frozen=true`；打包诊断确认 Pi runtime ready |
| 桌面 UI | 通过 | Windows 桌面窗口可启动；品牌为“ScanSci Pi \| 搜索科学”，研究、知识库、模型和 PPT 工作区可用 |
| 开源论文下载 | 通过 | 已下载 arXiv `1706.03762`、`1810.04805`、`2005.14165` 三篇 PDF；文件头和可解析性检查通过 |
| 知识库导入 | 通过 | 验收知识库包含 3 篇 Transformer/BERT/GPT-3 原始论文，均建立本地证据索引 |
| RAG / NotebookLM 式问答 | 通过 | 知识库 `nb_downloads_F_AI_scansci-pi_.local_acceptanc_7b634043442e`；问题回答带可回跳证据，BERT 双向 self-attention 引用可定位到原文；越界问题返回 `insufficient_evidence=true` |
| 中文综述 | 通过 | `run_a3846b67b9754eacb9ac`；内置 GLM，3 篇文献、9 条原文证据、11/11 主张获支持；完整比较 Transformer、BERT、GPT-3 的架构、训练、评价、适配和局限，未把并行路线写成简单替代 |
| 科学问题梳理 | 通过 | 最终 EXE 运行 `run-afe0ae00162a489b809e54a1d57cadc6`；内置 GLM，57.52 秒、1247 字；含核心问题、H1/H2/H3、留出集与负对照判别、具体推翻条件、14 天 pilot 及继续/修改/停止门槛 |
| 可编辑 PPTX | 通过 | `run_bd8a2a6336604e318c07`；9 页，使用 branches/cards/comparison/process 四类版式；逐页渲染检查无裁切、无重叠，PPTX 保持可编辑 |
| 失败收束 | 通过 | 上游 429/502 会进入有限次数自动重试；连续失败会返回明确错误，不会永久停留在处理中 |
| Skill 质量门控 | 通过 | `$good-question` 使用精简运行时契约；缺少必需字段、H1/H2/H3、证据边界、完整正文或出现乱码时拒绝完成；不安全公式、希腊字母与系数表述会触发本地安全科学框架，相邻异常叠词在交付前清理 |

## 关键产物

- 最终 EXE：`F:\AI\scansci-pi\dist\scanscipi\scanscipi.exe`
- 最终诊断：`F:\AI\scansci-pi\.local\final-diagnostics.json`
- 丰富 PPTX：`C:\Users\Liang\AppData\Local\ScanSciPi\presentations\Transformer_到_BERT_与_GPT-3_架构_训练范式与实证边界_20260721-115311.pptx`
- PPT 渲染 QA：`F:\AI\scansci-pi\.local\acceptance-20260721\ppt-package-final`
- 下载论文目录：`F:\AI\scansci-pi\.local\acceptance-20260721\downloads`
- 桌面 UI 工作区：`C:\Users\Liang\AppData\Local\ScanSciPi\workspace.sqlite`

## 本轮科学问题实测摘要

输入是“基于 2015—2024 年 100 个城市的地表温度、树冠覆盖率、人口密度、土地利用和气象数据，收束绿地缓解热岛问题”。最终 EXE 输出的问题聚焦“绿地与地表温度是否存在非线性关系，以及人口密度和土地利用是否构成边界条件”，并给出：

- H1：目标关系可跨预设样本层和独立留出数据复现；
- H2：表面关系主要由共同变化的背景因素解释，匹配或分层后明显减弱；
- H3：目标效应低于最小有意义门槛，或属于测量误差/不可复现模式；
- 判别方法：探索集与留出集分离，配合结果负对照或暴露负对照；观察性数据只解释为关联；
- 推翻条件：方向反转、半数以上样本层不复现、低于预设效应门槛，或负对照与目标关系同样强；
- 两周 pilot：D1–D14 完成变量字典、数据质量、20% 分层探索、留出集与负对照检查；按缺失率、跨层一致性、最小有意义效应和负对照强度作出继续/修改/停止决定。

## 使用建议

1. 复杂中文科研任务保持默认 `glm-4.7-flash`。
2. 先把论文导入知识库，再在“知识库”模式做 RAG、综述和 NotebookLM 式问答。
3. 制作 PPT 时提供源材料并选用幻灯片模式；成品仍建议像人工交付一样做一次快速逐页审阅。
4. 若界面显示自动重试，等待本轮收束即可；只有返回明确错误后才需要重新发起。
