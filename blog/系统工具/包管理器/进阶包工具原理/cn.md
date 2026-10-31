---
title: 完整介绍 apt 的原理
date: 2026-10-31
lang: zh-CN
tags: [Linux, 包管理器, apt, dpkg, Debian, 依赖解析]
summary: 从定位分层、软件源、update、依赖解析、安装链路、dpkg 状态、pinning、签名信任、缓存清理到常见坑，完整梳理 apt install 一条命令背后的原理。
source_issue: https://github.com/diaoyunxi/blog/issues/17
---

# 完整介绍 apt 的原理

在 Debian/Ubuntu 上执行 `sudo apt install nginx`，看似一步到位，背后其实是一条很长的链路：读取软件源配置 → 查本地包索引 → 做依赖求解 → 下载 .deb → 调 dpkg 解包 → 跑维护脚本 → 触发器 → 更新状态数据库。这篇文章把这条链路上的每一环拆开讲清楚。

## 一、定位与分层

apt（Advanced Package Tool）是 Debian 系的**包管理前端**：它负责"从哪些源取包、装哪些版本、谁依赖谁、按什么顺序装"这些**决策**；真正做"把 .deb 里的文件写到系统里"这件事的是底层的 **dpkg**。

一句话定位：

- **apt / apt-get / aptitude**：上层。读软件源配置、维护本地包索引缓存（`/var/lib/apt/lists/`）、做依赖解析与版本选择、生成"将要安装/删除哪些包"的方案，然后**调用 dpkg 执行**。
- **dpkg**：下层。只认本地 `.deb` 文件，负责解包（unpack）和配置（configure）两个阶段，维护 `/var/lib/dpkg/` 下的状态库。它**不知道**远程仓库、**不做**依赖求解、**不下载**任何东西。
- **apt-cache**：查询工具。`apt-cache policy nginx`、`apt-cache depends nginx` 等，读的就是本地索引。
- **aptitude**：另一个前端，和 apt-get 同级，但**依赖解析器不同**（见第四节），界面更适合交互式解决依赖冲突。
- **snap**：另一套完全独立的包管理栈（Core/Snapd 维护，二进制与 deb 格式不同），和 apt/dpkg 没有依赖关系，可以共存但文件布局各自为政。

所以严格说，**apt 本身不会解包文件**；`apt install` 最后一步永远是 fork 出 `dpkg` 来完成解包与维护脚本执行。

## 二、软件源配置

apt 从哪些位置取索引和包，由两类文件决定：

```text
/etc/apt/sources.list              # 传统入口
/etc/apt/sources.list.d/*.list      # 片段（one-line 格式）
/etc/apt/sources.list.d/*.sources   # 片段（deb822 格式，apt ≥ 1.1 支持）
```

### 1. one-line 格式（传统）

```bash
# /etc/apt/sources.list
deb [ arch=amd64 ] http://deb.debian.org/debian stable main restricted universe
deb-src http://deb.debian.org/debian stable main restricted universe
```

字段依次是：`类型`（`deb` / `deb-src`）、`可选的 [选项]`、`URI`（可以含 `$(ARCH)` 占位）、`suite`、`component`（多个）。

- **suite**：发行版代号或代号路径，如 `stable`、`testing`、`unstable`，或具体代号 `bookworm`、`noble`，也可以是精确路径 `stable/updates`（结尾带 `/` 时 component 必须省略）。
- **component**：组件名。Debian 有 `main` / `contrib` / `non-free`；Ubuntu 把组件命名为 `main` / `restricted` / `universe` / `multiverse`。含义大致是：
  - `main`：完全自由软件、Debian/Ubuntu 官方维护；
  - `restricted`：含闭源但必要的组件（Ubuntu 特有，如显卡驱动）；
  - `universe`：社区维护、自由软件；
  - `multiverse`：社区维护、自由/非自由混合（Ubuntu 特有）；
  - `contrib`、`non-free`（Debian 体系）：非官方维护/非自由软件。

### 2. deb822 格式（推荐的新写法）

deb822 把同一份信息写成"字段: 值"的多行 stanza，文件扩展名是 `.sources`，一个 stanza 一个源，多个 stanza 之间用空行分隔：

```bash
# /etc/apt/sources.list.d/ubuntu.sources
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: noble
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
```

它的优点：

- 多值字段（`Components:` 后面用空格分隔）可读性比一行挤一堆好；
- 可以用 `Enabled: no` 一行禁掉整个 stanza（one-line 只能整行注释）；
- apt 官方明确把 deb822 作为**逐步取代 one-line** 的目标格式；老 apt 遇到 `.sources` 会提示忽略，新 apt 则默认两者都读。

### 3. 加第三方源

