---
title: page-agent 的 MCP Server 配置与用法
date: 2026-11-01
lang: zh-CN
tags: [page-agent, MCP, 智能体, 浏览器自动化, GUI Agent]
summary: 介绍 alibaba/page-agent 项目中 MCP Server（@page-agent/mcp）的作用、安装、接入 MCP 客户端的配置方法，以及典型使用场景与限制。
source_issue: https://github.com/diaoyunxi/blog/issues/25
---

# page-agent 的 MCP Server 配置与用法

## 背景：page-agent 是什么

`alibaba/page-agent` 是一个开源的「页内 GUI 智能体」（in-page GUI agent）：它把一段 JavaScript 直接注入到网页里，让任意网页拥有自己的 AI 助手。与传统基于 Python、无头浏览器或浏览器扩展的自动化方案不同，page-agent 的核心诉求是**客户端增强**——不需要 headless 浏览器、不需要后端改造，一行 `<script>` 就能给 SaaS 产品、ERP、CRM、后台管理系统挂上一个 AI Copilot。

它的关键特性：

- **文本型 DOM 操作**：不做截图、不依赖多模态 LLM，直接基于可访问性树 / 文本化的 DOM 操作，权限需求低。
- **自带 LLM**：支持 OpenAI 兼容协议、DashScope、Ollama 本地模型等，用户可自由切换。
- **可选的 Chrome 扩展**：让 agent 跨多个标签页完成任务。
- **可选的 MCP Server**：让外部的 MCP 客户端（例如 Claude Desktop、Cursor、各种 MCP 宿主）通过 MCP 协议控制 page-agent，从而驱动浏览器。

本文聚焦最后一个能力：MCP Server。

## 定位与对比：MCP Server 在 page-agent 体系里做什么

page-agent 的 monorepo 里包含多个 npm 包，其中与 MCP 相关的是：

| 包名 | 角色 |
| --- | --- |
| `page-agent` | 主包，含 UI 面板与 `PageAgent` 类，通常直接挂在网页里 |
| `@page-agent/core` | 纯 agent 核心逻辑，不带 UI |
| `@page-agent/mcp` | **MCP Server**，把 page-agent 的浏览器控制能力暴露给外部 MCP 客户端 |
| `packages/extension` | Chrome 扩展，负责多页任务，MCP 实际与之配合工作 |

可以把它理解成一条链路：

```
MCP 客户端（Cursor / Claude 等）
   ↓  MCP 协议
@page-agent/mcp（MCP Server 进程）
   ↓  指令
page-agent / Chrome 扩展
   ↓  文本 DOM 操作
目标网页
```

与「直接在网页里挂 PageAgent」对比，MCP 的最大价值是：**让 agent 客户端不再需要写一段脚本调用 `agent.execute(...)`，而是把 page-agent 当成一个标准 MCP 工具集来调用**，复用 MCP 生态里现成的 LLM 工具调用框架。

## 快速上手

### 1. 安装 MCP Server

`@page-agent/mcp` 通过 npm 发布，安装到你要运行 MCP 服务进程的项目里（不一定是你的网页项目）：

```bash
npm install @page-agent/mcp
```

### 2. 启动 MCP Server

MCP Server 通常有两种宿主方式：

- **stdio**：作为子进程被 MCP 客户端（如 Claude Desktop、Cursor）拉起，最常见的做法；
- **SSE / HTTP**：把 MCP Server 暴露为独立进程，供远程客户端连接。

`@page-agent/mcp` 默认按 MCP 规范实现 stdio 入口，启动方式大致是：

```bash
node -e "import('@page-agent/mcp').then(m => m.main())"
```

或者在脚本里直接 `npx @page-agent/mcp`（以包实际暴露的 bin 为准，发布说明与包内 `package.json#bin` 字段为准）。

### 3. 在 MCP 客户端里配置

以 Cursor / Claude Desktop 这类常见宿主为例，在 MCP 配置里加一段：

```json
{
  "mcpServers": {
    "page-agent": {
      "command": "npx",
      "args": ["-y", "@page-agent/mcp"]
    }
  }
}
```

如果是 stdio 进程直连：

```json
{
  "mcpServers": {
    "page-agent": {
      "command": "node",
      "args": ["/path/to/node_modules/@page-agent/mcp/dist/main.js"]
    }
  }
}
```

