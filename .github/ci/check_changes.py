#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改动归属校验（ownership check）—— 两个 workflow 共用。

规则（在「改动全是 .md」之后执行）：
  - 新增文件（added）：直接放行，任何人都可以新增
  - 修改 / 删除 / 重命名（modified / removed / renamed）：
    要求「该文件的创建者」== 「本次操作者」
      * issue-blog-agent：本次操作者 = 开 Issue 的人
      * auto-merge-md-pr：本次操作者 = 开 PR 的人

「文件创建者」的判定：
  1. 找到该文件被首次加入仓库的那次提交（git: --diff-filter=A 最早一条；api: commits?path= 最后一页最后一条）
  2. 从提交信息里提取 Issue / PR 编号（Issue #N / Closes #N / (#N)）
     —— GitHub 里 issue 与 PR 共用编号，取 /issues/{N} 的 user.login 即为创建者：
        agent 生成的文件 → 当年开那个 Issue 的人；投稿合并的文件 → 当年开那个 PR 的人
  3. 提取不到编号 → 退回提交作者本人（用 /commits/{sha} 把 author 映射成 login）
  4. 提交作者是机器人且又提取不到编号 → 无法证明归属，判定为「未知」→ 拒绝

子命令：
  check  校验给定的改动列表，输出 allowed / report
  owned  列出某个用户拥有（创建）的全部 .md 文件，供 agent 参考

环境变量：GH_TOKEN 或 GITHUB_TOKEN、GITHUB_REPOSITORY、GITHUB_WORKSPACE（git 模式）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
WORKSPACE = os.environ.get("GITHUB_WORKSPACE") or "."

BOT_LOGINS = {"github-actions[bot]", "github-actions", "dependabot[bot]", "renovate[bot]"}

# 从提交信息里提取 Issue / PR 编号（按优先级）
PATTERNS = [
    re.compile(r"[Ii]ssue\s*#(\d+)"),
    re.compile(r"(?:[Cc]loses|[Cc]lose|[Ff]ix(?:es)?|[Rr]esolve[sd]?)\s*#(\d+)"),
    re.compile(r"\(#(\d+)\)"),
]


def log(msg: str) -> None:
    print(f"[ownership] {msg}", flush=True)


def emit(name: str, value: str) -> None:
    """写入 $GITHUB_OUTPUT，支持多行值。"""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    delim = "EOF_" + re.sub(r"\W", "", name).upper() + "_" + str(abs(hash(name)) % 10000)
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"{name}<<{delim}\n{value}\n{delim}\n")


# ----------------------------------------------------------------------------
# GitHub API
# ----------------------------------------------------------------------------
def api(path: str):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "User-Agent": "ownership-check",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def owner_of_number(num: str, depth: int = 0) -> str:
    """
    返回「编号 N 对应的真实发起人」—— 即有权改动该文件的人。

    这是归属（权限）判定的一环：拿不到真实发起人，就无法判断
    「本次操作者有没有权限改这个文件」。

    issue 与 PR 共用编号，/issues/{N} 对两者都返回 user.login。
    但当 N 指向一个**由机器人创建的** issue 或 PR 时（例如 agent 建的 PR 作者是
    github-actions[bot]），直接取到的创建者是机器人，不代表任何真人，
    据此判权限会得出「谁都没权限」的错误结论。
    所以这里顺着正文里的 `Closes #M` / `Issue #M` 往回找，直到找到人类发起人。

    适用所有「创建提交由机器人完成、编号指向 PR」的情形，不限于历史文件。
    """
    if depth > 3:
        return ""
    try:
        d = api(f"/repos/{REPO}/issues/{num}")
    except Exception as exc:  # noqa: BLE001
        log(f"查询 #{num} 失败：{exc}")
        return ""

    login = ((d.get("user") or {}).get("login") or "").strip()
    if login and login not in BOT_LOGINS:
        return login

    # 是机器人（agent 建的 PR / bot 提的 issue）→ 往回找真正的人类
    if "pull_request" in d:
        try:
            pr = api(f"/repos/{REPO}/pulls/{num}")
            body = pr.get("body") or ""
        except Exception:  # noqa: BLE001
            body = ""
        for pat in PATTERNS:
            m = pat.search(body)
            if m and m.group(1) != num:
                real = owner_of_number(m.group(1), depth + 1)
                if real:
                    log(f"#{num}（机器人创建）回溯到 #{m.group(1)} 的发起人 {real}")
                    return real
    return login or ""