原则：每个第三方源单独放一个文件，便于管理、便于 `signed-by=` 锁定公钥。示例（用 PPA 加一个源）：

```bash
# /etc/apt/sources.list.d/git-lfs.sources
Types: deb
URIs: https://ppa.launchpadcontent.net/git-core/git-lfs/ubuntu
Suites: noble
Components: main universe
Signed-By: /etc/apt/keyrings/git-lfs.ppa.keyring
```

公钥单独存放（`/etc/apt/keyrings/`），不要用已废弃的 `apt-key`（见第八节）。

## 三、apt update 到底做了什么

`apt update`（等价 `apt-get update`）**不安装任何包**，它做的是"同步索引"：

1. 遍历 `/etc/apt/sources.list` + `sources.list.d/` 里的**所有源**；
2. 对每个源先取 `dists/<suite>/InRelease`（或 `Release` + `Release.gpg`）；
3. 用本地公钥（`/etc/apt/trusted.gpg.d/` 或源里 `signed-by=` 指定的 keyring）对签名做 GPG 校验，再核对 `Release` 里的 SHA256/SHA512 与 `InRelease` 中是否一致；
4. `Release` 文件里会声明该源下有哪些索引（`Packages`、`Packages.gz`、`Packages.xz`、`Contents`、`Translation`…）以及每个文件的**路径与哈希**；
5. 按声明把 `Packages.gz` / `Packages.xz`（或 PDiff 增量）下载到 `/var/lib/apt/lists/partial/`，边下边用哈希校验；
6. 校验通过后才从 `partial/` 移到 `/var/lib/apt/lists/` 的正式位置，供后续 `apt-get` / `apt-cache` 查询。

不 update 会怎样：`/var/lib/apt/lists/` 里是**上一次 update 时的快照**。`apt install` 看到的"最新版"其实可能落后几周，`apt upgrade` 也只会升到旧快照里有版本；极端情况（源换了、包改名了）直接报"找不到包"。所以新机器或加源之后，**先 update 再 install** 是硬性顺序。

## 四、依赖解析原理（核心）

`.deb` 控制段里有一组元数据描述包的依赖关系，强弱不等：

| 字段 | 含义 | 强度 |
| --- | --- | --- |
| `Depends` | 运行时强依赖，缺了无法正常工作 | 硬 |
| `Pre-Depends` | 必须**先于本包配置完成**才生效的依赖（例如依赖 `dpkg` 新特性） | 硬 + 时序 |
| `Recommends` | 推荐依赖，缺了功能降级但能跑 | 软 |
| `Suggests` | 建议关联，更弱 | 软 |
| `Conflicts` | 装本包时对方必须不在 | 硬约束 |
| `Breaks` | 本包版本比对方新，对方旧版不能用 | 硬约束 |
| `Replaces` | 本包接管对方的某些文件 | 配合 Conflicts |
| `Provides` | 虚拟包，本包"提供"某个别的包名 | 让依赖可替代 |

版本约束语法如 `Depends: libc6 (>= 2.35)`；`Provides: virtual-font-libfoo` 可以让任何包写 `Depends: virtual-font-libfoo` 来选它。

### 求解过程

`apt` 拿到"目标包 + 当前 `/var/lib/dpkg/status` 的已安装状态"后，要解出一个**安装/删除/升级集合**，使得所有 `Depends`/`Pre-Depends` 被满足、所有 `Conflicts`/`Breaks` 不被违反。这个集合：

- 是**与/或逻辑关系**：`Depends: A | B` 表示装 A 或 B 之一即可；
- 允许**虚拟包替代**：`Depends: python3:any` 可以被 `python3.12` 通过 `Provides` 满足；
- 是一个**约束满足问题**，在理论上是 NP 完全的（因为可以还原 SAT 到它）。

apt 用的是**带评分的回溯搜索**（backtracking solver）：

1. 从"把目标包升到最高可用版本"作为初始假设；
2. 递归展开每个 `Depends`，遇到 `Conflicts` 就标记冲突候选；
3. 对每个包按评分（已安装版本最优先、再按 pinning 优先级、最后按版本号）挑选；
4. 走死胡同时回退、换次高版本、或接受删除某个包；
5. 最终输出一个**最小改动集合**，打印"将要安装 X 个包、释放 Y MB、下载 Z MB"。

`aptitude` 用的是**不同的解析器**：它倾向于"少装少删"，允许交互式选择；`apt-get` 的解析器更激进，必要时会删包（见 `full-upgrade`）。

解析失败的典型原因：`E: Unable to correct problems: you have held broken packages`。多半是：之前 `dpkg` 被 Ctrl-C 中断留下 `half-configured` 状态、有包被 `apt-mark hold` 住、或 `Depends` 与 `Conflicts` 形成死锁。修复入口是 `sudo dpkg --configure -a` 或 `sudo apt-get -f install`。

