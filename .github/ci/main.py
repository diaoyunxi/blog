#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Issue -> 中文博客 Agent

输入：一个 GitHub Issue 的标题 + 正文（需求）
输出：在 <BLOG_DIR>/<中文分类>/<中文主题目录>/ 下生成 cn.md，
      并把结果目录 / 分支名 / 标题写入 $GITHUB_OUTPUT 供 workflow 使用。

环境变量：
  LLM_BASE_URL / LLM_API_KEY / LLM_MODEL   模型（OpenAI 兼容 Chat Completions，需支持 function calling）
  BLOG_DIR                                 博客根目录名（默认 blog）
  ISSUE_BODY_FILE / ISSUE_TITLE_FILE       issue 内容文件（workflow 写入，避免 shell 注入）
  ISSUE_BODY / ISSUE_TITLE                 也可直接由环境变量传入
  ISSUE_NUMBER / ISSUE_URL / ISSUE_CREATED_AT / ISSUE_AUTHOR
  SEARCH_PROVIDER                          auto | tavily | serper | brave | ddg | bing
  SEARCH_API_KEY                           可选，搜索引擎 key（tavily/serper/brave）
  SEARCH_REGION / SEARCH_LANG              可选
  MAX_ROUNDS                               最大工具调用轮数（默认 16）
  MAX_429_RETRIES                          429 最大退避次数（默认 5，等待 2/4/8/16/32s）
  GITHUB_OUTPUT / GITHUB_STEP_SUMMARY      CI 输出
