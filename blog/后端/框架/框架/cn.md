---
title: Express 框架：从原理到用法的一次系统介绍
date: 2026-10-31
lang: zh-CN
tags: [Node.js, Express, Web框架, 中间件, 路由]
summary: 系统介绍 Express：它解决什么问题、内部怎么工作、最小示例到完整项目、常用配置、安全注意事项、常见坑与选型建议。
source_issue: https://github.com/diaoyunxi/blog/issues/18
---

# Express 框架：从原理到用法的一次系统介绍

## 背景：Express 解决什么问题

在 Node.js 早期，开发者如果想写一个 HTTP 服务，要直接调用原生的 `http.createServer`，然后手动解析 URL、手动从 `req.url` 里抠出路径、判断请求方法、解析请求体、写 Cookie——每件事都得自己写，重复且容易出错。随着项目变大，这些"通用胶水代码"会淹没真正的业务逻辑。

Express 就是为了解决这个问题而生的：它把"HTTP 服务器的通用能力"封装成一层薄薄的基础设施——**路由、中间件、请求/响应辅助方法**——让你把精力放在业务本身。它是 Node.js 生态里最老牌、最通用的 Web 框架，作者是 TJ Holowaychuk，长期由 expressjs 组织维护，至今仍是大量公司线上服务的核心。

## 定位与对比：它在同类方案里处于什么位置

Node.js 的 Web 框架大致可以分几类：

| 框架 | 定位 | 适合场景 |
| --- | --- | --- |
| **Express** | 薄、最小、不强制观点 | 单页应用后端、网站、混合、公共 HTTP API，需要灵活控制每一层 |
| **Fastify** | 高性能、JSON 优先、可插拔 | 以 JSON API 为主、对吞吐量敏感的服务 |
| **Koa** | 比 Express 更薄的中间件框架，原生 `async/await` | 团队愿意承担更多"组装"工作，追求清晰的控制流 |
| **NestJS** | 重型、面向 TypeScript、模块化 | 中大型企业后端，需要结构化架构与装饰器风格 |

它们的本质区别在于"观点"（opinion）：Express 官方定位就是 *fast, unopinionated, minimalist*——它只提供路由、中间件、HTTP 辅助方法这些"地基"，不替你选 ORM、不替你选模板引擎、不规定目录结构。好处是灵活、可控、生态中间件极多；代价是"灵活"的另一面是"你得自己做决定"。相比之下，Fastify 在吞吐量基准测试里通常更高（代价是 API 形态更"快框架"），Koa 更轻量但需要自己拼装更多，NestJS 则更重、更结构化。

> 一句话：**Express 不追求"跑最快"，追求"薄、可组合、生态大、可控"。**

## 快速上手：最短路径跑起来

### 1. 环境准备

需要先安装 Node.js。截至 2026 年，Express 5 要求 **Node.js 18 或更高**。

### 2. 初始化项目并安装

```bash
mkdir my-app && cd my-app
npm init -y
npm install express
```

### 3. 最小可运行示例（`index.js`）

```js
const express = require('express');
const app = express();
const port = 3000;

app.get('/', (req, res) => {
  res.send('Hello World!');
});

app.listen(port, () => {
  console.log(`Example app listening on port ${port}`);
});
```

运行并验证：

```bash
node index.js
# 另开一个终端
curl http://localhost:3000
# 输出: Hello World!
```

### 4. 用脚手架生成完整应用（更快）

Express 官方提供 `express-generator` 可执行文件，一次生成含目录结构、静态资源、模板的完整项目：

```bash
# 可执行文件的主版本号必须与 Express 主版本一致
npm install -g express-generator@4
express /tmp/foo && cd /tmp/foo
npm install
npm start
# 浏览器访问 http://localhost:3000
```

## 组成与原理：核心模块分别负责什么

### 1. 应用实例 `app` 与请求的生命周期

`express()` 返回一个"应用"实例，它本质上是**一条中间件链**。当 `app.listen()` 启动后，每次收到请求，Node 的 HTTP 服务器把 `req`、`res` 交给这条链，链按注册顺序逐个执行中间件，直到某个中间件调用了 `res.send()` / `res.end()` 把响应发完，或者把控制权交给下一个中间件。

一次典型请求的数据流：

```
浏览器/客户端
   ↓
Node HTTP 层（socket 连接、TCP）
   ↓
Express 应用实例（中间件链入口）
   ↓ 逐个执行
   1. 全局中间件（如 express.json()、cookie、cors…）
   2. 路由匹配（Method + Path）
   3. 路由级中间件 / 业务处理函数
   4. 错误处理中间件（4 参数的 next(err)）
   ↓
响应通过 res 写回 socket
```

