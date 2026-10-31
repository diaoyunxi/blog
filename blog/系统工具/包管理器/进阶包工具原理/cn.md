---
title: 完整介绍 apt 的原理
date: 2026-10-31
lang: zh-CN
tags: [Linux, 包管理器, apt, dpkg, Debian, Ubuntu, 依赖解析, 软件源]
summary: 从定位分层、软件源、update、依赖解析、安装链路、dpkg 状态、pinning、签名信任、缓存清理到常见坑，完整梳理 apt install 一条命令背后的原理。
source_issue: https://github.com/diaoyunxi/blog/issues/17
---

# 完整介绍 apt 的原理

在 Debian/Ubuntu 上执行 `sudo apt install nginx`，看似一步到位，背后其实是一条很长的链路：读取软件源配置 → 查本地包索引 → 做依赖求解 → 下载 `.deb` → 调 dpkg 解包 → 跑维护脚本与触发器 → 更新状态数据库。这篇文章把这条链路上的每一环拆开讲清楚。

## 一、定位与分层

apt（Advanced Package Tool）是 Debian 系的**包管理前端**：它负责“从哪些源取包、装哪些版本、谁依赖谁、按什么顺序装”这些**决策**；真正做“把 `.deb` 里的文件写到系统里”这件事的是底层的 **dpkg**。

各工具分工：

- **apt / apt-get / aptitude**：上层前端。读软件源配置、维护本地包索引缓存（`/var/lib/apt/lists/`）、做依赖解析与版本选择、生成“将要安装/删除哪些包”的方案，然后**调用 dpkg 执行**；
- **dpkg**：下层执行器。只认本地 `.deb` 文件，负责 unpack（解包）与 configure（配置）两个阶段，维护 `/var/lib/dpkg/` 下的状态库。它**不知道**远程仓库、**不做**依赖求解、**不下载**任何东西；
- **apt-cache**：查询工具。`apt-cache policy nginx`、`apt-cache depends nginx` 等，读的是本地索引与状态数据库；
- **aptitude**：与 apt-get 同级的另一个前端，解析器不同、交互更强，适合在依赖冲突时逐个决定升级/回退/保留；
- **snap**：另一套完全独立的包管理栈（Canonical 维护，二进制与 deb 格式不同），和 apt/dpkg 没有依赖关系，可以共存但文件布局各自为政。

所以严格说，**apt 本身不会解包文件**；`apt install` 最后一步永远是 fork 出 `dpkg` 来完成解包与维护脚本执行。

## 二、软件源配置

apt 从哪些位置取索引和包，由这两类文件决定：

```text
/etc/apt/sources.list              # 传统入口（one-line 格式）
/etc/apt/sources.list.d/*.list     # one-line 片段
/etc/apt/sources.list.d/*.sources   # deb822 片段（apt ≥ 1.1）
```

### 1. one-line 格式（传统）

```bash
# /etc/apt/sources.list
deb [ arch=amd64 ] http://deb.debian.org/debian stable main restricted universe
deb-src http://deb.debian.org/debian stable main restricted universe
```

字段依次是：`类型`（`deb` / `deb-src`）、可选的 `[选项]`、`URI`（可含 `$(ARCH)` 占位）、`suite`、`component`（可多个）。

- **suite**：发行版代号或代号路径，如 `stable`、`testing`、`unstable`，或具体代号 `bookworm`、`noble`；精确路径（如 `stable/updates`，结尾带 `/`）时 component 必须省略。
- **component**：组件名。Debian 常见 `main` / `contrib` / `non-free`；Ubuntu 常用 `main` / `restricted` / `universe` / `multiverse`。含义：
  - `main`：自由软件、官方维护；
  - `restricted`：含闭源但必要的组件（Ubuntu 特有，如显卡驱动）；
  - `universe`：社区维护的自由软件；
  - `multiverse`：社区维护、自由/非自由混合（Ubuntu 特有）；
  - `contrib` / `non-free`（Debian）：非官方维护/非自由软件。