"""

from __future__ import annotations

import base64
import json
import math
import os
import pathlib
import re
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

try:
    import openai
    from openai import OpenAI
except ImportError:  # 仅在真正调用模型时才需要
    openai = None
    OpenAI = None


# ----------------------------------------------------------------------------
# 基础配置
# ----------------------------------------------------------------------------
ROOT = pathlib.Path(os.getenv("GITHUB_WORKSPACE") or os.getcwd()).resolve()
BLOG_DIR_NAME = (os.getenv("BLOG_DIR") or "blog").strip("/") or "blog"
BLOG_ROOT = (ROOT / BLOG_DIR_NAME).resolve()

MODEL = os.getenv("LLM_MODEL") or "gpt-4o-mini"
BASE_URL = (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY") or ""
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS") or "16")
# 落盘自检不合格时最多退回重写几次（超过就接受，避免死循环）
MAX_REWRITE = int(os.getenv("MAX_REWRITE") or "2")
# 单次输出上限：长文（2000~3000 字）需要足够大的 max_tokens，
# 不显式设置时会受服务端默认值限制导致文章被截断（表现为「草草收尾、后半段缺失」）
MAX_TOKENS = int(os.getenv("MAX_TOKENS") or "16384")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE") or "0.2")
MAX_429_RETRIES = int(os.getenv("MAX_429_RETRIES") or "5")   # 2/4/8/16/32s
BASE_BACKOFF = float(os.getenv("BASE_BACKOFF") or "2")       # 首次等待秒数
# 检索预算：避免模型一直在检索、始终不落盘
MAX_SEARCH_CALLS = int(os.getenv("MAX_SEARCH_CALLS") or "6")
MAX_FETCH_CALLS = int(os.getenv("MAX_FETCH_CALLS") or "5")
# 从第几轮开始强制只调用 save_article（兜底，保证一定会落盘）
FORCE_SAVE_ROUND = int(os.getenv("FORCE_SAVE_ROUND") or max(4, MAX_ROUNDS - 4))

UA = "Mozilla/5.0 (compatible; BlogIssueBot/1.0; +https://github.com)"


def log(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 执行轨迹（完整记录每一轮模型输出 / 工具调用 / 工具返回，失败也保留）
# ----------------------------------------------------------------------------
TRACE: list[str] = []
TRACE_DIR = pathlib.Path(os.getenv("RUNNER_TEMP") or os.getenv("TMPDIR") or "/tmp")
TRACE_FILE = TRACE_DIR / "agent-trace.md"


def trace(msg: str) -> None:
    """写入轨迹并同步打印到 stdout（Actions 日志里也能逐条看到）。"""
    TRACE.append(msg)
    print(f"[trace] {msg}", flush=True)


def cut(text: object, limit: int = 800) -> str:
    s = str(text)
    return s if len(s) <= limit else s[:limit] + f" …(已截断，共 {len(s)} 字符)"


def dump_trace() -> str:
    """把轨迹写入 $RUNNER_TEMP/agent-trace.md、$GITHUB_STEP_SUMMARY，并返回全文。"""
    body = "\n".join(TRACE) if TRACE else "（无轨迹）"
    try:
        TRACE_FILE.write_text(body, encoding="utf-8")
        log(f"轨迹已写入 {TRACE_FILE}")
    except OSError as exc:
        log(f"轨迹写文件失败：{exc}")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n<details><summary>🤖 Agent 完整执行轨迹</summary>\n\n```text\n")
                f.write(body.replace("```", "'''"))
                f.write("\n```\n\n</details>\n")
        except OSError as exc:
            log(f"轨迹写 summary 失败：{exc}")
    return body


def fail(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"::error::[agent] {msg}", file=sys.stderr, flush=True)
    trace(f"❌ 失败：{msg}")
    body = dump_trace()
    emit("trace_tail", body[-6000:])
    emit("error_message", msg)
    sys.exit(code)


# ----------------------------------------------------------------------------
# 读取 issue 内容
# ----------------------------------------------------------------------------
def read_env_or_file(env_key: str, file_key: str) -> str:
    """先取环境变量本体；取不到再把 file_key 的值当成「文件路径」读出来。

    注意：file_key（如 ISSUE_BODY_FILE）本身是**存放路径的环境变量名**，
    它的值是路径而不是内容。早期实现把它直接 return 了，
    结果 Issue 正文变成了一串 "/home/runner/work/_temp/issue/body.md"，
    提示词里根本没有真实需求（模型只能靠 read_file 自己捞），
    依赖正文做分析的自检逻辑也就全部失效。
    """
    direct = os.getenv(env_key)
    if direct:
        return direct
    path = os.getenv(file_key) or os.getenv(file_key + "_PATH") or ""
    if path and pathlib.Path(path).exists():
        return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    return ""


ISSUE_TITLE = read_env_or_file("ISSUE_TITLE", "ISSUE_TITLE_FILE").strip()
ISSUE_BODY = read_env_or_file("ISSUE_BODY", "ISSUE_BODY_FILE").strip()
ISSUE_NUMBER = os.getenv("ISSUE_NUMBER", "")
ISSUE_URL = os.getenv("ISSUE_URL", "")
ISSUE_AUTHOR = os.getenv("ISSUE_AUTHOR", "")
ISSUE_CREATED_AT = (os.getenv("ISSUE_CREATED_AT") or "").strip()

try:
    TODAY = datetime.fromisoformat(ISSUE_CREATED_AT.replace("Z", "+00:00")).astimezone(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d")
except Exception:
    TODAY = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------
# 目录工具（目录名强制中文）
# ----------------------------------------------------------------------------
# 中日韩统一表意文字（含扩展 A 区）
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 目录名只保留汉字与数字，其余（英文、空格、符号）全部丢弃
SEG_KEEP_RE = re.compile(r"[^\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff0-9]")


def blog_tree(max_depth: int = 3, max_entries: int = 400) -> str:
    """列出博客目录结构，供模型判断分类。"""
    if not BLOG_ROOT.exists():
        return f"({BLOG_DIR_NAME}/ 目录尚不存在，需要你自行创建中文分类)"
    lines: list[str] = []
    count = 0

    def walk(d: pathlib.Path, depth: int) -> None:
        nonlocal count
        if depth > max_depth or count > max_entries:
            return
        try:
            entries = sorted(
                [p for p in d.iterdir() if not p.name.startswith(".")],
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except OSError:
            return
        for p in entries:
            if count > max_entries:
                return
            count += 1
            rel = p.relative_to(BLOG_ROOT).as_posix()
            if p.is_dir():
                lines.append(f"{'  ' * depth}{rel}/")
                walk(p, depth + 1)
            else:
                lines.append(f"{'  ' * depth}{rel}")

    walk(BLOG_ROOT, 0)
    return "\n".join(lines) if lines else "(目录为空)"


def read_file(path: str, limit: int = 200) -> str:
    """只读工具：读取 blog/ 下的 .md 文章，或运行器临时目录里的 Issue 正文。

    模型经常会先尝试 read_file 再去动笔（尤其是想再读一遍 Issue 正文）。
    早期版本没有这个工具，模型调用它直接 KeyError 白耗一轮。
    """
    raw = (path or "").strip()
    if not raw:
        return json.dumps({"ok": False, "error": "未提供 path"}, ensure_ascii=False)

    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = BLOG_ROOT / raw
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p

    tmp_root = pathlib.Path(
        os.getenv("RUNNER_TEMP") or os.getenv("TMPDIR") or tempfile.gettempdir()
    ).resolve()
    inside_blog = resolved == BLOG_ROOT or BLOG_ROOT in resolved.parents
    inside_tmp = resolved == tmp_root or tmp_root in resolved.parents
    if not (inside_blog or inside_tmp):
        return json.dumps(
            {"ok": False, "error": f"只允许读取 {BLOG_DIR_NAME}/ 或运行器临时目录下的文件：{raw}"},
            ensure_ascii=False,
        )
    if not resolved.is_file():
        return json.dumps({"ok": False, "error": f"文件不存在：{raw}"}, ensure_ascii=False)
    if not inside_tmp and resolved.suffix.lower() != ".md":
        return json.dumps({"ok": False, "error": "只允许读取 .md 文件"}, ensure_ascii=False)

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return json.dumps({"ok": False, "error": f"读取失败：{exc}"}, ensure_ascii=False)

    lines = text.split("\n")
    n = max(1, int(limit or 200))
    return json.dumps(
        {
            "ok": True,
            "path": str(resolved),
            "total_lines": len(lines),
            "returned_lines": min(n, len(lines)),
            "content": "\n".join(lines[:n]),
        },
        ensure_ascii=False,
    )


def sanitize_segment(seg: str, max_len: int = 40) -> str:
    """目录名单段清洗：只保留汉字与数字；不含汉字则报错，逼模型改用中文命名。"""
    s = (seg or "").strip().replace("\\", "/")
    if s in ("", ".", ".."):
        raise ValueError("目录段为空")
    s = SEG_KEEP_RE.sub("", s)
    if not CJK_RE.search(s):
        raise ValueError(
            f"目录段 {seg!r} 不含中文，已被拒绝——所有目录名必须使用中文，请改用中文重新调用（如 人工智能/检索增强生成）"
        )
    return s[:max_len] or "未命名"


def sanitize_rel_dir(raw: str) -> str:
    """把模型给出的目录清洗为相对 blog 根的安全中文路径。"""
    raw = (raw or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    if raw.lower().startswith(BLOG_DIR_NAME.lower() + "/"):
        raw = raw[len(BLOG_DIR_NAME) + 1 :]
    parts = [sanitize_segment(p) for p in raw.split("/")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("目录名为空")
    return "/".join(parts)


def sanitize_branch(rel: str) -> str:
    """分支名 = 博客根目录名 + 中文目录路径（根目录名本身不做中文过滤）。"""
    raw = (rel or "").replace("\\", "/").strip("/")
    parts = [sanitize_segment(p, 60) for p in raw.split("/")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("分支名为空")
    branch = "/".join([BLOG_DIR_NAME] + parts)
    branch = branch.replace("..", "").replace("//", "/").strip("/")
    return branch or f"{BLOG_DIR_NAME}/未命名"


# ----------------------------------------------------------------------------
# 联网搜索 / 抓取
# ----------------------------------------------------------------------------
def _fmt_results(items: list[dict]) -> str:
    if not items:
        return "（没有检索到结果，可换个更短的关键词重试）"
    out = []
    for i, it in enumerate(items, 1):
        out.append(
            f"{i}. {it.get('title','').strip()}\n   URL: {it.get('url','')}\n   {textwrap.shorten((it.get('snippet') or '').strip(), 500, placeholder=' ...')}"
        )
    return "\n".join(out)


def _tavily(query: str, n: int) -> list[dict]:
    key = os.getenv("SEARCH_API_KEY", "")
    if not key:
        raise RuntimeError("no tavily key")
    r = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "max_results": n,
            "search_depth": "advanced",
            "include_answer": "advanced",
        },
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    items = [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")} for x in data.get("results", [])]
    if data.get("answer"):
        items.insert(0, {"title": "Tavily 摘要", "url": "", "snippet": str(data["answer"])[:800]})
    return items


def _serper(query: str, n: int) -> list[dict]:
    key = os.getenv("SEARCH_API_KEY", "")
    if not key:
        raise RuntimeError("no serper key")
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": n, "hl": os.getenv("SEARCH_LANG", "zh-cn")},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    return [
        {"title": x.get("title", ""), "url": x.get("link", ""), "snippet": x.get("snippet", "")}
        for x in data.get("organic", [])
    ]


def _brave(query: str, n: int) -> list[dict]:
    key = os.getenv("SEARCH_API_KEY", "")
    if not key:
        raise RuntimeError("no brave key")
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": n},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("description", "")}
        for x in (data.get("web", {}) or {}).get("results", [])
    ]


def _duckduckgo(query: str, n: int) -> list[dict]:
    r = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": os.getenv("SEARCH_REGION", "cn-zh")},
        headers={"User-Agent": UA},
        timeout=45,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items: list[dict] = []
    for res in soup.select(".result, .web-result"):
        a = res.select_one("a.result__a")
        if not a:
            continue
        href = a.get("href", "")
        if "uddg=" in href:
            href = requests.utils.unquote(href.split("uddg=")[1].split("&")[0])
        sn = res.select_one(".result__snippet")
        items.append({"title": a.get_text(" ", strip=True), "url": href, "snippet": sn.get_text(" ", strip=True) if sn else ""})
        if len(items) >= n:
            break
    return items


def _bing_unwrap(href: str) -> str:
    """Bing 结果返回的是 bing.com/ck/a?...&u=a1aHR0c... 跳转链，还原成真实 URL。"""
    if "bing.com/ck/a" not in href:
        return href
    m = re.search(r"[?&]u=([^&]+)", href)
    if not m:
        return href
    raw = requests.utils.unquote(m.group(1))
    if raw.startswith("a1"):          # a1 前缀 + base64
        raw = raw[2:]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(padded).decode("utf-8", errors="ignore") or href
    except Exception:  # noqa: BLE001
        return href


def _bing(query: str, n: int) -> list[dict]:
    r = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "setlang": os.getenv("SEARCH_LANG", "zh-CN"), "count": n},
        headers={"User-Agent": UA},
        timeout=45,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.find("a", href=True)
        if not a:
            continue
        sn = li.find("p")
        items.append(
            {
                "title": a.get_text(" ", strip=True),
                "url": _bing_unwrap(a["href"]),
                "snippet": sn.get_text(" ", strip=True) if sn else "",
            }
        )
        if len(items) >= n:
            break
    return items


def search_web(query: str, max_results: int = 6) -> str:
    """联网搜索，返回标题/链接/摘要列表。"""
    provider = (os.getenv("SEARCH_PROVIDER") or "auto").lower()
    n = max(1, min(int(max_results or 6), 10))
    free = ["ddg", "bing"]
    order = {
        "tavily": ["tavily"] + free,
        "serper": ["serper"] + free,
        "brave": ["brave"] + free,
        "ddg": free,
        "bing": ["bing"],
        "auto": (["tavily"] + free if os.getenv("SEARCH_API_KEY") else free),
    }.get(provider, free)

    last_err = ""
    for p in order:
        try:
            fn = {"tavily": _tavily, "serper": _serper, "brave": _brave, "ddg": _duckduckgo, "bing": _bing}[p]
            items = fn(query, n)
            if items:
                log(f"search[{p}] {query!r} -> {len(items)} 条")
                return _fmt_results(items[:n])
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            log(f"search[{p}] 失败: {last_err}")
    return f"搜索失败：{last_err or '未知错误'}。请更换关键词重试，或在正文里标注该信息无法联网核实。"


def fetch_url(url: str, max_chars: int = 12000) -> str:
    """抓取网页正文（去标签、去脚本、截断）。"""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"},
            timeout=45,
            allow_redirects=True,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"抓取失败：{type(exc).__name__}: {exc}"

    ctype = r.headers.get("Content-Type", "")
    if "json" in ctype:
        return r.text[:max_chars]

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    title = soup.title.get_text(strip=True) if soup.title else ""
    head = f"标题: {title}\nURL: {r.url}\n\n" if title else f"URL: {r.url}\n\n"
    return (head + text)[:max_chars]


# ----------------------------------------------------------------------------
# 落盘工具
# ----------------------------------------------------------------------------
RESULT: dict[str, str] = {}

# 文件名合法字符：中文 / 字母数字 / . _ -，且必须以 .md 结尾
FILENAME_RE = re.compile(r"^[\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff.\-]+\.md$", re.IGNORECASE)


def sanitize_rel_file(raw: str) -> str:
    """把模型给出的文件路径清洗为相对 blog 根的安全 .md 路径（目录段仍强制中文）。"""
    raw = (raw or "").strip().replace("\\", "/").lstrip("/")
    if raw.lower().startswith(BLOG_DIR_NAME.lower() + "/"):
        raw = raw[len(BLOG_DIR_NAME) + 1:]
    parts = [p for p in raw.split("/") if p]
    if not parts:
        raise ValueError("文件路径为空")
    filename = parts[-1]
    if not filename.lower().endswith(".md"):
        raise ValueError(f"文件名 {filename!r} 必须以 .md 结尾（本仓库只允许改动 Markdown 文件）")
    if not FILENAME_RE.match(filename):
        raise ValueError(f"文件名 {filename!r} 含非法字符，只允许中文、字母、数字、点、下划线、连字符")
    dirs = [sanitize_segment(p) for p in parts[:-1]]
    return "/".join(dirs + [filename])


def _check_inside_blog(path: pathlib.Path, raw: str) -> pathlib.Path:
    resolved = path.resolve()
    if BLOG_ROOT != resolved and BLOG_ROOT not in resolved.parents:
        raise ValueError(f"非法路径（越出 {BLOG_DIR_NAME}/）：{raw}")
    return resolved


def finish(rel_file: str, operation: str, summary: str = "") -> str:
    """统一收尾：写入 RESULT，供 workflow 生成 commit / 回帖。"""
    verb = {"add": "add", "update": "update", "remove": "remove"}.get(operation, "add")
    rel_dir = rel_file.rsplit("/", 1)[0] if "/" in rel_file else ""
    RESULT.update(
        {
            "operation": verb,
            "target_file": rel_file,
            "target_dir": rel_dir,
            "cn_path": f"{BLOG_DIR_NAME}/{rel_file}",
            "full_dir": f"{BLOG_DIR_NAME}/{rel_dir}" if rel_dir else BLOG_DIR_NAME,
            "branch": sanitize_branch(rel_dir or rel_file),
            "title": f"docs({BLOG_DIR_NAME}): {verb} {rel_file}",
            "summary": summary or ISSUE_TITLE,
        }
    )
    log(f"已完成 {verb}：{RESULT['cn_path']}")
    return json.dumps(
        {
            "ok": True,
            "operation": verb,
            "file": RESULT["cn_path"],
            "note": "改动已落盘，请直接用一句话总结本次改动，不要再次调用工具。",
        },
        ensure_ascii=False,
    )


def save_article(target_dir: str, cn_md: str, summary: str = "") -> str:
    """【新增】在中文目录下写入 cn.md（目录名必须为纯中文）。"""
    rel = sanitize_rel_dir(target_dir)
    out_dir = _check_inside_blog(BLOG_ROOT / rel, target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cn_path = out_dir / "cn.md"
    existed = cn_path.exists()
    cn_path.write_text(cn_md.strip() + "\n", encoding="utf-8")
    return finish(f"{rel}/cn.md", "update" if existed else "add", summary)


def edit_article(target_file: str, cn_md: str, summary: str = "") -> str:
    """【修改】覆盖写入一篇已存在的 .md 文章（整篇替换）。"""
    rel = sanitize_rel_file(target_file)
    out = _check_inside_blog(BLOG_ROOT / rel, target_file)
    existed = out.exists()
    if not existed:
        return json.dumps(
            {"ok": False, "error": f"文件不存在，无法修改：{BLOG_DIR_NAME}/{rel}。"
                                   f"若要新增文章请改用 save_article。"},
            ensure_ascii=False,
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cn_md.strip() + "\n", encoding="utf-8")
    return finish(rel, "update", summary)


def delete_article(target_file: str, summary: str = "") -> str:
    """【删除】删除一篇已存在的 .md 文章。"""
    rel = sanitize_rel_file(target_file)
    out = _check_inside_blog(BLOG_ROOT / rel, target_file)
    if not out.exists():
        return json.dumps(
            {"ok": False, "error": f"文件不存在，无法删除：{BLOG_DIR_NAME}/{rel}"},
            ensure_ascii=False,
        )
    out.unlink()
    # 顺带清理因此变空的目录（不越过 blog 根）
    d = out.parent
    while d != BLOG_ROOT and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent
    return finish(rel, "remove", summary)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "联网搜索（用于核实事实、版本、数据、最新进展）。可多次调用，关键词要短而准。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，中英文均可"},
                    "max_results": {"type": "integer", "description": "返回条数，默认 6"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "打开某个 URL 并读取正文，用于核实搜索结果中的细节。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "要抓取的网页地址"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_blog_tree",
            "description": "重新查看博客目录结构，确认中文分类是否已存在。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "只读：查看 blog/ 下已有 .md 文章的内容（用于判断该改哪篇、避免重复造轮子）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对博客根目录的 .md 路径，如 人工智能/生成式模型/文生图扩散原理/cn.md"},
                    "limit": {"type": "integer", "description": "最多返回多少行，默认 200"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_article",
            "description": "【新增文章】在中文目录下创建 cn.md。目录名必须是中文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_dir": {
                        "type": "string",
                        "description": "相对博客根目录的多层中文目录，如 后端/数据库/索引选型；最后一段即以主题命名的文件夹",
                    },
                    "cn_md": {"type": "string", "description": "简体中文完整 Markdown 正文（含 YAML front matter）"},
                    "summary": {"type": "string", "description": "一句话总结本次新增内容"},
                },
                "required": ["target_dir", "cn_md"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_article",
            "description": "【修改文章】整篇覆盖写入一个已存在的 .md 文件。用于按 Issue 要求修订、补充、纠错已有文章。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_file": {
                        "type": "string",
                        "description": "相对博客根目录的 .md 文件路径，如 人工智能/生成式模型/文生图扩散原理/cn.md",
                    },
                    "cn_md": {"type": "string", "description": "替换后的简体中文完整 Markdown 正文（含 YAML front matter）"},
                    "summary": {"type": "string", "description": "一句话总结本次修改"},
                },
                "required": ["target_file", "cn_md"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_article",
            "description": "【删除文章】删除一个已存在的 .md 文件。仅当 Issue 明确要求删除时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_file": {
                        "type": "string",
                        "description": "相对博客根目录的 .md 文件路径，如 人工智能/生成式模型/文生图扩散原理/cn.md",
                    },
                    "summary": {"type": "string", "description": "一句话说明删除原因"},
                },
                "required": ["target_file"],
            },
        },
    },
]

WRITE_TOOLS = ("save_article", "edit_article", "delete_article")

TOOL_FUNCS = {
    "search_web": lambda **kw: search_web(kw.get("query", ""), kw.get("max_results", 6)),
    "fetch_url": lambda **kw: fetch_url(kw.get("url", "")),
    "list_blog_tree": lambda **kw: blog_tree(),
    "read_file": lambda **kw: read_file(kw.get("path", ""), kw.get("limit", 200)),
    "save_article": lambda **kw: save_article(
        kw.get("target_dir", ""), kw.get("cn_md", ""), kw.get("summary", "")
    ),
    "edit_article": lambda **kw: edit_article(
        kw.get("target_file", ""), kw.get("cn_md", ""), kw.get("summary", "")
    ),
    "delete_article": lambda **kw: delete_article(
        kw.get("target_file", ""), kw.get("summary", "")
    ),
}


def guess_intent() -> str:
    """根据 Issue 标题+正文粗判意图，决定强制落盘时锁定哪个工具。"""
    text = f"{ISSUE_TITLE}\n{ISSUE_BODY}"
    del_words = ("删除", "删掉", "删去", "移除", "去掉", "不要这篇", "下架")
    edit_words = ("修改", "改一", "更新", "修订", "补充", "纠错", "改正", "重写", "改写", "调整")
    if any(w in text for w in del_words):
        return "delete_article"
    if any(w in text for w in edit_words):
        return "edit_article"
    return "save_article"


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""你是一个"中文技术博客写作 Agent"，运行在 GitHub Actions 中。
你会收到一个 GitHub Issue（用户提出的写作/解答需求），据此对 {BLOG_DIR_NAME}/ 下的中文文章做
**新增 / 修改 / 删除** 三种操作之一，并把改动落盘到仓库。

## 第一步：判断操作类型

先读 Issue 意图，三选一：

- **新增**：Issue 要求写一篇新文章、介绍某个主题 → 用 `save_article`
- **修改**：Issue 要求修订 / 补充 / 纠错 / 更新已有某篇文章 → 用 `edit_article`
- **删除**：Issue 明确要求删掉某篇文章 → 用 `delete_article`

不确定时默认按「新增」处理；只有 Issue 明确点名要改或要删某篇时才用后两者。

## 重要：Issue 很短时必须自己把深度补齐

真实用户开 Issue 往往只有一句话，例如「介绍一下 https://github.com/xxx/yyy」、
「完整介绍一下 apt 的原理」——**不会给你列详细提纲**。
这时绝不能因为 Issue 短就写成一篇几百字的概览。你要把它当成一次约稿：
用户没说清楚的部分，由你按下面标准补全。

**判断与补全流程：**

1. 先判断主题类型（介绍某个东西 / 讲清某个原理 / 某个操作怎么做），再套用对应框架；
2. 框架里的每一条都写成独立小标题，不要合并成一段；
3. 拿不准有没有的维度（比如"安全注意"），检索后确认，确实不适用就在文中一句带过，不要整条消失；
4. 篇幅按 1500~2500 字写，主题复杂（如「原理」「架构」）可以写到 3000 字。

**框架 A —— 介绍某个项目 / 工具 / 仓库（Issue 给了链接或名字时用它）：**
   1. 背景：它解决什么问题、什么场景下会用到
   2. 定位与对比：和同类方案的本质区别（各自适合什么场景），不要只写优点
   3. 快速上手：最短路径跑起来的完整命令 / 代码（可直接复制）
   4. 组成与原理：核心模块 / 目录结构 / 关键文件分别负责什么，数据流怎么走
   5. 关键配置：常用参数、默认值、怎么改
   6. 安全与隐私：密钥如何管理、数据会传到哪里、需要收敛的风险
   7. 局限与坑：什么情况下不适用、常见报错与排查
   8. 选型建议：什么时候该用它，什么时候该换别的
   9. 参考链接

**框架 B —— 讲清某个原理 / 机制（Issue 出现"原理""是怎么工作的""背后发生了什么"时用它）：**
   1. 背景：为什么需要它，没有它的时候人们怎么做
   2. 定位与分层：它在整个体系里处于哪一层，上下游分别是谁、各自负责什么
   3. 核心流程：一次完整调用 / 一条命令背后发生了什么，按阶段拆开讲，每阶段给可验证的命令
   4. 关键数据与状态：它依赖哪些配置文件、目录、状态文件，里面存了什么
   5. 关键机制：涉及的核心算法 / 策略 / 优先级规则要讲清楚
   6. 常见坑与排查：报错信息 → 原因 → 解决办法
   7. 最佳实践：什么该做、什么不该做，给出可直接复制的命令
   8. 参考链接

两个框架可以按主题混合使用（例如「介绍 X 的原理」就 A+B 合并），
但**每个维度都不能空着**。

## 硬性要求

1. 博客根目录：{BLOG_DIR_NAME}/（仓库根目录下）。先检查 list_blog_tree 给出的既有分类：
   - 有合适分类就复用它（可以再往下加一层子目录）；
   - 没有合适分类就自行新建，允许多层子目录。
2. **所有目录名（含分类层和最后一层主题目录）必须使用简体中文**，例如：
   后端/数据库/索引选型、前端/构建工具/打包体积优化、数据库/查询优化。
   （注意：这些只是格式示例，**文章主题永远以下面的 Issue 为准**，不要照抄示例里的主题。）
   严禁出现任何英文单词、拼音、kebab-case、日期、issue 编号或泛化词（杂项、其他、新文章）。
   程序会过滤掉非汉字字符，纯英文目录会被直接拒绝并报错，届时请立刻改用中文重新调用。
3. 新增时最后一层目录名必须体现 issue 主题，用简短中文词组（4~12 字为宜），目录下文件名固定为 `cn.md`。
   **禁止**：末层与任一层父目录同名（如 后端/框架/框架）；
   禁止用泛化词单独做末层（框架、工具、原理、介绍、组件、系统、方案 这类词单独出现不合格），
   必须带上具体主题，例如 后端/框架/极简路由框架、系统工具/包管理器/依赖解析。
4. 只允许改动 `.md` 文件；`edit_article` / `delete_article` 的 `target_file` 必须是以 `.md` 结尾的相对路径。
5. **归属限制（重要）**：修改或删除已有文章时，该文件必须是**本次 Issue 提出者**创建的。
   - 下面会给出「本次提出者可改动的文件清单」，只在这个清单里挑目标；
   - 若目标文件不在清单中（是别人创建的），**不要调用改/删工具**，
     改为回复一句说明："该文章由 <其他人> 创建，当前 Issue 提出者无权修改/删除。"，不落盘。
   - 新增文章不受此限制，任何人都可以新增。
   - **不要重复造轮子**：下面若提示「本 Issue 之前已经生成过文章」，
     就必须用 `edit_article` 重写那篇，不许再 `save_article` 新增同主题文章。
6. 事实性内容（版本号、参数、基准数据、时间、人名、API 形态、价格）必须先用 search_web 检索，
   再用 fetch_url 打开 1~3 个权威来源核实。搜不到就明确写"截至 {TODAY} 未找到权威来源"，禁止编造。
   **检索预算（硬性）**：search_web 最多 {MAX_SEARCH_CALLS} 次、fetch_url 最多 {MAX_FETCH_CALLS} 次。
   拿到 2~3 条可靠证据就够，立刻动笔。禁止为了穷尽资料反复检索——
   检索配额用尽或轮数过半时，系统会强制你落盘，此时必须基于已有信息直接完成改动。
7. 结构建议：背景 → 核心概念/原理 → 实操步骤或示例（带代码/命令块）→ 常见坑 → 小结 → 参考链接。
   Markdown 规范，代码块标注语言。
   篇幅**默认 1500~2500 字**；若 Issue 正文明确要求更长篇幅，以 Issue 为准（上限 3000 字）。
   绝不许为了压缩篇幅丢掉该写的内容——宁可长，不可缺。
8. **逐条覆盖（硬性）**：Issue 正文里若出现编号清单、"请覆盖以下几点"、分条要求，
   文章必须**逐条对应**，每条用独立小标题或独立小节写清楚，不许合并、不许略过、不许只挑自己会写的写。
   写完后自查一遍 Issue 的每一条是否都落到了正文里，缺哪条就补哪条。
9. **用户给出的事实优先**：Issue 正文里给出的实测数据（配置常量、端点 URL、包名、版本号、代码片段）
   优先级高于你检索到的通用信息。先核实，核实后必须写进文章；
   尤其**不许擅自把用户指定的版本号换成你搜到的"最新版"**——用户锁定的版本要照写，可另行注明更新版本。
10. 文件开头必须写 YAML front matter：
   ---
   title: <中文标题>
   date: {TODAY}
   lang: zh-CN
   tags: [标签1, 标签2]
   summary: <一句话摘要>
   source_issue: {ISSUE_URL or ('#' + ISSUE_NUMBER if ISSUE_NUMBER else '')}
   ---
   修改已有文章时，保留原有的 `source_issue`，并把 `date` 更新为 {TODAY}。
11. 参考链接放在正文末尾的"参考"小节，只写你实际抓取或确认过的 URL。
12. 不要写与主题无关的内容，不要在正文里提及 issue、机器人或本流程。
13. **不要过早动笔**：Issue 若点名要写多个方面，每个方面都需要先有依据，
   允许把检索预算用满；"2~3 条证据就够"只适用于主题单一、方面很少的 Issue。
   落盘后系统会做自检（篇幅 + 逐条覆盖），不合格会把文章退回重写，
   与其被退回，不如第一次就写全——**宁可长，不可缺**。
14. 一次运行只做一种操作、只调用一次写入类工具（save_article / edit_article / delete_article 三选一）。

最后必须落盘（或按第 5 条明确说明无权改动），成功后用一句话总结即可。

补充：Issue 正文已在下面完整给出，不要为了读 Issue 再去调用工具；
`read_file` 只在你想确认某篇已有文章的原文时使用。"""