### 2. 中间件（Middleware）

中间件是 Express 最核心的扩展机制。它是一个签名为 `(req, res, next) => {}` 的函数，能做四件事之一：

- **结束响应**（`res.send(...)` 后链终止）
- **执行操作后继续**（改完 `req` 再调 `next()`，链继续往下走）
- **把请求终止在某个中间件**（不调 `next()`，后续中间件不会执行）
- **传递错误**（`next(err)`，跳入错误处理中间件）

中间件可以在**应用层**、**路由层**、**子应用层**注册，作用范围不同：

```js
// 应用级：作用于所有路由
app.use((req, res, next) => {
  console.log('每个请求都会走这里');
  next();
});

// 路由级：只作用于某条路由
app.get('/user/:id', (req, res, next) => {
  console.log('仅 GET /user/:id 走这里');
  next();
}, (req, res) => {
  res.send(`You got /user/${req.params.id}`);
});
```

### 3. 路由（Router）

`express.Router()` 返回一个"路由实例"，本身也是中间件，可以嵌套组合。这是 Express 大型项目做**分层**的标准方式：

```js
// routes/users.js
const router = require('express').Router();

router.get('/', (req, res) => res.send('All users'));
router.get('/:id', (req, res) => res.send(`User ${req.params.id}`));

module.exports = router;
```

```js
// app.js
const usersRouter = require('./routes/users');
app.use('/users', usersRouter); // 所有 /users 下的请求交给该 router
```

路由路径支持：

- **通配符** `*`、正则 `:param(\\d+)`
- **路由参数** `:id`，通过 `req.params.id` 读取
- **`app.param(name, fn)`**：当某路由参数出现时执行一次预处理（v5 中 `:name` 形式的前导冒号被静默忽略）

### 4. 请求 / 响应对象

Express 在原生 `req`、`res` 之上加了一层"辅助方法"，这些是它"薄"但又好用的关键：

| 类别 | 常用方法 | 用途 |
| --- | --- | --- |
| `req` | `req.params` / `req.query` / `req.body` | 路由参数 / URL 查询 / 请求体 |
| `req` | `req.acceptsCharsets()` / `req.acceptsEncodings()` / `req.acceptsLanguages()` | 内容协商（v5 起方法名变成复数） |
| `req` | `req.get('Header-Name')` | 取请求头 |
| `res` | `res.status(code)` / `res.json(obj)` / `res.send(body)` / `res.sendFile(path)` | 发响应 |
| `res` | `res.redirect(status, url)` | 重定向（v5 参数顺序改为 status 在前） |

### 5. 视图与模板引擎

Express 内置"视图系统"，通过 `app.set('view engine', ...)` 选择模板引擎，官方支持 14 种以上（如 EJS、Pug、Handlebars，统一由 `@ladjs/consolidate` 维护）。

```js
app.set('view engine', 'ejs');
app.get('/', (req, res) => {
  res.render('home', { title: 'Hello' }); // 渲染 views/home.ejs
});
```

### 6. 静态文件与内容协商

```js
app.use(express.static('public')); // 把 public 目录映射到根路径
```

配合 `res.sendFile()`、`res.type()`、`res.format()` 可以做内容类型协商，让同一个端点根据客户端 `Accept` 头返回不同格式。

## 关键配置：常用参数与默认值

- **`express.json()` / `express.urlencoded({ extended: true })`**：解析请求体。v5 起默认内置了一个 `body-parser`，但仍建议显式注册以控制限制。
- **`app.set('trust proxy', true)`**：让 `req.ip` 在反向代理（如 Nginx、Load Balancer）后读取真实的 `X-Forwarded-For`。生产环境放在代理之后必须开。
- **`app.disable('x-powered-by')`**：关闭默认响应头，避免暴露框架信息。
- **`express.json({ limit: '10kb' })`**：限制请求体大小，防超大 payload。
- **`express.static(..., { maxAge: '7d', etag: true })`**：给静态资源加缓存。

## 安全与隐私

Express 本身不内置安全中间件，安全靠组合。生产环境强烈建议：

```js
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

app.use(helmet());                    // 设置一组安全的响应头
const limiter = rateLimit({ windowMs: 15*60*1000, max: 100 });
app.use('/api/', limiter);           // 限流，防暴力请求
app.use(express.json({ limit: '10kb' })); // 限制请求体大小
```

需要特别注意的几件事：

