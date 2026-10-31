---
title: 在博客中加入 Live2D 看板娘：live2d-widget 实战
date: 2026-10-31
lang: zh-CN
tags: [Live2D, 博客, 前端, 看板娘]
summary: 介绍开源项目 live2d-widget 的功能、实现原理与多种部署方式，帮助你在博客中轻松加入会互动的 Live2D 看板娘。
source_issue: https://github.com/diaoyunxi/blog/issues/15
---

## 背景

Live2D 看板娘（也常被称为「动态壁纸娘」）是很多技术博客的标配装饰：页面角落漂浮一个 2D 动画角色，鼠标悬停、点击按钮时会有气泡提示和互动效果，给纯文字博客增添不少生气。

[stevenjoezhang/live2d-widget](https://github.com/stevenjoezhang/live2d-widget) 是目前最流行的开源方案之一，口号是「把萌萌哒的看板娘抱回家」。它**轻量级**——除 Live2D Cubism Core 外无其他运行时依赖，核心代码由 TypeScript 编写，易于集成。

> 注意：本仓库**不包含任何角色模型**，所有展示用模型的版权归原作者所有，不得用于商业用途。

## 核心概念与原理

`live2d-widget` 的核心思路分三层：

1. **资源加载层**：`autoload.js` 会自动拉取 `waifu.css`（样式）与 `waifu-tips.js`（交互逻辑），并暴露全局函数 `initWidget`。
2. **渲染层**：`waifu-tips.js` 调用 `initWidget(config)` 初始化看板娘，通过 Live2D Cubism Core 渲染模型。Cubism Core 会根据模型版本**动态加载**：Cubism 2 模型加载 `live2d.min.js`（`cubism2Path`），Cubism 3+ 模型加载官方 `live2dcubismcore.min.js`（`cubism5Path`），以减小体积。
3. **交互层**：`waifu-tips.json` 定义了基于 **CSS 选择器**的触发规则——当页面匹配某选择器时，看板娘会显示对应的提示文字，实现「评论表单被聚焦」「标签页切换」等场景化互动。

自 1.0 版本起，**不再需要后端 API**：旧版本的 `apiPath` 参数已废弃，模型资源全部通过静态方式提供，只要存在 `model_list.json` 和模型对应的 `textures.cache`，即可支持换装等功能。

### 主要配置项

| 选项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `waifuPath` | string | jsDelivr 上的 `waifu-tips.json` | 看板娘资源路径 |
| `cdnPath` | string | jsDelivr 上的 `fghrsh/live2d_api` | 模型仓库 CDN 路径 |
| `modelId` | number | `0` | 默认使用的模型 id |
| `tools` | string[] | 若干 | 显示的小工具按钮 |
| `drag` | boolean | `false` | 是否支持拖动看板娘 |
| `showToggleAfterQuit` | boolean | `true` | 点击关闭后是否显示重新唤起按钮 |
| `logLevel` | string | `error` | 日志等级：`error`/`warn`/`info`/`trace` |

## 使用方法

### 一、最简方式（一行代码）

将下面这行加入 HTML 的 `<head>` 或 `<body>` 中即可：

```html
<script src="https://fastly.jsdelivr.net/npm/live2d-widgets@1.0.1/dist/autoload.js"></script>
```

对于 Hexo 等静态博客，需要在主题的模板文件中添加；若网站启用了 PJAX，需将该脚本放到 PJAX 刷新区域之外，避免每次翻页都重新加载看板娘。

### 二、本地开发（可深度定制）

```bash
git clone https://github.com/stevenjoezhang/live2d-widget.git
cd live2d-widget
npm install
```

**如果需要 Cubism 3+ 模型**，还需单独下载 [Cubism SDK for Web](https://www.live2d.com/en/)，解压到 `src/` 目录（例如 `src/CubismSdkForWeb-5-r.4`）。Cubism 2 模型可跳过此步。

```bash
npm run build
```

编译流程：`src/`（TypeScript）→ `build/` → `dist/`（可直接使用的网页文件）。

### 三、部署方式

**1. 通过 jsDelivr CDN 加载 Fork 仓库**

Fork 本仓库并修改后推送，然后在页面中引用：

```html
<script src="https://fastly.jsdelivr.net/gh/你的用户名/live2d-widget@latest/autoload.js"></script>
```

注意：修改后需**创建新的 git tag 并推送**，`@latest` 才会指向更新后的文件；CDN 缓存也可能延迟生效。

**2. Cloudflare Pages 部署**

在 Cloudflare Pages 中创建项目并关联 Fork 仓库，构建命令设为 `npm run build` 即可。

**3. 自托管（Self-host）**

将 `dist/` 目录下的文件放到你的服务器上，修改 `autoload.js` 中的 `live2d_path` 常量为 `dist` 目录的完整 URL（**末尾必须带 `/`**），然后正常引入 `autoload.js`：

```html
<script src="https://example.com/path/to/live2d-widget/dist/autoload.js"></script>
```

## 常见坑

- **模型版本不匹配**：默认 `cdnPath` 指向的模型是 Cubism 2 格式，如果换成了 Cubism 5 模型但 Core 路径没改，会渲染失败。
- **Hexo 静态博客**：把 live2d-widget 文件放在博客源文件目录（如 `source/`）下，重新部署时会自动上传；可能需要设置 Hexo 的 `skip_render` 防止文件被插件错误修改。
- **PJAX 冲突**：启用了 PJAX 的网站，看板娘不必每页刷新，`autoload.js` 必须放在 PJAX 区域外。
- **`waifu-tips.json` 的默认选择器规则**针对 Hexo NexT 主题，其他主题需要自行调整 CSS 选择器。
- **内容合规**：`waifu-tips.json` 中的提示文字可能不适合所有场合，工作网站使用前请自行审查。

## 小结

`live2d-widget` 用极低的接入成本（一行 script 标签）给博客带来高度可定制的 Live2D 互动看板娘，支持 Cubism 2/3/5 多版本模型、静态资源部署、无后端依赖，是技术博客「萌化」改造的首选方案。深度定制时可 Fork 后修改 `waifu-tips.json`、按钮交互和样式，通过 CDN 或自托管完成部署。

## 参考

- [stevenjoezhang/live2d-widget GitHub 仓库](https://github.com/stevenjoezhang/live2d-widget)
- [Live2D 官方网站](https://www.live2d.com/en/)
