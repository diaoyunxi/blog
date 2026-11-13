---
title: CORS 跨域共享机制：原理、初衷、优缺点与绕过方法
date: 2026-11-07
lang: zh-CN
tags: [CORS, 跨域, 同源策略, Web安全, 预检请求]
summary: 从同源策略的约束出发，讲清 CORS 的 HTTP 头机制、简单请求与预检流程、配置优缺点，以及常见绕过与攻击手段。
source_issue: https://github.com/diaoyunxi/blog/issues/26
---

# CORS 跨域共享机制：原理、初衷、优缺点与绕过方法

## 背景：为什么要出现 CORS

浏览器的**同源策略（Same-Origin Policy, SOP）**要求"源 = 协议 + 域名 + 端口"三者完全一致，跨源请求默认被拦截。这导致前后端分离、CDN 跨域、API 被多方调用等场景都无法直接读取响应数据。

**CORS（Cross-Origin Resource Sharing）** 是一种基于 HTTP 响应头的浏览器安全机制，它允许服务器声明"哪些源（domain、scheme、port 之外的 origin）可以在我这儿读数据"，从而**可控地**放松同源策略。它不改变网络层，只改变浏览器对响应结果"读不读给你"这一决定。

注意：CORS 只是浏览器的"读闸口"。如果攻击者根本不需要读响应体（比如只是触发服务端动作、或目标是内网），同源策略并不能拦住，这时候要配合 **CSRF 防护**等其他手段。

## 定位与分层

CORS 涉及三层角色：

- **浏览器**：发起请求时自动带上 `Origin` 头（简单请求）或先发 `OPTIONS` 预检（非简单请求）。
- **服务器**：根据请求头返回 `Access-Control-Allow-*` 系列响应头，声明哪些源、哪些方法、哪些头被允许。
- **JavaScript 运行时**：只有当响应头与当前源匹配且满足凭据规则时，才把响应体交给脚本读取；否则只抛一个通用的网络错误，具体细节不暴露给 JS。

## 核心原理

### 1. 简单请求（Simple Request）

满足以下全部条件，浏览器可以直接发请求（不发 OPTIONS 预检），但仍需检查响应头是否允许该源：

- 方法是 `GET`、`HEAD` 或 `POST`
- 手动设置的头只能是 CORS 白名单头：`Accept`、`Accept-Language`、`Content-Language`、`Content-Type`（且只能是 `application/x-www-form-urlencoded`、`multipart/form-data`、`text/plain` 这三种之一）、`Range`（单段）
- 没有自定义其他请求头
- 没有注册 `xhr.upload` 事件监听、没有使用 `ReadableStream` 等
- 不读取响应以外的副作用

例如：

```js
fetch("https://api.other.com/data", {
  method: "GET",
  headers: { "Accept": "application/json" }
});
```

服务端响应头：

```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
```

如果只希望允许 `https://foo.example` 访问，则响应：

```http
Access-Control-Allow-Origin: https://foo.example
```

**关键规则**：如果请求携带凭据（Cookie / HTTP Auth），则 `Access-Control-Allow-Origin` **不能是 `*`**，必须明确回显具体源。

### 2. 非简单请求：预检（Preflight）

不满足上面简单条件的请求（自定义头、`PUT`/`DELETE`、JSON body 等），浏览器会先发一个 `OPTIONS` 预检：

```http
OPTIONS /doc HTTP/1.1
Host: bar.other
Origin: https://foo.example
Access-Control-Request-Method: POST
Access-Control-Request-Headers: content-type,x-pingother
```

服务端批准时返回：

```http
HTTP/1.1 204 No Content
Access-Control-Allow-Origin: https://foo.example
Access-Control-Allow-Methods: POST, GET, OPTIONS
Access-Control-Allow-Headers: X-PINGOTHER, Content-Type
Access-Control-Max-Age: 86400
```

- `Access-Control-Max-Age`：预检结果的缓存秒数，减少重复 OPTIONS。
- 只有预检通过（且源匹配）后，浏览器才会发出真正的 `POST /doc` 请求。

