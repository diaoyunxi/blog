---
title: page-agent 的 demo CDN 脚本与仓库介绍
date: 2026-10-31
lang: zh-CN
tags: [page-agent, 前端, 智能体, CDN, DOM, 安全]
summary: 介绍 page-agent@1.8.0 的 IIFE demo 脚本、所属仓库、三条落地路径、纯文本 DOM 工作链路、安全要点、已知局限与选型建议。
source_issue: https://github.com/diaoyunxi/blog/issues/16
---

# page-agent 的 demo CDN 脚本与仓库介绍

## 背景

想在网页里加一个「能听懂自然语言、直接点按钮、填表单」的智能体，但又不想部署 Python runner、无头浏览器或浏览器扩展？`alibaba/page-agent` 的定位就是 **in-page GUI agent**：一段脚本跑在浏览器里，把当前页面的 DOM 信息交给 LLM，由 LLM 决定下一步动作。官方仓库 README 把自身与 `browser-use` 的关系说得明确：DOM 处理组件与 prompt 源自 browser-use，但 PageAgent 是**客户端网页增强**，不是服务端自动化。

本文以 `page-agent@1.8.0` 的 IIFE demo 脚本为例：

```text
https://cdn.jsdelivr.net/npm/page-agent@1.8.0/dist/iife/page-agent.demo.js
```

实测该文件约 203 KB，由 Vite 打成 IIFE，运行时会自行创建 `style` 标签把面板 CSS 内联注入页面；内置默认模型 `qwen3.5-plus` 与官方测试端点，也支持用 URL query 覆盖配置。

## 这个文件到底是什么

### IIFE 与 ESM 入口的区别

npm 包 `page-agent@1.8.0` 的 `package.json` 中：

```json
{
  "type": "module",
  "main": "./dist/esm/page-agent.js",
  "module": "./dist/esm/page-agent.js",
  "exports": {
    ".": {
      "import": "./dist/esm/page-agent.js",
      "types": "./dist/esm/PageAgent.d.ts"
    }
  }
}
```

- **ESM 入口**（`dist/esm/page-agent.js`）：供 `import { PageAgent } from 'page-agent'` 使用，依赖 ES module 语义、tree-shaking、构建工具解析路径，适合工程化接入。
- **IIFE 入口**（`dist/iife/page-agent.demo.js`）：把整包打包成一个自执行函数，不依赖任何模块系统，直接在 `<script>` 里执行，浏览器原生可加载。它适合：
  1. CDN 一行引入；
  2. 书签脚本 / 控制台注入；
  3. 不经过构建工具的评估环境。

demo 版额外内联了 CSS 与演示配置，加载后自动创建 `window.pageAgent` 实例并弹出面板，开箱即用于技术评估。

### 为什么锁定 1.8.0 版本号

URL 里的 `@1.8.0` 是精确版本锁定。CDN 上的包会随 npm 发版更新，若写 `@latest` 或省略版本，某天升级可能导致 API 或行为突变。锁定 `1.8.0` 保证可复现、可审计。截至 2026-10-31，官方 README 的示例已使用 `1.12.4`，但本文以 1.8.0 为基准；生产建议按自身验证过的版本锁定，并配合 SRI。

### 国内镜像

如果 jsDelivr 不可达，npm 包元数据里给了国内可用镜像：

```text
https://registry.npmmirror.com/page-agent/1.8.0/files/dist/iife/page-agent.demo.js
```

## 所属仓库

- **定位**：`alibaba/page-agent`，描述为 "GUI Agent Living in Your Webpage. Control web interfaces with natural language."。
- **开源许可证**：MIT。
- **monorepo 结构**（根据 `page-agent@1.8.0` 依赖）：
  - `page-agent`：面向用户的 ESM/IIFE 入口。
  - `@page-agent/core`：核心 agent 循环与 DOM 解析。
  - `@page-agent/llms`：LLM 客户端封装，支持 OpenAI 兼容协议。
  - `@page-agent/page-controller`：页面状态、动作执行、高亮反馈。
  - `@page-agent/ui`：面板 UI 组件。
  - 仓库还包含 Chrome 扩展、MCP Server 等可选能力（MCP 处于 Beta）。
- **与 Playwright、browser-use 的本质区别**：
  - Playwright / 无头浏览器：从外部驱动浏览器，需要运行环境、驱动进程。
  - browser-use：服务端/桌面端自动化，常配合截图或多模态模型。
  - **page-agent：从页面内部增强**，脚本直接跑在目标网页里，通过 DOM 文本与 LLM 交互，无需外部进程。

## 使用与部署的三条路径

### ① CDN 引入 / 书签脚本 / 控制台注入（仅技术评估）

```html
<script
  src="https://cdn.jsdelivr.net/npm/page-agent@1.8.0/dist/iife/page-agent.demo.js"
  crossorigin="anonymous"
></script>
```

- 脚本执行后自动执行 `window.pageAgent = new PageAgent(cfg)` 并调用 `panel.show()`。
- 支持 URL query 覆盖配置：`?model=&baseURL=&apiKey=&lang=`，`lang` 默认 `zh-CN`。
- 加 `?autoInit=false` 可只加载脚本、不自动创建实例，方便手动 `new window.PageAgent(...)`。
- 书签脚本或控制台粘贴 `<script>` 标签可实现快速验证，但**不适合生产**。

