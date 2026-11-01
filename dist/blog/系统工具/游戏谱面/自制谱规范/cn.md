---
title: Phigros 自制谱（Fanmade）JSON 文件规范与写法
date: 2026-10-31
lang: zh-CN
tags: [Phigros, 音乐游戏, 谱面制作, JSON, Sonolus, PGR编辑器]
summary: 探究 Phigros 自制谱面的 JSON 文件结构、必填字段、音符与判定线写法，以及打包与调试要点
source_issue: https://github.com/diaoyunxi/blog/issues/19
---

# Phigros 自制谱（Fanmade）JSON 文件规范与写法

## 一、背景：什么是 Phigros 自制谱

Phigros 是 Pigeon Games（鸽游）开发的一款"无判定线"（laneless）音乐游戏，玩家需要在屏幕上动态浮动的判定线上按节奏点击、长按、滑动以击中音符。游戏本身不开放谱面编辑器，但社区发展出一整套第三方制作工具链，允许玩家制作"自制谱"（fanmade song / fanmade chart），并通过特定格式打包后在官方 App 或第三方引擎（如 Sonolus）中加载运行。

Phigros 谱面的核心数据通常以 **JSON 文件** 形式存放，每个难度一份独立 JSON（如 `EASY.json`、`HARD.json`、`INSANE.json`），描述该难度下所有音符、判定线移动、BPM 变化、判定窗口、UI 特效等。这篇文章聚焦在 **JSON 文件该怎么写**，覆盖文件结构、关键字段、音符类型、判定线脚本、打包流程，以及常见坑。

> 说明：Phigros 的谱面格式由第三方编辑器（如 **PGR Editor / Phigros Chart Editor / PGR Editor Web**）导出，官方并未发布严格的 schema 文档；不同引擎（Phigros App、Sonolus）在读取时存在细微差异。本文以社区编辑器导出的常见形态为基准，并标注了与官方引擎的兼容性注意点。

## 二、整体定位：谱面在整个包里处于哪一层

一个可加载的 Phigros 自制谱包（常见扩展名 `.pkr` 或 ZIP）通常包含以下文件：

```
MySong/
  song.ogg / song.mp3 / song.flac   # 音频文件
  BGM.txt / song.mp3                # 音频与元数据
  song.json                        # 歌曲级元数据（封面、BPM、难度列表等）
  EASY.json / HARD.json / INSANE.json  # 各难度谱面数据（核心 JSON）
  background.jpg / video.mp4        # 可选：背景
  info.json / pgrinfo.json         # 可选：包级说明
  icon.png                         # 可选：封面
```

- **歌曲级 JSON（`song.json` / `info.json`）**：记录封面、BPM 表、判定偏移、各难度的引用文件名等，相当于"目录"。
- **难度级 JSON（`EASY.json` 等）**：真正描述"谱面本身"的文件，包含所有音符、判定线轨迹、特效。这是本文的重点。
- **音频**：通常是 `.ogg` / `.mp3`，部分引擎支持 `.flac`；文件名需与 JSON 里 `bgm` 字段一致。
- **封面/背景**：`.jpg` / `.png` / `.mp4`，可选，但影响加载效果。

不同工具链对"目录里放哪些文件"的约定略有差异，建议以你使用的编辑器导出的样板为准。

## 三、难度级 JSON：字段逐项拆解

以社区编辑器导出的难度 JSON 为例，骨架通常长这样（**键名因编辑器版本而异，以下为常见形态**）：

```json
{
  "bpm": [
    { "time": 0.0, "value": 128 }
  ],
  "offset": 1.5,
  "notes": [
    {
      "start": 1.5,
      "end": 2.0,
      "type": 1,
      "judge": 1,
      "pos": [0.5, 0.5],
      "rot": 0.0,
      "size": 1.0
    }
  ],
  "judgementLine": [
    { "time": 0.0, "pos": [0.5, 0.5], "rot": 0.0, "size": 1.0 }
  ],
  "bgs": [
    { "time": 0.0, "url": "background.jpg", "scale": 1.0, "rot": 0.0, "trans": 0.0 }
  ],
  "uiType": 1,
  "uiSpeed": 1.0,
  "uiScale": 1.0,
  "uiTrans": 0.0,
  "uiRot": 0.0
}
```