配置完重启客户端，就能看到 MCP 客户端把 `@page-agent/mcp` 暴露的工具列出来（点击、输入、读 DOM 摘要、导航等），后续 LLM 就能像调用普通 MCP 工具一样驱动浏览器。

### 4. 配合 Chrome 扩展

MCP 控制的是「当前打开的浏览器里的页内 agent」。如果任务是跨标签页 / 多页任务，需要安装 page-agent 的 Chrome 扩展（`packages/extension`），MCP 端的指令会经扩展路由到具体标签页上的 `PageAgent` 实例。

## 关键配置

MCP Server 本身的配置面不大，主要决定的是「agent 行为」，与你在网页里直接 `new PageAgent({...})` 时的参数保持一致。最常用的字段：

- `model`：模型名（如 `qwen3.5-plus`、`gpt-5.2`、`qwen3:14b`）。
- `baseURL`：OpenAI 兼容端点；本地 Ollama 可填 `http://localhost:11434/v1`。
- `apiKey`：LLM 密钥。本地部署模型通常填占位符（如 `NA`），但字段需要存在。
- `language`：界面语言，如 `en-US`、`zh-CN`。
- `autoInit`：是否自动初始化 demo agent；做 MCP 对接时通常置 `false`，由 MCP 端按会话创建实例。

这些字段通常通过环境变量或 MCP Server 的启动参数注入。例如用 Ollama 本地模型：

```env
LLM_MODEL_NAME=qwen3:14b
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=NA
```

## 安全与隐私

- **API Key 管理**：page-agent 的 demo CDN 用的是官方测试 LLM，仅用于技术评估；正式使用必须替换成自己的 `apiKey`，并通过环境变量而非硬编码注入。
- **数据流向**：MCP 协议本身只传递 DOM 摘要与操作指令，但被操作页面里的敏感数据（输入框内容、Cookie 等）可能进入 LLM 上下文，生产环境要评估脱敏策略。
- **浏览器侧权限**：MCP 经 Chrome 扩展落地，扩展的 host 权限范围越窄越好；只给你真正要 agent 化的站点开权限。
- **MCP 端身份**：把 MCP Server 暴露到网络上时务必加鉴权，stdio 模式则把进程权限收到运行 MCP 宿主的那个账户即可。

## 局限与坑

1. **Beta 状态**：MCP Server 在 page-agent 仓库里标注为 Beta，工具列表和命令参数在版本迭代间可能变；锁定版本、升级前跑一遍回归。
2. **必须配合扩展**：MCP 不是凭空控制浏览器，它最终落在「目标网页里已经注入了 page-agent」或「扩展托管的标签页」上，扩展没装好时 MCP 端指令会落空。
3. **文本 DOM 限制**：不做截图，因此对纯 canvas、重度图形界面、需要像素级判断的页面支持有限；这类场景要另走多模态方案。
4. **跨标签页时序**：多标签任务里 LLM 可能并发下发指令，注意任务排队与超时。
5. **密钥暴露**：本地开发用 demo iife 时，`.env` 里的 AK 会被内联进脚本，分发该脚本前要彻底清理。

## 选型建议

- 你只想在网页里加个 Copilot 入口 → 直接用 `page-agent`，不必上 MCP。
- 你的 agent 客户端（Cursor / Claude / 自建宿主）通过 MCP 调用工具，需要让它「顺手」控制浏览器 → 选 `@page-agent/mcp`。
- 任务跨多个网站标签页 → 必须装 Chrome 扩展，让 MCP 指令有载体。
- 强依赖截图 / 视觉理解 → page-agent 的文本 DOM 路线不合适，考虑 browser-use 或专用多模态 agent。

## 参考

- 项目主页与特性说明：https://github.com/alibaba/page-agent
- 仓库文档目录：https://github.com/alibaba/page-agent/tree/main/docs
- 开发者指南（monorepo 结构、各包职责）：https://raw.githubusercontent.com/alibaba/page-agent/main/docs/developer-guide.md
- 上游参考实现 browser-use：https://github.com/browser-use/browser-use

> 注：截至 2026-11-01，`@page-agent/mcp` 仍标注为 Beta，具体工具清单与 CLI 入口以包内 `package.json` 与当前版本 README 为准；本文命令为常见 MCP 宿主接法示例，落库前请先 `npm i` 后核对 bin。
