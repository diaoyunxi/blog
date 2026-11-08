/*
 * worker.js — Cloudflare Workers 入口（Static Assets）
 * 何时会执行到这里（其余请求由资产层直出，0 调用、0 费用）：
 *   1. wrangler.toml 的 run_worker_first 列出的动态路径（目前是 /api/*）
 *   2. 未命中任何静态资产、且未被 _redirects / not_found_handling 接住的请求
 *
 * 静态资产的常规工作已交给资产层原生能力：
 *   _headers（安全头 + 缓存）、_redirects（/feed 301、/post/* → index.html 200）、
 *   not_found_handling = "404-page"。
 * 下面这些分支是动态路径的兜底，保证即使经由 Worker 返回，行为也与 Pages 一致。
 *
 * 👉 后续加功能：在 wrangler.toml 的 run_worker_first 数组里登记路径，
 *    然后在本文件的 fetch() 顶部按 pathname 分派即可（见 "扩展点" 注释）。
 */

// 安全头（与 _headers 的 /* 规则一致；动态响应补一份，静态资产由资产层注入）
const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
  "Content-Security-Policy":
    "default-src 'self'; img-src 'self' data: https:; " +
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; " +
    "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; " +
    "script-src 'self' https://cdn.jsdelivr.net; " +
    "connect-src 'self' https://api.github.com; frame-ancestors 'none'",
};

// 缓存策略（对应 _headers 的路径级规则）
function cacheFor(pathname) {
  if (pathname.startsWith("/assets/")) return "public, max-age=31536000, immutable";
  if (pathname.startsWith("/blog/")) return "public, max-age=3600";
  return null;
}

// 取某条静态资产；ASSETS.fetch 期望绝对 URL，host 不影响匹配
function getAsset(env, request, origin, path) {
  const req = new Request(new URL(path, origin), request);
  return env.ASSETS.fetch(req);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ---- 扩展点：未来新增的动态接口在这里分派 ----
    // if (url.pathname.startsWith("/api/")) return handleApi(request, env);
    // 别忘了把路径登记进 wrangler.toml 的 run_worker_first 数组。
    const origin = url.origin;
    const pathname = url.pathname;

    // 1) /feed → /rss.xml（301）
    if (pathname === "/feed") {
      return Response.redirect(origin + "/rss.xml", 301);
    }

    // 2) 精确匹配资产（根路径归一化为 index.html）
    const want = pathname === "/" ? "/index.html" : pathname;
    let res = await getAsset(env, request, origin, want);
    let status = res.status;

    // 3) 未命中回退：/post/* 走 SPA 外壳，其余走 404
    if (status === 404) {
      if (pathname.startsWith("/post/")) {
        res = await getAsset(env, request, origin, "/index.html");
        status = 200;
      } else {
        res = await getAsset(env, request, origin, "/404.html");
        status = 404;
      }
    }

    // 4) 附加响应头
    const headers = new Headers(res.headers);
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
    const cache = cacheFor(pathname);
    if (cache) headers.set("Cache-Control", cache);

    return new Response(res.body, { status, headers });
  },
};
