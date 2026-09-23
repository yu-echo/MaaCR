<div align="center">

<img src="./logo.png" alt="MaaCR" width="200" />

# MaaCR

**皇室战争国服 · 基于 MaaFramework 的自动化助手**

自动开游戏 · 自动进局 · 按策略下牌 · 结算循环 · 日常任务 · 三级自愈

[![Release](https://img.shields.io/github/v/release/yu-echo/MaaCR?style=flat-square&label=%E4%B8%8B%E8%BD%BD)](https://github.com/yu-echo/MaaCR/releases/latest)
[![License](https://img.shields.io/github/license/yu-echo/MaaCR?style=flat-square)](LICENSE)
[![MaaFramework](https://img.shields.io/badge/MaaFramework-%E9%A9%B1%E5%8A%A8-blue?style=flat-square)](https://github.com/MaaXYZ/MaaFramework)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20MuMu%20%E6%A8%A1%E6%8B%9F%E5%99%A8-lightgrey?style=flat-square)]()
[![Stars](https://img.shields.io/github/stars/yu-echo/MaaCR?style=flat-square&logo=github)](https://github.com/yu-echo/MaaCR/stargazers)

</div>

---

## 这是什么

把一套自写的 OpenCV + adb 皇室战争挂机脚本，**重构到 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 之下**。

换掉的是「胶水层」，不是「识别能力」：设备层（446 行的 adb 封装）与自写 GUI 整块删除，
交给 MaaFramework 的 `AdbController` 和 [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)；
而模板图、量化读法、出牌策略原样保留。

**收益**：白拿 MFAAvalonia 的图形界面、多实例、定时执行、热键；流程变成声明式 JSON，
可以用 MaaDebugger / VSCode 插件可视化调试；识别结果与失败截图自动落盘。

> 这是个人自用工具，只针对**国服（腾讯代理版）**和 **MuMu 模拟器 720×1280 竖屏**调过。
> 别的分辨率、别的模拟器、别的服，没试过，也不保证。

## ⚠️ 先说清楚定位

> **它的目标是「快速刷完尽可能多的对局」**（刷宝箱 / 刷对局时长 / 刷卡牌大师进度），
> **不是上分**。所以「输」是设计的一部分，不是 bug。
>
> 当前策略是「强攻一路 + 另一边直接摆烂」——一路猛推保证至少一冠，另一边完全不守，
> 对面顺着空档很快推到三冠，而三冠会**立刻结束对局**（不用拖满 3 分钟），
> 单位时间能刷的局数接近翻倍。
>
> ⇒ **评估它好不好用，看的是「每局对战耗时」**（日志里会打），不是胜率。
>
> 反过来想让它赢：现在这套打法赢不了。必须加「场上敌方单位识别」
> （红血条 = 敌方、蓝血条 = 我方）做成「有敌人先防守、防住再反推」——
> 那是比现在大一个量级的活，见「路线图」。

## 功能介绍

### 对战

- 自动把游戏调到前台并**等到它真的就位**再开始（冷启动十几秒不会误判）
- 自动进局、按优先级与圣水条件出牌、结算后自动确认并进下一局
- 破塔后落点自动切到敌方半场深位，往国王塔压（拿三冠的关键两步）
- 局数与时间双安全阀，到数就停

### 日常

- **商店免费项**：只领价格写着「免费」的卡 —— 判据是那两个**字**（白字掩码匹配），不是颜色，
  免费项不一定是绿卡。看到「已收集！」就停（它是「今天已领完」的信号，列表实测有 37~55 屏）
- **部落捐赠**：只捐**亮绿色**的可捐请求，灰的（自己发起的）跳过；点一下就直接捐出，
  没有二次确认弹窗，底部的「确定」只在全部捐完之后点一次（那是退出聊天的按钮）
- 两个任务跑完都自动回主界面，可以串起来一把跑完（界面里有「**日常一条龙**」预设）

### 自愈（认不出来的界面）

- ① 底部导航条还在 → 点「对战」回主界面（子页面卡住的正解，代价最低）
- ② 没有导航条 → 当全屏弹层处理（开宝箱那种多阶段动画），严格限次
- ③ 认不出来 **且画面也定格了**够久 → 判定真卡住，重启游戏（最贵但最确定）
- ⚠️ **绝不按返回键兜底** —— 实测返回键会弹出游戏自己的「要退出吗」对话框，越「恢复」越乱

### 识别（不依赖 OCR）

- 圣水：洋红条**最右侧被点亮的列** ÷ 满条宽 × 10（白字会在条上打空洞，空洞不影响最右边界）
- 敌塔血量：粉色血条**宽度就是血量**
- 结算皇冠：金冠 = 已拿、蓝枕 = 没拿，按颜色数色块
- 手牌：10 张卡面模板逐槽匹配（含精英形态两套素材，避免漏牌）
- 自动捡「认不出来的卡面」存盘，供人工补进模板

## 使用说明

### 1. 下载

到 [Releases](https://github.com/yu-echo/MaaCR/releases/latest) 下载 **`MaaCR-win-x86_64-vX.Y.Z.zip`**。

只有 Windows 包 —— 底层识别与「启动前准备」都绑死了 MuMu 模拟器，出别的平台包没意义。

> 想试还没发版的最新代码：Actions 里任何一次 `install` 跑完，都能在当次运行的
> Artifacts 里下到预览包（版本号带 `-ci.`）。

### 2. 解压，然后双击 `MFAAvalonia.exe`

**解压到纯英文路径**下再跑（中文路径容易出各种怪问题）。里面已经自带了一份 Python
和全部依赖，不需要你装 Python，也不用 `pip install` 任何东西。

如果双击报错、提示缺少 .NET：MFAAvalonia 不是自包含发布，需要 **.NET 10 桌面运行时**。
双击包里的 **`install-deps-win.bat`** 装一下（它走 winget，没有 winget 就自动打开官方下载页），
**装完重启电脑**再试。

### 3. 包里的目录长这样

```
MaaCR-win-x86_64-vX.Y.Z/
├── MFAAvalonia.exe         ← 双击这个
├── install-deps-win.bat    ← 缺 .NET 时才需要
├── interface.json          ← 任务与选项的定义（MFAAvalonia 读它）
├── resource/               ← 模板图与流水线（仓库里的 assets/resource）
├── agent/                  ← 识别与动作的 Python 代码
├── python/                 ← 自带的 Python，已装好 MaaFw / opencv / numpy
├── runtimes/ libs/ plugins/← MaaFramework 的原生库
├── tools/preflight.py      ← 启动前检查设备、拉起模拟器
└── docs/ README.md LICENSE
```

> 别在这棵树下找 `assets/`：发布包里 `interface.json` 和 `resource/`
> 是**直接跟 `MFAAvalonia.exe` 同层**的，这是 MFAAvalonia 的加载约定。

## 使用前准备

1. **Windows + MuMu 模拟器**（实测 MuMu Player 12），模拟器里装好**国服皇室战争**
   （`com.tencent.tmgp.supercell.clashroyale`）。
2. **分辨率保持 720×1280 竖屏**。本项目全部模板与坐标都是按它量的，
   `interface.json` 里 `display_short_side: 720` 也是为此 —— 换分辨率要重采全部模板并重标坐标。
3. **手动登录一次**。微信 / QQ 授权本工具不碰；识别到登录页会直接停下等你。
4. 模拟器设置里打开 **USB 调试**。

> ### 🔒 关于「只驱动模拟器，不碰真机」
> 旧版实测过一个坑：开发机**插着的真机上装了同一个国服包**，所以按包名挑设备根本区分不开，
> 一旦模拟器端口全断而程序回退到「第一台在线设备」，就会去操作真机。
> 所以 `tools/preflight.py` 会在启动前检查目标设备是不是 `127.0.0.1`，不是就**拒绝启动**。
> 确实想在真机上跑：设环境变量 `MAACR_ALLOW_REMOTE=1` 显式放行（后果自负）。

## 跑起来

1. 启动 MuMu（不用自己开游戏，工具会把它调到前台）；
2. 开 `MFAAvalonia.exe`，选设备时**选 MuMu 的 `127.0.0.1:<端口>`**；
3. 第一跑就勾「自动对战」，把「最多打几局」设成 **1**；
4. 点开始，看日志与 `debug/` 下的识别可视化图。

日常任务在同一页的「日常任务」分组里，也可以直接用「**日常一条龙**」预设一把跑完（商店 + 部落）。

### 只想验证它认不认得准

第一次跑就把「最多打几局」设成 **1**，**并且盯着它跑**。

> ⚠️ 本版本去掉了「演练模式（只识别不点击）」开关，所以**它会真的点击你的游戏**。
> 认错了随时手动停。想先只验证「认不认得准」而不点击，界面上暂时没有入口
> （底层 `dry` 参数还留在 Agent 里，需要时可以再放出来）。

> 验证完记得把开关关掉再跑真的。关掉后如果它还是不动，那不是这个开关的问题 ——
> 见「常见问题」那一行。

### 命令行自检（不需要模拟器）

发布包里也能跑，用的是自带的 Python：

```bash
python/python.exe tools/validate.py             # 资源引用、节点名、Custom 注册、interface 配置
python/python.exe tools/preflight.py --check    # 检查设备与模拟器状态，不做任何改动
```

`tools/validate.py` 抓的是几类**不会报错、只会静默失效**的问题：
模板图路径写错、`next` 指向不存在的节点、pipeline 用了没注册的 Custom 名、
`interface.json` 的 `entry` 拼错、选项覆盖了不存在的节点、`pretask` 路径不符合
MFAAvalonia 的解析约定。
建议每次改完 pipeline 都跑一遍（CI 里也是跑它）。

## 从源码跑（开发）

想改代码、加任务，就自己拉仓库跑。和发布包的区别是：**这里的 Python 要你自己装**。

```bash
git clone https://github.com/yu-echo/MaaCR
cd MaaCR
pip install -r agent/requirements.txt
python tools/validate.py
```

然后把 MFAAvalonia 的**数据目录指向本仓库的 `assets/`**（`interface.json` 在里面），
选 MuMu 设备、勾任务、点开始。

> ⚠️ 改 `interface.json` 里 `agent` / `pretask` 的路径前，先读
> [`docs/zh_cn/3.1-打包发布.md`](docs/zh_cn/3.1-打包发布.md)。
> 这几个字段的**解析基准各不相同**，写错了不会报错、只会「点开始没反应」。

### 开发时最常跑的几个命令

```bash
python tools/validate.py                        # 改完 pipeline / interface.json 必跑
python tools/preflight.py --check                # 只检查设备与模拟器，不做改动
python -m compileall -q agent tools              # 语法检查（CI 里也跑这个）
```

### 怎么发版

打一个 `v*` 标签推上去，工作流会自动：下载 MaaFramework + MFAAvalonia → 装自带 Python
→ 组装发布包 → 生成更新日志 → 建 GitHub Release 并附上 zip。

```bash
git tag v0.1.1 && git push origin v0.1.1
```

细节（产物结构、`interface.json` 的路径怎么改写、上游版本怎么锁、怎么本地试跑）在
[`docs/zh_cn/3.1-打包发布.md`](docs/zh_cn/3.1-打包发布.md)。

## 文档

改动之前先看哪一页：

| 页 | 什么时候看 |
| --- | --- |
| [`docs/zh_cn/README.md`](docs/zh_cn/README.md) | **总索引**（文档按 `章节.小节` 编号，跟框架文档一个体例） |
| [`1.1-快速开始`](docs/zh_cn/1.1-快速开始.md) | 第一次装、第一次跑 |
| [`1.2-术语与概念`](docs/zh_cn/1.2-术语与概念.md) | 看不懂日志里的词时 |
| [`2.1-识别原理`](docs/zh_cn/2.1-识别原理.md) | 圣水 / 塔血 / 皇冠 / 手牌怎么读出来的 |
| [`2.2-日常任务`](docs/zh_cn/2.2-日常任务.md) | 商店免费项、部落捐赠各自的判据 |
| [`3.1-打包发布`](docs/zh_cn/3.1-打包发布.md) | 发布包结构、`interface.json` 路径改写规则、发版 |
| [`3.2-迁移对照`](docs/zh_cn/3.2-迁移对照.md) | 旧脚本→框架的对照、框架语义陷阱、**待实机验证清单** |

## 调策略

对战改 `agent/cr_config.py` 一个文件就够：

| 想改什么 | 改哪里 |
| --- | --- |
| 出牌优先级 | `PRIORITY`（从上往下找第一张「在手 + 圣水够」的） |
| 什么时候出牌 | 界面上的「出牌圣水门槛」，或 `MIN_ELIXIR`（默认 8） |
| 两次出牌间隔 | `PLAY_COOLDOWN`（默认 1.2 秒） |
| 落点 | `SPOTS` / `MAIN_LANE` / `LANE_SPOT` / `DEEP_SPOT`，或给单张牌 `SPOT_OVERRIDE` |
| 换卡组 | 把卡面裁进 `assets/resource/image/cards/`，再写进 `CARDS` |
| 部落最多捐几次 | 界面上的「部落最多捐几次」，或 `DONATE_ROUNDS`（默认 4） |
| 「免费」认得太松/太严 | `FREE_LABEL_THRESHOLD`（默认 0.78）、`FREE_LABEL_DY`（点卡身时上移 175px） |
| 商店滑动快慢 | `SHOP_SCROLL` / `SHOP_SCROLL_WAIT` —— 商店内容是**懒加载**的，必须慢滑 |
| 判定「可捐」的门槛 | `DONATE_LIT_SAT`（按钮底色饱和度，默认 60） |

> 换卡组时的坑：同一张牌有**普通形态**和**精英/觉醒形态**两套素材，对战时会交替出现。
> 只录一套，轮到另一套那一轮就会认不出来、白白错过出牌机会。
> 每套卡组最多 2 个觉醒位，所以是 8 张牌 + 2 个精英形态 = **10 张模板**，数量固定。
> 用 `same_as` 把精英形态关联到普通形态，`PRIORITY` 里就只用写普通形态的 id。

> 日常任务那两条的判据为什么长这样（每一步都对应旧版一次翻车），
> 单独写在了 [`docs/zh_cn/2.2-日常任务.md`](docs/zh_cn/2.2-日常任务.md) —— 想动它们之前先读那一页。

## 目录结构

> 这棵树是**源码仓库**的。发布包的布局不一样（`interface.json` 与 `resource/`
> 跟 `MFAAvalonia.exe` 同层），见上面「包里的目录长这样」。

```
MaaCR/
├── .github/
│   ├── workflows/
│   │   ├── check.yml               #   push/PR：语法检查 + tools/validate.py
│   │   └── install.yml             #   打 v* 标签：组装发布包并建 Release
│   └── cliff.toml                  #   更新日志的分组规则
├── assets/
│   ├── interface.json              # ProjectInterface V2：通用 UI 的入口
│   └── resource/
│       ├── default_pipeline.json   # 全局默认参数（延迟 / 匹配算法与阈值）
│       ├── base/.gitkeep           # 空目录，但必须在（pretask 的工作目录）
│       ├── image/                  # 模板图（720×1280 原生裁剪，勿缩放）
│       │   ├── cards/              #   10 张手牌
│       │   ├── anchors/            #   界面锚点（含开宝箱的多阶段素材）
│       │   ├── nav/                #   底部导航图标（__ 分隔多状态）
│       │   └── shop/ clan/         #   日常任务：「免费」/「已收集」/「免费！」/「捐赠」
│       ├── model/                  # OCR 模型位（当前不用 OCR，空目录）
│       └── pipeline/               # 任务流水线
│           ├── main.json           #   入口 + 状态分发
│           ├── battle.json         #   各对战界面状态节点
│           ├── daily.json          #   商店免费项 / 部落捐赠
│           └── recover.json        #   未知界面自愈
├── agent/                          # 自定义识别 / 动作（Python）
│   ├── main.py                     #   AgentServer 启动入口
│   ├── cr_config.py                #   ★ 坐标与策略，要调就改这里
│   ├── cr_vision.py                #   纯识别：读数、认手牌、找按钮、白字掩码匹配
│   ├── cr_strategy.py              #   出牌决策（纯函数）
│   ├── cr_nav.py                   #   底部导航，四段容错
│   ├── cr_daily.py                 #   日常任务：两段扫描循环
│   ├── cr_stuck.py                 #   「真卡住」判定（智能 + 画面定格）
│   └── cr_nodes.py                 #   把上面这些注册成框架的 Custom 节点
├── tools/
│   ├── validate.py                 #   项目自检（改了 pipeline 就跑；CI 也跑）
│   ├── preflight.py                #   启动前准备：设备安全检查 + 拉起模拟器
│   ├── install.py                  #   组装发布包（CI 调；也可本地跑）
│   ├── install-deps-win.bat        #   装 .NET 10 桌面运行时（发布包里才用得上）
│   └── ci/setup_embed_python.py    #   给发布包装一份自带 Python
├── logo.png                        # 当前用的图标（README 头部就是它）
├── logo/                           # 8 次 logo 迭代的留档（见 logo/README.md）
├── deps/tools/                     # 官方 JSON Schema（编辑器补全 / 校验用）
└── docs/zh_cn/                     # 文档：平铺 + 编号（索引见 docs/zh_cn/README.md）
```

## 设计要点

**分工原则**：能用 JSON 表达的搬去 pipeline（界面锚点、颜色校验、双重确认、
多阶段模板、导航定位、重启游戏），好处是能被通用 UI 与调试器可视化；
框架表达不了的留在 Agent：

| 留在 Agent 的东西 | 为什么 |
| --- | --- |
| 圣水 / 塔血读数 | 要算「最右被点亮列 ÷ 满条宽」，是几何计算，内置算法给不了 |
| 底部确认按钮定位 | `ColorMatch` 拿得到最大色块，但给不出「长宽比 1.5~9」这个形状约束 |
| 手牌识别 + 出牌决策 | 手牌、圣水、破塔判定是**同一个原子决策**的三个输入，拆开反而要多传状态 |
| 三级自愈阶梯 | 三段互斥的 if/elif 各带计数器，拆成 pipeline 分支要额外写好几个识别 |
| 白字掩码匹配 | 画面与模板**都要**先二值化成「是不是白像素」；框架的 `green_mask` 只盖模板侧，且官方文档明确不建议「把主体以外全涂绿」 |
| 商店 / 部落的扫描循环 | 「扫一屏 → 领掉这一屏**所有**目标 → 看终止信号 → 慢滑一屏」，带跨屏去重与计数；而且「滑到底」的判据是「画面**还在不在动**」，`wait_freezes` 是「**等**它不动」，语义正好相反 |

**状态判定必须「模板 + 颜色」双重确认**，且判定顺序按「误判代价」排：
结算排第一，因为误判会让程序点错按钮（左边紧邻「再来一场」，点错直接再开一局）。
（pipeline 里就是 `And` + 有序的 `next` 列表。）

**认不出来 ≠ 卡住**：加载动画、开宝箱动画都是「认不出来但画面一直在变」，属于正常。
只有「认不出来 **且画面也定格了**」才是真卡住 —— 否则冷启动（实测 13 秒）会被无限重启。

**别用 `cached_image` 当「当前画面」**：它是「上一次识别时」留下的那一帧，
在自定义动作里连着取两次会拿到同一张图。日常任务判「画面还在不在动」完全依赖真帧，
所以 `MaaDriver.shot()` 走的是 `post_screencap()`。

更多设计取舍见 [`docs/zh_cn/3.2-迁移对照.md`](docs/zh_cn/3.2-迁移对照.md)。

## 常见问题

| 现象 | 先看这里 |
| --- | --- |
| **双击 `MFAAvalonia.exe` 报错、起不来** | 缺 .NET 10 桌面运行时。双击 `install-deps-win.bat`，装完**重启电脑** |
| **所有识别都失分（匹配度 0.00）** | 大概率是**屏幕熄了** —— 模拟器闲置会自动熄屏，黑屏时模板匹配全军覆没。看 `CR.Boot` 的日志，或手动点亮模拟器 |
| 点开始就报 `pretask failed` | 路径解析问题（`pretask.exec` 不走 PATH、工作目录是 `resource/base`）。跑一下 `tools/validate.py`，它会直接告诉你哪一行不对 |
| 卡在某页不动 | 看日志有没有触发三级自愈。子页面（商店 / 社交 / 卡牌）没做锚点，本来就返回 unknown，靠①回主界面兜底 |
| 报「界面未知」然后重启游戏 | 说明「认不出来 + 画面定格」同时成立。把那一屏截图发出来补个锚点就好 |
| 一直不出牌 | 检查圣水门槛是否过高、手牌是否认得出（看日志的 `手牌=[...]`）。认不出就是卡面模板缺了精英形态 |
| 点下去没反应 | 旧版最坑的一类失败：坐标落在两行按钮中间的空隙上，点了等于没点还不报错。每个写死坐标都要在截图上肉眼确认过 |
| 领商店第一屏就报「画面已静止（差 0.00），判定到底」 | 说明**重新截帧没生效**（拿到的是缓存帧）。这是日常任务最需要实机确认的一条，见 [`docs/zh_cn/2.2-日常任务.md`](docs/zh_cn/2.2-日常任务.md) 第五节 |
| 部落一个都没捐出去 | 看日志「看到 N 个「捐赠」按钮，其中可捐(亮绿) N 个」。可捐为 0 说明匹配到的都是灰按钮（自己发起的请求，本来就捐不了） |
| 选错设备（驱动到真机了） | 该检查被跳过了。确认没设 `MAACR_ALLOW_REMOTE`，并检查「环境准备」的日志 |

## 路线图

- [x] 阶段 1：最小闭环（主界面 → 进对战 → 出牌 → 结算 → 循环）
- [x] 阶段 2：导航容错 + 三级自愈 + 重启游戏
- [x] 阶段 3：日常任务——商店免费项、部落捐赠
- [x] 阶段 4：打包发布——GitHub Release + 自带 Python + 更新日志
- [ ] 阶段 5：补锚点（部落聊天页、社交页、训练日预览页、商店各子标签），减少走兜底路径
- [ ] 阶段 6：防守判断（识别己方半场的红血条 → 有敌人先防守），把胜率拉起来
- [ ] `tools/validate.py` 增加官方 schema 校验（能抓「字段名写错」这类静默问题）
- [ ] 多分辨率支持（坐标改按比例存 + 模板按分辨率分目录）
- [ ] 日常任务实机验证（`docs/zh_cn/2.2-日常任务.md` 第五节列的那几条，都还没在真机上跑过）

## 鸣谢

- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) —— 本项目的框架
- [MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia) —— 通用图形界面
- [MaaPracticeBoilerplate](https://github.com/MaaXYZ/MaaPracticeBoilerplate) —— 目录约定、
  发布流程与 Agent 写法的参考
- [syoius/MaaYuan](https://github.com/syoius/MaaYuan) —— 发布包结构与 README 的参考

## License

[MIT](LICENSE)