def existing_article_hint() -> str:
    """
    找出 blog/ 里已经由「同一个 Issue」生成过的文章。

    同一 Issue 被重跑（手动 dispatch / 失败重试）时，模型默认按「新增」处理，
    结果同一个主题在仓库里留下两篇内容重复的文章。
    这里按 front matter 的 source_issue 反查，命中就明确要求它改用 edit_article 覆盖更新。
    """
    if not BLOG_ROOT.exists():
        return ""
    targets = {ISSUE_URL} if ISSUE_URL else set()
    if ISSUE_NUMBER:
        targets.add(f"/issues/{ISSUE_NUMBER}")
        targets.add(f"#{ISSUE_NUMBER}")
    if not targets:
        return ""

    hits: list[str] = []
    try:
        for p in sorted(BLOG_ROOT.rglob("*.md")):
            if p.name.lower().startswith("en."):
                continue
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            if any(t and t in head for t in targets):
                hits.append(p.relative_to(BLOG_ROOT).as_posix())
    except OSError:
        return ""

    if not hits:
        return ""
    return (
        "⚠️ 本 Issue 之前已经生成过文章，blog/ 里现存：\n"
        + "\n".join(f"- {BLOG_DIR_NAME}/{h}" for h in hits)
        + "\n\n**本次必须调用 `edit_article` 更新这些文件中的那篇（整篇重写），"
        "绝对不要再用 `save_article` 新增一篇**，否则仓库里会留下重复内容。"
        "若你判断确实需要另开一篇不同主题的文章，也要先说明为什么现有那篇不适用。"
    )


