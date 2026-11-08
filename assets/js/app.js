/* ============================================================
   app.js — 博客前端逻辑
   - 真实路径路由： /            首页（?q=关键词&cat=分类）
                  /post/<slug>/ 文章
     （配合 Workers 的 worker.js / _redirects 做 SPA 回退）
   - 读取 posts.json 索引，按需 fetch 并渲染 /blog/<path>/cn.md | en.md
   - 站内搜索 / 分类筛选 / 目录导航 / 代码复制 / 阅读进度 / 上下篇
   - 中文·EN 切换 与 明暗主题
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 配置 ---------- */
  var CONFIG = {
    postsUrl: "/posts.json",
    siteName: "diaoyunxi · 博客",
    i18n: {
      "zh-CN": {
        heroEyebrow: "ISSUE 驱动的 AI 双语博客",
        heroTitle: "记录 AI 与工程的思考",
        heroSubtitle: "每一篇文章都源于一个 GitHub Issue，由 AI 联网检索、撰写并自动归档。",
        articlesTitle: "全部文章",
        articlesCount: "篇",
        allCategories: "全部分类",
        back: "返回首页",
        loading: "正在加载文章…",
        empty: "没有匹配的文章。",
        emptyHint: "换个关键词，或点「全部分类」重置筛选。",
        postedOn: "发布于",
        category: "分类",
        source: "来源 Issue",
        notFound: "未找到该文章",
        notFoundHint: "文章可能已被移动或删除。",
        searchPlaceholder: "搜索标题、摘要、标签…",
        searchEmpty: "没有匹配的结果",
        copy: "复制",
        copied: "已复制",
        tocTitle: "目录",
        prev: "上一篇",
        next: "下一篇",
        minutes: "分钟",
        treeTitle: "目录",
        browseTree: "按目录浏览",
        enterFolder: "只看这个目录",
        navLabel: "文章导航",
        expandAll: "全部展开",
        collapseAll: "全部折叠",
        blogRoot: "我的博客",
        postsUnit: "篇",
        untagged: "随笔",
        undated: "未标日期",
        unclassified: "未分类",
      },
      en: {
        heroEyebrow: "ISSUE-DRIVEN AI BILINGUAL BLOG",
        heroTitle: "Notes on AI & Engineering",
        heroSubtitle:
          "Every post starts from a GitHub Issue, researched and written by AI, then archived automatically.",
        articlesTitle: "All Articles",
        articlesCount: "posts",
        allCategories: "All",
        back: "Back to home",
        loading: "Loading articles…",
        empty: "No matching articles.",
        emptyHint: "Try another keyword, or reset the filter with “All”.",
        postedOn: "Posted on",
        category: "Category",
        source: "Source Issue",
        notFound: "Article not found",
        notFoundHint: "It may have been moved or removed.",
        searchPlaceholder: "Search title, summary, tags…",
        searchEmpty: "No matches",
        copy: "Copy",
        copied: "Copied",
        tocTitle: "On this page",
        prev: "Previous",
        next: "Next",
        minutes: " min read",
        treeTitle: "Directory",
        browseTree: "Browse by folder",
        enterFolder: "Only this folder",
        navLabel: "Article navigation",
        expandAll: "Expand all",
        collapseAll: "Collapse all",
        blogRoot: "My Blog",
        postsUnit: "posts",
        untagged: "Note",
        undated: "Undated",
        unclassified: "Uncategorized",
      },
    },
  };

  /* ---------- 状态 ---------- */
  var state = {
    posts: [],
    lang: localStorage.getItem("blog-lang") || "zh-CN",
    theme:
      localStorage.getItem("blog-theme") ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"),
    query: "",
    // 目录树聚焦路径（对应 blog/ 下的真实目录路径，如 "系统工具/包管理器"）
    category: "",
    tocObserver: null,
  };

  var app = document.getElementById("app");

  /* ---------- 工具 ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function t(key) {
    var m = CONFIG.i18n[state.lang] || CONFIG.i18n["zh-CN"];
    return m[key] !== undefined ? m[key] : key;
  }
  function fmtDate(d) {
    if (!d) return "";
    var dt = new Date(d);
    if (isNaN(dt.getTime())) return d;
    return dt.toISOString().slice(0, 10);
  }
  function byDateDesc(a, b) {
    return (b.date || "").localeCompare(a.date || "");
  }
  function normalized(s) {
    return String(s || "").toLowerCase();
  }

  /* ---------- URL ---------- */
  function postUrl(slug) {
    return "/post/" + String(slug).split("/").map(encodeURIComponent).join("/") + "/";
  }
  function parseRoute() {
    var path;
    try { path = decodeURIComponent(location.pathname); } catch (e) { path = location.pathname; }
    var m = path.match(/^\/post\/(.+?)\/?$/);
    if (m) return { view: "post", slug: m[1] };
    var params = new URLSearchParams(location.search);
    return { view: "home", q: params.get("q") || "", cat: normPath(params.get("cat") || "") };
  }
  function navigate(url, replace) {
    if (replace) history.replaceState(null, "", url);
    else history.pushState(null, "", url);
    router();
  }
  function syncUrl() {
    var url = "/";
    var parts = [];
    if (state.query) parts.push("q=" + encodeURIComponent(state.query));
    if (state.category) parts.push("cat=" + encodeURIComponent(state.category));
    if (parts.length) url += "?" + parts.join("&");
    history.replaceState(null, "", url);
  }

  /* ---------- 主题 / 语言 ---------- */
  function applyTheme() {
    document.documentElement.setAttribute("data-theme", state.theme);
    localStorage.setItem("blog-theme", state.theme);
  }
  function applyLang() {
    localStorage.setItem("blog-lang", state.lang);
    document.documentElement.setAttribute("lang", state.lang);
    document.querySelectorAll(".lang-switch button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === state.lang));
    });
    var sp = document.getElementById("search-input");
    if (sp) sp.placeholder = t("searchPlaceholder");
  }
  function setMeta(name, content) {
    var el = document.querySelector('meta[name="' + name + '"]');
    if (el) el.setAttribute("content", content);
  }
  function setTitle(title) {
    document.title = title ? title + " · " + CONFIG.siteName : CONFIG.siteName;
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
      marked.setOptions({ gfm: true, breaks: false });
      html = marked.parse(body);
    } else {
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
      } catch (e) { /* 单篇公式渲染失败不影响正文 */ }
    }
  }

  /* ---------- 正文增强：代码复制 + 标题锚点 ---------- */
  function decorateProse(prose) {
    // 可横向滚动的区域（代码块 / 宽表格）需可聚焦，便于键盘用户滚动
    prose.querySelectorAll("pre, table, pre code").forEach(function (el) {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    });
    prose.querySelectorAll("pre").forEach(function (pre) {
      if (pre.parentElement && pre.parentElement.classList.contains("code-wrap")) return;
      var wrap = document.createElement("div");
      wrap.className = "code-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = t("copy");
      btn.setAttribute("aria-label", t("copy"));
      btn.addEventListener("click", function () {
        var code = wrap.querySelector("code");
        var text = code ? code.innerText : "";
        var done = function () {
          btn.textContent = t("copied");
          btn.classList.add("is-done");
          setTimeout(function () {
            btn.textContent = t("copy");
            btn.classList.remove("is-done");
          }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(fallbackCopy);
        } else {
          fallbackCopy();
        }
        function fallbackCopy() {
          var ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand("copy"); done(); } catch (e) { /* 忽略 */ }
          document.body.removeChild(ta);
        }
      });
      wrap.appendChild(btn);
    });
  }

  /* ---------- 目录（TOC） ---------- */
  function buildToc(prose) {
    var heads = Array.prototype.slice.call(prose.querySelectorAll("h2, h3"));
    return heads.map(function (h, i) {
      if (!h.id) h.id = "sec-" + i;
      return { id: h.id, text: (h.textContent || "").trim(), level: h.tagName === "H2" ? 2 : 3 };
    });
  }

  function renderToc(items) {
    if (!items.length) return "";
    var html = '<details class="toc" id="toc">';
    html += '<summary class="toc__title">' + esc(t("tocTitle")) + "</summary>";
    html += '<ul class="toc__list">';
    items.forEach(function (it) {
      html += '<li class="toc__item toc__item--h' + it.level + '">' +
        '<a href="#' + esc(it.id) + '" data-toc="' + esc(it.id) + '">' + esc(it.text) + "</a></li>";
    });
    html += "</ul></details>";
    return html;
  }

  function syncTocOpen() {
    var d = document.getElementById("toc");
    if (!d) return;
    var wide = window.matchMedia("(min-width: 1200px)").matches;
    d.open = wide;
  }

  function bindToc(prose, aside) {
    if (!aside) return;
    aside.querySelectorAll("[data-toc]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        var el = document.getElementById(a.getAttribute("data-toc"));
        if (!el) return;
        var top = el.getBoundingClientRect().top + window.pageYOffset - 88;
        window.scrollTo({ top: top, behavior: "smooth" });
      });
    });

    if (state.tocObserver) state.tocObserver.disconnect();
    var links = Array.prototype.slice.call(aside.querySelectorAll("[data-toc]"));
    if (!("IntersectionObserver" in window)) return;
    state.tocObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          var id = en.target.id;
          links.forEach(function (l) {
            l.classList.toggle("is-active", l.getAttribute("data-toc") === id);
          });
        });
      },
      { rootMargin: "-88px 0px -70% 0px", threshold: 0 }
    );
    prose.querySelectorAll("h2, h3").forEach(function (h) { state.tocObserver.observe(h); });
  }

  /* ---------- 数据加载 ---------- */
  function loadPosts() {
    return fetch(CONFIG.postsUrl + "?t=" + Date.now())
      .then(function (r) { return r.ok ? r.json() : { posts: [] }; })
      .then(function (data) {
        state.posts = data.posts || [];
        return state.posts;
      });
  }

  /* ---------- 筛选 ---------- */
  function queryMatches(p, q) {
    if (!q) return true;
    var hay = normalized(
      [p.title, p.summary, p.category, p.slug].concat(p.tags || []).join(" ")
    );
    return hay.indexOf(q) !== -1;
  }

  // 分类筛选改为「目录前缀」匹配：选中某目录就只看它（含全部子目录）下的文章
  function normPath(s) { return String(s || "").replace(/\s*\/\s*/g, "/").replace(/^\/|\/$/g, ""); }
  function inPath(p, prefix) {
    if (!prefix) return true;
    return p.slug === prefix || p.slug.indexOf(prefix + "/") === 0;
  }
  function filteredPosts() {
    var q = normalized(state.query.trim());
    var prefix = normPath(state.category);
    return state.posts
      .filter(function (p) {
        if (!inPath(p, prefix)) return false;
        return queryMatches(p, q);
      })
      .sort(byDateDesc);
  }

  /* ---------- 渲染：树形导航栏（首页主导航 / 文章页左侧导航共用） ----------
     形状：根节点「我的博客」→ 分类文件夹 → 年份文件夹 → 文章行（日期 / 标签 / 阅读时长）；
     每层带数量徽标，支持全部展开 / 全部折叠、当前文章高亮。
     只复用站点主题变量，不引入新的主题色。 */
  var NAV_ICON_FOLDER =
    '<svg class="nav-tree__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.2a2 2 0 0 1 1.5.7l1 1.1H18.5A2.5 2.5 0 0 1 21 9.3v7.2a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5v-9z"/></svg>';
  var NAV_ICON_YEAR =
    '<svg class="nav-tree__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 9.5h17M8 3.5v3M16 3.5v3"/></svg>';
  var NAV_ICON_FILE =
    '<svg class="nav-tree__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3.5H7.5A2 2 0 0 0 5.5 5.5v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8.5z"/><path d="M14 3.5v5h5"/></svg>';
  var NAV_ICON_CHEV =
    '<svg class="nav-tree__chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  function navShortDate(p) {
    var d = fmtDate(p.date);
    return d && d.length >= 10 ? d.slice(5) : d;
  }
  function navYear(p) {
    var d = fmtDate(p.date);
    return d && d.length >= 4 ? d.slice(0, 4) : t("undated");
  }
  function navTag(p) {
    return (p.tags && p.tags.length && p.tags[0]) || t("untagged");
  }
  function navMinutes(p) {
    if (p.minutes) return p.minutes;
    // 旧版 posts.json 没有 minutes 时，用摘要长度兜底估算
    return Math.max(1, Math.round(String(p.summary || p.title || "").length / 500));
  }

  // 聚合：一级分类 → 年份 → 文章（按日期倒序）
  function buildNavGroups(posts) {
    var groups = [];
    var index = Object.create(null);
    posts.slice().sort(byDateDesc).forEach(function (p) {
      var segs = String(p.slug || "").split("/");
      var cat = segs[0] || t("unclassified");
      var year = navYear(p);
      if (!index[cat]) {
        index[cat] = { name: cat, path: cat, count: 0, years: [], yearIndex: Object.create(null) };
        groups.push(index[cat]);
      }
      var g = index[cat];
      g.count++;
      if (!g.yearIndex[year]) {
        g.yearIndex[year] = { name: year, count: 0, posts: [] };
        g.years.push(g.yearIndex[year]);
      }
      var y = g.yearIndex[year];
      y.count++;
      y.posts.push(p);
    });
    groups.forEach(function (g) {
      g.years.sort(function (a, b) { return b.name.localeCompare(a.name); });
    });
    groups.sort(function (a, b) { return a.name.localeCompare(b.name, "zh-Hans-CN"); });
    return groups;
  }

  function navChevron(open, key) {
    return '<button type="button" class="nav-tree__toggle" data-navtoggle="' + esc(key) +
      '" aria-expanded="' + (open ? "true" : "false") + '" aria-label="' +
      esc(open ? t("collapseAll") : t("expandAll")) + '">' + NAV_ICON_CHEV + "</button>";
  }

  function renderNavBar(posts, currentSlug, focusCat) {
    var groups = buildNavGroups(posts);
    var cur = null;
    if (currentSlug) {
      for (var i = 0; i < posts.length; i++) {
        if (posts[i].slug === currentSlug) { cur = posts[i]; break; }
      }
    }
    var activeCat = cur ? String(cur.slug).split("/")[0] : (focusCat ? String(focusCat).split("/")[0] : "");
    var activeYear = cur ? navYear(cur) : "";

    var html = "";
    html += '<nav class="nav-bar" aria-label="' + esc(t("navLabel")) + '">';
    html += '<div class="nav-bar__tools">';
    html += '<button type="button" class="nav-bar__btn" data-nav-all="open">' + esc(t("expandAll")) + "</button>";
    html += '<button type="button" class="nav-bar__btn" data-nav-all="close">' + esc(t("collapseAll")) + "</button>";
    html += "</div>";
    html += '<div class="nav-tree">';
    html += '<div class="nav-tree__root">';
    html += '<span class="nav-tree__toggle nav-tree__toggle--leaf" aria-hidden="true"></span>';
    html += NAV_ICON_FOLDER;
    html += '<span class="nav-tree__label">' + esc(t("blogRoot")) + "</span>";
    html += '<span class="nav-tree__count">' + posts.length + " " + esc(t("postsUnit")) + "</span>";
    html += "</div>";
    html += '<ul class="nav-tree__list">';

    groups.forEach(function (g, gi) {
      var catActive = activeCat && g.name === activeCat;
      html += '<li class="nav-tree__item">';
      html += '<div class="nav-tree__row nav-tree__row--folder' + (catActive ? " is-active" : "") + '">';
      html += navChevron(true, "cat-" + gi);
      html += NAV_ICON_FOLDER;
      html += '<a class="nav-tree__label" href="/?cat=' + encodeURIComponent(g.path) +
        '" title="' + esc(t("enterFolder")) + '">' + esc(g.name) + "</a>";
      html += '<span class="nav-tree__count">' + g.count + "</span>";
      html += "</div>";
      html += '<ul class="nav-tree__children">';
      g.years.forEach(function (y, yi) {
        // 文章页展开当前文章所在年份；首页默认展开每个分类下最新的年份
        var yearOpen = (activeYear && y.name === activeYear) || (!activeYear && yi === 0);
        var yearActive = catActive && activeYear && y.name === activeYear;
        html += '<li class="nav-tree__item">';
        html += '<div class="nav-tree__row nav-tree__row--folder nav-tree__row--year' +
          (yearActive ? " is-active" : "") + '">';
        html += navChevron(yearOpen, "cat-" + gi + "-year-" + yi);
        html += NAV_ICON_YEAR;
        html += '<span class="nav-tree__label">' + esc(y.name) + "</span>";
        html += '<span class="nav-tree__count">' + y.count + "</span>";
        html += "</div>";
        html += '<ul class="nav-tree__children"' + (yearOpen ? "" : " hidden") + ">";
        y.posts.forEach(function (p) {
          var isCur = currentSlug && p.slug === currentSlug;
          html += '<li class="nav-tree__item">';
          html += '<div class="nav-tree__row nav-tree__row--post' + (isCur ? " is-current" : "") + '">';
          html += '<span class="nav-tree__toggle nav-tree__toggle--leaf" aria-hidden="true"></span>';
          html += NAV_ICON_FILE;
          html += '<a class="nav-tree__title" href="' + postUrl(p.slug) + '">' + esc(p.title) + "</a>";
          html += '<span class="nav-tree__date">' + esc(navShortDate(p)) + "</span>";
          html += '<span class="nav-tree__tag">' + esc(navTag(p)) + "</span>";
          html += '<span class="nav-tree__mins">' + navMinutes(p) + " min</span>";
          html += "</div></li>";
        });
        html += "</ul></li>";
      });
      html += "</ul></li>";
    });

    html += "</ul></div></nav>";
    return html;
  }

  function bindNavBar(scope) {
    if (!scope) return;
    scope.querySelectorAll("[data-navtoggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var box = btn.parentElement && btn.parentElement.nextElementSibling;
        if (!box || !box.classList.contains("nav-tree__children")) return;
        var open = box.hasAttribute("hidden");
        if (open) box.removeAttribute("hidden");
        else box.setAttribute("hidden", "");
        btn.setAttribute("aria-expanded", String(open));
      });
    });
    scope.querySelectorAll("[data-nav-all]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var open = btn.getAttribute("data-nav-all") === "open";
        var bar = btn.closest(".nav-bar");
        if (!bar) return;
        bar.querySelectorAll(".nav-tree__children").forEach(function (box) {
          if (open) box.removeAttribute("hidden");
          else box.setAttribute("hidden", "");
        });
        bar.querySelectorAll("[data-navtoggle]").forEach(function (b) {
          b.setAttribute("aria-expanded", String(open));
        });
      });
    });
  }

  function renderBreadcrumb() {
    var prefix = normPath(state.category);
    if (!prefix) return "";
    var segs = prefix.split("/");
    var html = '<nav class="crumb" aria-label="目录路径">';
    html += '<button type="button" class="crumb__item" data-cat="">全部</button>';
    var acc = "";
    segs.forEach(function (s, i) {
      acc = acc ? acc + "/" + s : s;
      html += '<span class="crumb__sep">/</span>';
      html +=
        '<button type="button" class="crumb__item' + (i === segs.length - 1 ? " is-current" : "") +
        '" data-cat="' + esc(acc) + '">' + esc(s) + "</button>";
    });
    html += "</nav>";
    return html;
  }

  /* ---------- 渲染：首页（目录树视图） ---------- */
  function renderHome() {
    var L = t;
    var posts = filteredPosts();
    var prefix = normPath(state.category);
    var q = state.query.trim();

    setTitle("");
    setMeta("description", "由 Issue 驱动的 AI 双语博客，涵盖人工智能、工程实践与技术随笔。");

    var html = "";
    html += '<section class="hero">';
    html += '<span class="hero__eyebrow">' + esc(L("heroEyebrow")) + "</span>";
    html += '<h1 class="hero__title">' + esc(L("heroTitle")) + "</h1>";
    html += '<p class="hero__subtitle">' + esc(L("heroSubtitle")) + "</p>";
    html += "</section>";

    html += '<div class="section-head">';
    html += "<h2>" + esc(L("articlesTitle")) + "</h2>";
    html += '<span class="count">' + posts.length + " " + esc(L("articlesCount")) + "</span>";
    html += "</div>";

    html += renderBreadcrumb();

    if (!posts.length) {
      html += '<div class="empty-state">';
      html += "<p>" + esc(L("empty")) + "</p>";
      html += "<small>" + esc(L("emptyHint")) + "</small>";
      html += "</div>";
    } else if (q) {
      // 有搜索词时给扁平结果列表，比在树里找更好扫
      html += renderCards(posts);
    } else {
      // 首页主导航：分类 → 年份 → 文章的树形导航栏
      html += '<div class="nav-bar-wrap">' + renderNavBar(posts, "", prefix) + "</div>";
    }

    app.classList.remove("is-post");
    app.innerHTML = html;
    bindHome();
    bindNavBar(app);
    window.scrollTo(0, 0);
    updateSearchPanel();
    updateProgress();
  }

  /* 搜索结果 / 无树数据时的扁平卡片列表 */
  function renderCards(posts) {
    var html = '<div class="post-grid">';
    posts.forEach(function (p) {
      html += '<article class="post-card" tabindex="0" role="link" aria-label="' + esc(p.title) + '">';
      html += '<a class="post-card__link" href="' + postUrl(p.slug) + '">';
      html += '<div class="post-card__cat">' + esc(pathLabel(p.slug)) + "</div>";
      html += '<h3 class="post-card__title">' + esc(p.title) + "</h3>";
      html += '<p class="post-card__summary">' + esc(p.summary || "") + "</p>";
      html += '<div class="post-card__meta"><span>' + esc(fmtDate(p.date)) + "</span>";
      var langs = [];
      if (p.cn) langs.push("中文");
      if (p.en) langs.push("EN");
      html += '<span class="post-card__lang">' + langs.join(" · ") + "</span></div>";
      html += "</a></article>";
    });
    html += "</div>";
    return html;
  }

  // 文章所在目录（去掉最后一段）作为路径标签
  function pathLabel(slug) {
    var segs = String(slug || "").split("/");
    return segs.slice(0, -1).join(" / ") || segs[0] || "";
  }

  function bindHome() {
    // 进入某个目录（只看它下面的文章）
    app.querySelectorAll("[data-cat]").forEach(function (b) {
      b.addEventListener("click", function () {
        state.category = normPath(b.getAttribute("data-cat"));
        state.query = "";
        var si = document.getElementById("search-input");
        if (si) si.value = "";
        syncUrl();
        renderHome();
      });
    });
  }

  /* ---------- 渲染：文章 ---------- */
  function renderPost(slug) {
    var sorted = state.posts.slice().sort(byDateDesc);
    var idx = -1;
    for (var i = 0; i < sorted.length; i++) {
      if (sorted[i].slug === slug) { idx = i; break; }
    }
    var post = sorted[idx];
    if (!post) { renderNotFound(); return; }

    var file = state.lang === "en" && post.en ? post.en : (post.cn || post.en);
    var actualLang = file === post.en ? "en" : "zh-CN";
    if (!file) { renderNotFound(); return; }

    setTitle(post.title);
    setMeta("description", post.summary || post.title);

    app.classList.add("is-post");
    app.innerHTML = '<div class="loading">' + esc(t("loading")) + "</div>";

    fetch(file + "?t=" + Date.now())
      .then(function (r) { if (!r.ok) throw new Error("404"); return r.text(); })
      .then(function (md) {
        var L = t;
        var mins = Math.max(1, Math.round(stripFrontMatter(md).length / 500));

        var html = "";
        html += '<div class="article-layout">';

        // 标题区
        html += '<header class="article-head">';
        html += '<a class="back-link" href="/">';
        html += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>';
        html += esc(L("back")) + "</a>";
        html += '<nav class="crumb crumb--post" aria-label="目录路径">';
        var segs2 = String(post.slug || "").split("/");
        var acc2 = "";
        segs2.forEach(function (s, i) {
          acc2 = acc2 ? acc2 + "/" + s : s;
          if (i > 0) html += '<span class="crumb__sep">/</span>';
          if (i === segs2.length - 1) {
            html += '<span class="crumb__item is-current">' + esc(s) + "</span>";
          } else {
            html += '<a class="crumb__item" href="/?cat=' + encodeURIComponent(acc2) + '">' + esc(s) + "</a>";
          }
        });
        html += "</nav>";
        html += '<h1 class="article-head__title">' + esc(post.title) + "</h1>";
        html += '<div class="article-head__meta">';
        html += "<span>" + esc(L("postedOn")) + " " + esc(fmtDate(post.date)) + "</span>";
        html += '<span class="post-card__lang">' + (actualLang === "en" ? "EN" : "中文") + "</span>";
        html += "<span>" + mins + esc(L("minutes")) + "</span>";
        html += "</div>";
        if (post.tags && post.tags.length) {
          html += '<div class="article-head__tags tag-row">';
          post.tags.forEach(function (tg) { html += '<span class="tag">' + esc(tg) + "</span>"; });
          html += "</div>";
        }
        if (post.source_issue) {
          html += '<div class="article-head__source"><a href="' + esc(post.source_issue) +
            '" target="_blank" rel="noopener">' + esc(L("source")) + " ↗</a></div>";
        }
        html += "</header>";

        // 左侧树形导航栏（与首页同款）
        html += '<aside class="article-nav" aria-label="' + esc(t("navLabel")) + '">' +
          renderNavBar(state.posts, post.slug, "") + "</aside>";

        // 目录区（渲染后填充）—— 可滚动，需可聚焦
        html += '<aside class="article-side" id="article-side" tabindex="0" aria-label="'
          + esc(t("tocTitle")) + '"></aside>';

        // 正文区
        html += '<div class="article-body">';
        html += '<div class="prose" id="prose"></div>';

        var prev = sorted[idx + 1];
        var next = sorted[idx - 1];
        if (prev || next) {
          html += '<nav class="post-nav" aria-label="' + esc(L("articlesTitle")) + '">';
          if (prev) {
            html += '<a class="post-nav__item post-nav__item--prev" href="' + postUrl(prev.slug) + '">';
            html += '<span class="post-nav__label">← ' + esc(L("prev")) + "</span>";
            html += '<span class="post-nav__title">' + esc(prev.title) + "</span></a>";
          }
          if (next) {
            html += '<a class="post-nav__item post-nav__item--next" href="' + postUrl(next.slug) + '">';
            html += '<span class="post-nav__label">' + esc(L("next")) + " →</span>";
            html += '<span class="post-nav__title">' + esc(next.title) + "</span></a>";
          }
          html += "</nav>";
        }
        html += "</div>";
        html += "</div>";

        app.innerHTML = html;
        bindNavBar(app);

        var prose = document.getElementById("prose");
        prose.innerHTML = renderMarkdown(md);
        decorateProse(prose);
        highlightAndMath(prose);

        var tocItems = buildToc(prose);
        var side = document.getElementById("article-side");
        side.innerHTML = renderToc(tocItems);
        syncTocOpen();
        bindToc(prose, side);

        window.scrollTo(0, 0);
        updateProgress();
      })
      .catch(function () { renderNotFound(); });
  }

  function renderNotFound() {
    app.classList.remove("is-post");
    setTitle(t("notFound"));
    app.innerHTML =
      '<div class="container" style="padding:64px 0;text-align:center">' +
      '<h1 class="hero__title" style="font-size:2rem">' + esc(t("notFound")) + "</h1>" +
      '<p style="color:var(--text-2)">' + esc(t("notFoundHint")) + "</p>" +
      '<p><a class="back-link" href="/" style="justify-content:center">' + esc(t("back")) + "</a></p>" +
      "</div>";
  }

  /* ---------- 搜索面板 ---------- */
  function updateSearchPanel() {
    var panel = document.getElementById("search-panel");
    if (!panel) return;
    var q = normalized(state.query.trim());
    if (!q) { panel.classList.remove("is-open"); panel.innerHTML = ""; return; }
    var hits = state.posts.filter(function (p) { return queryMatches(p, q); }).sort(byDateDesc).slice(0, 6);
    if (!hits.length) {
      panel.innerHTML = '<div class="search-panel__empty">' + esc(t("searchEmpty")) + "</div>";
      panel.classList.add("is-open");
      return;
    }
    var html = '<ul class="search-panel__list">';
    hits.forEach(function (p) {
      html += '<li><a href="' + postUrl(p.slug) + '">';
      html += '<span class="search-panel__title">' + esc(p.title) + "</span>";
      html += '<span class="search-panel__cat">' + esc(pathLabel(p.slug)) + "</span></a></li>";
    });
    html += "</ul>";
    panel.innerHTML = html;
    panel.classList.add("is-open");
  }

  /* ---------- 阅读进度 / 回到顶部 ---------- */
  function updateProgress() {
    var fill = document.getElementById("progress-fill");
    var main = document.querySelector(".article-body");
    var topBtn = document.getElementById("back-top");
    if (topBtn) topBtn.classList.toggle("is-visible", window.pageYOffset > 600);

    if (!fill) return;
    if (!main) { fill.style.width = "0%"; return; }
    var docTop = main.getBoundingClientRect().top + window.pageYOffset;
    var scrolled = window.pageYOffset - docTop;
    var total = Math.max(1, main.offsetHeight - window.innerHeight * 0.75);
    var p = Math.min(1, Math.max(0, scrolled / total));
    fill.style.width = (p * 100).toFixed(2) + "%";
  }

  /* ---------- 路由 ---------- */
  function router() {
    var r = parseRoute();
    if (r.view === "post") {
      state.query = "";
      state.category = "";
      var si = document.getElementById("search-input");
      if (si) si.value = "";
      renderPost(r.slug);
    } else {
      state.query = r.q || "";
      state.category = r.cat || "";
      var si2 = document.getElementById("search-input");
      if (si2 && si2.value !== state.query) si2.value = state.query;
      renderHome();
    }
    updateSearchPanel();
  }

  /* ---------- 启动 ---------- */
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
        router();
      });
    });

    // 搜索
    var input = document.getElementById("search-input");
    var searchBox = document.getElementById("search-box");
    if (input) {
      input.addEventListener("input", function () {
        state.query = input.value;
        syncUrl();
        updateSearchPanel();
        if (parseRoute().view === "home") {
          renderHome();
          var i2 = document.getElementById("search-input");
          if (i2) { i2.focus(); i2.setSelectionRange(i2.value.length, i2.value.length); }
        }
      });
      input.addEventListener("focus", updateSearchPanel);
    }
    var searchBtn = document.getElementById("search-toggle");
    if (searchBtn && searchBox) {
      searchBtn.addEventListener("click", function () {
        searchBox.classList.toggle("search--open");
        if (searchBox.classList.contains("search--open")) input && input.focus();
      });
    }
    document.addEventListener("click", function (e) {
      if (!e.target.closest || !e.target.closest("#search-box")) {
        var panel = document.getElementById("search-panel");
        if (panel) panel.classList.remove("is-open");
      }
    });

    // 站内链接：拦截同源链接，改用 History API（保留新标签页打开等原生行为）
    document.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      if (a.target === "_blank" || a.hasAttribute("download")) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#" || href.indexOf("//") === 0) return;
      var url;
      try { url = new URL(href, location.origin); } catch (err) { return; }
      if (url.origin !== location.origin) return;
      e.preventDefault();
      navigate(url.pathname + url.search + url.hash);
    });

    var backTop = document.getElementById("back-top");
    if (backTop) {
      backTop.addEventListener("click", function () {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }

    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () { updateProgress(); ticking = false; });
    }, { passive: true });

    window.addEventListener("resize", function () { syncTocOpen(); }, { passive: true });
    window.addEventListener("popstate", router);

    loadPosts().then(router).catch(function () { router(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else { boot(); }
})();
