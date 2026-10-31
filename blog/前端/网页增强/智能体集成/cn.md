---
title: page-agent 的 demo CDN 脚本与仓库介绍
date: 2026-10-31
lang: zh-CN
tags: [page-agent, 前端, 智能体, CDN, jsDelivr]
summary: 介绍 alibaba/page-agent 的仓库定位、一条 script 即可上手的 demo CDN 用法、带参数初始化与 NPM 接入，以及演示模式的注意事项。
source_issue: https://github.com/diaoyunxi/blog/issues/16
---

# page-agent 的 demo CDN 脚本与仓库介绍

## 背景

很多前端团队想在网页里加一个「能听懂自然语言、直接操作界面」的智能体，但又不想为此部署后端、浏览器扩展或无头浏览器。`alibaba/page-agent` 正是为此而生：它是一个运行在页面里的 JavaScript GUI 智能体（in-page GUI agent），把当前页面的 DOM 信息交给 LLM，由 LLM 决定点哪里、填什么。仓库描述是 "Control web interfaces with natural language"，截至检索时已积累数万个 star，定位是**客户端网页增强**，而不是服务端自动化。

它的一大好处是「一行 script 就能体验」：官方提供了 demo CDN 脚本，直接引入就能得到一个开箱即用的演示智能体，适合在 SaaS 产品里做 AI Copilot、表单自动填充、无障碍访问等场景快速验证。

## 仓库与核心特性

- **无需扩展 / Python / 无头浏览器**：纯页面内 JavaScript，集成成本极低。
- **基于文本 DOM，不依赖截图**：不需要多模态模型或额外权限，普通文本模型即可驱动。
- **自带 LLM（BYO LLM）**：支持主流模型，也支持本地部署模型；示例中用了 `qwen3.5-plus` 配合 DashScope 的 OpenAI 兼容接口。
- **可选能力**：Chrome 扩展做跨页任务、MCP Server（Beta）从外部控制。

## 实操：demo CDN 一条引入

最快的体验方式是引入官方 demo 脚本（示例版本 `1.12.4`，请以仓库最新 tag 为准）：

```html
<script
  src="https://cdn.jsdelivr.net/npm/page-agent@1.12.4/dist/iife/page-agent.demo.js"
  crossorigin="anonymous"
></script>
```

如果 jsDelivr 访问受限，仓库给出了国内 CDN 镜像：

```text
https://registry.npmmirror.com/page-agent/1.12.4/files/dist/iife/page-agent.demo.js
```

**带参数初始化、替换自己的模型**：在 URL 上追加 `?autoInit=false`，脚本只会加载但**不自动创建演示智能体**，然后你可以用 `new window.PageAgent(...)` 手动实例化并传入自己的 LLM 配置。

**⚠️ 注意**：demo CDN 用的是官方的**免费测试 LLM API**，官方明确写着 "For technical evaluation only"（仅供技术评估），使用即代表接受其使用条款。生产环境不要直接依赖这个 demo 端点，应改走 NPM 接入 + 自有 API Key。

## NPM 正式接入

需要可控、可用自有模型的正式集成，建议走 NPM：

```bash
npm install page-agent
```

```js
import { PageAgent } from 'page-agent'

const agent = new PageAgent({
  model: 'qwen3.5-plus',
  baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  apiKey: 'YOUR_API_KEY',
  language: 'en-US',
})

await agent.execute('Click the login button')
```

`execute` 接收自然语言指令，智能体会自行在页面 DOM 上完成动作。更多编程化用法见仓库文档。

## 常见坑

- **版本要锁**：demo 脚本带的是具体版本号（如 `1.12.4`），升级时记得同步改脚本里的版本，避免行为突变。
- **demo 端点别上生产**：免费测试 API 有使用条款和稳定性约束，正式业务请用自己的 LLM。
- **客户端定位**：它是页面内增强，不是跨站爬虫/服务端 runner；跨标签页任务要靠官方 Chrome 扩展。
- **CDN 可达性**：海外 jsDelivr 与境内 npmmirror 按需选择，别把只有一份源硬编码进线上页面。

## 小结

`alibaba/page-agent` 让「网页里住着一个 GUI 智能体」这件事一行 script 就能验证：demo CDN 适合快速评估，NPM 接入 + 自有 LLM 适合落地。它基于文本 DOM、不依赖截图，集成门槛低，适合 SaaS Copilot、表单自动填充和无障碍增强。注意区分 demo 测试端点与正式接入，锁定版本并按需切换 CDN。

## 参考

- GitHub 仓库 alibaba/page-agent：https://github.com/alibaba/page-agent
- jsDelivr 公共 CDN：https://www.jsdelivr.com/