### 2. deb822 格式（新写法）

把同一份信息写成多行 stanza，文件扩展名 `.sources`，多个 stanza 之间用空行分隔：

```bash
# /etc/apt/sources.list.d/ubuntu.sources
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: noble
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
```

优点：多值字段可读性更好；可用 `Enabled: no` 一行禁掉整个 stanza；是 apt 官方正在**逐步取代 one-line** 的目标格式。老版本 apt 遇到 `.sources` 会忽略，新 apt 两者都读。

### 3. 加第三方源

原则：每个第三方源单独放一个 `.sources` 文件，公钥单独放到 `/etc/apt/keyrings/`，用 `Signed-By:` 锁定：

```bash
# /etc/apt/sources.list.d/git-lfs.sources
Types: deb
URIs: https://ppa.launchpadcontent.net/git-core/git-lfs/ubuntu
Suites: noble
Components: main universe
Signed-By: /etc/apt/keyrings/git-lfs.ppa.keyring
```

公钥导入示例（PPA 的 key 一般从 launchpad 抓取）：

```bash
sudo mkdir -p /etc/apt/keyrings
sudo gpg --keyserver keyserver.ubuntu.com --recv-keys <指纹>
sudo gpg --export -a <指纹> | sudo tee /etc/apt/keyrings/git-lfs.ppa.keyring
sudo gpg --dearmor -o /etc/apt/keyrings/git-lfs.ppa.keyring.gpg /etc/apt/keyrings/git-lfs.ppa.keyring
```

不要再用已废弃的 `apt-key`（见第八节）。

## 三、apt update 到底做了什么

`apt update`（等价 `apt-get update`）**不安装任何包**，它做的是“同步索引”：

1. 遍历 `/etc/apt/sources.list` + `sources.list.d/` 里的**所有源**；
2. 对每个源先取 `dists/<suite>/InRelease`（或 `Release` + `Release.gpg`）；
3. 用本地公钥（`/etc/apt/trusted.gpg.d/`、`/etc/apt/keyrings/` 或源里 `Signed-By:` 指定的 keyring）对签名做 GPG 校验，并核对 `Release` 里记录的 SHA256/SHA512 与 `InRelease` 是否一致；
4. `Release` 文件声明该源下有哪些索引（`Packages`、`Packages.gz`、`Packages.xz`、`Contents`、`Translation` 等）以及每个文件的**路径与哈希**；
5. 按声明把 `Packages.gz` / `Packages.xz`（或 PDiff 增量）下载到 `/var/lib/apt/lists/partial/`，边下边哈希校验；
6. 校验通过后才从 `partial/` 移到 `/var/lib/apt/lists/` 的正式位置，供后续 `apt-get` / `apt-cache` 查询。

不 update 会怎样：`/var/lib/apt/lists/` 里是**上一次 update 时的快照**。`apt install` 看到的“最新版”可能落后几周，`apt upgrade` 也只会升到旧快照里存在的版本；极端情况（源换了、包改名了）直接报“找不到包”。所以新机器或加源之后，**先 update 再 install** 是硬性顺序。

## 四、依赖解析原理（本文核心）

`.deb` 控制段里有一组元数据描述包的依赖关系，强弱不等（Debian Policy 7.x 节“Declaring relationships between packages”）：

| 字段 | 含义 | 强度 |
| --- | --- | --- |
| `Depends` | 运行时强依赖，缺了无法正常工作 | 硬 |
| `Pre-Depends` | 必须**先于本包配置完成**才生效的依赖（如依赖 `dpkg` 新特性） | 硬 + 时序 |
| `Recommends` | 推荐依赖，缺了功能降级但能跑 | 软 |
| `Suggests` | 建议关联，更弱 | 软 |
| `Enhances` | 存在则增强功能，比 Suggests 略强 | 软 |
| `Conflicts` | 装本包时对方必须不在 | 硬约束 |
| `Breaks` | 本包版本比对方新，对方旧版不能用 | 硬约束 |
| `Replaces` | 本包接管对方的某些文件（常配合 Conflicts） | 硬约束 |
| `Provides` | 虚拟包：本包“提供”某个别的包名 | 让依赖可替代 |

