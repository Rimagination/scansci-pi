# ScanSci Pi 内置 Agent Reach

ScanSci Pi 已经内置 Agent Reach 风格的互联网渠道路由，不需要另外安装
`agent-reach` CLI，也不需要开启 shell 权限。

在对话中直接提出以下请求即可：

- “读取这个网页：`https://...`”
- “搜索 GitHub 上的 …”
- “看看这个 RSS/Atom 源最近更新了什么”
- “搜一下 B 站的 …”
- “看看 V2EX 最近的热门主题”
- “检查当前互联网渠道是否可用”

Pi 会调用内置 `agent_reach` 工具，并根据 `status`、`read`、`search` 三种
操作选择渠道。网页、RSS/Atom、公开 GitHub、B 站公开搜索和 V2EX 公开
接口不依赖额外安装；YouTube 字幕、私有仓库以及需要登录的平台仍可能
需要用户已有的授权浏览器会话。对于这类页面，Pi 会升级到内置
`browser_access` 只读浏览器桥接；它会使用用户 Chrome 的登录态读取渲染后
文字，完成后关闭自己创建的后台 tab。ScanSci 不会注入 Cookie、代替用户
登录、执行任意 JavaScript 或执行任意 shell 命令。

统一路由规则是：普通关键词用 `search_web`，公开直链和结构化渠道用
`agent_reach`，登录态/动态渲染/反爬导致公开读取不足时用 `browser_access`。
同一个 URL 不会无理由在多个读取器之间重复请求。

返回结果会标出原始 URL、实际后端和证据级别。搜索结果属于发现线索，
页面/RSS/API 返回内容才是已读取的来源；回答中应保留这个区别。

该能力是对 [Agent-Reach](https://github.com/Panniantong/Agent-Reach) 的
ScanSci 原生适配，遵循其 MIT 许可；ScanSci 只复用其多渠道路由理念，
不把上游安装器、凭据文件或任意命令执行器带入桌面应用。