## 五、apt install 的完整执行链路

`sudo apt install nginx` 内部：

1. **决策阶段**：读本地索引做依赖求解，输出"将要安装哪些 .deb 及其版本"；
2. **下载阶段**：把每个 .deb 下到 `/var/cache/apt/archives/partial/`，支持多线程、断点续传、SHA256 校验；通过后才移到 `/var/cache/apt/archives/`；
3. **调用 dpkg**：按拓扑序逐个 `dpkg --unpack` 再 `dpkg --configure`，两阶段分离是关键——先只解包、不跑配置脚本，最后统一配置；
4. **维护脚本**（每个包可自带 4 个 shell 脚本，按顺序执行）：
   - `preinst`：解包前跑，用于占位、停服务；
   - `postinst`：解包后、配置阶段跑，做初始化、起服务、写配置；
   - `prerm`：卸载前；
   - `postrm`：卸载后；
5. **触发器 `dpkg-trigger`**：某些包（如 `fonts-dejavu`、`libgtk`）声明"我变了要通知 X"，系统里所有被通知的包延迟到**本次操作全部结束后**统一跑一遍触发器，避免每个包装一次都重复重建缓存；
6. **配置文件冲突（conffile）**：包里的 `/etc/nginx/nginx.conf` 之类被标为 conffile，dpkg 发现本地版本和包里的不一样就停手，交互环境下弹"保留本地版 / 用新版 / 显示差异"。脚本里没 TTY 就默认按 `/etc/dpkg/dpkg.cfg.d/` 里 `force-confdef` / `force-confold` 决定；
7. **事务性**：apt **不是原子事务**。任何一步失败都不会自动回滚到操作前的系统状态。能做的只是"已解包未配置"的包保持半安装，`sudo dpkg --configure -a` 续上。

## 六、dpkg 层与状态文件

- `/var/lib/dpkg/status`：所有已装包的**单一大文件**，含包名、版本、状态、`Depends` 等。`apt-cache` 也读它。
- `/var/lib/dpkg/info/`：每个包的 `*.postinst`、`*.postrm`、`*.conffiles`、`*.md5sums`、`*.list`（文件清单）等。
- 包状态机（在 status 里每个包记录）：
  - `install ok installed`（正常）
  - `install ok unpacked`（已解包未配置）
  - `install reinstreq half-configured`（配置中断）
  - `install ok half-installed`（更烂）
- 常用查询：
  ```bash
  dpkg -l nginx                  # 查安装状态与版本
  dpkg -S /usr/sbin/nginx        # 反查：哪个包装了某文件
  dpkg -L nginx                  # 正查：某包装了哪些文件
  ```
- dpkg **不认依赖关系、不下载、不解依赖**，只认单个 .deb。它没有"远程"概念，所有索引/下载/求解都是 apt 的事。

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
- 写 pin：
  ```bash
  # /etc/apt/preferences.d/git-lfs
  Package: git-lfs
  Pin: version 3.*
  Pin-Priority: 999
  ```
- 混 stable/testing 或加 PPA 时，**必须**给目标分布钉高 pin、给实验分布钉低 pin（比如 `unstable` 设 50），否则 `apt full-upgrade` 可能把整个系统推到一半是 stable 一半是 testing 的烂状态。

## 八、签名与信任链

- 仓库根下 `dists/<suite>/` 三个关键文件：
  - `Release`：声明该分布下所有索引文件的**路径 + SHA256/SHA512 + 大小**；
  - `InRelease`：`Release` 本体 + 其 GPG 签名一起塞进一个文件；
  - `Release.gpg`：`Release` 的独立签名（老仓库用）。
- apt 拿 `InRelease`（或 `Release`+`Release.gpg`）→ 用公钥验签 → 比对 `Release` 里的哈希是否与下载下来的索引一致。**任何一环被篡改都会直接拒绝该源**。
- 公钥来源：
  - 系统发行版自带的公钥在 `/usr/share/keyrings/`；
  - 第三方公钥**必须**放 `/etc/apt/keyrings/`（或 `/etc/apt/trusted.gpg.d/`），并在源里用 `signed-by=` 显式指向：
    ```bash
    # /etc/apt/sources.list.d/example.sources
    Types: deb
    URIs: https://example.com/deb
    Suites: stable
    Components: main
    Signed-By: /etc/apt/keyrings/example.gpg
    ```
- **`apt-key` 已被废弃**（Ubuntu 22.04 起默认不再读它）：原因是它把第三方公钥加进系统级信任库（`/etc/apt/trusted.gpg` 或 `/etc/apt/trusted.gpg.d/`），等于告诉 apt"我信任这个 key 签的**任何包**"——攻击者只要拿到同一把 key（或伪造）就能往任意源塞包。`signed-by=` + `/etc/apt/keyrings/` 的写法把信任**限定到某个源**，显著缩小攻击面。

