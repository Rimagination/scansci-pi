# ScanSci 科研 Agent 架构演进

本文是 ScanSci 面向“好用的科研 Agent”的架构基线和演进清单。目标不是
把 ScanSci 变成另一个通用编码 Agent，而是让 Agent 能够在可追溯、可复核、
可恢复的约束下完成科研工作：发现问题、检索文献、获取合法全文、建立证据、
比较方法、生成带引用的研究产物，并在不确定时明确暴露不确定性。

## 当前基线

ScanSci 当前已经具备以下核心基础设施：

- `@earendil-works/pi-coding-agent` sidecar runtime；
- Python 主控的任务契约、风险等级、工具白名单和预算；
- 可恢复的 Pi session、JSONL 运行记录和跨轮次会话；
- 自己实现的 MCP bridge，支持 stdio、SSE、Streamable HTTP、工具发现和写工具授权；
- 论文发现、合法获取、清洁 HTML、证据库、检索、引用核验和科研产物工具；
- 面向 UI 的 MCP 市场，但保存配置不会自动执行服务器。

因此，当前的主要问题不是“缺一个 MCP 包”，而是运行时能力还没有完全形成
一个统一的科研 Agent 控制面。

## 实施状态（v0.2）

以下基础能力已经落地并有回归测试：

- `scansci.capability.v1`：Python 主控的统一能力目录，覆盖内置科研工具、插件状态和 MCP 服务器的风险、审批、幂等性与激活方式；
- deferred MCP：MCP 可选择按需模式，启动时仅暴露 `search` / `call` 代理，真正使用时才启动服务器并获取工具 schema；direct 模式仍是已有配置的默认兼容行为；
- 科研子 Agent：委派时自动生成只读任务契约，禁止继承写工具或外部写权限，并要求结构化交接；
- `scansci.contract-advisor.v1`：任务交付后读取持久化 run、工具调用和证据链接，记录完成缺口与建议，但不自动执行补救；
- 稳定资源 URI：run、artifact、evidence 与 paper 使用 `scansci://` 引用，避免会话和子 Agent 重复携带大段材料；
- `scansci.agent-benchmark.v1`：对持久化 run 做能力调用、证据链接和缺口处理的可重复验收。

## 对外部项目的取舍

### 官方 Pi

官方 Pi 的核心策略是保持最小内核，通过 extension、skill、package 和 SDK
构建工作流。它明确把 MCP、子 Agent、计划模式和权限弹窗留给扩展层；同时提供
动态工具、运行时启停工具、会话分叉和可定制 compaction。

ScanSci 应吸收：

1. 动态工具注册与运行时工具集合，而不是每个任务都固定加载全部工具；
2. 把工具提示、工具权限和工具结果渲染元数据作为同一个能力描述；
3. 保留完整会话历史，同时允许按任务策略压缩上下文。

ScanSci 不应照搬：

- 放弃 Python 主控的权限契约；
- 把科研证据规则交给模型或 Pi extension；
- 用通用 shell 工具替代论文获取、证据锚点和引用核验。

参考：

- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md
- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md

### `pi-mcp-adapter`

它的关键价值不是“提供 MCP”，而是把大量 MCP 工具折叠成少量代理工具，
按需搜索、延迟连接并避免启动时把数百个工具 schema 全塞进上下文。

ScanSci 当前 bridge 会在创建 session 时连接全部启用服务器，并直接暴露读取工具。
这便于权限审计和现有测试，但在多服务器、多工具的科研工作区里会增加启动延迟、
上下文占用和失败面。后续应吸收它的按需发现思想，同时保留 ScanSci 的写权限闸门。

### `oh-my-pi`

`oh-my-pi` 是 Pi 的增强版分支，不是一个普通 MCP 插件。它值得借鉴的方向包括：

- deferred tool discovery：工具默认可发现但不全部进入活动工具集；
- LSP、浏览器、Python/JS 持久执行和更强的文件/搜索语义；
- 子 Agent 的隔离、计划模式下的工具收缩和父 Agent 的 spawn policy；
- advisor/第二模型对已完成轮次做质量复核；
- 结构化输出、内部 URI 和跨工具的统一资源寻址。

ScanSci 会把这些能力改造成科研语义：论文、证据片段、引用、数据集、图表和
实验结果是统一资源，而不是简单文件；子 Agent 默认只返回结构化发现和证据引用，
不能直接改变主工作区。

参考：https://github.com/can1357/oh-my-pi

## 目标架构