版本约束语法如 `Depends: libc6 (>= 2.35-0`… 实际写 `(>= 2.35)`。虚拟包让替代成为可能：`Provides: virtual-font-libfoo` 后，任何写 `Depends: virtual-font-libfoo` 的包都可以被它满足。

### 求解过程

`apt` 拿到“目标包 + 当前 `/var/lib/dpkg/status` 的已安装状态”后，要解出一个**安装/删除/升级集合**，使所有 `Depends`/`Pre-Depends` 被满足、所有 `Conflicts`/`Breaks` 不被违反。这个集合：

- 是**与/或逻辑**：`Depends: A | B` 表示装 A 或 B 之一即可；
- 允许**虚拟包替代**；
- 是一个**约束满足问题**，理论上是 NP 完全的（可把 SAT 规约到它）。

apt 用的是**带评分的回溯搜索**（backtracking solver）：

1. 以“把目标包升到最高可用版本”作为初始假设；
2. 递归展开每个 `Depends`，遇 `Conflicts` 标记冲突候选；
3. 对每个包按评分挑选：已安装版本最优先、再按 pinning 优先级、最后按版本号；
4. 走死胡同时回退、换次高版本、或接受删除某个包；
5. 最终输出**最小改动集合**，打印“将安装 X 个包、释放 Y MB、下载 Z MB”。

`aptitude` 用不同的解析器：倾向于“少装少删”，允许交互选择；`apt-get` 的解析器更激进，必要时会删包（见 `full-upgrade`）。

解析失败的典型原因：`E: Unable to correct problems: you have held broken packages`。多半是：之前 `dpkg` 被 Ctrl-C 中断留下 `half-configured` 状态、有包被 `apt-mark hold` 住、或 `Depends` 与 `Conflicts` 形成死锁。修复入口是 `sudo dpkg --configure -a` 或 `sudo apt-get -f install`。

## 五、apt install 的完整执行链路

`sudo apt install nginx` 内部：

1. **决策阶段**：读本地索引做依赖求解，输出“将要安装哪些 `.deb` 及其版本”；
2. **下载阶段**：把每个 `.deb` 下到 `/var/cache/apt/archives/partial/`，支持多线程、断点续传、SHA256 校验；通过后才移到 `/var/cache/apt/archives/`；
3. **调用 dpkg**：按拓扑序逐个 `dpkg --unpack` 再 `dpkg --configure`，两阶段分离是关键——先只解包、不跑配置脚本，最后统一配置；
4. **维护脚本**（每个包可自带 4 个 shell 脚本，按顺序执行）：
   - `preinst`：解包前跑，用于占位、停服务；
   - `postinst`：解包后、配置阶段跑，做初始化、起服务、写配置；
   - `prerm`：卸载前；
   - `postrm`：卸载后；
5. **触发器 `dpkg-trigger`**：某些包（如 `fonts-dejavu`、`libgtk`）声明“我变了要通知 X”，被通知的包延迟到**本次操作全部结束后**统一跑一遍触发器，避免每个包装一次都重复重建缓存；
6. **配置文件冲突（conffile）**：包里的 `/etc/nginx/nginx.conf` 之类被标为 conffile，dpkg 发现本地版本和包里的不一样就停手，交互环境下弹“保留本地版 / 用新版 / 显示差异”；脚本里没 TTY 就按 `/etc/dpkg/dpkg.cfg.d/` 里 `force-confdef` / `force-confold` 决定；
7. **事务性**：apt **不是原子事务**。任何一步失败都不会自动回滚到操作前的系统状态。能做的只是“已解包未配置”的包保持半安装，`sudo dpkg --configure -a` 续上。

## 六、dpkg 层与状态文件

