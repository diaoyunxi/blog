---
title: DeepSeek Harness（dsh）详解
date: 2026-10-31
lang: zh-CN
tags: [DeepSeek, Agent, 智能体框架, 插件架构, 开源]
summary: 介绍 DeepSeek AI 开源智能体框架 DeepSeek Harness（dsh）：它解决什么问题、架构原理、快速上手、配置与插件生态、安全与隐私、局限与选型建议。
source_issue: https://github.com/diaoyunxi/blog/issues/20
---

# DeepSeek Harness（dsh）详解

DeepSeek Harness（简称 dsh）是 DeepSeek AI 官方推出的开源智能体（Agent）框架，MIT 许可，核心代码用 TypeScript 编写，底层由 Cordis 插件引擎驱动。它的设计哲学可以浓缩为一句话：**"模型是大脑，Harness 是身体"**——给定一个 LLM，dsh 提供一整套工具、沙箱、会话、UI、调度与扩展机制，让开发者能在配置层自由拼装自己的 Agent，而不必改动源码。

## 1. 背景：它解决什么问题

过去用 LLM 做编码助手，常见两条路：

1. **厂商封装黑盒**：IDE 插件或 CLI 助手，功能固定，无法深入替换工具、模型路由或权限策略。
2. **自己搭框架**：在 LangChain 或裸 OpenAI API 上拼代码，但工具注册、沙箱隔离、会话日志、事件驱动扩展点都要手写，工程量大。

dsh 的切入点介于两者之间：它给一个**功能完整、可观测、可逆注册**的"骨架"，所有能力——包括模型选择、文件编辑、Shell、搜索、子 Agent、工作流、Web UI——都以**插件**形式挂载在 Cordis 内核上。Cordis 的设计思想来自学术论文《A Programming Paradigm for Spatiotemporal Composability》，强调时空可组合性与事件驱动。

它适合以下场景：

- 想要本地/私有化编码 Agent，且每个组件（模型、沙箱、工具）都能被替换；
- 做 Agent 架构研究，需要完整的事件流与配置树；
- 把 Agent 嵌入自己的产品，用 Python / TypeScript SDK 驱动。

## 2. 定位与对比

| 维度 | dsh（DeepSeek Harness） | 厂商黑盒助手（Cursor/Copilot） | LangChain 等通用框架 |
|---|---|---|---|
| 可替换性 | 全部组件可配置层替换 | 基本固定 | 库级 API，需自己写调度 |
| 核心哲学 | 一切皆插件 | 产品导向 | 工具链可组合 |
| 可观测性 | 仅追加会话日志 + Trajectory 视图 | 黑盒 | 需自建 |
| 许可 | MIT | 多为商用 | 各库不同 |
| 默认模型 | DeepSeek（填 API Key 即用） | 绑定自家模型 | 任意 provider |

dsh 与 IDE 助手的本质区别：IDE 助手围绕"当前编辑器窗口"，dsh 是独立进程，有自己的配置目录、会话历史、权限系统与插件生命周期。与 LangChain 等框架相比，dsh 把"Agent 循环"（模型 → 工具 → 结果 → 模型）内置在核心插件里，而非让开发者手写 ReAct 循环。

## 3. 快速上手

### 前置条件

- **Node.js ≥ 24.9**（npm / npx 路线要求）
- **DeepSeek API Key**（或任意 OpenAI 兼容端点）
- 操作系统：Linux / macOS / Windows

### 3.1 最快捷径：npx 启动 Web UI

```bash
# 确认 Node 版本
node -v

# 一键启动（默认 http://127.0.0.1:3080，自动打开浏览器）
npx @deepseek-ai/dsh web

# 不打开浏览器（例如 SSH 远程场景）
npx @deepseek-ai/dsh web --no-open
```

启动后浏览器会显示 dsh 的 Web UI。

### 3.2 在 Web UI 里完成初始化

