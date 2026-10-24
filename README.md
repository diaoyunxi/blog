# Issue → 中文博客 Agent

GitHub Issue 一创建，CI 里的 AI Agent 就按你的要求在 `blog/<中文分类>/<中文主题>/` 下写 `cn.md`，校验改动合法后**直接提交并推送到主分支**，再回帖提交链接。不建分支、不开 PR。

## 目录结构

```
.github/
├── ci/
│   ├── main.py            # Agent 主程序（OpenAI 兼容 Chat Completions + function calling）
│   └── requirements.txt
└── workflows/
    ├── issue-blog-agent.yml   # issues.opened → 生成 → .md 校验（失败重跑）→ 直推主分支 → 回帖
    └── auto-merge-md-pr.yml   # pull_request_target.opened/reopened → .md 校验通过则自动合并
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
| `MERGE_METHOD` | Variables | 可选 | PR 自动合并方式：`squash`（默认）/ `merge` / `rebase` |
| `DELETE_BRANCH` | Variables | 可选 | 自动合并后是否删除源分支，默认 `true` |
| `ABORT_ON_CONFLICT` | Variables | 可选 | PR 冲突时放弃合并并留言，默认 `true` |

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

## PR 自动合并（仅 .md）

`.github/workflows/auto-merge-md-pr.yml` 在 PR **打开或重新打开**时触发（`pull_request_target`）：

1. 读取 PR 元信息：非 `OPEN` 状态、或仍是草稿 → 跳过。
2. 用 API（`--paginate --slurp`）拉全部分页的改动文件，逐个判断后缀：
   - 全部是 `.md` → 自动合并
   - 有任何一个非 `.md` → **不合并**，在 PR 下留言列出违规文件
   - 没有任何改动 → 不合并，留言说明
3. 合并前轮询等待 GitHub 算出合并状态（`mergeable` / `mergeStateStatus`）；
   冲突（`CONFLICTING` / `DIRTY`）时留言并放弃，否则执行 `gh pr merge`。
4. 优先 `--auto`（等 checks/review 满足后自动落），失败则回退为直接合并；合并后回帖说明（含来源：fork 投稿 / 同仓库分支）。

> `mergeable` 在 gh CLI 里是枚举 `MERGEABLE / CONFLICTING / UNKNOWN`，不是 `true / false`，
> 判冲突要比较 `CONFLICTING` 而不是布尔值。

### 为什么用 pull_request_target

Issue→Blog Agent 已经**直推主分支**，不再产生 PR。所以会走到这里的 PR 全部来自外部投稿者，
也就是 **fork PR**。而 fork PR 在 `pull_request` 事件下 `GITHUB_TOKEN` 会被强制降为只读，
`gh pr merge` 必然 403 —— 必须用 `pull_request_target` 才有写权限。

`pull_request_target` 的默认风险是把「写权限 token」和「不可信的 PR 代码」放进同一个 runner。
本 workflow 之所以安全，是因为它满足以下全部条件：

- ❌ 没有 `actions/checkout`，从不把 PR 的 head 代码拉到 runner 上
- ❌ 不构建、不装依赖、不跑测试、不执行 PR 里的任何脚本
- ✅ 只通过 REST API 读取**文件名**做后缀判断，连文件内容都不打开
- ✅ 加上「diff 只允许 .md」这道门，即使误合并也不会有可执行代码进入仓库

> ⚠️ **维护约定**：以后不要在本文件里加入 checkout PR head、`npm install` / `pip install`、
> 或直接运行 PR 中脚本的步骤。加了就等于把写权限 token 交给不可信代码。

需要的仓库设置：

- Settings → General → **Allow auto-merge**：已开启（否则 `--auto` 会失败，会回退直接合并）
- Settings → Actions → General → Workflow permissions：**Read and write permissions**
- Settings → Actions → General → **Require approval for all external contributors**：
  若开启，外部 fork 投稿的 workflow 需要你点一次批准才会跑（不是全自动）。
  想完全无人值守就关掉它——鉴于本 workflow 不执行 PR 代码，关闭的风险可接受。

手动补跑：Actions → **Auto-merge PR (md-only)** → Run workflow → 填 `pr_number`。

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
- ⚠️ 自动合并没有人工 review 环节，防线只有「diff 仅 .md」。若希望更安全，可给 `main` 加分支保护
  （要求 review 或指定检查通过），此时 `--auto` 会在条件满足后才落合并，等于多一道人工闸门。

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