- `/var/lib/dpkg/status`：所有已装包的**单一大文件**，含包名、版本、状态、`Depends` 等；`apt-cache` 也读它；
- `/var/lib/dpkg/info/`：每个包的 `*.postinst`、`*.postrm`、`*.conffiles`、`*.md5sums`、`*.list`（文件清单）等；
- 包状态机（在 status 里每个包记录）：
  - `install ok installed`（正常）
  - `install ok unpacked`（已解包未配置）
  - `install reinstreq half-configured`（配置中断）
  - `install ok half-installed`（更烂）

常用查询：

```bash
dpkg -l nginx                  # 查安装状态与版本
dpkg -S /usr/sbin/nginx        # 反查：哪个包装了某文件
dpkg -L nginx                  # 正查：某包装了哪些文件
```

dpkg **不认依赖关系、不下载、不解依赖**，只认单个 `.deb`。它没有“远程”概念，所有索引/下载/求解都是 apt 的事。

## 七、版本选择与优先级（pinning）

`apt-cache policy` 读的是 `/etc/apt/preferences` + `/etc/apt/preferences.d/` 里所有 pin 配置 + `APT::Default-Release`。

- **数值语义**：
  - `P >= 1000`：即使降级也装；
  - `990 <= P < 1000`：即使不来自 target release 也装；
  - `500 <= P < 990`：默认不降级；
  - `100 <= P < 500`：只在该分布有该版本且本地更旧时装；
  - `0 < P < 100`：仅在本地没装过时装；
  - `P < 0`：永远不装。
- 默认（无 preferences）：已装包 `P=100`，target release 里 `P=990`，其他 release 里 `P=500`，标了 `NotAutomatic` 的 archive `P=1`。
- 写 pin 示例：

```text
# /etc/apt/preferences.d/git-lfs
Package: git-lfs
Pin: version 3.*
Pin-Priority: 999
```

混 stable/testing 或加 PPA 时，**必须**给目标分布钉高 pin、给实验分布钉低 pin（如 `unstable` 设 50），否则 `apt full-upgrade` 可能把整个系统推到一半 stable 一半 testing 的烂状态。

## 八、签名与信任链

- 仓库根下 `dists/<suite>/` 三个关键文件：
  - `Release`：声明该分布下所有索引文件的**路径 + SHA256/SHA512 + 大小**；
  - `InRelease`：`Release` 本体 + 其 GPG 签名一起塞进一个文件；
  - `Release.gpg`：`Release` 的独立签名（老仓库用）。
- apt 拿 `InRelease`（或 `Release` + `Release.gpg`）→ 用公钥验签 → 比对 `Release` 里的哈希是否与下载下来的索引一致。**任何一环被篡改都会直接拒绝该源**。

公钥放置与 `apt-key`：

- 现在推荐用 `/etc/apt/trusted.gpg.d/`、`/etc/apt/keyrings/` 存 `.gpg`/`.keyring`，并在源里用 `Signed-By:` 指定；
- `apt-key` 已废弃：它把第三方 key 加成了**全局信任**，一旦某个公钥泄露或某个源被污染，攻击者可以用这把 key 给**任意** `.deb` 签名后冒充官方源分发恶意包；
- 用 `Signed-By:` 后信任是**源级别**的：该公钥只能验它对应源的 `InRelease`，不会越权。

## 九、缓存与清理

三个目录各自作用：

- `/var/cache/apt/archives/`：已下载、校验过的 `.deb`，供离线安装与重复使用；
- `/var/cache/apt/archives/partial/`：下载中、未校验完成的暂存区，失败或被中断的 `.deb` 留在这里；
- `/var/lib/apt/lists/`：`apt update` 下载的远程索引快照，是 `apt-cache` / `apt-get` 的“数据库”；`/var/lib/apt/lists/partial/` 是下载中的暂存。

常用清理命令：

```bash
sudo apt clean            # 清空 /var/cache/apt/archives/*.deb（保留 partial）
sudo apt autoclean        # 只删“当前源里已不再可下载”的 .deb（版本已失效）
sudo apt autoremove       # 删“被自动装来当依赖、现在没人依赖”的包
sudo apt autoremove --purge  # 同上，连 /etc 配置一起删
```

