# Issue → 中文博客 Agent

GitHub Issue 一创建，CI 里的 AI Agent 就按你的要求在 `blog/<中文分类>/<中文主题>/` 下写 `cn.md`、开分支、提 PR，并回帖 PR 编号。

## 目录结构

```
.github/
├── ci/
│   ├── main.py            # Agent 主程序（OpenAI 兼容 Chat Completions + function calling）
│   └── requirements.txt
└── workflows/
    └── issue-blog-agent.yml   # issues.opened → 生成 → 分支/提交 → PR → 回帖
blog/                      # 博客根目录（可在 vars.BLOG_DIR 改），内容由 Agent 生成
```

## 需要配置的 Secrets / Variables

| 名称 | 位置 | 必填 | 说明 |
|---|---|---|---|
| `LLM_BASE_URL` | Secrets | ✅ | OpenAI 兼容地址，如 `https://apihub.agnes-ai.com/v1` |
| `LLM_API_KEY` | Secrets | ✅ | 模型 Key |
| `LLM_MODEL` | Variables | 推荐 | 默认 `gpt-4o-mini`，必须支持 function calling |
| `MAX_429_RETRIES` | Variables | 可选 | 429 最大退避次数，默认 5（等待 2/4/8/16/32s） |
| `BASE_BACKOFF` | Variables | 可选 | 首次退避秒数，默认 2 |
| `SEARCH_API_KEY` | Secrets | 可选 | 配了走 Tavily，不配回退 DuckDuckGo / Bing |
| `SEARCH_PROVIDER` | Variables | 可选 | `auto` / `tavily` / `serper` / `brave` / `ddg` / `bing` |
| `BLOG_DIR` | Variables | 可选 | 默认 `blog` |
| `MAX_ROUNDS` | Variables | 可选 | Agent 最大工具轮数，默认 16 |

## 触发与流程

1. 有人新建 Issue（默认仅 OWNER / MEMBER / COLLABORATOR 触发，防外部输入滥用）。
2. Agent 读取 Issue 标题 + 正文，列出 `blog/` 目录树，联网检索核实事实。
3. 选定或新建**纯中文**目录（可多层），例如 `blog/后端/数据库/索引选型/`：
   - 只生成一个文件 `cn.md`（简体中文）
   - 带 YAML front matter（title / date / lang / tags / summary / source_issue）。
4. 以该目录路径建分支（如 `blog/后端/数据库/索引选型`），add + commit，推送。
5. `gh pr create` 建 PR（标题与 commit 一致：`docs(blog): add <中文目录>`），正文 `Closes #<issue>`。
6. `gh issue comment` 在原 Issue 回帖 PR 编号与链接。

若同名分支和 PR 已存在，会复用并追加提交，不会重复开 PR。

## 目录名强制中文

`sanitize_rel_dir()` 会过滤掉所有非汉字/数字字符：

- `AI/RAG/intro-to-rag` → 段内无汉字 → 直接报错，模型收到错误后改用中文重试
- `后端/Database/索引选型` → `后端/索引选型`

纯英文目录名不会被接受，分支名同样只保留中文。

## 429 / 错误处理

`chat_with_backoff()`：

- HTTP **429**：指数退避 2 → 4 → 8 → 16 → 32 秒，最多 5 次；仍失败则 `fail()` 退出
- 响应头带 `Retry-After` 时取其较大值
- 其他任何非 2xx 状态码：**立即 fail**，不重试

## 手动调试

Actions → **Issue → Blog (CN) Agent** → Run workflow → 填 `issue_number`。

## 安全提示（重要）

- Issue 正文会原样进入模型上下文，属于**提示词注入**高风险输入。默认只对仓库成员/协作者的 Issue 自动执行；若要放开给所有人，把 workflow 里的 `if:` 条件改为按 label 触发更稳妥。
- `permissions` 已按最小权限给到 `contents/pull-requests/issues: write`。
- 生成内容一律走 PR，不直接推主分支，保留人工 review 环节。