def front_matter_issue(path: str, sha: str, mode: str) -> str:
    """文件 front matter 里的 source_issue 是最直接的归属证据（agent 生成的文章都有）。"""
    try:
        if mode == "git" and sha:
            text = git_out("show", f"{sha}:{path}")
        else:
            d = api(f"/repos/{REPO}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(sha or 'main')}")
            import base64 as _b64
            text = _b64.b64decode(d.get("content", "")).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    m = re.search(r"source_issue\s*:\s*.*?/issues/(\d+)", text[:3000])
    return m.group(1) if m else ""


def commit_login(sha: str) -> str:
    try:
        d = api(f"/repos/{REPO}/commits/{sha}")
        return ((d.get("author") or {}).get("login") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


# ----------------------------------------------------------------------------
# git 模式：批量拿到「每个文件是被哪次提交加入的」
# ----------------------------------------------------------------------------
def git_out(*args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True,
        text=True,
        cwd=WORKSPACE,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{r.stderr.strip()[:300]}")
    return r.stdout


def git_bodies(shas: list[str]) -> dict[str, str]:
    if not shas:
        return {}
    out = git_out("show", "-s", "--format=%H%x1f%B%x1e", *shas)
    result: dict[str, str] = {}
    for chunk in out.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        sha, _, body = chunk.partition("\x1f")
        result[sha.strip()] = body
    return result


def git_added_map(prefix: str) -> dict[str, dict]:
    """path -> {sha, an, ae, msg}，取最早一次加入该文件的提交。"""
    out = git_out("log", "--diff-filter=A", "--name-only", "--format=COMMIT%x1f%H%x1f%an%x1f%ae")
    shas: dict[str, dict] = {}
    cur = None
    for line in out.split("\n"):
        if line.startswith("COMMIT\x1f"):
            parts = line.split("\x1f")
            cur = parts[1]
            shas.setdefault(cur, {"an": parts[2] if len(parts) > 2 else "",
                                  "ae": parts[3] if len(parts) > 3 else "",
                                  "paths": []})
        elif line.strip() and cur:
            shas[cur]["paths"].append(line.strip())

    bodies = git_bodies(list(shas.keys()))
    mapping: dict[str, dict] = {}
    for sha, info in shas.items():
        for p in info["paths"]:
            # 遍历顺序是新的在前，后写入的（更早的提交）覆盖前者
            mapping[p] = {"sha": sha, "an": info["an"], "ae": info["ae"],
                          "msg": bodies.get(sha, "")}
    return mapping


def api_oldest_commit(path: str) -> dict | None:
    """api 模式：取最旧一次触及该文件的提交。"""
    quoted = urllib.parse.quote(path)
    last: list | None = None
    for page in range(1, 6):
        try:
            items = api(f"/repos/{REPO}/commits?path={quoted}&per_page=100&page={page}")
        except Exception as exc:  # noqa: BLE001
            log(f"查询 {path} 提交历史失败：{exc}")
            return None
        if not items:
            break
        last = items
        if len(items) < 100:
            break
    if not last:
        return None
    c = last[-1]
    return {
        "sha": c.get("sha", ""),
        "login": ((c.get("author") or {}).get("login") or "").strip(),
        "name": (((c.get("commit") or {}).get("author") or {}).get("name") or "").strip(),
        "msg": (c.get("commit") or {}).get("message", ""),
    }


# ----------------------------------------------------------------------------
# 创建者判定
# ----------------------------------------------------------------------------
def resolve_creator(sha: str, author_name: str, author_email: str,
                    message: str, mode: str, path: str = "") -> tuple[str, str]:
    # ① 文件 front matter 里的 source_issue（最直接）
    if path:
        num = front_matter_issue(path, sha, mode)
        if num:
            login = owner_of_number(num)
            if login:
                return login, f"文件 front matter 记录的来源 Issue #{num} 的发起人"

    # ② 提交信息里的 Issue / PR 编号（会自动回溯机器人创建的 PR）
    for pat in PATTERNS:
        m = pat.search(message or "")
        if m:
            login = owner_of_number(m.group(1))
            if login:
                return login, f"来源 Issue/PR #{m.group(1)} 的发起人"

    if author_name in BOT_LOGINS or "github-actions[bot]" in (author_email or ""):
        # 机器人提交但没记录来源编号 → 无法证明归属
        return "", "创建提交来自机器人且未记录来源 Issue/PR"

    if mode == "git" and sha:
        login = commit_login(sha)
        if login:
            return login, "创建该文件的提交作者"
        return (author_name or "").strip(), "创建该文件的提交作者（未映射账号）"

    return (author_name or "").strip(), "创建该文件的提交作者"


def creator_of(path: str, mode: str, added_map: dict | None = None) -> tuple[str, str]:
    if mode == "git":
        info = (added_map or {}).get(path)
        if not info:
            return "", "未找到该文件的创建提交"
        return resolve_creator(info["sha"], info["an"], info["ae"], info["msg"], mode, path)

    c = api_oldest_commit(path)
    if not c:
        return "", "未找到该文件的创建提交"
    if c["login"] in BOT_LOGINS or not c["login"]:
        # 可能是 squash 合并，作者信息在 commit.author.name 里
        return resolve_creator(c["sha"], c["name"], "", c["msg"], "api", path)
    return resolve_creator(c["sha"], c["login"], "", c["msg"], "api", path)


# ----------------------------------------------------------------------------
# 子命令：check
# ----------------------------------------------------------------------------
def load_files(path: str) -> list | None:
    """
    读取改动清单。

    返回 None 表示「读不到 / 不是合法 JSON」——这必须被当成明确的错误抛出来，
    绝不能退化成「空列表」而被当成「没有改动」通过校验：那正是历史上
    「改动清单被写成空文件 → 归属校验静默失败」的根因。
    """
    if not path:
        log("::error::未提供 --files-json，无法校验归属")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        log(f"::error::改动清单文件不可读（{path}）：{exc}")
        return None
    if not raw.strip():
        log(f"::error::改动清单文件为空（{path}）——上游生成步骤很可能已经失败，请检查 git_changes.py 的输出")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log(f"::error::改动清单不是合法 JSON（{path}）：{exc}")
        return None
    if not isinstance(data, list):
        log(f"::error::改动清单格式错误（{path}）：应为数组，实际为 {type(data).__name__}")
        return None
    return data


def cmd_check(args) -> int:
    files = load_files(args.files_json)
    if files is None:
        emit("allowed", "false")
        emit("report", "改动清单读取失败，拒绝（详见上方 ::error:: 输出）")
        return 2

    actor = (args.actor or "").strip().lower()
    if not actor:
        log("::error::未提供本次操作者（--actor），无法校验归属")
        emit("allowed", "false")
        emit("report", "未获取到操作者身份，拒绝")
        return 2

    try:
        added_map = git_added_map(args.prefix) if args.mode == "git" else None
    except Exception as exc:  # noqa: BLE001
        # 索引建不出来时不能让异常直接冒泡成「无理由的 exit 1」，
        # 否则 workflow 只会打印一句误导性的「改动涉及他人创建的文件」。
        log(f"::error::构建「文件创建者」索引失败：{type(exc).__name__}: {exc}")
        emit("allowed", "false")
        emit("report", f"构建创建者索引失败：{exc}")
        return 3

    added, checked, violations = [], [], []
    for item in files:
        raw_status = (item.get("status") or "").lower()
        path = item.get("path") or item.get("filename") or ""
        # 重命名时以原路径判定归属
        if raw_status.startswith("r") and item.get("previous_filename"):
            lookup = item["previous_filename"]
        else:
            lookup = path
        if not path:
            continue

        if raw_status.startswith("a"):
            added.append(path)
            continue

        creator, why = creator_of(lookup, args.mode, added_map)
        ok = bool(creator) and creator.lower() == actor
        row = {"path": path, "status": raw_status, "creator": creator or "（未知）",
               "reason": why, "ok": ok}
        checked.append(row)
        if not ok:
            violations.append(row)
            log(f"✗ {path}（{raw_status}）创建者是 {creator or '未知'}，本次操作者是 {args.actor}")

    allowed = not violations
    status_cn = {"added": "新增", "modified": "修改", "removed": "删除",
                 "renamed": "重命名", "changed": "修改", "copied": "复制"}

    lines = [f"- 本次操作者：`{args.actor}`",
             f"- 新增文件 {len(added)} 个（无需归属校验）",
             f"- 修改/删除文件 {len(checked)} 个"]
    if checked:
        lines.append("")
        lines.append("| 文件 | 变更 | 创建者 | 判定 |")
        lines.append("|---|---|---|---|")
        for r in checked:
            lines.append(
                f"| `{r['path']}` | {status_cn.get(r['status'], r['status'])} | "
                f"`{r['creator']}` | {'✅ 本人' if r['ok'] else '❌ 非本人'} |")
    if violations:
        lines.append("")
        lines.append("**以下文件不是本次操作者创建的，已拒绝：**")
        lines.append("")
        for r in violations:
            lines.append(f"- `{r['path']}`（创建者 `{r['creator']}`，{r['reason']}）")

    report = "\n".join(lines)
    print(report)
    emit("allowed", "true" if allowed else "false")
    emit("report", report)
    emit("violations", "\n".join(f"- `{r['path']}`" for r in violations) or "（无）")
    emit("added_count", str(len(added)))
    emit("checked_count", str(len(checked)))
    return 0 if allowed else 1


# ----------------------------------------------------------------------------
# 子命令：owned
# ----------------------------------------------------------------------------
def cmd_owned(args) -> int:
    actor = (args.actor or "").strip().lower()
    if args.mode == "git":
        all_files = [p.strip() for p in git_out("ls-files", "--", args.prefix).split("\n") if p.strip()]
        added_map = git_added_map(args.prefix)
    else:
        tree = api(f"/repos/{REPO}/git/trees/{args.branch}?recursive=1")
        all_files = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
        added_map = None

    md_files = [p for p in all_files if p.lower().endswith(".md") and p.startswith(args.prefix)]
    owned, others = [], []
    for p in md_files:
        creator, _ = creator_of(p, args.mode, added_map)
        if creator and creator.lower() == actor:
            owned.append(p)
        else:
            others.append(p)

    data = {"actor": args.actor, "owned": sorted(owned), "others": sorted(others)}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log(f"{args.actor} 可改动 {len(owned)} 个文件，不可改动 {len(others)} 个")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="改动归属校验")
    ap.add_argument("cmd", choices=["check", "owned"])
    ap.add_argument("--mode", choices=["git", "api"], default="git")
    ap.add_argument("--actor", default="", help="本次操作者 login")
    ap.add_argument("--prefix", default="blog", help="归属校验生效的目录前缀")
    ap.add_argument("--branch", default="main", help="api 模式下列文件用的分支")
    ap.add_argument("--files-json", default="", help="check：[{path,status}] 的 JSON 文件")
    ap.add_argument("--out", default="", help="owned：输出 JSON 路径")
    args = ap.parse_args()

    if not REPO:
        print("::error::GITHUB_REPOSITORY 未设置", flush=True)
        return 2
    if not TOKEN:
        print("::error::GH_TOKEN / GITHUB_TOKEN 未设置", flush=True)
        return 2

    if args.cmd == "check":
        return cmd_check(args)
    return cmd_owned(args)


if __name__ == "__main__":
    sys.exit(main())