1. **配置模型**：`设置 → 模型`，填入 DeepSeek API Key，保存。模型路由立即生效，无需重启。也支持填入任意 OpenAI 兼容 endpoint。
2. **选择工作区**：点"选择工作区"，把启动 dsh 时的项目目录添加进去并选中。选中之前会话输入框不可用。
3. **运行第一个任务**：在会话里输入：

   ```
   Summarize this repository and identify its main packages.
   ```

   Agent 会读文件、跑命令、维护计划；若权限策略要求审批，Web UI 会先弹确认框。

### 3.3 从源码安装（贡献 / 深度定制）

```bash
git clone https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

`pnpm run build` 产出仓库 artifacts；`pnpm dsh web` 直接复用这些产物，不会二次编译。

### 3.4 命令行常用形态

| 命令 | 作用 |
|---|---|
| `dsh web` | 启动 Web UI（默认 3080 端口） |
| `dsh --profile web --dump-config` | 打印当前 profile 启动后的完整配置树 |
| `dsh plugin --profile web add "github:dsh-external/dsh-session-search#main"` | 用 git 源安装插件 |

桌面版提供 Windows 64 位与 macOS Apple 芯片安装包，无需命令行。

## 4. 组成与原理

### 4.1 顶层结构

dsh 由三层组成：

```
┌─────────────────────────────────┐
│  UI 层                          │
│  Web UI / 桌面 / TUI / CLI     │
├─────────────────────────────────┤
│  能力插件层（全部可替换）        │
│  模型 / 工具 / 沙箱 / 会话      │
│  搜索 / 记忆 / 子 Agent / 工作流 │
│  PTC / 调度 / 技能(Skills)      │
├─────────────────────────────────┤
│  Cordis 内核（一切皆插件的引擎） │
│  插件加载/卸载/依赖管理/事件总线 │
└─────────────────────────────────┘
```

Cordis 内核**自身不提供任何业务能力**，它只负责：

- 插件生命周期（加载、卸载、可逆注册）
- 依赖声明与拓扑排序
- 事件广播（会话级 / Agent 级 / 能力级三级事件）
- 服务注册与发现

任何能力（模型 adapter、文件编辑工具、沙箱策略、UI 组件）都做成插件，通过服务 + 事件与兄弟插件协作。"无特权内核"意味着你删除某个插件，系统不会崩溃，只是能力降级。

### 4.2 数据流：一次对话发生了什么

1. **用户输入**进入会话插件，系统提示词 + 历史 + 上下文注入合并后交给**模型插件**。
2. 模型输出工具调用请求，事件总线广播，**工具插件**（文件、Shell、搜索等）执行。
3. 工具结果通过事件回写会话，再次喂给模型。
4. 全过程（系统提示词、思维链、每次工具调用与结果、子 Agent 调度、上下文注入）追加写入**仅追加会话日志**。
5. **Trajectory 视图**按来源回放同一份事件流，用于恢复、分叉、检索与回放。

### 4.3 关键目录与配置文件

- `~/.dsh/`（或启动目录的 `dsh` 子目录）：会话日志、profile 配置、插件缓存。
- `package.json`：dsh 仓库入口；插件以 `dsh-plugin` GitHub topic 标注以便发现。
- `CONTRIBUTING.md` / `AGENTS.md`：开发规范。

## 5. 关键配置

### 5.1 运行模式（Mode）

| 模式 | 工具集 | 典型用途 |
|---|---|---|
| **标准模式** | 完整工具集（文件、Shell、搜索、计划、子 Agent） | 日常编码 |
| **PTC 模式** | 模型直接生成 TypeScript 程序组合多轮工具调用 | 复杂多步任务，减少往返 |
| **极简模式** | 最小工具集 | 模型基准测试 |
| **创造模式** | 运行时检查 + 插件试验 + 自定义 preset | 开发新插件、实验能力组合 |

### 5.2 Profile 与组合包

- `--profile web` 等参数选择一份基础配置；
- 组合包（bundle）在 profile 之上叠加，`dsh --profile web --dump-config` 可打印最终完整配置树；
- 插件用 `dsh plugin --profile <name> add <git-url>` 安装，源码改动无需重启即生效；bundle 则是一行安装。

### 5.3 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--port` | 3080 | Web UI 端口 |
| `--no-open` | false | 启动后不自动打开浏览器 |
| `DSH_TELEMETRY_DISABLED` | 0 | 设为 1 关闭遥测 |
| `--profile <name>` | （无） | 选择基础配置 |
| `--dump-config` | （无） | 打印启动配置树后退出 |

