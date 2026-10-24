# Issue → 中文博客 Agent

GitHub Issue 一创建，CI 里的 AI Agent 就按你的要求在 `blog/<中文分类>/<中文主题>/` 下写 `cn.md`，校验改动合法后**直接提交并推送到主分支**，再回帖提交链接。不建分支、不开 PR。

## 目录结构

```
.github/
├── ci/
│   ├── main.py            # Agent 主程序（OpenAI 兼容 Chat Completions + function calling）
│   └── requirements.txt
└── workflows/
    └── issue-blog-agent.yml   # issues.opened → 生成 → .md 校验（失败重跑）→ 直推主分支 → 回帖
blog/                      # 博客根目录（可在 vars.BLOG_DIR 改），内容由 Agent 生成
```

## 需要配置的 Secrets / Variables

| 名称 | 位置 | 必填 | 说明 |
|---|---|---|---|
| `LLM_BASE_URL` | Secrets | ✅ | OpenAI 兼容地址，当前 `https://apihub.agnes-ai.com/v1` |
| `LLM_API_KEY` | Secrets | ✅ | 模型 Key |
| `LLM_MODEL` | Variables | 推荐 | 当前 `agnes-3.0-flash`，必须支持 function calling |
| `MAX_429_RETRIES` | Variables | 可选 | 429 最大退避次数，默认 5（等待 2/4/8/16/32s） |
| `BASE_BACKOFF` | Variables | 可选 | 首次退避秒数，默认 2 |
| `SEARCH_API_KEY` | Secrets | 可选 | 配了走 Tavily，不配回退 DuckDuckGo / Bing |
| `SEARCH_PROVIDER` | Variables | 可选 | `auto` / `tavily` / `serper` / `brave` / `ddg` / `bing` |
| `BLOG_DIR` | Variables | 可选 | 默认 `blog` |
| `MAX_ROUNDS` | Variables | 可选 | Agent 最大工具轮数，默认 16 |
| `MAX_ATTEMPTS` | Variables | 可选 | Agent 整轮重跑次数上限，默认 2（即失败最多再跑一次） |

## 触发与流程

1. 有人新建 Issue（默认仅 OWNER / MEMBER / COLLABORATOR 触发，防外部输入滥用）。
2. Agent 读取 Issue 标题 + 正文，列出 `blog/` 目录树，联网检索核实事实。
3. 选定或新建**纯中文**目录（可多层），例如 `blog/后端/数据库/索引选型/`：
   - 只生成一个文件 `cn.md`（简体中文）
   - 带 YAML front matter（title / date / lang / tags / summary / source_issue）。
4. **校验改动**：`git diff --cached --name-only` 列出全部变更文件，**必须全部以 `.md` 结尾**。
   - 出现任何非 `.md` 改动（或 Agent 报错、空产出）→ 丢弃本次结果（`git reset --hard` + `git clean -fd`）→ 整轮重跑。
   - 最多跑 `MAX_ATTEMPTS` 次（默认 2），用完仍不合法才判失败并回帖。
5. 校验通过后直接在主分支 commit（`docs(blog): add <中文目录>`，正文含 `Closes #<issue>`），`pull --rebase` 后推送。
6. `gh issue comment` 在原 Issue 回帖目录、文件与提交链接。

> 中文路径下 `git diff --name-only` 默认会把路径转义成 `"blog/\346\265\213\350\257\225/cn.md"` 这种带引号的八进制形式，
> 导致 `.md` 后缀判断失效。因此所有 diff 调用统一加 `-c core.quotepath=false`。

## 改动白名单（仅 .md）

守卫有两道，防止 Agent 幻觉改到代码或 workflow 文件：

- Agent 步骤内：每次产出后校验，不合法就丢弃重跑。
- 推送步骤内：提交前再校验一次，发现非 `.md` 立即终止推送。

判断逻辑等价于：

```bash
CHANGED="$(git -c core.quotepath=false diff --cached --name-only)"
NON_MD="$(printf '%s\n' "$CHANGED" | sed '/^[[:space:]]*$/d' | grep -vE '\.md$' || true)"
[ -n "$NON_MD" ] && { git reset --hard HEAD; git clean -fd; }   # 丢弃重跑
```

## 目录名强制中文

`sanitize_rel_dir()` 会过滤掉所有非汉字/数字字符：

- `AI/RAG/intro-to-rag` → 段内无汉字 → 直接报错，模型收到错误后改用中文重试
- `后端/Database/索引选型` → `后端/索引选型`

纯英文目录名不会被接受（`main.py` 的 `sanitize_branch()` 同样只保留中文）。

## 429 / 错误处理

`chat_with_backoff()`：

- HTTP **429**：指数退避 2 → 4 → 8 → 16 → 32 秒，最多 5 次；仍失败则 `fail()` 退出
- 响应头带 `Retry-After` 时取其较大值
- 其他任何非 2xx 状态码：**立即 fail**，不重试

## 手动调试

Actions → **Issue → Blog (CN) Agent** → Run workflow → 填 `issue_number`。

## 安全提示（重要）

- Issue 正文会原样进入模型上下文，属于**提示词注入**高风险输入。默认只对仓库成员/协作者的 Issue 自动执行；若要放开给所有人，把 workflow 里的 `if:` 条件改为按 label 触发更稳妥。
- `permissions` 已按最小权限给到 `contents/issues: write`（不再需要 `pull-requests: write`）。
- ⚠️ **当前流程会直接推送主分支，没有 PR 环节**，也就没有人工 review。唯一的防线是「改动仅含 `.md`」这道白名单校验。
  若希望保留 review，把这版 workflow 的推送步骤改回建分支 + `gh pr create` 即可。
- 建议给 `main` 分支加一条 branch protection：**Require a pull request before merging** 之外的规则要注意，
  设置为允许 `github-actions[bot]` 推送，否则直接 push 会被规则拒绝。
- 并发：多个 Issue 同时触发时，`concurrency` 按 Issue 号分组并不会阻止它们同时推 `main`；
  推送步骤已用 `git pull --rebase` 降低冲突概率，极端情况下仍可能因 rebase 冲突失败（重跑一次即可）。

## 仓库设置要求（否则推送会失败）

Settings → Actions → General → Workflow permissions 需要：

- 勾选 **Read and write permissions**

即 `default_workflow_permissions = write`，否则 `GITHUB_TOKEN` 没有 `contents: write`，无法推送主分支。
可用一条命令确认：

```bash
gh api /repos/<owner>/<repo>/actions/permissions/workflow --jq '.'
# 期望：default_workflow_permissions = "write"
```

若主分支启用了 branch protection 且包含限制推送的规则，还需把 `github-actions[bot]` 加入允许列表。
