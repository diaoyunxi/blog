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

import json
import os
import pathlib
import re
import sys
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
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE") or "0.2")
MAX_429_RETRIES = int(os.getenv("MAX_429_RETRIES") or "5")   # 2/4/8/16/32s
BASE_BACKOFF = float(os.getenv("BASE_BACKOFF") or "2")       # 首次等待秒数

UA = "Mozilla/5.0 (compatible; BlogIssueBot/1.0; +https://github.com)"


def log(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


def fail(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"::error::[agent] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ----------------------------------------------------------------------------
# 读取 issue 内容
# ----------------------------------------------------------------------------
def read_env_or_file(env_key: str, file_key: str) -> str:
    for key in (env_key, file_key):
        val = os.getenv(key)
        if val:
            return val
    path = os.getenv(file_key + "_PATH") or ""
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
                "url": a["href"],
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


def save_article(target_dir: str, cn_md: str, summary: str = "") -> str:
    """校验目录并写入 cn.md（目录名必须为纯中文）。"""
    rel = sanitize_rel_dir(target_dir)
    out_dir = (BLOG_ROOT / rel).resolve()
    if BLOG_ROOT != out_dir and BLOG_ROOT not in out_dir.parents:
        raise ValueError(f"非法目录: {target_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    cn_path = out_dir / "cn.md"
    cn_path.write_text(cn_md.strip() + "\n", encoding="utf-8")

    branch = sanitize_branch(rel)
    title = f"docs({BLOG_DIR_NAME}): add {rel}"
    RESULT.update(
        {
            "target_dir": rel,
            "cn_path": f"{BLOG_DIR_NAME}/{rel}/cn.md",
            "full_dir": f"{BLOG_DIR_NAME}/{rel}",
            "branch": branch,
            "title": title,
            "summary": summary or ISSUE_TITLE,
        }
    )
    log(f"已写入 {RESULT['cn_path']}")
    return json.dumps(
        {
            "ok": True,
            "dir": rel,
            "files": [RESULT["cn_path"]],
            "branch": branch,
            "note": "文章已落盘，请直接用一句话总结本次写入的内容，不要再次调用工具。",
        },
        ensure_ascii=False,
    )


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
            "name": "save_article",
            "description": "把最终的简体中文文章写入磁盘。必须在检索核实之后调用，且只调用一次。目录名必须是中文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_dir": {
                        "type": "string",
                        "description": "相对博客根目录的多层中文目录，如 后端/数据库/索引选型；最后一段即以主题命名的文件夹",
                    },
                    "cn_md": {"type": "string", "description": "简体中文完整 Markdown 正文（含 YAML front matter）"},
                    "summary": {"type": "string", "description": "一句话总结本次新增内容（会写入 PR 正文）"},
                },
                "required": ["target_dir", "cn_md"],
            },
        },
    },
]

TOOL_FUNCS = {
    "search_web": lambda **kw: search_web(kw.get("query", ""), kw.get("max_results", 6)),
    "fetch_url": lambda **kw: fetch_url(kw.get("url", "")),
    "list_blog_tree": lambda **kw: blog_tree(),
    "save_article": lambda **kw: save_article(
        kw.get("target_dir", ""), kw.get("cn_md", ""), kw.get("summary", "")
    ),
}


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""你是一个"中文技术博客写作 Agent"，运行在 GitHub Actions 中。
你会收到一个 GitHub Issue（用户提出的写作/解答需求），必须产出一篇简体中文文章落盘到仓库。

硬性要求：
1. 博客根目录：{BLOG_DIR_NAME}/（仓库根目录下）。先检查 list_blog_tree 给出的既有分类：
   - 有合适分类就复用它（可以再往下加一层子目录）；
   - 没有合适分类就自行新建，允许多层子目录。
2. **所有目录名（含分类层和最后一层主题目录）必须使用简体中文**，例如：
   后端/数据库/索引选型、人工智能/检索增强生成、前端/构建工具。
   严禁出现任何英文单词、拼音、kebab-case、日期、issue 编号或泛化词（杂项、其他、新文章）。
   程序会过滤掉非汉字字符，纯英文目录会被直接拒绝并报错，届时请立刻改用中文重新调用。
3. 最后一层目录名必须体现 issue 主题，用简短中文词组（4~12 字为宜）。
4. 在该目录下只创建一个文件：cn.md（简体中文）。
5. 事实性内容（版本号、参数、基准数据、时间、人名、API 形态、价格）必须先用 search_web 检索，
   再用 fetch_url 打开 1~3 个权威来源核实。搜不到就明确写"截至 {TODAY} 未找到权威来源"，禁止编造。
6. 结构建议：背景 → 核心概念/原理 → 实操步骤或示例（带代码/命令块）→ 常见坑 → 小结 → 参考链接。
   正文 800~1500 字，Markdown 规范，代码块标注语言。
7. 文件开头必须写 YAML front matter：
   ---
   title: <中文标题>
   date: {TODAY}
   lang: zh-CN
   tags: [标签1, 标签2]
   summary: <一句话摘要>
   source_issue: {ISSUE_URL or ('#' + ISSUE_NUMBER if ISSUE_NUMBER else '')}
   ---
8. 参考链接放在正文末尾的"参考"小节，只写你实际抓取或确认过的 URL。
9. 不要写与主题无关的内容，不要在正文里提及 issue、机器人或本流程。

最后必须调用 save_article 落盘，成功后用一句话总结即可。"""


def build_user_prompt() -> str:
    return (
        f"Issue #{ISSUE_NUMBER}: {ISSUE_TITLE}\n"
        f"Issue 链接: {ISSUE_URL}\n"
        f"提出者: {ISSUE_AUTHOR}\n"
        f"日期: {TODAY}\n\n"
        f"当前博客目录结构（根目录 {BLOG_DIR_NAME}/，全部为中文）：\n{blog_tree()}\n\n"
        f"Issue 正文（需求）如下：\n-----\n{ISSUE_BODY}\n-----\n\n"
        "请先检索核实，再调用 save_article 写入 cn.md（目录名必须是中文）。"
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

    for round_no in range(1, MAX_ROUNDS + 1):
        resp = chat_with_backoff(
            client,
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=TEMPERATURE,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
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
            log(f"第 {round_no} 轮未调用工具，继续等待落盘")
            messages.append(
                {
                    "role": "user",
                    "content": "请继续：若已完成检索，立即调用 save_article 写入 cn.md（目录名必须是中文）。",
                }
            )
            continue

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            log(f"第 {round_no} 轮调用 {name}")
            try:
                out = TOOL_FUNCS[name](**args)
            except Exception as exc:  # noqa: BLE001
                out = f"工具执行失败：{type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(out)[:20000]})
            if name == "save_article" and RESULT:
                return

    if not RESULT:
        fail(f"达到最大轮数 {MAX_ROUNDS} 仍未生成文章")


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
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            "### 🤖 Issue → 中文博客\n\n"
            f"- 目录：`{RESULT['full_dir']}`\n"
            f"- 文件：`{RESULT['cn_path']}`\n"
            f"- 分支：`{RESULT['branch']}`\n"
            f"- 摘要：{RESULT['summary']}\n"
        )


def main() -> None:
    run_agent()
    if not RESULT:
        fail("未产出任何文件")
    for k, v in RESULT.items():
        emit(k, v)
    emit("created", "true")
    write_summary()
    log(json.dumps(RESULT, ensure_ascii=False))


if __name__ == "__main__":
    main()