## 九、缓存与清理

| 路径 | 作用 |
| --- | --- |
| `/var/cache/apt/archives/` | 已下载的 .deb，装完不删 |
| `/var/cache/apt/archives/partial/` | 正在下的临时区 |
| `/var/lib/apt/lists/` | 各源的 `Packages.gz` 等索引 |
| `/var/lib/apt/lists/partial/` | 索引同步中的临时区 |

三条清理命令：

```bash
sudo apt clean           # 删 /var/cache/apt/archives/*.deb，保留 lock 与 partial
sudo apt autoclean       # 只删那些"本地已装版本 == 缓存版本、且仓库已不再提供"的包
sudo apt autoremove      # 删"当初因为依赖被拉进来、现在没人依赖"的包
```

`apt clean` 最狠，装完大批包后跑它安全；`autoclean` 温和；`autoremove` 要小心——它只看依赖图，**不看你手动 `apt install` 过什么**。如果你 `apt install foo` 装了一个你**自己也在用**的库，`autoremove` 不会误删它（apt 会把它标记为"手动安装"）；但 `--purge` 加在 `autoremove` 后面会把包和它的 `/etc` 配置一起带走，不可逆。

## 十、常见坑与最佳实践

1. **脚本里别用 `apt`，用 `apt-get`**。`apt` 面向交互，输出带颜色、进度条、"The following packages will be installed" 多行说明；`apt-get` 面向脚本，输出稳定、无装饰、可 `--quiet`。脚本里解析 `apt` 输出（如 grep "E:"）会随版本改样式而烂掉。
2. **不要解析 apt 输出**来判成败，判成败只看退出码（`|| true` 是反模式，会吞错）。要查"装了哪些"用 `apt-cache` / `dpkg -l`。
3. **`apt upgrade` vs `apt full-upgrade`**：前者**只升不装不删**（遇到需要新依赖/删包的包就跳过），后者（`apt-get dist-upgrade`）允许装新依赖、删冲突包。大版本跨 release 升级**必须**用 `full-upgrade`。
4. **`apt-mark hold` / `unhold`**：把某个包钉死不参与 upgrade/autoremove。
   ```bash
   sudo apt-mark hold openssh-server
   sudo apt-mark showhold
   ```
5. **Dockerfile 里 `apt-get update && apt-get install` 同层写**：
   ```dockerfile
   RUN apt-get update && apt-get install -y nginx && rm -rf /var/lib/apt/lists/*
   ```
   原因：Docker 按层缓存。`update` 和 `install` 写在同一 `RUN` 里，层内一次性执行、不产生中间层，`update` 产生的 `/var/lib/apt/lists/` 还能顺手 `rm -rf` 掉，镜像更小。
6. **源不可达 / `Hash Sum mismatch`**：多半是**镜像本身有问题**（同步到一半、被中间盒子改了内容）。处理：换镜像、或 `sudo apt update` 再 `install`；若报 `Hash Sum mismatch`，把 `/var/cache/apt/archives/partial/` 清一遍再试。
7. **`dpkg: error: dpkg frontend lock is held`**：后台有另一个 apt/dpkg 在跑（未关的 apt 终端、`unattended-upgrades`、`snapd` 装系统包时）。先 `sudo systemctl stop unattended-upgrades`、`sudo dpkg --configure -a`，再 `sudo apt-get -f install` 修依赖。

## 小结

`apt install` 一条命令的真实链路：**读源 → 用本地索引做带评分回溯的依赖求解 → 多线程下载 .deb 到 archives → 调 dpkg 两阶段解包/配置 → 跑 preinst/postinst/prerm/postrm → 跑 dpkg-trigger → 更新 /var/lib/dpkg/status**。理解了"上层 apt 做决策、下层 dpkg 做执行、索引驱动、签名守护、pinning 控版本"这几条主线，看到 `E: held broken packages`、`Hash Sum mismatch`、conffile 弹窗时就知道问题卡在哪一环，而不是只会盲目 `apt-get -f install`。

## 参考

- apt 官方手册（Debian man pages）：
  - https://manpages.debian.org/stretch/apt/sources.list.5.en.html
  - https://manpages.debian.org/stretch/apt/apt.conf.5.en.html
  - https://manpages.debian.org/stretch/apt/apt_preferences.5.en.html
- Debian APT Wiki 与 CLI 说明：https://wiki.debian.org/AptCLI
- RFC822/deb822 格式说明：https://man7.org/linux/man-pages/man5/deb822.5.html
