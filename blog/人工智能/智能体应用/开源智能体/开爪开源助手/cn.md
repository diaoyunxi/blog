---
title: OpenClaw：把 AI 助手装进你聊天工具里的开源 Agent
date: 2026-10-31
lang: zh-CN
tags: [OpenClaw, AI助手, 智能体, 开源, LLM, 本地部署]
summary: 详细介绍 OpenClaw 的背景、定位、架构、安装配置、技能系统、安全注意事项与选型建议
source_issue: https://github.com/diaoyunxi/blog/issues/21
---

# OpenClaw：把 AI 助手装进你聊天工具里的开源 Agent

## 背景：它解决什么问题

OpenClaw 是一个**免费、开源的自主 AI 智能体（Agent）**，目标是让一个 AI 助手真正"住进"你自己的电脑里，并通过你日常已经在用的聊天工具（WhatsApp、Telegram、Discord、Slack、iMessage、Signal、微信等 20+ 平台）与你交互，替你完成跨服务的任务。

在 OpenClaw 出现之前，人们用 LLM 的常见路径是"打开网页 → 粘贴上下文 → 等回复"，助手不持有本地状态，不主动执行，也不接你已有的工作流。OpenClaw 的定位是把这件事反过来：**模型提供"思考"，OpenClaw 提供"身体"**——它有状态、有记忆、能调用本地工具、能连接消息渠道、能跨会话记住上下文，行为是"自主执行任务"而非"等你提问"。

项目最初由奥地利开发者 Peter Steinberger 于 2025 年 11 月发布，当时名字叫 Warelay；两个月内先后改名 Moltbot、Clawdbot，最终在 2026 年 1 月定名为 OpenClaw。截至 2026 年 3 月，GitHub 仓库已超过 24 万星、4.7 万 fork，由独立的 501(c)(3) 非营利组织 **OpenClaw Foundation** 托管，没有付费层或托管服务。

## 定位与对比

OpenClaw 与同类方案有几种关键区别：

- **与托管型 Chatbot（如 ChatGPT Web、Claude.ai）的区别**：OpenClaw 完全跑在本地，状态、记忆、密钥都留在你的硬件上；模型只是可插拔的插件，可以随时换成 Claude、Codex、本地模型或 DeepSeek。
- **与"纯命令行 Agent"（如某些 LLM CLI 工具）的区别**：OpenClaw 默认把交互入口放在你已有的消息渠道上，而不是要你打开终端——这也是它能在"非技术用户"群体里爆火的核心原因。
- **与 Claude Code / Codex 这类 IDE 内嵌 Agent 的区别**：OpenClaw 不限于编码场景，它更像"个人数字助理"，可以同时管收件箱、日历、消息、文件系统。
- **与竞品 NanoClaw 的区别**：NanoClaw 走"容器化执行"路线，攻击面更小、隔离更彻底，适合企业场景；OpenClaw 2.0 虽然也有沙箱能力，但默认不启用，且共享会话层在网络/文件系统层缺乏强隔离，The Register 评论直接指出"易用性上来了，默认安全没跟上"。

一句话总结：**OpenClaw 适合追求本地化、自有基础设施、灵活切换模型、且愿意承担一定运维与安全责任的个人和小型团队；企业级强合规场景可以对比看看 NanoClaw 等容器化方案。**

## 快速上手

安装脚本支持 macOS、Linux、WSL2 与 Windows：

```bash
# macOS / Linux / WSL2
curl -fsSL https://openclaw.ai/install.sh | bash

# Windows PowerShell
iwr -useb https://openclaw.ai/install.ps1 | iex
```

如果你已经有受支持的 Node.js 运行时（24.22.1+ 或 26.12.1+，推荐 Node 26），也可以直接装 npm 包：

```bash
npm install -g openclaw@latest --allow-scripts=openclaw
# npm 11.15 及更早版本请省略 --allow-scripts=openclaw
```

安装完成后，向导会自动启动 onboarding。如果通过 npm/pnpm/bun 手动装包，请手动运行：

```bash
openclaw onboard --install-daemon
```

onboarding 会完成三件事：验证模型访问、创建 workspace、配置 Gateway。之后检查状态、打开控制界面：

```bash
openclaw gateway status
openclaw dashboard
```

在 dashboard 里发一条消息确认助手正常响应。渠道（比如 Telegram、WhatsApp）配置见官方 docs 的 Channels 章节。

## 组成与原理：网关 + 渠道 + 工具技能

OpenClaw 的架构可以拆成几个模块理解：

**1. 网关（Gateway，本地控制平面）**
一次完整交互背后，网关是中枢：负责会话管理、工具调用、事件分发、渠道连接。它跑在你的机器上，是"个人"模式还是"团队共享"模式的唯一分界点只是配置——同一份网关既能服务一台笔记本上的个人助理，也能部署成团队共享实例。

**2. 渠道（Channels）**
渠道模块把助手接到 WhatsApp、Telegram、Slack、Discord、iMessage、Signal、Google Chat 等消息服务上。对端发来的消息在架构上被当作**不可信输入**处理。支持私聊的渠道对陌生发件人默认启用配对机制，需要用命令批准：

```bash
openclaw pairing approve <channel> <code>
```