风险：

- `apt clean` 会破坏“离线安装”能力——下完又删，每次都要重新下；
- `autoremove` 的“坑”：它只看 `/var/lib/dpkg/status` 里标记为“自动安装”的包。如果你当年用 `sudo apt install xxx`（手动安装）装过某个库，它**不会**被自动删除；但如果你 `sudo apt install` 过 A，A 又自动拉了 B，后来你删了 A，`autoremove` 会把 B 也删掉——所以装关键依赖前先 `apt-mark hold <包>` 保护一下：

```bash
sudo apt-mark hold libc6
sudo apt-mark unhold libc6
```

## 十、常见坑与最佳实践

1. **apt vs apt-get**：`apt` 面向交互（进度条、彩色、`DO NOT RESTART SYSTEMS SERVICELESSLY` 之类提示），`apt-get` 面向脚本。**脚本里别用 `apt`**，它的输出格式随时可能变；`apt-get` 保证 `E:`/`W:` 前缀稳定。
2. **不要在脚本里解析 apt 输出**：要判断“装了没有”，用 `dpkg-query`：

   ```bash
   dpkg-query -W -f='${Status}\n' nginx   # 输出 "nginx: install ok installed"
   ```
3. **`apt upgrade` vs `apt full-upgrade`**：
   - `upgrade`：只升级已装包，**不删任何包**，即使要删依赖也宁可不升；
   - `full-upgrade`（= `dist-upgrade`）：允许**删除/替换**包来满足新依赖，跨大版本升级（如 22.04 → 24.04）或混分布时用；
4. **`apt-mark hold`**：保护关键包不被 `full-upgrade` 降级/替换：

   ```bash
   sudo apt-mark hold linux-image-generic
   ```
5. **Dockerfile 里 `apt-get update && apt-get install` 同层写**：分层缓存只看每层指令，若 `update` 一层、`install` 另一层，`update` 层会因任何 `install` 列表变化全部失效；合并在同一 `RUN` 里可最大化层命中，同时减少旧镜像层里残留过期索引带来的安全/正确性问题。
6. **源不可达 / Hash Sum mismatch / dpkg 锁**：
   - 源不可达：`apt-get update` 报 `Temporary failure resolving ...`，先 `resolvectl status` 或检查 DNS/代理；
   - `Hash Sum mismatch`：多为 DNS 劫持或镜像缓存不一致，可 `sudo apt clean && sudo apt update` 重试，或换镜像；
   - `dpkg frontend lock`（`E: Unable to acquire the dpkg frontend lock`）：另一个包管理进程还在跑，`sudo lsof /var/lib/dpkg/lock` 看是谁；**不要**直接删锁文件，先 `sudo kill <pid>`，再 `sudo dpkg --configure -a` 修复半装状态。

## 十一、参考链接

- Debian Policy Manual（依赖关系第 7 节）：<https://www.debian.org/doc/debian-policy/>
- Debian 官方手册索引：<https://www.debian.org/doc/>
- APT 官方文档：<https://www.freedesktop.org/software/apt/doc/>
- apt(8) man 页（Ubuntu noble）：<https://manpages.ubuntu.com/manpages/noble/man8/apt.8.html>
- apt_preferences(5) man 页：<https://manpages.ubuntu.com/manpages/noble/man5/apt_preferences.5.html>
- dpkg(8) man 页：<https://manpages.ubuntu.com/manpages/noble/man8/dpkg.8.html>

## 小结

`apt install` 不是一条命令，而是“**决策（apt）+ 执行（dpkg）**”两层：apt 负责“装什么、什么顺序、和谁冲突”，dpkg 负责“把文件落到盘上、跑脚本、更新状态”。理解了这条链路，绝大多数疑难杂症（`held broken packages`、`Hash Sum mismatch`、`dpkg frontend lock`）都能对症下药。