### ② npm install 接到自己的 OpenAI 兼容端点（生产）

```bash
npm install page-agent
```

```js
import { PageAgent } from 'page-agent'

const agent = new PageAgent({
  model: 'qwen3.5-plus',
  baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  apiKey: 'YOUR_API_KEY',
  language: 'zh-CN',
})

await agent.execute('点击登录按钮')
```

生产要点：
- `apiKey` 必须走后端代理，绝不要硬编码在前端。
- 自托管 IIFE/ESM 构建产物，不直接依赖公共 CDN。
- CSP：允许加载你自托管的脚本；严格 CSP 下需要 `nonce` 或 SRI。
- 版本锁定：`package.json` 写精确版本，构建产物带 hash 或固定 tag。

### ③ 克隆仓库本地开发

```bash
git clone https://github.com/alibaba/page-agent
cd page-agent
npm install
npm run dev:demo
```

`dev:demo` 会启动本地 Vite 构建并监听 IIFE 产物（默认 5174 端口）。配合浏览器书签脚本，可以在任意站点上注入本地构建的 demo 进行调试。

## 工作原理

page-agent 采用**纯文本 DOM 解析**，不截图、不依赖多模态模型：

1. **抽取可交互元素**：从当前 DOM 中筛选 `button`、`a`、`input`、`[role]`、可点击元素等，生成结构化描述。
2. **文本快照**：把可交互元素及其上下文转成紧凑文本，作为 LLM 观察。
3. **LLM 决策**：把任务文本 + 页面快照发给 LLM，模型返回下一步动作（点击、输入、选择等）。
4. **执行动作**：`page-controller` 在真实 DOM 上执行操作。
5. **高亮反馈**：在页面上高亮被操作元素，用户可直观看到 agent 在做什么。

这条链路的优势是不需要视觉模型，普通文本模型即可驱动；局限是只能感知 DOM 文本，看不到纯视觉状态。

## 安全与隐私

1. **demo 端点不是生产 API**：`https://page-ag-testing-ohftxirgbn.cn-shanghai.fcapp.run` 是官方免费测试服务，仅供评估。使用即代表接受其使用条款；不可把演示端点作为生产依赖。
2. **前端硬编码 apiKey 的风险**：浏览器侧的代码对任何用户可见，把 `apiKey` 写进前端等于公开。生产必须通过后端代理：前端把请求发给自家后端，后端持有密钥并转发到 LLM。
3. **DOM 文本会上传给 LLM 服务商**：agent 会把页面上的可交互文本发给 LLM。若页面包含敏感信息（手机号、订单号、token、内部代号），必须先脱敏。可自定义 prompt、数据掩码、字段白名单。
4. **收敛手段**：
   - `allowlist`：只允许操作特定 `data-agent` 标记的元素或特定 CSS 选择器。
   - 数据掩码：在把 DOM 文本发给 LLM 前，用正则/自定义序列化替换敏感字段。
   - 审计日志：记录每次 agent 决策与动作，便于复盘。

## 局限与坑

- **整页 Canvas / WebGL 页面基本失效**：纯文本 DOM 解析无法理解画布内容。
- **跨域 iframe**：默认只能操作当前文档，跨域 iframe 内容受同源策略限制。
- **SPA / PJAX 路由切换**：路由变化后 DOM 结构改变，agent 的观察可能滞后；需要在 `routechange` 或 `history` 钩子后重新初始化快照。
- **面板 z-index 遮挡**：demo 面板使用极高的 `z-index`（`2147483642`），可能遮挡你的浮层。
- **模型幻觉导致误点**：LLM 可能点错按钮或填错输入框。
- **操作不可回滚**：DOM 操作一旦执行无法自动撤销，生产必须加入人工确认步骤。

## 选型建议

适合 page-agent 的场景：
- SaaS 产品内嵌 AI Copilot；
- 表单密集页面（ERP、CRM、后台系统）的快速填充；
- 无障碍自然语言控制；
- 在自有页面上做客户端增强。

更合适用 Playwright / browser-use 的场景：
- 跨站爬虫、多步工作流、测试自动化；
- 需要无头浏览器或外部进程驱动；
- 多标签页、跨域名任务。

需要外部 Agent 客户端远程控制浏览器时，可关注 page-agent 官方 MCP Server（Beta）。

## 小结

`page-agent` 用一行 IIFE 脚本就能让任意网页“住进”一个 GUI agent：demo 脚本适合快速评估，npm 接入 + 自有 LLM + 后端代理适合生产落地。它基于纯文本 DOM、不依赖截图，集成成本低，但要对 DOM 外内容（Canvas/WebGL/跨域 iframe）保持清醒，并在敏感页面上做好脱敏与人工确认。

## 参考

- GitHub 仓库：https://github.com/alibaba/page-agent
- 官方文档：https://alibaba.github.io/page-agent/
- npm 包：https://www.npmjs.com/package/page-agent
- IIFE demo 脚本：https://cdn.jsdelivr.net/npm/page-agent@1.8.0/dist/iife/page-agent.demo.js
