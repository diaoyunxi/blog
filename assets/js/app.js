/* ============================================================
   app.js — 博客前端逻辑
   - Hash 路由（静态托管友好）： #/ 首页 · #/post/<slug> 文章
   - 读取 posts.json 索引，按需 fetch 并渲染 blog/<path>/cn.md | en.md
   - 支持 中文/EN 切换 与 明暗主题
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 配置 ---------- */
  var CONFIG = {
    postsUrl: "posts.json",
    repo: "https://github.com/diaoyunxi/blog",
    // 界面文案（随语言切换）
    i18n: {
      "zh-CN": {
        heroEyebrow: "ISSUE 驱动的 AI 双语博客",
        heroTitle: "记录 AI 与工程的思考",
        heroSubtitle: "每一篇文章都源于一个 GitHub Issue，由 AI 联网检索、撰写并自动归档。",
        articlesTitle: "全部文章",
        articlesCount: "篇",
        back: "返回首页",
        loading: "正在加载文章…",
        empty: "暂时还没有文章。",
        emptyHint: "在 GitHub 仓库新建一个 Issue，即可自动生成一篇博客。",
        readMore: "阅读",
        tags: "标签",
        postedOn: "发布于",
        category: "分类",
        source: "来源 Issue",
        notFound: "未找到该文章",
        notFoundHint: "文章可能已被移动或删除。",
        langLabel: "语言",
      },
      en: {
        heroEyebrow: "ISSUE-DRIVEN AI BILINGUAL BLOG",
        heroTitle: "Notes on AI & Engineering",
        heroSubtitle:
          "Every post starts from a GitHub Issue, researched and written by AI, then archived automatically.",
        articlesTitle: "All Articles",
        articlesCount: "posts",
        back: "Back to home",
        loading: "Loading articles…",
        empty: "No articles yet.",
        emptyHint: "Open a new Issue in the GitHub repo to generate one automatically.",
        readMore: "Read",
        tags: "Tags",
        postedOn: "Posted on",
        category: "Category",
        source: "Source Issue",
        notFound: "Article not found",
        notFoundHint: "It may have been moved or removed.",
        langLabel: "Language",
      },
    },
  };

  /* ---------- 状态 ---------- */
  var state = {
    posts: [],
    lang: localStorage.getItem("blog-lang") || "zh-CN",
    theme: localStorage.getItem("blog-theme") ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  };

  var app = document.getElementById("app");

  /* ---------- 工具 ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function t(key) {
    return (CONFIG.i18n[state.lang] && CONFIG.i18n[state.lang][key]) || key;
  }
  function fmtDate(d) {
    if (!d) return "";
    var dt = new Date(d);
    if (isNaN(dt)) return d;
    return dt.toISOString().slice(0, 10);
  }

  /* ---------- 主题 / 语言 ---------- */
  function applyTheme() {
    document.documentElement.setAttribute("data-theme", state.theme);
    var light = document.getElementById("hljs-light");
    var dark = document.getElementById("hljs-dark");
    if (light && dark) {
      if (state.theme === "dark") { light.disabled = true; dark.disabled = false; }
      else { light.disabled = false; dark.disabled = true; }
    }
    localStorage.setItem("blog-theme", state.theme);
  }
  function applyLang() {
    localStorage.setItem("blog-lang", state.lang);
    document.documentElement.setAttribute("lang", state.lang);
    document.querySelectorAll(".lang-switch button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === state.lang));
    });
  }

  /* ---------- Markdown 渲染 ---------- */
  function stripFrontMatter(md) {
    if (!md.startsWith("---")) return md;
    var end = md.indexOf("\n---", 3);
    if (end === -1) return md;
    return md.slice(end + 4).replace(/^\n+/, "");
  }

  function renderMarkdown(md) {
    var body = stripFrontMatter(md);
    var html;
    if (window.marked) {
      marked.setOptions({ gfm: true, breaks: false, headerIds: true, mangle: false });
      html = marked.parse(body);
    } else {
      // 极端降级：仅做基础段落与标题处理
      html = "<p>" + esc(body).replace(/\n{2,}/g, "</p><p>") + "</p>";
    }
    if (window.DOMPurify) {
      html = DOMPurify.sanitize(html, {
        ADD_TAGS: ["math", "semantics", "mrow", "mi", "mo", "mn", "annotation"],
        ADD_ATTR: ["href", "target", "rel", "aria-hidden"],
      });
    }
    return html;
  }

  function highlightAndMath(root) {
    if (window.hljs) {
      root.querySelectorAll("pre code").forEach(function (el) { hljs.highlightElement(el); });
    }
    if (window.renderMathInElement) {
      try {
        renderMathInElement(root, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
          ],
          throwOnError: false,
        });
      } catch (e) { /* 忽略单篇文章的数学渲染错误 */ }
    }
  }

  /* ---------- 数据加载 ---------- */
  function loadPosts() {
    return fetch(CONFIG.postsUrl + "?t=" + Date.now())
      .then(function (r) { return r.ok ? r.json() : { posts: [] }; })
      .then(function (data) { state.posts = data.posts || []; return state.posts; });
  }

  /* ---------- 渲染：首页 ---------- */
  function renderHome() {
    var L = t;
    var posts = state.posts.slice().sort(function (a, b) {
      return (b.date || "").localeCompare(a.date || "");
    });

    var html = "";
    html += '<section class="hero">';
    html += '<span class="hero__eyebrow">' + esc(L("heroEyebrow")) + "</span>";
    html += '<h1 class="hero__title">' + esc(L("heroTitle")) + "</h1>";
    html += '<p class="hero__subtitle">' + esc(L("heroSubtitle")) + "</p>";
    html += "</section>";

    html += '<section class="container">';
    html += '<div class="section-head"><h2>' + esc(L("articlesTitle")) +
      '</h2><span class="count">' + posts.length + " " + esc(L("articlesCount")) + "</span></div>";

    if (!posts.length) {
      html += '<p class="loading">' + esc(L("empty")) + "<br><small>" + esc(L("emptyHint")) + "</small></p>";
    } else {
      html += '<div class="post-grid">';
      posts.forEach(function (p) {
        var href = "#/post/" + encodeURIComponent(p.slug);
        html += '<article class="post-card" data-href="' + href + '" tabindex="0" role="link" aria-label="' + esc(p.title) + '">';
        html += '<div class="post-card__cat">' + esc(p.category || "") + "</div>";
        html += '<h3 class="post-card__title">' + esc(p.title) + "</h3>";
        html += '<p class="post-card__summary">' + esc(p.summary || "") + "</p>";
        html += '<div class="post-card__meta"><span>' + esc(fmtDate(p.date)) + "</span>";
        var langs = [];
        if (p.cn) langs.push("中文");
        if (p.en) langs.push("EN");
        html += '<span class="post-card__lang">' + langs.join(" · ") + "</span></div>";
        html += "</article>";
      });
      html += "</div>";
    }
    html += "</section>";

    app.innerHTML = html;
    app.querySelectorAll(".post-card").forEach(function (card) {
      var go = function () { location.hash = card.getAttribute("data-href"); };
      card.addEventListener("click", go);
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
      });
    });
    window.scrollTo(0, 0);
  }

  /* ---------- 渲染：文章 ---------- */
  function renderPost(slug) {
    var post = state.posts.find(function (p) { return p.slug === slug; });
    if (!post) { renderNotFound(); return; }

    // 选择语言文件
    var file = (state.lang === "en" && post.en) ? post.en : (post.cn || post.en);
    if (!file) { renderNotFound(); return; }

    app.innerHTML = '<div class="loading">' + esc(t("loading")) + "</div>";

    fetch(file + "?t=" + Date.now())
      .then(function (r) { if (!r.ok) throw new Error("404"); return r.text(); })
      .then(function (md) {
        var L = t;
        var html = "";
        html += '<article class="container--read">';
        html += '<a class="back-link" href="#/" data-link>' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>' +
          esc(L("back")) + "</a>";
        html += '<header class="article-head">';
        html += '<div class="article-head__cat">' + esc(post.category || "") + "</div>";
        html += '<h1 class="article-head__title">' + esc(post.title) + "</h1>";
        html += '<div class="article-head__meta">';
        html += "<span>" + esc(L("postedOn")) + " " + esc(fmtDate(post.date)) + "</span>";
        if (post.tags && post.tags.length) {
          html += '<span class="tag-row">';
          post.tags.forEach(function (tg) { html += '<span class="tag">' + esc(tg) + "</span>"; });
          html += "</span>";
        }
        if (post.source_issue) {
          html += '<a href="' + esc(post.source_issue) + '" target="_blank" rel="noopener">' +
            esc(L("source")) + " ↗</a>";
        }
        html += "</div></header>";
        html += '<div class="prose" id="prose"></div>';
        html += "</article>";

        app.innerHTML = html;
        var prose = document.getElementById("prose");
        prose.innerHTML = renderMarkdown(md);
        highlightAndMath(prose);
        window.scrollTo(0, 0);
      })
      .catch(function () { renderNotFound(); });
  }

  function renderNotFound() {
    app.innerHTML =
      '<div class="container" style="padding:64px 0;text-align:center">' +
      '<h1 class="hero__title" style="font-size:2rem">' + esc(t("notFound")) + "</h1>" +
      '<p style="color:var(--text-2)">' + esc(t("notFoundHint")) + "</p>" +
      '<p><a class="back-link" href="#/" data-link style="justify-content:center">' + esc(t("back")) + "</a></p>" +
      "</div>";
  }

  /* ---------- 路由 ---------- */
  function router() {
    var hash = location.hash || "#/";
    var m = hash.match(/^#\/post\/(.+)$/);
    if (m) { renderPost(decodeURIComponent(m[1])); }
    else { renderHome(); }
  }

  function boot() {
    document.getElementById("year").textContent = new Date().getFullYear();
    applyTheme();
    applyLang();

    document.getElementById("theme-toggle").addEventListener("click", function () {
      state.theme = state.theme === "dark" ? "light" : "dark";
      applyTheme();
    });
    document.querySelectorAll(".lang-switch button").forEach(function (b) {
      b.addEventListener("click", function () {
        state.lang = b.getAttribute("data-lang");
        applyLang();
        router(); // 重新渲染当前视图
      });
    });
    // 拦截站内链接，使用 hash 路由
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[data-link]");
      if (a) { e.preventDefault(); location.hash = a.getAttribute("href"); }
    });

    loadPosts().then(router).catch(function () { router(); });
    window.addEventListener("hashchange", router);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else { boot(); }
})();
