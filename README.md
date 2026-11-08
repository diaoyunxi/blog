# Issue → 中文博客 Agent

GitHub Issue 一创建，CI 里的 AI Agent 就按你的要求在 blog/<中文分类>/<中文主题>/ 下写 cn.md，校验改动合法后直接提交并推送到主分支，再回帖提交链接。不建分支、不开 PR。

> 本文件为文档目录；全部说明文档统一存放于 `doc/`。

## 文档目录

- [00 · 概览](doc/00-overview.md)　`本文档总述`
- [01 · 目录结构](doc/01-目录结构.md)
- [02 · 需要配置的 Secrets / Variables](doc/02-需要配置的-Secrets-Variables.md)
- [03 · 触发与流程](doc/03-触发与流程.md)
- [04 · 改动归属校验（新增放行，改/删需本人创建）](doc/04-改动归属校验-新增放行-改-删需本人创建.md)
- [05 · 改动白名单（仅 .md）](doc/05-改动白名单-仅-md.md)
- [06 · PR 自动合并（仅 .md）](doc/06-PR-自动合并-仅-md.md)
- [07 · 目录名强制中文](doc/07-目录名强制中文.md)
- [08 · 429 / 错误处理](doc/08-429-错误处理.md)
- [09 · 手动调试](doc/09-手动调试.md)
- [10 · 安全提示（重要）](doc/10-安全提示-重要.md)
- [11 · 仓库设置要求（否则推送会失败）](doc/11-仓库设置要求-否则推送会失败.md)
- [12 · 🌐 静态站点（Cloudflare Workers + Static Assets）](doc/12-静态站点-Cloudflare-Workers-Static-Assets.md)
- [AI 提示词全记录](doc/ai-prompts.md)

> `blog/` 下的 `cn.md` / `en.md` 是站点正文，`dist/` 是构建产物，二者保留原位；仅 `docs/ai-prompts.md` 收进 `doc/`。

## 保留原位的文档与资源

- [blog/人工智能/智能体应用/OpenClaw与DeepSeek Harness对比/cn.md](blog/人工智能/智能体应用/OpenClaw与DeepSeek Harness对比/cn.md)
- [blog/人工智能/智能体应用/OpenClaw开源助手/cn.md](blog/人工智能/智能体应用/OpenClaw开源助手/cn.md)
- [blog/人工智能/智能体应用/page-agent的MCP Server配置与用法/cn.md](blog/人工智能/智能体应用/page-agent的MCP Server配置与用法/cn.md)
- [blog/人工智能/智能体应用/开源智能体/cn.md](blog/人工智能/智能体应用/开源智能体/cn.md)
- [blog/人工智能/生成式模型/文生图扩散原理/cn.md](blog/人工智能/生成式模型/文生图扩散原理/cn.md)
- [blog/人工智能/生成式模型/文生图扩散原理/en.md](blog/人工智能/生成式模型/文生图扩散原理/en.md)
- [blog/前端/博客装饰/看板娘组件/cn.md](blog/前端/博客装饰/看板娘组件/cn.md)
- [blog/前端/网页增强/页内智能体/cn.md](blog/前端/网页增强/页内智能体/cn.md)
- [blog/后端/Web安全/CORS跨域共享机制/cn.md](blog/后端/Web安全/CORS跨域共享机制/cn.md)
- [blog/后端/异步运行时/Rust异步运行时Tokio/cn.md](blog/后端/异步运行时/Rust异步运行时Tokio/cn.md)
- [blog/后端/框架/极简路由框架/cn.md](blog/后端/框架/极简路由框架/cn.md)
- [blog/系统工具/包管理器/进阶包工具原理/cn.md](blog/系统工具/包管理器/进阶包工具原理/cn.md)
- [blog/系统工具/游戏谱面/自制谱规范/cn.md](blog/系统工具/游戏谱面/自制谱规范/cn.md)
- [dist/blog/人工智能/智能体应用/OpenClaw与DeepSeek Harness对比/cn.md](dist/blog/人工智能/智能体应用/OpenClaw与DeepSeek Harness对比/cn.md)
- [dist/blog/人工智能/智能体应用/OpenClaw开源助手/cn.md](dist/blog/人工智能/智能体应用/OpenClaw开源助手/cn.md)
- [dist/blog/人工智能/智能体应用/page-agent的MCP Server配置与用法/cn.md](dist/blog/人工智能/智能体应用/page-agent的MCP Server配置与用法/cn.md)
- [dist/blog/人工智能/智能体应用/开源智能体/cn.md](dist/blog/人工智能/智能体应用/开源智能体/cn.md)
- [dist/blog/人工智能/生成式模型/文生图扩散原理/cn.md](dist/blog/人工智能/生成式模型/文生图扩散原理/cn.md)
- [dist/blog/人工智能/生成式模型/文生图扩散原理/en.md](dist/blog/人工智能/生成式模型/文生图扩散原理/en.md)
- [dist/blog/前端/博客装饰/看板娘组件/cn.md](dist/blog/前端/博客装饰/看板娘组件/cn.md)
- [dist/blog/前端/网页增强/页内智能体/cn.md](dist/blog/前端/网页增强/页内智能体/cn.md)
- [dist/blog/后端/Web安全/CORS跨域共享机制/cn.md](dist/blog/后端/Web安全/CORS跨域共享机制/cn.md)
- [dist/blog/后端/异步运行时/Rust异步运行时Tokio/cn.md](dist/blog/后端/异步运行时/Rust异步运行时Tokio/cn.md)
- [dist/blog/后端/框架/极简路由框架/cn.md](dist/blog/后端/框架/极简路由框架/cn.md)
- [dist/blog/系统工具/包管理器/进阶包工具原理/cn.md](dist/blog/系统工具/包管理器/进阶包工具原理/cn.md)
- [dist/blog/系统工具/游戏谱面/自制谱规范/cn.md](dist/blog/系统工具/游戏谱面/自制谱规范/cn.md)

---

> 文档与代码一致性按 `doc/` 各分册核对；实现以仓库源码为准。