下面逐项解释。

### 3.1 `bpm` —— 节拍速度表

- 是一个数组，**按时间顺序**描述 BPM 变化。
- 每项 `{ "time": 秒数, "value": BPM 数值 }`，表示从该时间起 BPM 变为该值，直到下一条 `bpm` 项或文件末尾。
- 第一项的 `time` 通常为 0，`value` 为该曲基础 BPM。
- **关键**：Phigros 是"秒"为单位的时间轴，BPM 变化时所有后续音符的"秒"仍按绝对时间填写，**不要**写成相对小节的数值。

### 3.2 `offset` —— 判定线进入时间 / 整体偏移

- 数值单位是秒。
- 通常表示判定线进入画面、或音频与判定线同步所需的偏移量。
- 制作时需结合音频开头静默段、视频首帧延迟调校。

### 3.3 `notes` —— 音符数组（最核心）

Phigros 中音符按"类型"（type）区分四种基础玩法，常见编码为：

| type | 名称 | 含义 |
|------|------|------|
| 1 | Tap | 在判定线到达该点时单击 |
| 2 | Hold | 长按（`start` 按下、`end` 松开） |
| 3 | Drag | 滑动（沿 `pos` 连线拖到 `end` 位置） |
| 4 | Flick | 在 Hold 末端甩出（方向由 `rot` 或额外字段描述） |

每个 note 对象的常见字段：

- `start` / `end`：起止秒数（Tap 只关心 `start`；Hold 需 `start`+`end`；Flick 依附于 Hold 末端）。
- `type`：上述 1~4 之一。
- `judge`：判定窗口等级（1~4，对应"Good / Okay / Bad / Miss"窗口）；通常 1 最严，数值越大越宽。社区默认 1。
- `pos` / `endPos`：`[x, y]` 归一化坐标（0~1，对应屏幕相对位置），Tap/Hold 起点；Drag 用 `pos` 起、`endPos` 终。
- `rot`：旋转角度（度），用于 Flick 方向、Hold 末端方向、特效朝向。
- `size`：相对判定线宽度的大小系数（1.0 为标准）。
- 部分编辑器还带 `effect` / `bark` 等扩展字段（音符特效、视觉提示）。

**判定窗口（judge）**：Phigros 有 4 档判定窗口，社区通常用 `1`（最严）、`2`、`3`、`4`（最宽）来标识，**数值越小越难**。默认 `1`。

### 3.4 `judgementLine` —— 判定线轨迹

Phigros 的"laneless"特性体现在判定线（`judgementLine`）会随时间移动、旋转、缩放，从而让同一首歌在不同位置被击打。

- 每个元素 `{ "time", "pos", "rot", "size" }` 表示该秒判定线的状态。
- 在两个相邻元素之间，引擎通常做 **插值**（线性/缓动）来平滑移动。
- 元素不一定要每秒一个，只在你需要"变"的时刻写即可；引擎会按 `time` 排序后插值。
- 想让判定线在某段时间"冻结"在某位置，就在那个位置之后插入一个相同状态的新 keyframe。

### 3.5 `bgs` —— 背景切换

- 数组，每项 `{ "time", "url", "scale", "rot", "trans" }`。
- `url` 指向包内相对文件；`trans` 通常指透明度（0=透明，1=不透明，或反之，编辑器版本不同约定相反，看样板）。
- 在 `time` 时切换到该背景，并可做缩放/旋转/透明度过渡。

### 3.6 UI 相关（`uiType` / `uiSpeed` / `uiScale` / `uiTrans` / `uiRot`）

- 控制 UI 层（如特效层、辅助线、判定线本身的样式）的可见性与形态。
- 社区编辑器一般默认 `uiType=1`，`uiSpeed=1`，其它字段为 0/1 中性值；高级玩家可做"隐藏 UI"、"慢速回放"等效果。

