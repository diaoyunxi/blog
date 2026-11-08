> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「PR 自动合并（仅 .md）」章节拆分而来。

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