### 3. 核心请求/响应头速查

请求头（浏览器或库可自动填充，开发者一般不手工设）：

| 头 | 作用 |
|---|---|
| `Origin` | 标记发起方源 |
| `Access-Control-Request-Method` | 预检：实际方法 |
| `Access-Control-Request-Headers` | 预检：实际要发的自定义头 |

响应头（服务端控制）：

| 头 | 作用 |
|---|---|
| `Access-Control-Allow-Origin` | 允许哪些 origin 读响应；`*` 表示任意源（无凭据时） |
| `Access-Control-Allow-Methods` | 允许的方法 |
| `Access-Control-Allow-Headers` | 允许的自定义头 |
| `Access-Control-Allow-Credentials` | `true` 时允许携带 Cookie / 认证信息（此头存在时 `ACAO` 不能用 `*`） |
| `Access-Control-Expose-Headers` | 让 JS 能读取哪些非默认响应头 |
| `Access-Control-Max-Age` | 预检缓存 |
| `Vary: Origin` | 告诉中间缓存：同一 URL 按 Origin 区分（**强烈建议加上**，否则 CDN / 代理可能把 A 源的 `ACAO: A` 缓存后返回给 B 源） |

## 常用配置示例

### Nginx 片段

```nginx
location /api/ {
  # 回显 Origin（生产环境务必换成白名单校验，禁止 * 或任意回显）
  add_header Access-Control-Allow-Origin $http_origin;
  add_header Access-Control-Allow-Credentials true;
  add_header Access-Control-Allow-Methods "GET,POST,PUT,DELETE,OPTIONS";
  add_header Access-Control-Allow-Headers "Content-Type,Authorization";
  add_header Vary Origin;

  if ($request_method = OPTIONS) {
    add_header Access-Control-Allow-Origin $http_origin;
    add_header Access-Control-Allow-Credentials true;
    add_header Access-Control-Allow-Methods "GET,POST,PUT,DELETE,OPTIONS";
    add_header Access-Control-Allow-Headers "Content-Type,Authorization";
    add_header Access-Control-Max-Age 86400;
    add_header Vary Origin;
    return 204;
  }
}
```

### Node/Express 示例（白名单校验）

```js
const allowedOrigins = ["https://foo.example"];
app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (allowedOrigins.includes(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Access-Control-Allow-Credentials", "true");
  }
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});
```

## 优点

1. **精细控制**：相比把 API 域名换成前端子域名的土办法，可以按源、按方法、按头、按凭据粒度开放。
2. **兼容性强**：所有现代浏览器支持（Baseline 级别，2015 年起主流浏览器实现），无需前端代理。
3. **对简单请求零额外开销**：表单提交、`GET` 等不会触发 OPTIONS。
4. **支持凭据场景**：`ACAC: true` 允许带 Cookie 调用，适合前后端分离且用 Cookie 会话的项目。
5. **服务器说了算**：浏览器只是执行者，策略由服务端响应头决定，便于按业务动态调整。

## 缺点

1. **配置易错**：漏加 `Vary: Origin`、忘记处理 `OPTIONS`、`ACAO: *` 与凭据混用、白名单写前缀/后缀匹配，都会造成安全漏洞或跨域失败。
2. **跨源读数据 ≠ 跨源访问**：CORS 不阻止发送请求本身（比如 `<img>`、`<form>` 动作可以打到别处），它只限制"脚本能不能读响应体"，因此不能替代 CSRF 防护。
3. **调试不透明**：浏览器出于安全故意对 JS 隐藏失败细节，只能在控制台看网络面板；不同浏览器行为（特别是 `null` origin、Sandbox iframe）存在差异。
4. **缓存坑**：中间层（CDN、反代）若未缓存 `Vary: Origin`，会把某源的 `ACAO` 误发给另一源。
5. **预检成本**：非简单请求多一次 OPTIONS 往返，延迟增大；`Access-Control-Max-Age` 配小了会重复预检。

## 常见绕过 / 攻击手法（及对应防护）

