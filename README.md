# Issue → 双语博客（CN/EN）Agent

GitHub Issue 一创建，CI 里的 AI Agent 就按你的要求在 `blog/` 下选址建目录、写 `cn.md` + `en.md`、开分支、提 PR，并回帖 PR 编号。

## 目录结构

```
.github/
├── ci/
│   ├── main.py            # Agent 主程序（OpenAI 兼容 Chat Completions + function calling）
│   └── requirements.txt
└── workflows/
    └── issue-blog-agent.yml   # issues.opened → 生成 → 分支/提交 → PR → 回帖
blog/                      # 你的博客根目录（可在 vars.BLOG_DIR 改）
```

## 需要配置的 Secrets / Variables

| 名称 | 位置 | 必填 | 说明 |
|---|---|---|---|
| `LLM_BASE_URL` | Secrets | ✅ | OpenAI 兼容地址，如 `https://api.openai.com/v1`、DeepSeek/通义/火山等兼容端点 |
| `LLM_API_KEY` | Secrets | ✅ | 模型 Key |
| `LLM_MODEL` | Variables | 推荐 | 默认 `gpt-4o-mini`，建议用支持 function calling 的模型 |
| `SEARCH_API_KEY` | Secrets | 可选 | 配了就走 Tavily（provider=auto 时优先），不配则回退到免 Key 的 DuckDuckGo |
| `SEARCH_PROVIDER` | Variables | 可选 | `auto` / `tavily` / `serper` / `brave` / `ddg` |
| `BLOG_DIR` | Variables | 可选 | 默认 `blog` |
| `MAX_ROUNDS` | Variables | 可选 | Agent 最大工具轮数，默认 16 |

模型必须支持 **function calling / tool calls**，否则 Agent 无法调用搜索与落盘工具。

## 触发与流程

1. 有人新建 Issue（默认限制：仅 OWNER / MEMBER / COLLABORATOR 触发，防外部输入滥用）。
2. Agent 读取 Issue 标题 + 正文，列出 `blog/` 目录树，联网检索核实事实。
3. 选定或新建目录（可多层），例如 `blog/ai/rag/intro-to-rag/`：
   - `cn.md`（简体中文）
   - `en.md`（English）
   - 两篇都带 YAML front matter（title / date / lang / tags / summary / source_issue）。
4. 以该目录路径建分支（如 `blog/ai/rag/intro-to-rag`），add + commit，推送。
5. `gh pr create` 建 PR（标题与 commit 一致：`docs(blog): add <目录> (cn/en)`），PR 正文 `Closes #<issue>`。
6. `gh issue comment` 在原 Issue 回帖 PR 编号与链接。

若同名分支和 PR 已存在，会复用并追加提交，不会重复开 PR。

## 手动调试

Actions → **Issue → Blog (CN/EN) Agent** → Run workflow → 填 `issue_number`。

## 安全提示（重要）

- Issue 正文会原样进入模型上下文，属于**提示词注入**高风险输入。默认只对仓库成员/协作者的 Issue 自动执行；若要放开给所有人，把 workflow 里的 `if:` 条件改为按 label 触发更稳妥。
- `permissions` 已按最小权限给到 `contents/pull-requests/issues: write`。
- 生成内容一律走 PR，不直接推主分支，保留人工 review 环节。
