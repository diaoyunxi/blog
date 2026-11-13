> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「需要配置的 Secrets / Variables」章节拆分而来。

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
| `CLOUDFLARE_API_TOKEN` | Secrets | 部署用 | Cloudflare API Token（需 **Workers Scripts 编辑**权限，不是 Pages 权限） |
| `CLOUDFLARE_ACCOUNT_ID` | Secrets | 部署用 | Cloudflare Account ID |
| `SITE_URL` | Variables | 推荐 | RSS / sitemap 使用的站点根地址；迁移后设为 workers.dev 或自定义域名 |