以下攻击均要求目标响应 **`Access-Control-Allow-Credentials: true`**（或至少 `*` 但允许无凭据读到敏感数据）才真正有效。

### 1. 动态回显 Origin（反射型）

服务器直接 `Access-Control-Allow-Origin: $http_origin` 不加校验。

攻击：任意恶意站点 `https://evil.com` 发起带 Cookie 的跨域请求即可读取响应并回传。

防护：**只回显白名单内的 Origin**，不要信任客户端带来的 Origin 字符串本身。

### 2. 白名单匹配错误

- **前缀 / 后缀匹配**：允许 `*.example.com`，攻击者注册 `evil.example.com`（前缀匹配）或 `example.com.evil.net`（后缀匹配，如 `hackersnormal-website.com`）。
- **正则写法过宽**：把 `https://a.example.com` 写成 `https://a\.example\.com$` 容易误伤 `evil-a.example.com`。

防护：用**精确域名数组**或**严格子域校验**（`origin.endsWith(".example.com") && origin !== "example.com"` 这类），并显式排除 scheme。

### 3. 把 `null` 当 Origin 白名单

浏览器在以下情况会发 `Origin: null`：跨域重定向、序列化数据请求、`file:` 协议、Sandbox iframe（`sandbox="allow-scripts"` 的 iframe 内 fetch 跨域时 Origin 为 null）。

攻击：Sandbox iframe 里发起带 Cookie 请求，服务端若信任 `null`，等价于开放给任何 iframe。

防护：**白名单里绝不包含字符串 `null`**；若确需本地开发支持，用独立开发域名，不要生产环境放行。

### 4. 把有 XSS 漏洞的子域加入白名单

CORS 建立的是"两个源之间的信任"。若 `sub.vulnerable.com` 有 XSS，攻击者可注入 JS 在该子域内发起跨域请求读取 `vulnerable.com` 的敏感 API。

防护：不要仅凭"是我子域"就加入白名单；子域必须通过完整的安全审计。

### 5. 混合 scheme（HTTP 白名单进 HTTPS 主站）

白名单里允许 `http://trusted.example.com`，攻击者劫持该明文子域（中间人 / 重定向）后，可伪造跨域请求读主站数据，即使主站是 HTTPS。

防护：白名单中**只允许 https 源**；子域一律启用 HSTS；不在白名单中混入 http scheme。

### 6. 内网 / 无凭据场景

攻击者无法直连内网时，可利用内网里某台设备的 `Access-Control-Allow-Origin: *`，把公网浏览器当作跳板读内网 API。

防护：内网 API 不要无条件 `*`；结合网络层 ACL 与 CORS 白名单。

## 实操排查清单（遇到跨域失败时）

1. 打开 DevTools → Network，看预检 OPTIONS 是否 204/200。
2. 看请求有没有 `Origin`（`data:` 协议或 `file:` 下可能变 `null`）。
3. 看响应 `Access-Control-Allow-Origin` 是否回显当前源；`*` 与凭据是否冲突。
4. 看 `Vary: Origin` 是否在，检查 CDN 缓存。
5. 看是否遗漏 `Access-Control-Allow-Credentials`、`Access-Control-Expose-Headers`。
6. 浏览器 CORS 报错故意模糊，**不要靠 JS 的 catch 信息**排查，直接看 Network 面板。

## 小结

CORS 是把"谁能读"的决定权交给服务端的响应头。它的**初衷**是在保留同源策略默认安全性的前提下，让前后端分离与多源协作成为可能；**优点**是粒度细、兼容好、服务端主导；**缺点**是配置稍有不慎就成漏洞，且它不替代 CSRF 防护。绕过/攻击手段几乎都围绕**"反射 Origin""白名单匹配错""null / 子域 / 混合 scheme 误入白名单"**三条主线，防御的核心只有一句话：**白名单精确、凭据按需、`Vary: Origin` 必加、http 源不入白名单**。

## 参考

- MDN：[CORS - HTTP | MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)
- PortSwigger Web Security Academy：[CORS 教程与常见漏洞](https://portswigger.net/web-security/cors)
