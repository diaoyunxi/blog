/*
 * worker.js — Cloudflare Workers 入口（Static Assets）
 * 职责（替代原 Pages 的 _headers / _redirects，Workers 不自动解析它们）：
 *   1. 服务静态资产（dist/）
 *   2. /feed           → 301 到 /rss.xml
 *   3. /post/<slug>/  → SPA 外壳 index.html（200）
 *   4. 其余未匹配       → 404.html（404）
 *   5. 注入安全响应头 + 缓存策略
 */

// 安全头（对应 _headers 的 /* 规则）
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