```text
用户任务
   ↓
任务理解与科研路由
   ↓
主控层：任务契约 / 风险 / 预算 / 审批 / 恢复
   ↓
能力目录：工具、MCP、技能、知识库、浏览器、产物插件
   ↓
执行层：Pi session / 子 Agent / 检索流水线 / 浏览器 / MCP
   ↓
证据与产物层：Evidence Graph / 引用对象 / 报告 / PPT / Notebook
   ↓
质量层：证据充分性 / 引用核验 / 结果自评 / 回归 benchmark
```

各层边界：

- **主控层**决定能不能做、最多做多少、是否需要用户确认；模型不能扩大权限。
- **能力目录**只描述能力和状态，不在保存配置时自动执行外部程序。
- **执行层**负责调用和恢复，不负责解释科学结论。
- **证据层**负责来源、精确引用、锚点和版本；自然语言不能替代证据对象。
- **质量层**既评估答案，也评估检索路径、工具失败、成本和可复现性。

## 首批改进顺序

### P0：能力目录统一化

新增一个跨 Python/TypeScript 的能力描述协议，统一记录：

- `id`、`kind`、`source`、`version`、`status`；
- 输入/输出 schema；
- 风险级别、是否需要审批、是否允许子 Agent；
- 估计 token/cost、超时、重试和幂等语义；
- 证据要求和可生成的科研产物类型。

这样 MCP、内置科研工具、插件和未来子 Agent 不再各自维护一套能力判断。

### P0：MCP 按需发现

保留当前 direct-tool 模式作为兼容模式，新增 deferred 模式：

- session 启动只加载服务器摘要和工具索引；
- Agent 先搜索能力，再激活具体工具；
- 服务器连接延迟到真正调用；
- 写工具仍必须通过 ScanSci 任务契约和 `allow_write` 双重授权；
- 记录服务器、工具、schema、调用和失败的完整 trace。

### P1：科研子 Agent

子 Agent 不直接共享主 session 的完整上下文。每个子任务拥有：

- 明确的目标、输入证据范围和只读工具租约；
- 独立预算和取消信号；
- 结构化输出 schema，例如 `paper_candidates`、`evidence_findings`、
  `method_comparison`；
- 只能通过 artifact/evidence patch 向主 Agent 返回结果。

第一批适合并行的子任务是：多源论文发现、DOI 元数据核验、局部证据抽取、
引用一致性检查；不把“最终科学结论”拆给多个模型各自自由发挥。

### P1：Advisor 与任务结束判定

参考 `oh-my-pi` 的 advisor 思路，增加轻量的完成后检查，但检查对象必须是
科研任务契约：

- 是否完成用户目标；
- 是否满足必需工具组；
- 每个结论是否有可追溯证据；
- 是否把“发现线索”误写成“已验证事实”；
- 是否留下未解决风险和下一步。

Advisor 只能提出结构化缺口，不能绕过权限自动补做高风险动作。

### P2：科研资源 URI

借鉴 `oh-my-pi` 的内部 URI 思路，ScanSci 已定义并开始返回：

- `scansci://paper/<doi-or-id>`
- `scansci://evidence/<doc-id>/<evidence-id>`
- `scansci://artifact/<run-id>/<artifact-id>`
- `scansci://run/<run-id>`

所有工具都能返回这些稳定引用，UI、子 Agent、报告和 session 压缩都引用资源
而不是重复复制大段文本。

## 不变的产品原则

1. 证据优先：没有来源锚点的结论必须标记为推测或待核验。
2. 主控优先：模型、MCP、子 Agent 都不能扩大自己的权限。
3. 可恢复：长任务可以暂停、重试、分叉和从事件记录重建。
4. 可观察：每次检索、工具调用、引用选择和失败都能解释。
5. 可替换：Pi 是运行时，不是科研领域模型；未来可以替换模型、MCP 或 UI。
6. 渐进增强：没有外部服务、API key 或本地模型时，核心证据工作流仍然可用。

## 近期验收指标

- 多 MCP 服务器启动时，未使用工具不进入模型活动工具集；
- 子 Agent 不会获得父任务未授权的写工具；
- 恢复同一任务不会重复产生不可幂等的下载、写入或外部提交；
- 生成的科研答案能回到证据片段、原文锚点和检索 trace；
- 复杂任务的失败能区分为：能力缺失、权限拒绝、来源不可达、证据不足、模型判断不足；
- 每个新能力都有至少一个回归测试和一个可观测指标。