## 四、歌曲级 JSON（`song.json` / `info.json`）常见字段

```json
{
  "title": "My Song",
  "artist": "Some Artist",
  "album": "Some Album",
  "origin": "some-source",
  "bpm": 128,
  "difficulty": 10,
  "offset": 0,
  "bgm": "song.ogg",
  "cover": "icon.png",
  "chapters": [
    { "name": "EASY",  "type": "easy",    "grade": 4,  "chart": "EASY.json"  },
    { "name": "HARD",  "type": "hard",    "grade": 8,  "chart": "HARD.json"  },
    { "name": "INSANE","type": "insane",  "grade": 12, "chart": "INSANE.json"}
  ]
}
```

- `chapters` 是难度数组，每项的 `chart` 指向对应的难度 JSON 文件名；`grade` 是难度星级（Phigros 谱面通常 1~15，IN 档社区常用 10~14）。
- `bgm` 必须是包内实际存在的音频文件相对名。
- `offset` 是整首歌曲的全局音频偏移，单位秒，可以为 0。

## 五、一个最小可运行的难度 JSON 示例

下面这个 `HARD.json` 演示一段基础节奏（128 BPM，4/4 拍，4 个小节，约 7.5 秒），含 Tap / Hold / Drag 各一例：

```json
{
  "bpm": [
    { "time": 0.0, "value": 128 }
  ],
  "offset": 1.5,

  "notes": [
    { "start": 1.5, "type": 1, "judge": 1, "pos": [0.5, 0.5] },
    { "start": 1.75, "type": 1, "judge": 1, "pos": [0.6, 0.5] },
    { "start": 2.0, "type": 1, "judge": 1, "pos": [0.4, 0.5] },

    { "start": 2.5, "end": 3.0, "type": 2, "judge": 1, "pos": [0.5, 0.3] },

    { "start": 3.5, "end": 4.0, "type": 3, "judge": 1, "pos": [0.2, 0.5], "endPos": [0.8, 0.5] }
  ],

  "judgementLine": [
    { "time": 0.0, "pos": [0.5, 0.5], "rot": 0.0, "size": 1.0 },
    { "time": 3.0, "pos": [0.5, 0.3], "rot": 0.0, "size": 1.0 },
    { "time": 4.0, "pos": [0.5, 0.5], "rot": 0.0, "size": 1.0 }
  ],

  "bgs": [
    { "time": 0.0, "url": "background.jpg", "scale": 1.0, "rot": 0.0, "trans": 1.0 }
  ]
}
```

要点：
- `offset` 与首条 note 的 `start` 对齐（都 1.5 秒）才能让判定线进入时正好接上第一个音符。
- 判定线 keyframe 与音符位置匹配（3.0 秒时判定线在 `[0.5, 0.3]`，正好是 Hold 起点）。
- 所有 `pos` 用归一化坐标（0~1），写错量级会导致音符跑到画面外。

## 六、写谱面的实操建议

1. **先做 BPM 表，再做音符**。Phigros 是"秒"时间轴，先确定全曲 BPM 变化点，再据此把小节线换算成秒，最后才逐个落音符。
2. **`pos` 必须归一化**。0~1 对应屏幕宽/高；1.0 是右下角。写 0.5/0.5 居中。
3. **判定线 keyframe 要稀疏但关键位置必须有**。不要每秒都写 keyframe（会爆量），只在"线要动"的时刻写；引擎会做插值。
4. **Hold 的 `start` 和 `end` 必须成对**；单独写 `start` 不写 `end` 会被判 Miss。
5. **Flick 依附 Hold**：Flick 是 Hold 的"末端甩出"，需要先在 `end` 位置放 Hold，再用 Flick 在该 `end` 位置继续描述方向（`rot`）。
6. **`judge` 默认 1**（最严）。如果整张谱面都设 4（最宽），在高端玩家那里会被认为是"放水"。
7. **文件名与歌曲级 JSON 的 `chart` 字段必须一一对应**，错一个字母就加载失败。
8. **编码用 UTF-8**（不带 BOM），中文曲名/谱名不要出现非法字符。