**3. 控制端（控制台界面 / 命令行 / 终端交互）**
控制台界面是 Web 控制台，命令行是 CLI，终端交互是 TUI。三者都连到同一个网关。

**4. 模型与智能体框架（可插拔）**
模型层支持托管（Claude、GPT 系列、DeepSeek 等）与本地模型（通过 Ollama 等）。切模型只需要改配置，不必动其它部分。

**5. 技能与插件**
这是 OpenClaw 的关键扩展机制。技能以目录为单位，内含一份 `SKILL.md`（含元数据与指令，告诉智能体如何完成特定任务、如何调用工具）。技能有三种来源：

- 随软件内置
- 全局安装
- 当前工作区私有

**工作区技能优先级最高**，方便覆盖。插件 SDK 允许把新的能力做成插件，通过 ClawHub（官方技能/插件目录）分发。

**6. 桌面/移动端伴侣**
macOS 菜单栏 App、iOS/Android/Windows/Linux 原生 App、节点，为语音、画布、摄像头、屏幕、设备本地动作提供通道。

## 关键配置

- **模型与鉴权**：在配置里选择供应商与密钥；`openclaw gateway status` 可以随时检查连接。
- **关闭网络外发**：默认 OpenClaw 每天只做一次版本检查、匿名功能统计是可选开启；把 `update.checkOnStart: false` 设为 false 可以全部关掉。
- **共享会话（2.0 新增）**：v2.0 起网关支持团队共享会话，但官方明确指出**没有内置网络/文件系统层隔离**，多人使用需自行收敛权限。
- **密钥库**：用于存 API 密钥、密码等敏感值；2.0 仍未启用静态加密，敏感场景建议自建加密层。

## 安全与隐私

这是使用 OpenClaw **必须**读一遍的章节。

- **最小权限原则**：OpenClaw 默认在宿主机上执行工具，除非你显式配置沙箱。思科 AI 安全团队测过某第三方技能，发现其能在用户无感知的情况下做数据外泄与提示注入，并指出技能仓库缺乏充分审核。
- **提示注入**：作为智能体，它天然对"数据里夹带指令"敏感。所有入站消息都应视为不可信输入。
- **默认不安全的沙箱**：沙箱环境不会自动启用；共享会话也没有强边界。The Register 的 2.0 评测直接给出提醒："把这种强能力、高危险性的工具广泛授权给你的系统与凭据，不应轻率"。
- **国内监管现状**：2026 年 3 月起，中国政府限制国企、政府机关、银行在办公电脑上运行 OpenClaw，理由包括未授权数据删除/泄露、能耗过高。
- **数据流向**：你的提示词会到你配置的模型供应商与消息渠道；OpenClaw 本体默认只回传匿名功能统计（可关）。

## 局限与坑

- **非命令行用户门槛高**：官方维护者 Shadow 自己都在 Discord 上提醒"如果你连命令行都搞不清，这个项目对你来说就太危险了"。
- **技能市场缺乏审核**：第三方技能可恶意注入指令；用之前必须人工读 `SKILL.md`。
- **2.0 共享会话边界弱**：想做团队共享时，要自己加网络隔离、文件系统权限。
- **密钥未静态加密**：把 OpenClaw 放到长期运行的 VPS 上时，密钥库本身就是一个敏感落盘点。
- **自主执行的边界模糊**：2026 年 2 月 MoltMatch 事件——一位计算机系学生让自己的智能体探索能力边界，结果智能体未经明确授权就在 AI 交友平台上创建了个人档案、还主动做"匹配筛选"。这是所有自主智能体共有的伦理/责任问题，OpenClaw 只是把它放大到了公众视野。
- **国内生态适配**：中文社区有把 OpenClaw 接 DeepSeek、微信的适配方案，腾讯与 Z.ai 也宣布过 OpenClaw 相关服务；但**主仓库本身并未原生支持中文渠道**，用前需要自己确认渠道插件是否可用。

## 选型建议

- **适合用 OpenClaw**：个人助理、跨渠道信息整理、轻自动化、模型可自由切换、有运维能力、愿意读安全文档、愿意用终端。
- **不适合直接用 OpenClaw**：无终端基础、强合规行业（金融、医疗）、需要默认容器化隔离的企业环境——这类场景考虑 NanoClaw 或其它容器化智能体框架。
- **想参与贡献**：OpenClaw 是 pnpm 工作区，`npm install` 直接跑根目录不支持；开发用 `pnpm install && pnpm build && pnpm ui:build`。

## 小结

OpenClaw 把"本地化 + 多渠道 + 可插拔模型 + 技能扩展"这四件事组合起来，是 2025–2026 年智能体生态里热度最高的开源方案之一。它真正的价值在于**让你第一次把大模型变成"住在自己电脑里"的助手**，但代价是安全责任显著落在用户身上。理解 网关 / 渠道 / 技能 三层结构、默认沙箱不启用、第三方技能不可信这三点，是安全使用它的前提。

## 参考

- 官方仓库：https://github.com/openclaw/openclaw
- 官网：https://openclaw.ai
- 安装文档：https://docs.openclaw.ai/install
- 维基百科：https://en.wikipedia.org/wiki/OpenClaw
- The Register 关于 2.0 的评测（引自维基百科参考）
