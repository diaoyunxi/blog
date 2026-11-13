> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「🌐 静态站点（Cloudflare Workers + Static Assets）」章节拆分而来。

## 🌐 静态站点（Cloudflare Workers + Static Assets）

仓库同时是一个**纯静态博客站点**：Agent 只负责往 `blog/` 写 Markdown，站点由前端在运行时读取并渲染，
因此**新增文章不需要改任何前端代码**——推送即上线。

站点部署为一个 **Cloudflare Worker + 静态资产**：`dist/` 经 `wrangler.toml` 的 `[assets]`
挂载，`worker.js` 作为动态入口保留备用。**绝大多数请求根本不会进 Worker**——
静态文件由边缘直出，免费且不限量。与旧 Pages 部署的关键差别：

| Pages | Workers |
|---|---|
| `pages_build_output_dir` | `[assets].directory = "dist"` |
| Pages Functions 先于静态资产执行 | 默认资产优先；只有 `run_worker_first` 列出的动态路径先跑 Worker |
| 自动识别 `index.html` / `404.html` | 需显式声明 `not_found_handling = "404-page"` |
| `_headers` / `_redirects` | Workers 原生同样支持，两个文件保留在 `dist/` 中 |

> ✅ `_headers` / `_redirects` 在 Workers 静态资产里**依然原生生效**，
> 安全头、`/feed` 跳转、`/post/*` SPA 回退与 404 都由资产层处理，不需要跑 Worker。
> `worker.js` 保留这些分支只是给动态路径做兜底。

### 架构

```
浏览器
 ├── GET /                    → index.html（唯一 HTML 外壳）
 ├── GET /posts.json          → build.mjs 生成的文章索引
 ├── GET /blog/<分类>/<主题>/cn.md → 原始 Markdown（运行时按需拉取）
 └── 渲染：marked + DOMPurify + highlight.js + KaTeX
```

- **全外链**：HTML 通过 `<link>` / `<script src>` 引用 `assets/` 下的样式与脚本，无内联样式表；
  渲染依赖走 CDN（marked / DOMPurify / highlight.js / KaTeX）。
- **样式分离**：`assets/css/base.css` 管整页与组件，`assets/css/markdown.css` 专管 Markdown 正文排版。
- **路由**：真实路径（`/`、`/post/<中文分类>/<中文主题>/`），由 `_redirects` 的
  `/post/* → /index.html 200` 做 SPA 回退；链接走 History API，中键/新标签页打开等原生行为不受影响。
- **交互**：站内搜索、分类筛选、文章目录（TOC）、代码一键复制、阅读进度、上下篇导航、明暗主题、中英切换。
- **树形导航栏**：首页主导航与文章页左侧栏共用同一个组件，按「根节点 → 分类 → 年份 → 文章」分组，每层带文章数徽标，文章行展示日期、标签与阅读时长；支持「全部展开 / 全部折叠」与当前文章高亮。配色全部沿用主题变量，图片只描述形状。

### 构建

```bash
npm run build     # = node build.mjs
```

`build.mjs` 会：扫描 `blog/` 下的 `cn.md` / `en.md` → 解析 front matter → 生成
`dist/posts.json`（文章索引，含阅读时长 `minutes`，站点据此渲染列表与树形导航）、`dist/rss.xml`、`dist/sitemap.xml`、`dist/robots.txt`
→ 拷贝 `index.html` / `assets/` / `blog/` / `_headers` / `_redirects` 到 `dist/`。

> `dist/` 即 Workers 的静态资产目录。仓库里保留了一份快照，但每次部署前都会先跑
> `node build.mjs` 重新生成，**新文章会自动进入索引**。

### 部署到 Cloudflare Workers

**方式一（推荐，CI 自动部署）**：已内置 `.github/workflows/deploy-worker.yml`。在仓库
Settings → Secrets and variables 配置 `CLOUDFLARE_API_TOKEN`（需 Workers Scripts 编辑权限）与
`CLOUDFLARE_ACCOUNT_ID` 后，`main` 每次推送都会自动构建并执行 `wrangler deploy`。
未配置这两个 Secret 时该 workflow 会安全跳过，不会让主分支 CI 变红。

**方式二（手动）**：

```bash
npm install
SITE_URL=https://你的域名 npm run deploy   # = node build.mjs && wrangler deploy
```

> 首次部署会创建名为 `diaoyunxi-blog` 的 Worker，默认地址为
> `https://diaoyunxi-blog.<账户子域>.workers.dev`。绑定自定义域名后请把 `SITE_URL` 设为该域名，
> 否则 RSS / sitemap 仍指向旧的 Pages 地址。确认 Workers 正常后即可删除原 Pages 项目，
> 避免两套部署并存。

### 请求计费与扩展 Worker 功能

Workers 的计费单位是「**Worker 脚本被调用的次数**」，不是 HTTP 请求总数。

| 请求类型 | 是否跑 Worker | 计费 |
|---|---|---|
| 命中 `dist/` 的静态文件（HTML/CSS/JS/图片/Markdown） | ❌ | 免费、不限量 |
| `_redirects` / `_headers` / `404-page` 处理的请求 | ❌ | 免费、不限量 |
| `run_worker_first` 列出的动态路径 | ✅ | 计入 Worker 请求数 |
| 未命中资产、需动态兜底的请求 | ✅ | 计入 Worker 请求数 |

免费版 10 万次/天（UTC 重置），付费版 $5/月含 1000 万次/月，超出 $0.30/百万次。
**不要**把 `run_worker_first` 改回 `true`：那会让每个 CSS、每张图片都变成一次计费调用，
一次页面打开十几个；免费版超额后这些请求还会直接返回 429 而不是退回静态资产，等于站点挂掉。

**后续要加功能**（计数器、评论、订阅、鉴权、动态 API 等）：

1. 在 `wrangler.toml` 的 `run_worker_first` 数组里登记路径（目前占位为 `["/api/*"]`）；
   若新功能要作用于**已存在的静态资产路径**（例如给 `/blog/*.md` 加鉴权），这一步是必须的，
   因为默认资产优先会绕过 Worker。
2. 在 `worker.js` 的 `fetch()` 顶部「扩展点」按 `url.pathname` 分派，需要静态文件时用
   `env.ASSETS.fetch()` 取回。
3. 需要绑定 KV / D1 / R2 / 环境变量时，加在 `wrangler.toml` 顶层即可，`worker.js` 通过 `env` 读取。

只新增 `/api/*` 这类路径时其实不加数组项也会落到 Worker（未命中资产即进入 Worker），
但显式登记更清晰，也方便以后对静态路径加逻辑。

### 本地预览

```bash
npm install
npm run dev       # = node build.mjs && wrangler dev
# 或：npm run build && python3 -m http.server -d dist
```

### 修改站点外观

- 配色、字号、间距、组件 → `assets/css/base.css`（顶部 `:root` 即设计令牌）
- 正文排版（表格、代码块、公式）→ `assets/css/markdown.css`
- 交互逻辑 → `assets/js/app.js`
- 首页 / 文章页树形导航栏 → `assets/js/app.js` 的 `renderNavBar()` / `bindNavBar()` 与 `assets/css/base.css` 的 `.nav-bar` 段
- 站点标题 / 描述 / 默认域名 → `index.html` 与 `build.mjs` 顶部的 `SITE_URL`
- 动态功能（接口、鉴权、计数、A/B）→ `worker.js` 的「扩展点」+ `wrangler.toml` 的 `run_worker_first`