# 中文字符 + 英文单词计数，用来衡量正文篇幅
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9._\-]{2,}")
# 常见英文噪音词，不作为「要点锚点」
_ANCHOR_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "not", "are", "you",
    "was", "how", "why", "code", "bash", "text", "conf", "http", "https",
    "com", "www", "org", "net", "html", "please", "issue", "github",
}


def article_length(md: str) -> int:
    """正文字数：汉字数 + 英文单词数（粗略但够用）。"""
    cn = len(_CJK_CHAR_RE.findall(md or ""))
    en = len([w for w in _WORD_RE.findall(md or "") if w.lower() not in _ANCHOR_STOP])
    return cn + en


# 无编号清单时的「通用框架维度」——用于短 Issue 的结构兜底，
# 每个维度给若干锚点，命中任一即视为该维度已覆盖。
FRAMEWORK_DIMENSIONS: list[tuple[str, tuple[str, ...]]] = [
    ("背景/定位对比", ("对比", "区别", "与", "不同于", "相比", "定位", "背景", "为什么", "区别在")),
    ("快速上手/实操命令", ("安装", "命令", "npm ", "apt ", "git ", "curl", "示例", "```", "用法", "运行")),
    ("组成/原理/流程", ("原理", "流程", "结构", "模块", "目录", "链路", "阶段", "机制", "架构", "解析")),
    ("关键配置/参数", ("配置", "参数", "默认值", "选项", "文件", "环境变量")),
    ("局限/坑/排查", ("局限", "坑", "注意", "报错", "排查", "风险", "不适", "问题", "失败")),
    ("小结/选型", ("小结", "总结", "选型", "建议", "什么时候", "该用", "适合")),
    ("参考链接", ("## 参考", "http://", "https://")),
]


