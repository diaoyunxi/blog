#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 `git diff --cached --name-status` 转成 [{"path","status","previous_filename"}] 的 JSON。

为什么要单独成一个文件：
  这段逻辑原先是写在 workflow 的 `run: |` 块里的内嵌 `python3 -c '...'`。
  YAML 块标量只剥离「统一的最外层缩进」，块内部各行相对缩进会被原样保留，
  于是 `items = []`（相对缩进 0）后面跟着 `for line in sys.stdin:`（相对缩进 2），
  Python 直接抛 IndentationError: unexpected indent → JSON 文件被写成空文件 →
  下游 check_changes.py 读空文件抛 JSONDecodeError → 归属校验被误判为「不通过」。
  这个 bug 不会输出任何 ::error::，只会表现为「Agent 明明成功却反复重跑后失败」。
  独立成文件后缩进由文件本身保证，彻底消除该类问题。

用法：
  python .github/ci/git_changes.py [输出文件路径]
  不传路径时写到标准输出。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def build_items() -> list[dict]:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-status"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(
            "::error::git diff --cached 执行失败："
            + (proc.stderr or "").strip()[:300],
            file=sys.stderr,
            flush=True,
        )
        sys.exit(3)

    items: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        path = (parts[-1] if len(parts) > 1 else "").strip()
        previous = (
            parts[1].strip()
            if len(parts) > 2 and status.startswith("R")
            else ""
        )
        if not path:
            continue
        items.append({"path": path, "status": status, "previous_filename": previous})
    return items


def main() -> int:
    items = build_items()
    payload = json.dumps(items, ensure_ascii=False)

    out = sys.argv[1] if len(sys.argv) > 1 else ""
    if out:
        out = os.path.expandvars(out)
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError as exc:
            print(f"::error::写入改动清单失败：{exc}", file=sys.stderr, flush=True)
            return 4
        print(f"[git-changes] 已写入 {len(items)} 条改动到 {out}", flush=True)
    else:
        sys.stdout.write(payload)

    for item in items:
        print(f"[git-changes] {item['status']}\t{item['path']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