### 5.4 模型路由

- 支持多 provider：DeepSeek、任意 OpenAI 兼容端点；
- 不同 Agent 或不同会话可选不同 provider/model；
- 路由切换**无需重启**；
- plan 模式下默认不切模型（保持一致性）。

## 6. 安全与隐私

### 6.1 沙箱与审批

dsh 内置**沙箱插件**：文件写、Shell 执行等副作用操作，若当前权限策略标记为"需审批"，Web UI / CLI 会先弹确认框。沙箱策略本身也是插件，可替换（例如换成容器级隔离）。

### 6.2 会话日志与隐私

- 会话日志采用**仅追加**设计，本地存储，不自动上传；
- 遥测可关闭：`DSH_TELEMETRY_DISABLED=1`；
- 匿名 ID 可重置；
- **注意**：模型请求与日志贡献行为取决于你选的 provider 和 profile——用 DeepSeek 官方 API 时，提示词与工具结果会发到 DeepSeek 服务器；用本地 OpenAI 兼容端点（如 Ollama）则不出网。

### 6.3 安全须知

官方 README 在 "Run" 之前放了一段 **safety notice**，明确 dsh 处于 developer preview、核心插件与 API 频繁变动、会有不兼容修改，并提醒你审查后再在生产环境运行。Agent 有 Shell 能力，务必在隔离环境（容器 / 虚拟机 / 专用用户）中跑，不要给生产机器 root 权限。

## 7. 局限与坑

1. **Developer Preview 阶段**：API 不稳定，版本间可能不兼容；升级前读 changelog。
2. **Node.js 版本要求较新**：24.9+，老系统升级 Node 前注意全局工具兼容性。
3. **SSH 远程启动时 `--no-open` 必须加**，否则浏览器打开的是本地转发地址，会失败。
4. **插件 git 源安装后改动即时生效，但 bundle 安装需要重启 web**——文档里有区分，容易踩混。
5. **选择工作区前会话不可用**：新手容易以为"启动就能打字"，实际必须先选中工作区。
6. **模型请求隐私边界**：用云端 API 时，你的代码与提示词会离开机器；敏感项目用本地端点。
7. **PTC 模式**生成的 TypeScript 程序是模型写的，执行前同样受沙箱/审批保护，但不要默认信任其正确性。

## 8. 选型建议

| 你的需求 | 建议 |
|---|---|
| 想要"开箱即用、图形界面"的编码助手 | 先用 dsh 桌面版或 Web UI，标准模式 |
| 要嵌入产品、程序化驱动 Agent | Python / TypeScript SDK |
| 做 Agent 架构研究、可观测性 | dsh 的仅追加日志 + Trajectory 视图是现成的 |
| 想要多模型路由、不想绑厂商 | dsh 支持任意 OpenAI 兼容端点 |
| 团队已经深度使用 LangChain 生态 | dsh 可作为"Agent 运行时"，LangChain 的 prompt 工具仍可在插件层共存；但两套事件模型要权衡 |
| 只是简单补全、不想装框架 | 用 IDE 内置助手更轻 |

什么时候**不**该用 dsh：需求只是"在编辑器里 Tab 补全"，或公司已经锁定某厂商 IDE 助手且不允许自定义插件——dsh 的复杂度过高，收益不明显。

## 9. 参考

- 官方主页：https://www.deepseek.com/harness/
- GitHub 仓库：https://github.com/deepseek-ai/deepseek-harness
- 官方文档（快速入门）：https://deepseek-harness.github.io/deepseek-harness/guide/quickstart
- npm 包：`@deepseek-ai/dsh`（`npx @deepseek-ai/dsh web`）
- 插件社区：GitHub topic `dsh-plugin`
- 社区支持：GitHub Discussions
- 桌面版下载（Windows 64 / macOS Apple 芯片）：见 GitHub Releases
- Cordis 设计论文：《A Programming Paradigm for Spatiotemporal Composability》