def framework_check(md: str) -> list[str]:
    """短 Issue（无编号清单）时的结构兜底：按通用框架维度检查小标题与内容。"""
    text = md or ""
    headings = "\n".join(
        l for l in text.split("\n") if l.lstrip().startswith("#")
    )
    haystack = (headings + "\n" + text).lower()
    missing: list[str] = []
    for name, anchors in FRAMEWORK_DIMENSIONS:
        if not any(a.lower() in haystack for a in anchors):
            missing.append(name)

    n_headings = len([l for l in text.split("\n") if l.lstrip().startswith("##")])
    problems: list[str] = []
    if missing:
        problems.append(
            "文章缺少以下通用维度（短 Issue 也必须有，一条都不许空）：\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
    if n_headings < 6:
        problems.append(
            f"结构太薄：只有 {n_headings} 个二级/三级小标题，短 Issue 至少要 6 个小标题把各维度分开写"
        )
    return problems


def required_length() -> int:
    """从 Issue 正文里解析篇幅要求（如「2000~3000 字」），取下限；解析不到用默认值。"""
    patterns = [
        re.compile(r"(\d{3,5})\s*[~～\-—至到]\s*(\d{3,5})\s*字"),
        re.compile(r"(\d{3,5})\s*字\s*(?:以上|以上|左右)?"),
    ]
    for pat in patterns:
        m = pat.search(ISSUE_BODY or "")
        if m:
            try:
                return max(300, int(m.group(1)))
            except ValueError:
                pass
    # Issue 没写篇幅要求时：真实用户的 Issue 往往只有一句话，
    # 这时按「有深度的技术文章」给下限，而不是旧的 800 字概览档。
    return 1500


def issue_checklist() -> list[tuple[str, list[str]]]:
    """
    从 Issue 正文里抽出「逐条要求」及每条的锚点词。

    支持 `1. xxx` / `1、xxx` / `1) xxx` / `① xxx` 等编号写法。
    锚点词优先取英文专有名词（InRelease、autoremove…），中文条目取标题短句。
    """
    body = ISSUE_BODY or ""
    items: list[tuple[str, list[str]]] = []
    pat = re.compile(
        r"^\s*(?:\d{1,2}\s*[\.、)．]|[①-⑳])\s*(.+?)\s*$", re.MULTILINE
    )
    for m in pat.finditer(body):
        title = m.group(1).strip()
        if len(title) < 4:
            continue
        # 条目正文可能很长（一段），只取前 200 字抽锚点，标题显示截断
        title = title[:200]
        anchors = [
            w for w in _WORD_RE.findall(title)
            if w.lower() not in _ANCHOR_STOP and not w.isdigit()
        ]
        anchors = sorted(set(anchors), key=len, reverse=True)[:6]
        if not anchors:
            # 纯中文条目：取前 10 个汉字做短语锚点
            cn = "".join(_CJK_CHAR_RE.findall(title))[:10]
            anchors = [cn] if len(cn) >= 3 else []
        if anchors:
            items.append((title[:60], anchors))
    # 正文条目过多时（>12）多半不是要求清单，忽略
    return items[:12]


def review_article(md: str) -> tuple[bool, str]:
    """
    落盘后的自检：篇幅是否达标、Issue 逐条要求是否都写进了正文。

    这是「模型第 3 轮就草草落盘、把用户列的要点砍掉一大半」的兜底：
    不合格就把结论退回给模型重写，而不是直接结束。
    """
    problems: list[str] = []

    n = article_length(md or "")
    need = required_length()
    if n < need:
        problems.append(f"篇幅不足：当前约 {n} 字，要求不少于 {need} 字")

    checklist = issue_checklist()
    if checklist:
        # Issue 自带编号清单 → 逐条核对
        missing: list[str] = []
        for title, anchors in checklist:
            hits = [a for a in anchors if a.lower() in (md or "").lower()]
            # 锚点少则要求全部命中；锚点多时要求命中 40%（至少 2 个），
            # 避免「只提到一个名词就宣称覆盖了这一条」。
            need = len(anchors) if len(anchors) <= 3 else max(2, math.ceil(len(anchors) * 0.4))
            if len(hits) < need:
                missing.append(f"{title}（命中 {len(hits)}/{need}）")
        if missing:
            problems.append(
                "以下 Issue 点名要写的方面在正文里找不到对应内容（共 "
                f"{len(missing)} 条）：\n" + "\n".join(f"  - {t}" for t in missing)
            )
    else:
        # Issue 只有一句话、没有清单 → 按通用框架检查结构是否够完整
        problems.extend(framework_check(md))

    if not problems:
        return True, f"自检通过（约 {n} 字，逐条要求均已覆盖）"
    trace(
        "[review] 检出条目 "
        f"{len(issue_checklist())} 条；要求篇幅 {required_length()} 字，实际 {n} 字"
    )
    return False, "\n".join(problems)


def owned_files_hint() -> str:
    """本次 Issue 提出者可改动的文件清单（由 workflow 预先算好写入 JSON）。"""
    path = os.getenv("OWNED_MAP_FILE") or ""
    if not path or not pathlib.Path(path).exists():
        return "（本次提出者可改动清单未提供，请只做新增，不要修改或删除已有文章）"
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "（清单解析失败，请只做新增，不要修改或删除已有文章）"
    owned = data.get("owned") or []
    if not owned:
        return ("本次提出者目前**没有**任何自己创建的文章，因此只能新增，不能修改或删除已有文章。")
    return "本次提出者可改动（修改/删除）的文件：\n" + "\n".join(f"- {p}" for p in owned)


def build_user_prompt() -> str:
    return (
        f"Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}\n"
        f"Issue 链接: {ISSUE_URL}\n"
        f"提出者: {ISSUE_AUTHOR}\n"
        f"日期: {TODAY}\n\n"
        f"当前博客目录结构（根目录 {BLOG_DIR_NAME}/，全部为中文）：\n{blog_tree()}\n\n"
        f"{owned_files_hint()}\n\n"
        f"{existing_article_hint()}\n\n"
        f"Issue 正文（需求）如下：\n-----\n{ISSUE_BODY}\n-----\n\n"
        "请先判断操作类型（新增 / 修改 / 删除），需要核实时先检索，"
        "然后调用 save_article / edit_article / delete_article 落盘（目录名必须是中文，只能改 .md）。"
    )


# ----------------------------------------------------------------------------
# 模型调用（429 指数退避；其他非成功状态码直接 fail）
# ----------------------------------------------------------------------------
def _status_code_of(exc: BaseException) -> int | None:
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    if code:
        return int(code)
    code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    return int(code) if code else None


def _retry_after_of(exc: BaseException) -> float:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    try:
        return float(headers.get("Retry-After") or headers.get("retry-after") or 0)
    except (TypeError, ValueError):
        return 0.0


def chat_with_backoff(client, **kwargs):
    """调用 Chat Completions：
    - HTTP 429：指数退避等待 2/4/8/16/32s，最多 5 次；仍失败则 fail
    - 其他非 2xx：立即 fail
    """
    delay = BASE_BACKOFF
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            status = _status_code_of(exc)
            if status == 429 or exc.__class__.__name__ == "RateLimitError":
                if attempt >= MAX_429_RETRIES:
                    fail(f"模型返回 429（限流），已退避重试 {MAX_429_RETRIES} 次仍失败：{exc}")
                wait = max(delay, _retry_after_of(exc))
                log(f"429 限流，第 {attempt + 1}/{MAX_429_RETRIES} 次退避，等待 {wait:.0f}s 后重试")
                trace(f"⏳ 模型返回 429，第 {attempt + 1}/{MAX_429_RETRIES} 次退避，等待 {wait:.0f}s")
                time.sleep(wait)
                delay *= 2
                continue
            if status is not None:
                fail(f"模型调用失败（HTTP {status}）：{exc}")
            fail(f"模型调用失败：{type(exc).__name__}: {exc}")
    fail("模型调用失败：未知错误")


def run_agent() -> None:
    if OpenAI is None:
        fail("未安装 openai 依赖，请先 pip install -r .github/ci/requirements.txt")
    if not API_KEY:
        fail("缺少 LLM_API_KEY secret")
    if not ISSUE_BODY.strip():
        fail("Issue 正文为空，无法生成文章")

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180, max_retries=0)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt()},
    ]
    trace(
        f"模型 {MODEL} @ {BASE_URL}；最大轮数 {MAX_ROUNDS}，"
        f"检索预算 search≤{MAX_SEARCH_CALLS} / fetch≤{MAX_FETCH_CALLS}，第 {FORCE_SAVE_ROUND} 轮起强制落盘"
    )
    trace(f"博客根目录 {BLOG_DIR_NAME}/，目录树：\n{cut(blog_tree(), 1200)}")
    trace(f"Issue #{ISSUE_NUMBER}《{ISSUE_TITLE}》正文长度 {len(ISSUE_BODY)} 字符")

    no_tool_rounds = 0
    n_search = 0
    n_fetch = 0

    # 按 Issue 意图决定「强制落盘」时锁定哪个写入工具
    force_tool = os.getenv("FORCE_TOOL") or guess_intent()
    # 本 Issue 若已生成过文章，强制落盘时也必须锁定为「修改」，否则会再新增一篇重复的
    if existing_article_hint() and force_tool == "save_article":
        force_tool = "edit_article"
    trace(f"意图判定：强制落盘时锁定 {force_tool}")

    for round_no in range(1, MAX_ROUNDS + 1):
        trace(f"──────── 第 {round_no} 轮 ────────")

        # 预算提示：把剩余配额明确告诉模型
        if round_no == max(2, FORCE_SAVE_ROUND - 3):
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"提示：你已用掉 search_web {n_search}/{MAX_SEARCH_CALLS} 次、"
                        f"fetch_url {n_fetch}/{MAX_FETCH_CALLS} 次。请停止检索，"
                        f"基于已有信息直接调用 {force_tool} 完成改动。\n"
                        f"文章主题严格固定为本次 Issue：#{ISSUE_NUMBER}《{ISSUE_TITLE}》，"
                        f"不要写其他主题。\nIssue 原文：\n{ISSUE_BODY[:600]}"
                    ),
                }
            )
            trace("已注入『停止检索、立即落盘 + 重申主题』提示")

        # 兜底：接近轮数上限时强制只调用写入类工具
        force_save = round_no >= FORCE_SAVE_ROUND
        if force_save:
            trace(f"第 {round_no} 轮进入强制落盘模式（tool_choice={force_tool}）")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"本轮必须调用 {force_tool} 落盘，禁止再检索。\n"
                        f"主题严格为 Issue #{ISSUE_NUMBER}《{ISSUE_TITLE}》。\n"
                        f"若是新增：目录最后一段用中文概括该主题，不要使用任何示例里的目录名。\n"
                        f"若是修改或删除：target_file 必须是上文清单里本次提出者可改动的文件。\n"
                        f"Issue 原文：\n{ISSUE_BODY[:800]}"
                    ),
                }
            )

        def _call(tc_value):
            return chat_with_backoff(
                client,
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice=tc_value,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )

        try:
            resp = _call(
                {"type": "function", "function": {"name": force_tool}} if force_save else "auto"
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            if not force_save:
                raise
            trace(f"强制落盘模式调用失败（{type(exc).__name__}），退回 auto 模式")
            resp = _call("auto")

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if msg.content:
            trace(f"模型输出文本：{cut(msg.content, 600)}")
        if tool_calls:
            names = ", ".join(tc.function.name for tc in tool_calls)
            trace(f"模型请求调用工具：{names}")
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                **(
                    {
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                            }
                            for tc in tool_calls
                        ]
                    }
                    if tool_calls
                    else {}
                ),
            }
        )

        if not tool_calls:
            if RESULT:
                return
            no_tool_rounds += 1
            trace(f"⚠️ 第 {round_no} 轮未返回任何工具调用（连续第 {no_tool_rounds} 次）")
            if no_tool_rounds >= 3:
                fail(
                    f"模型连续 {no_tool_rounds} 轮未返回 function calling 结果。"
                    f"当前模型 {MODEL} 很可能不支持 tools/function calling，"
                    "请更换为支持 function calling 的模型（或改用支持工具调用的模型名）。"
                )
            log(f"第 {round_no} 轮未调用工具，继续等待落盘")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"请继续：若已完成检索，立即调用 {force_tool} 落盘"
                        "（新增用 save_article，修改用 edit_article，删除用 delete_article；"
                        "目标路径必须是中文目录下的 .md）。"
                    ),
                }
            )
            continue

        no_tool_rounds = 0
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # 检索预算拦截：配额用尽时直接返回提示，不再真的发请求
            if name == "search_web" and n_search >= MAX_SEARCH_CALLS:
                out = f"检索预算已用尽（{MAX_SEARCH_CALLS}/{MAX_SEARCH_CALLS}）。请立即用已有信息调用 save_article 写文章。"
                trace(f"⛔ search_web 预算用尽，拒绝调用")
            elif name == "fetch_url" and n_fetch >= MAX_FETCH_CALLS:
                out = f"抓取预算已用尽（{MAX_FETCH_CALLS}/{MAX_FETCH_CALLS}）。请立即用已有信息调用 save_article 写文章。"
                trace(f"⛔ fetch_url 预算用尽，拒绝调用")
            else:
                if name == "search_web":
                    n_search += 1
                elif name == "fetch_url":
                    n_fetch += 1
                trace(f"调用 {name}（累计 search {n_search}/{MAX_SEARCH_CALLS}、fetch {n_fetch}/{MAX_FETCH_CALLS}），参数：{cut(args, 600)}")
                try:
                    out = TOOL_FUNCS[name](**args)
                except Exception as exc:  # noqa: BLE001
                    out = f"工具执行失败：{type(exc).__name__}: {exc}"
                    trace(f"❌ {name} 抛出异常：{type(exc).__name__}: {exc}")
                else:
                    trace(f"✅ {name} 返回：{cut(out, 1200)}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(out)[:20000]})
            if name in WRITE_TOOLS and RESULT:
                # 落盘后自检：篇幅 + Issue 逐条覆盖，不合格就退回重写
                md_now = args.get("cn_md") or ""
                n_rewrite = sum(
                    1 for m in messages if isinstance(m.get("content"), str)
                    and m["content"].startswith("❌ 文章未通过自检")
                )
                ok, why = review_article(md_now)
                if ok:
                    trace(f"✅ 自检通过：{why}")
                    trace(f"第 {round_no} 轮落盘成功，结束循环")
                    return
                if n_rewrite >= MAX_REWRITE:
                    trace(f"⚠️ 已退回重写 {n_rewrite} 次，仍未完全满足，接受当前结果：{why}")
                    trace(f"第 {round_no} 轮落盘成功，结束循环")
                    return

                trace(f"❌ 文章未通过自检（第 {n_rewrite + 1}/{MAX_REWRITE} 次退回重写）：\n{why}")
                RESULT.clear()
                out = (
                    "❌ 文章未通过自检，本次落盘已作废，请重写一篇更完整的：\n"
                    f"{why}\n\n"
                    "要求：\n"
                    "1. 上面列出的每个缺失方面都要补上独立小标题，不许合并、不许略过；\n"
                    f"2. 正文字数不少于 {required_length()} 字；\n"
                    "3. 补齐需要的事实时可以继续用 search_web / fetch_url 检索；\n"
                    "4. 写完后再次调用同一个写入工具提交完整全文（整篇替换，不要只写增量）。"
                )
                messages.append({"role": "tool", "tool_call_id": tc.id + "_review", "content": out})
                break

    if not RESULT:
        fail(
            f"达到最大轮数 {MAX_ROUNDS} 仍未生成文章。"
            "常见原因：目录名反复被中文校验拒绝、搜索持续失败导致模型不敢落盘，或模型不遵循工具调用。"
        )


# ----------------------------------------------------------------------------
# CI 输出
# ----------------------------------------------------------------------------
def emit(name: str, value: str) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        delim = "EOF_" + re.sub(r"\W", "", name).upper()
        f.write(f"{name}<<{delim}\n{value}\n{delim}\n")


def write_summary() -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    op_cn = {"add": "新增", "update": "修改", "remove": "删除"}.get(RESULT.get("operation", ""), "改动")
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            "### 🤖 Issue → 中文博客\n\n"
            f"- 操作：{op_cn}\n"
            f"- 目录：`{RESULT['full_dir']}`\n"
            f"- 文件：`{RESULT['cn_path']}`\n"
            f"- 分支：`{RESULT['branch']}`\n"
            f"- 摘要：{RESULT['summary']}\n"
        )


def main() -> None:
    run_agent()
    if not RESULT:
        fail("未产出任何改动（可能是 Issue 要求修改/删除了别人创建的文章，已按归属规则拒绝）")
    trace(f"🎉 完成：{RESULT.get('operation')} {RESULT['full_dir']} / 分支 {RESULT['branch']}")
    dump_trace()
    for k, v in RESULT.items():
        emit(k, v)
    emit("created", "true")
    emit("trace_tail", ("\n".join(TRACE))[-6000:])
    write_summary()
    log(json.dumps(RESULT, ensure_ascii=False))


if __name__ == "__main__":
    main()