## 七、常见坑与排查

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| 谱面打不开 / 提示"invalid chart" | JSON 语法错（缺逗号、引号不闭合、BOM 头） | 用 `jq . yourfile.json` 校验；编辑器另存为 UTF-8 无 BOM |
| 音符全部飘出屏幕 | `pos` 写成 0~100 或 0~10 量级 | 改成 0~1 归一化坐标 |
| 判定线不动 / 跳变 | `judgementLine` 未排序、缺首帧、时间戳倒序 | 按 `time` 升序排好；首帧 `time=0` 必填 |
| Hold 按了但没分 | 只写了 `start`，漏写 `end` | 补上 `end`，且 `end > start` |
| Flick 方向反 | `rot` 符号记错 | 用编辑器可视化对照角度方向 |
| 判定窗口太宽 / 太严 | `judge` 字段写错档位 | 社区惯例：默认 1；最宽 4 |
| 加载后音频不同步 | 全局 `offset` 或首 note 的 `start` 没对齐 | 微调全局 `offset`，确保首 note `start` ≥ 首判定线进入时刻 |
| 某难度不显示 | 歌曲级 JSON 的 `chapters` 漏写该难度或 `chart` 名写错 | 核对章节名与文件实际名 |
| Sonolus 报"unsupported chart" | 用了 Phigros App 专有的扩展字段（如某些特效字段） | 删掉 Sonolus 不识别的字段，或换回 Phigros App 加载 |

## 八、工具链与参考

- **编辑器**：PGR Editor（Web 端）、Phigros Chart Editor（桌面/移动端）、`pgr-tools`（命令行工具集，社区维护）。
- **引擎 / 运行端**：Phigros 官方 App（Android/iOS，支持 fanmade 包导入）；Sonolus（开源，跨平台，可加载 Phigros 风格谱面，详见其 GitHub）。
- **格式参考**：Phigros 官方 Wiki 的 "Fanmade songs" 章节、Sonolus 仓库 `docs/` 下的 chart 说明。
- **社区**：Discord "Phigros Fanmade" 频道、相关 QQ 群；新版编辑器与引擎字段经常微调，**以你当前使用的工具导出的样板 JSON 为准**。

> 截至 2026-10-31，未找到 Pigeon Games 官方发布的"Phigros 谱面 JSON Schema"文档；本文的字段集合基于社区编辑器与 Sonolus 开源项目逆向整理，**字段名与编码在不同工具版本间可能有差异**，遇到加载失败时优先对照你手上那份能成功加载的样板 JSON 逐字段比对。

## 九、小结

- Phigros 自制谱 = **音频 + 歌曲级 JSON + 若干难度级 JSON（核心）**。
- 难度 JSON 五大块：`bpm` 表、`offset`、`notes`（四种玩法 + 判定窗口 + 归一化坐标 + 旋转）、`judgementLine`（关键帧插值）、`bgs` / UI 字段。
- 写谱心法：先 BPM、再坐标、后判定线；`pos` 归一化、Hold 成对、keyframe 排序、编码 UTF-8 无 BOM。
- 工具链优先看样板，字段以编辑器导出的为准；加载失败时用 `jq` 校验 JSON 结构 + 对照样板逐字段查。

## 参考

- Phigros 官方 Wiki：https://phigros.fandom.com/wiki/Phigros_Wiki
- Phigros 歌曲列表（含难度说明）：https://phigros.fandom.com/wiki/Songs
- Phigros 官网 / 下载页（Play Store）：https://play.google.com/store/apps/details?id=com.PigeonGames.Phigros
- Sonolus（Phigros 风格引擎）：https://github.com/Sinolus/sonolus
- Phigros Wiki（日文，含 fanmade 章节）：https://wikiwiki.jp/phigros/
