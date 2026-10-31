/* ============================================================
   build.mjs — 静态站构建脚本（Node 原生，无依赖）
   作用：扫描 blog/ 下的 cn.md / en.md，解析 front matter，
        生成 dist/posts.json、dist/rss.xml、dist/sitemap.xml，
        并把站点文件打包进 dist/（Cloudflare Pages 输出目录）。
   在 Cloudflare Pages 上，每次 push 都会重新运行，自动纳入新增文章。
   ============================================================ */
import { readFileSync, writeFileSync, mkdirSync, readdirSync, copyFileSync, existsSync, statSync, rmSync } from "node:fs";
import { join, dirname, relative, extname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const DIST = join(ROOT, "dist");
const BLOG = join(ROOT, "blog");

// 站点根地址（部署到 Cloudflare Pages 后按需修改，例如 https://你的域名）
const SITE_URL = process.env.SITE_URL || "https://diaoyunxi-blog.pages.dev";
const SITE_TITLE = "diaoyunxi · 博客";
const SITE_DESC = "由 Issue 驱动的 AI 双语博客";

/* ---------- 递归列举文件 ---------- */
function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    if (name.startsWith(".")) continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/* ---------- 解析 front matter ---------- */
function parseFrontMatter(text) {
  const fm = {};
  if (!text.startsWith("---")) return fm;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return fm;
  const block = text.slice(3, end).trim();
  for (const line of block.split("\n")) {
    const m = line.match(/^([A-Za-z0-9_-]+)\s*:\s*(.*)$/);
    if (!m) continue;
    let key = m[1], val = m[2].trim();
    if (val.startsWith("[") && val.endsWith("]")) {
      fm[key] = val.slice(1, -1).split(",").map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
    } else {
      fm[key] = val.replace(/^["']|["']$/g, "");
    }
  }
  return fm;
}

/* ---------- 生成文章索引 ---------- */
function buildPosts() {
  const files = walk(BLOG);
  const byDir = {}; // dir -> { cn, en }
  for (const f of files) {
    if (extname(f) !== ".md") continue;
    const base = relative(BLOG, f);
    const dir = dirname(base);
    const name = base.slice(dir.length + 1);
    if (name === "cn.md") (byDir[dir] = byDir[dir] || {}).cn = "/blog/" + base;
    else if (name === "en.md") (byDir[dir] = byDir[dir] || {}).en = "/blog/" + base;
  }

  const posts = [];
  for (const dir of Object.keys(byDir)) {
    const entry = byDir[dir];
    const primary = entry.cn || entry.en;
    const text = readFileSync(join(BLOG, primary.replace(/^\/blog\//, "")), "utf8");
    const fm = parseFrontMatter(text);
    const segs = dir.split("/");
    posts.push({
      slug: dir,
      category: segs.slice(0, -1).join(" / ") || segs[0],
      title: fm.title || segs[segs.length - 1],
      date: fm.date || "",
      tags: fm.tags || [],
      summary: fm.summary || "",
      lang: fm.lang || "zh-CN",
      source_issue: fm.source_issue || "",
      cn: entry.cn || null,
      en: entry.en || null,
    });
  }
  posts.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return posts;
}

/* ---------- 生成 RSS ---------- */
function buildRss(posts) {
  const items = posts.map((p) => {
    const link = `${SITE_URL}/post/${p.slug.split("/").map(encodeURIComponent).join("/")}/`;
    return `    <item>
      <title>${escapeXml(p.title)}</title>
      <link>${escapeXml(link)}</link>
      <guid isPermaLink="false">${escapeXml(p.slug)}</guid>
      <pubDate>${p.date ? new Date(p.date).toUTCString() : ""}</pubDate>
      <description>${escapeXml(p.summary || "")}</description>
    </item>`;
  }).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>${escapeXml(SITE_TITLE)}</title>
    <link>${escapeXml(SITE_URL)}</link>
    <description>${escapeXml(SITE_DESC)}</description>
    <language>zh-CN</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
${items}
  </channel>
</rss>`;
}

/* ---------- 生成 Sitemap ---------- */
function buildSitemap(posts) {
  const urls = [`<url><loc>${escapeXml(SITE_URL)}/</loc></url>`].concat(
    posts.map((p) => `<url><loc>${escapeXml(SITE_URL)}/post/${p.slug.split("/").map(encodeURIComponent).join("/")}/</loc></url>`)
  ).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>`;
}

function escapeXml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c])
  );
}

/* ---------- 拷贝文件到 dist ---------- */
function copyToDist() {
  if (existsSync(DIST)) rmSync(DIST, { recursive: true, force: true });
  mkdirSync(DIST, { recursive: true });

  const copyList = ["index.html", "404.html", "assets", "blog", "_headers", "_redirects"];
  for (const item of copyList) {
    const src = join(ROOT, item);
    if (!existsSync(src)) continue;
    const st = statSync(src);
    if (st.isDirectory()) copyDir(src, join(DIST, item));
    else copyFileSync(src, join(DIST, item));
  }
}
function copyDir(src, dest) {
  mkdirSync(dest, { recursive: true });
  for (const name of readdirSync(src)) {
    if (name.startsWith(".")) continue;
    const s = join(src, name), d = join(dest, name);
    if (statSync(s).isDirectory()) copyDir(s, d);
    else copyFileSync(s, d);
  }
}

/* ---------- 主流程 ---------- */
function main() {
  const posts = buildPosts();
  copyToDist();
  writeFileSync(join(DIST, "posts.json"), JSON.stringify({ generated: new Date().toISOString(), count: posts.length, posts }, null, 2), "utf8");
  writeFileSync(join(DIST, "rss.xml"), buildRss(posts), "utf8");
  writeFileSync(join(DIST, "sitemap.xml"), buildSitemap(posts), "utf8");
  // robots
  writeFileSync(join(DIST, "robots.txt"),
    `User-agent: *\nAllow: /\nSitemap: ${SITE_URL}/sitemap.xml\n`, "utf8");
  console.log(`✅ 构建完成：${posts.length} 篇文章 -> dist/`);
}

main();
