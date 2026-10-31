---
title: 开源 AI 智能体 Cindy：实现原理与使用方法
date: 2026-10-31
lang: zh-CN
tags: [AI Agent, 开源, Electron, 多设备]
summary: 介绍 makecindy/cindy 仓库的定位、monorepo 实现结构、开发流程与使用方式。
source_issue: https://github.com/diaoyunxi/blog/issues/14
---

# 开源 AI 智能体 Cindy：实现原理与使用方法

Cindy（仓库 `makecindy/cindy`）是一个"想到就能做到"的开源 AI 智能体客户端，主打**开箱即用**、多设备互联、可自由定制。它的口号是：连接你的电脑与手机，沿用你已有的模型与订阅，塑造一个懂你工作习惯的陪伴型智能体。客户端以 Apache-2.0 许可开源，任何人都可以审计、分叉并改进它。

## 一、定位与核心能力

Cindy 把"你的电脑变成你的服务器"，无需额外租用服务器或自建后端：

- **多设备互通**：工作机、台式机、笔记本与手机属于同一个 Cindy 空间，可在另一台设备打开同一会话、继续对话并访问其文件。
- **共享模型与订阅**：跨设备使用已配置的模型提供方，包括受支持的订阅、API 提供方与本地模型。
- **远程桌面**：手机内置远程桌面，在聊天不够用时可直接打开应用、输入并操作被连接电脑。
- **整合现有 agent**：把 Claude Code、Codex 与 Pi 等"agent 引擎（harness）"汇聚到一个共享界面下，并加上多设备接入、工具与陪伴能力。
- **真实工具落地**：与本地文件、浏览器、应用交互，可输出图表、交互控件与富 HTML；支持自动化例程、Slack/Telegram 等聊天渠道、Skills/插件/MCP 扩展。

需要明确：项目文件保留在各自电脑上，远程访问并非整盘同步；云陪伴体的对话、记忆、技能与共享附件通过 Cindy 服务同步，模型提供方仍按其请求计费。

## 二、实现结构（monorepo）

该仓库包含 Cindy 的**开源桌面与移动客户端**及其共享包，组织为一个 pnpm monorepo：

| 路径 | 说明 |
| --- | --- |
| `apps/desktop` | 基于 Electron 的桌面客户端 |
| `apps/mobile` | 基于 Expo / React Native 的移动客户端 |
| `packages/*` | 共享客户端能力（认证、设备互联、agent 编排、模型提供方等） |
| `apps/*-bin` | 随桌面应用分发的工具二进制（如 claude-code、codex、ripgrep，按平台在 `pnpm install` 时下载，不入库） |

注意：后端服务位于**另一个独立仓库**，不在本 monorepo 内。客户端默认连接 Cindy 官方云服务（端点清单见 `config/endpoint.json`、`config/endpoint.global.json`），桌面自动更新来自官方 CDN——外部开发者无需自建服务端即可开发测试。

## 三、环境准备

开发前置条件：

- Node.js 22.x
- pnpm 10.x（v11 尚不支持）
- Git LFS

## 四、开发与运行

最小入口流程：

```bash
git clone https://github.com/makecindy/cindy.git
cd cindy
git lfs pull
pnpm install
```

开发入口按账号区域选择：

```bash
# 中国大陆 Cindy 账号
pnpm restart:desktop:remote --region=cn
# 全球 Cindy 账号
pnpm restart:desktop:remote --region=global
```

远程开发使用你自己的 Cindy 云账号与既有登录态，可在开发客户端的同时继续既有会话。"Skip Sign-In"（跳过登录）模式下仅运行本地 agent、显示为"未登录"，服务端能力不可用，且不向 TapDB 上报。

## 五、使用方式

- 客户端**免费**，可授权你已付费的订阅（含 Claude Code / Codex 套餐）、连接自有 API key 或使用本地模型；也可使用 Cindy 托管模型服务。但"免费客户端"不等于"无限模型用量"，提供方限额与计费仍然适用。
- 支持 macOS、Windows、Linux、iOS、Android。Linux 用户可参考 Ubuntu、Arch、Omarchy 安装指南完成安装、更新、keyring 配置与从手动安装的迁移。

## 六、贡献与隐私

- 贡献通过向 `main` 分支提 PR，先阅读 `CONTRIBUTING.en.md`；每个提交需带 DCO 签名（`git commit -s`），无需 CLA。
- 官方分发构建包含 TapDB 使用统计（设备标识、版本、启动与活跃事件，登录后与账号关联，**不收集**聊天/文件/工作目录内容）；桌面与移动均可在设置中关闭使用统计。

## 小结

Cindy 把"多设备 + 多 agent 引擎 + 真实工具"串成一条开箱即用的链路，并以 pnpm monorepo 形式开源其桌面/移动客户端，降低了从审计到二次开发的门槛。关注它时，需分清"仓库内的客户端/共享包"与"仓库外的后端服务"。

## 参考

- https://github.com/makecindy/cindy