- **CORS**：前后端跨域时必须显式配置 `cors` 中间件，不要图省事全开 `*`。
- **密钥与敏感值**：API Key、JWT 密钥、数据库口令一律放环境变量（`process.env`），**不要写进代码**，更不要提交进仓库。
- **依赖漏洞**：Express 团队会在官方文档首页披露已知 CVE（如 2026 年的 body-parser DoS 漏洞 CVE-2026-111181），建议用 `npm audit` 与依赖更新机制跟踪。
- **路径穿越**：`res.sendFile()` 在 v5 默认对隐藏目录（`.cache`、`.git` 等）更严格，路径中含点目录会 404 除非显式 `dotfiles: 'allow'`，这是好的默认行为。

## 局限与坑：什么情况下不适用、常见报错与排查

### 什么时候 Express 不是最优选择

- **极致性能 JSON API**：基准测试中 Fastify 通常比 Express 吞吐更高；如果你的服务以"每秒几万次 JSON 调用"为目标，Fastify 或 Bun 原生 HTTP 可能更合适。
- **复杂大型架构**：Express 不强制结构，几百个路由堆在一个文件里也"能跑"，大型团队通常需要叠加 NestJS 这类有约束的框架来保证架构一致性。
- **纯静态站点 / 边缘计算**：Express 是 Node 进程模型，不适合直接部署到 Cloudflare Workers 等边缘运行时（可用 `wrangler` 改写，但生态差异大）。

### 常见坑与排查

1. **`Cannot read property of undefined` 在 `req.body` 上** —— 你忘了注册 `express.json()` 或 `express.urlencoded()`，导致请求体没被解析，`req.body` 是 `undefined`。
2. **升级到 Express 5 后某些旧写法直接崩** —— v5 是破坏性大版本。典型的变化包括：
   - `app.del()` 移除，必须用 `app.delete()`；
   - `req.param(name)` 移除，要显式用 `req.params` / `req.body` / `req.query`；
   - `res.json(obj, status)` 改成 `res.status(status).json(obj)`；
   - `res.redirect(url, status)` 改成 `res.redirect(status, url)`（参数顺序反了）；
   - `res.sendfile()` 改成 `res.sendFile()`（驼峰）；
   - `res.redirect('back')` 魔法字符串被移除，用 `req.get('Referrer') || '/'`。

   官方提供了 **codemod** 自动迁移工具，一行命令批量改代码：

   ```bash
   npx codemod@latest @expressjs/v5-migration-recipe
   # 或针对单个 codemod，例如只改 del→delete：
   npx codemod@latest @expressjs/route-del-to-delete
   ```

3. **路由参数匹配不上** —— 路径参数要用 `:name`，别忘了通过 `req.params.name` 读；正则参数写 `:id(\\d+)`。
4. **生产环境看不到真实 IP** —— 没开 `app.set('trust proxy', true)`，或反向代理没把 `X-Forwarded-For` 传进来。
5. **静态文件 404** —— 检查路径相对 `__dirname` 是否正确，容器化部署时尤其容易踩。
6. **错误被吞了** —— 中间件里的 `throw` 没接住，加一个 4 参数的错误中间件放链尾兜底：

   ```js
   // 放所有路由之后
   app.use((err, req, res, next) => {
     console.error(err.stack);
     res.status(500).send('Something broke');
   });
   ```

## 最佳实践

- **分层**：路由 / 控制器 / 服务 / 模型各放各目录，`Router` 嵌套组合；
- **中间件顺序**：先 `express.json()` 等业务解析，再业务路由，最后放兜底错误中间件；
- **错误处理**：统一在错误中间件里决定 4xx / 5xx，业务函数里用 `next(err)` 抛；
- **环境变量**：端口、密钥、数据库串都读 `process.env`，本地用 `.env` 文件 + `dotenv` 加载；
- **限流与校验**：对入口端点挂 `express-rate-limit`，对输入做 schema 校验（如 `zod`）；
- **日志**：用 `morgan` 做访问日志，生产用结构化日志（`pino`）；
- **跟踪安全通告**：订阅 expressjs GitHub 仓库，跑 `npm audit`。

## 小结

Express 是"地基"型框架：不替你设计，但把所有通用 HTTP 能力打包成最薄的接口，让你能自由组合。它的优势是**生态大、文档全、可控、上手快**；代价是**性能非顶级、不强制架构、生产安全要自己拼中间件**。只要清楚这几个边界，配合官方 codemod 跟上 v5 的破坏性变更，它是 Node.js 后端最稳妥的起点之一。

## 参考

- [Express 官方仓库](https://github.com/expressjs/express)
- [Express 官方文档](https://expressjs.com/)
- [Upgrade to Express v5 迁移指南](https://expressjs.com/en/guide/migrating-5/)
