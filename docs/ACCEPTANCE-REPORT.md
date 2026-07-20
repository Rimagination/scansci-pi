# ScanSciPi 交付验收报告

验收时间：2026-07-21（Asia/Shanghai）  
项目目录：`F:\AI\scansci-pi`  
原项目：`D:\scansci-html`（本次实现未在原项目中写入代码）

## 当前结论

最终 `scanscipi.exe` 已能启动并完成本地证据闭环、开源论文下载、结构化综述和可编辑 PPTX 生成；真实桌面 UI 也已完成知识库导入、问答和引用回跳。

本次交付**尚不能标记为全部完成**。最终 EXE 的两个免配置托管模型（GLM-4.7 Flash 与 Qwen2.5 7B）当前都被上游网关以 HTTP 429 限流，因此依赖生成模型的高质量中文综述、丰富 PPT 叙事和科学问题梳理无法在最终构建上完成最后一次在线复验。软件会在约 62 秒后退出处理态并显示明确错误，不会无限卡住。

## 构建信息

- EXE：`F:\AI\scansci-pi\dist\scanscipi\scanscipi.exe`
- 版本：`0.2.0`
- build id：`20260721-063556`
- build commit：`546688d`
- EXE 大小：49,271,781 bytes
- 健康检查：`status=ok`、`frozen=true`、`executable=scanscipi.exe`
- 源码测试：`565 passed, 5 warnings`，耗时 90.61 秒

## 验收矩阵

| 能力 | 最终 EXE 结果 | 证据 |
| --- | --- | --- |
| 桌面启动 | 通过 | 真实 Windows 窗口标题“搜索科学 Pi”，健康检查 build id 与最终构建一致 |
| 知识库导入 | 通过 | UI 选择 `downloads` 文件夹后显示 1 个知识库、3 篇来源，3 篇均显示“已建立证据索引” |
| RAG / NotebookLM 式问答 | 通过 | UI 运行 `run_39df5495c78b469ea45f`；回答 BERT 使用双向 self-attention，引用 `[1]` 可回跳到 1810.04805 第 3 页原文 |
| 越界拒答 | 通过 | 关于“2025 年火星全球液态海洋”的问题返回空答案、0 引用、`insufficient_evidence=true` |
| 开源论文下载 | 通过 | `run_21cc9c4b4b8c44ea946c`；arXiv 1706.03762，2,215,244 bytes，文件头 `%PDF` |
| 综述闭环 | 基础通过，生成质量待复验 | `run_5ac91f829d0e40258ed4`；16.65 秒，5 节、7 个检索式、30 条证据、3 篇文献、8 个最终引用、11 个支持性主张，引用核验通过。429 时使用忠实证据摘录，不冒充模型扩写 |
| PPTX 生成 | 基础通过，丰富叙事待复验 | `run_46e5c64e90264975a140`；5.45 秒，3 篇来源、7 页、Python-PPTX 可编辑文件；逐页渲染检查无重叠、无裁切，模型 429 时使用来源优先的降级大纲 |
| 科学问题梳理 | 开发构建曾通过，最终在线复验受阻 | `$good-question` 的真实模型运行约 44 秒，产出核心问题、假设、变量、最小数据、证伪条件、替代解释和 pilot；最终 EXE 当前因 429 无法重跑 |
| 内置 GLM 直接对话 | 阻塞 | 最终 EXE 61.85 秒后返回应用层 502，明确说明上游 `HTTP 429` |
| 内置 Qwen 备用模型 | 阻塞 | 最终 EXE 61.82 秒后得到同一上游 `HTTP 429`；测试后已恢复默认 GLM |

## 关键产物

- 最终 PPTX：`F:\AI\scansci-pi\.local\acceptance-20260721\presentations\从_Transformer_到_BERT_与_GPT-3_共享架构_训练目标与两条适配路线_20260721-064831.pptx`
- PPT 渲染 QA：`F:\AI\scansci-pi\.local\acceptance-20260721\ppt-qa-packaged-final`
- 下载论文：`F:\AI\scansci-pi\.local\acceptance-20260721\downloads\1706.03762.pdf`
- 最终 EXE 验收工作区：`F:\AI\scansci-pi\.local\acceptance-20260721\workspace.sqlite`
- 桌面 UI 工作区：`C:\Users\Liang\AppData\Local\ScanSciPi`

## 真实桌面 UI 验收步骤

1. 启动最终 `scanscipi.exe`，确认窗口品牌为“ScanSci Pi | 搜索科学”。
2. 进入“知识库”，通过 Windows 文件夹选择器导入 3 篇 PDF。
3. 新建研究，切换到“知识库”模式，提问“BERT 的自注意力是双向还是只能看左侧上下文？”。
4. UI 显示理解问题、检索与综合、证据核验、交付回答四个阶段均完成。
5. 点击回答中的 `[1]`，右侧成功打开 1810.04805 第 3 页的证据片段。
6. 切回“通用”模式调用 GLM；约 60 秒后 UI 明确显示“模型流式响应暂时不可用（HTTP 429），请稍后重试”。

## 剩余交付门槛

上游免配置模型网关恢复后，需要在**同一个最终 EXE** 上重新执行以下三项，并保存运行记录：

1. 通用模式直接对话成功返回；
2. `$good-question` 完整科学问题梳理成功；
3. 使用生成模型分别重跑一篇中文综述和一份 PPT，复核引用与逐页视觉质量。

上述三项通过后，才满足“所有能力都可由内置模型实际完成”的最终交付定义。
