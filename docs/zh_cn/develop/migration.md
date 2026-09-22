# 从旧版脚本迁移到 MaaFramework：对照与待验证清单

> 这份文档解释**这次重构到底改了什么、为什么这么改、哪些地方还没实机验证**。
> 动手改代码前先读一遍，能省掉很多返工。

旧的 `crbot`（自写 OpenCV + adb + PyQt6）与 MaaCR 是**同一套识别资产**在两种架构下的实现。
模板图、阈值、量化读法、出牌策略全部保留；被替换的只有设备层与界面层。

---

## 一、模块去向一览

| 旧版文件 | 规模 | 去向 |
| --- | --- | --- |
| `device.py` | 446 行 | **删除**。截图/点击/滑动归 `AdbController`；模拟器生命周期归 `tools/preflight.py` |
| `startup.py` | 196 行 | 拆：`StuckWatcher` → `agent/cr_stuck.py`；开模拟器 → `tools/preflight.py`；等游戏就位 → `CR.Boot` |
| `nav.py` | 174 行 | `agent/cr_nav.py`（改成「查询吃帧、动作吃 driver」，可离线自检） |
| `vision.py` | 278 行 | 一拆二：锚点/颜色匹配 → pipeline 内置算法；量化读数 → `agent/cr_vision.py` |
| `strategy.py` | 97 行 | `agent/cr_strategy.py`，**几乎零改动** |
| `config.py` | 363 行 | 一拆三：坐标阈值 → pipeline JSON + `interface.json`；策略参数 → `agent/cr_config.py`；模板清单 → `image/` |
| `bot.py` | 313 行 | 主循环 → `pipeline/main.json` 的 `next` 分发 + `battle.json` / `recover.json` |
| `app.py` + `gui_app.py` + `gui/` | ~32KB | **删除**，改用 MFAAvalonia |
| `daily.py` | 674 行 | **未迁完**（阶段 3）。模板已放好，逻辑待迁 |
| `capture.py` | 119 行 | 不迁。采图改用 MFA 工具箱 / VSCode 插件 |
| `templates/` | 45 张 | 活跃的 27 张进 `image/`，按用途分子目录 |

> **`templates/store/` 那 12 张没有迁移**：它们已无任何代码引用（历史遗留）。
> 旧版的 `templates/login_page.png`、`templates/anchor_*.png` 同理（已被 `templates/anchors/` 取代）。

---

## 二、核心思维转换：if/elif 链 = next 有序列表

这是整个迁移最关键的一条。旧版 `vision.analyze()` 是**按固定优先级**逐条判断、返回第一个命中的状态；
MaaFramework 的 `next` 列表是**按顺序**逐个识别、命中第一个就执行。**这两件事是同一个东西。**

```
analyze() 判定顺序                        pipeline 的 next
────────────────────────────────────      ──────────────────────────────
（新增）对局数够了就收工              →   对局数已达标      (Custom)
1. result_confirm + 蓝色双重确认     →   结算界面          (And)
2. cadpa 锚点（登录页）              →   登录页            (TemplateMatch)
3. chest_stars*（多阶段动画）        →   宝箱弹层          (TemplateMatch, template 为 list)
4. 手牌 ≥ 2 张 或（≥1 张 且圣水条左端亮）→ 对战中          (Custom)
5. deck_slots（卡组页）              →   卡组页            (TemplateMatch)
6. 主界面「对战」按钮橙色占比         →   主界面            (ColorMatch)
7. cancel（匹配中）                  →   匹配中            (TemplateMatch)
8. 全部未命中                        →   未知界面处理      (Custom，三级自愈)
```

⚠️ **判定顺序必须原样保留**，它是按「误判代价」排的，不是随便写的。

---

## 三、字段语义对照（容易踩的地方）

| 旧版写法 | MaaFramework | 注意 |
| --- | --- | --- |
| `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` | `TemplateMatch` | `method` 默认就是 5，与 cv2 一致 ⇒ **阈值可照搬**，不用重标定 |
| `_frac(frame, box, HSV_RANGE) > 0.40` | `ColorMatch` | ⚠️ `count` 是**像素个数**不是占比，必须 `阈值 × roi宽 × roi高`；例 `0.40×190×56 = 4256` |
| `cv2.COLOR_BGR2HSV` | `ColorMatch.method: 40` | ⚠️ 默认是 **4（RGB）**，不显式写就按 RGB 解释你的 HSV 三元组，判据全失效 |
| `time.sleep(n)` | `post_delay: n` | |
| `while matches_done < N` | Agent 侧计数 + `CR.MatchesReached` | **没有用节点的 `max_hit`**：max_hit 用完只会跳过该节点，`next` 会落到「未知界面恢复」开始乱点 |
| `nav.goto()`「处理完再重试」 | `"[JumpBack]节点名"` | 语义完全对应 |
| `restart_game()` | `CR.UnknownRecover` 内部 `post_stop_app` + `post_start_app` | 也可以拆成 `StopApp` / `StartApp` 两个纯 JSON 节点 |
| 自写 `Logger`（控制台+文件双写） | 框架 `debug/maafw.log` + `focus` 字段 + `print` | Agent 的 stdout 会进通用 UI 的日志 |
| 失败时存截图 | `save_on_error` / `save_draw` | 旧版人工做「画框存图复核」，`save_draw` 把它自动化了 |

### ⚠️ `timeout` 的语义极易搞错

pipeline 的 `timeout` 是「**当前节点等待它的 `next` 命中的时间**」，不是「本节点自己的超时」。
官方文档原话：**调整本节点识别等待时间应改上一节点的 timeout**。

### ⚠️ pipeline JSON 不写注释

官方 sample 与真实社区项目（MaaClashRoyaleCN 等）的 pipeline 都是**纯 JSON**。
所以本项目把设计理由放在这份文档与 Agent 代码注释里，**不在 pipeline 里写 `//`**。
`interface.json` 是可以写注释的（官方模板本身就带注释）。

---

## 四、留在 Agent 的东西，以及为什么

| 留在 Agent 的 | 为什么不能用 pipeline 表达 |
| --- | --- |
| `read_elixir` 圣水读数 | 「最右侧被点亮的列 ÷ 满条宽」是几何计算。`ColorMatch` 只能回答「这片区域有多少洋红像素」，给不出最右边界 |
| `read_enemy_towers` 塔血 | 同上（血条宽度就是血量） |
| `find_bottom_button` | `ColorMatch` + `order_by: Area` 能拿到最大色块，但**给不出「长宽比 1.5~9」这个形状约束**，而那正是用来排除别的蓝色 UI 的 |
| `read_crowns` 皇冠数 | 理论可拆成 6 个固定 roi 的 `ColorMatch`，但现版本用了「形态学闭运算 + 连通域计数」是实测零误报的；换成 6 个独立判据属于**用确定换不确定**，先不动 |
| 手牌识别 + 出牌决策 | 手牌、圣水、破塔判定是**同一个原子决策**的三个输入，拆成节点后框架只知道单槽结果，反而要多传状态 |
| 三级自愈阶梯 | 三段是**互斥的 if/elif**，各带计数器（试满几次就降级）。拆成分支要靠 3~4 个自定义识别表达「该轮到哪一段了」，计数器还得在 Agent 侧另存一份 |
| 白字掩码匹配 | 见下节 |

### 白字掩码匹配的现状

旧版最有用的一招：把画面和模板**都先转成白色像素掩码**再比，等于把背景整个忽略掉。
实测收益：商店「免费」正确位置 1.000、14 张对照截图次高分全部 < 0.60（零误报）；
部落「捐赠」灰按钮 0.997 / 绿按钮 0.898（**原色匹配绿按钮只有 0.822，会被 0.85 阈值丢掉**）。

MaaFramework 的 `TemplateMatch` 只有 `green_mask`，**没有任意掩码**。两条路：

- **方案 A（推荐先试）**：把模板的**非白像素涂成纯绿 `(0,255,0)`** 再开 `green_mask: true`。
  `green_mask` 只跳过**模板侧**涂绿区域，画面侧不用动 ⇒ 语义正好等于掩码匹配。
  ⚠️ **需要实测确认框架对「绿色」的判定容差**（文档只说「涂绿区域不匹配」，没给容差），
  以及涂绿边界像素的抗锯齿影响。
- **方案 B（保底）**：把 `cr_vision.find_white_text` 注册成 Custom 识别，行为与旧版 100% 一致。

> 当前代码里 `find_white_text` / `sat_val_of` 已经就位，但**还没有任何节点调用它们**
> —— 它们是阶段 3（日常任务）要用的。这是有意保留的，不是死代码。

---

## 五、⚠️ 需要实机验证的清单

这份清单是本次迁移里**语义有近似、或依赖框架行为、或我无法离线验证**的地方。
按风险从高到低排，建议逐条过一遍。

### 5.1 卡住判定的「重置」语义（最需要验证）

- **旧版**：主循环每轮 `watch.feed(frame, state == UNKNOWN)`，看到非 unknown 就**立刻**归零计数器。
- **新版**：`next` 分发没有「每轮必过」的钩子，所以改成按时间间隔判定 ——
  两轮 unknown 间隔超过 `UNKNOWN_RESET_GAP`（默认 4 秒）就认为中途认出来过，计数归零
  （见 `cr_stuck.StuckWatcher.feed` 与 `cr_nodes._State.tick_unknown`）。
- **风险**：认出来但 `post_delay` 很短（< 4 秒）时，计数器可能不会及时归零，
  导致自愈阶梯过早降级到「重启游戏」。
- **怎么验**：让它在一局里经历「对战中 → 子页面 → 回主界面」若干次，看日志里
  `home_tries` 是否每次从 1 开始。如果不对，把 `UNKNOWN_RESET_GAP` 调小，或改成
  在 `CR.InBattle` / `CR.OnResult` 里显式归零。

### 5.2 ColorMatch 的 `count` 换算

`0.40 × 190 × 56 = 4256`（结算页「确定」按钮的蓝色占比）与 `0.5 × 250 × 64 = 8000`
（主界面「对战」按钮的橙色占比）都是按旧版阈值推算的，**没有实机跑过**。
另外 `ColorMatch` 返回的 box 是「命中像素的外接框」，与旧版「整个 roi 的占比」不完全等价
—— 尤其当 roi 内只有部分区域着色时，两者的判据宽度不同。

- **怎么验**：开 `save_draw: true`，看这两个节点的命中率与可视化框。
  偏严就调低 `count`，偏松就调高。

### 5.3 `target: [369, 966]` 与缩放后的坐标系

旧版的 `input tap` 用的是**设备物理像素**；MaaFramework 的 `roi` / `target` 用的是
**按 `display_short_side: 720` 缩放后**的坐标。
国服皇室战争在 MuMu 上是 720×1280 竖屏，缩放比正好 1:1，所以两者应当一致 ——
但这是**推断**，必须实测。

- **怎么验**：跑一次「主界面 → 点对战」，看是否真的进了匹配。没进就说明有偏移，
  需要按实际缩放比换算（或把 `display_short_side` 设成 1280 让短边是 720 的整数倍）。

### 5.4 `CustomAction.RunArg.box` 的坐标系

`CR.OnResult` 用识别框中心去点「确定」而不是写死坐标（`anchors/result_confirm.png`
命中的位置正是那个按钮，旧版写死的 `RESULT_CONFIRM_TAP = (472,1149)` 就是它的中心）。
这条依赖「`argv.box` 与 `post_click` 用同一套坐标系」，同样是推断。

- **怎么验**：看日志里点下去之后有没有真的关掉结算页。没有就把 `RESULT_CONFIRM_TAP` 作为
  回退打开（代码里已经保留了回退分支）。

### 5.5 Agent 的状态是模块级单例

`cr_nodes._State` 是模块级单例，一个 Agent 进程内只能跑一条任务链。
通用 UI 的多实例会各自起一个 Agent 进程，所以这一点成立 —— 但如果同一个实例里
同时跑两个任务（比如「自动对战」和未来的「商店免费项」并行），计数会互相污染。

- **怎么验**：阶段 3 加入日常任务后，确认通用 UI 是串行执行任务链，或者把状态改成
  按 `task_detail.task_id` 分桶。

### 5.6 未实机验证的部分（环境所限）

以下**完全没有跑过**（本次重构是在没有模拟器的环境下完成的，只做了离线校验）：

- Agent 与框架的实际握手（`AgentServer.start_up` / `join`）；
- 所有 Custom 识别/动作的真实调用；
- `CR.Boot` 里 `dumpsys window` 的 `mCurrentFocus=` 解析（各 Android 版本格式略有差异，
  代码写得宽容、拿不到就当「不确定」，但仍需实测）；
- 整条流水线能否完整打完一局。

**已完成的离线校验**（可复现）：

```bash
python tools/validate.py
#   pipeline 文件节点数：11
#   检查模板引用：5 处 / 检查节点引用：17 处 / 检查 Custom 注册：识别 2 个 / 动作 6 个
#   全部通过。
python -m py_compile agent/*.py     # 语法检查通过
```

---

## 六、下次继续时从哪开始

按优先级：

1. **先跑通阶段 1**（见 README 路线图）：用「演练模式」验证识别，再用正常模式打 1 局。
   把上面 5.1~5.4 逐条验掉。
2. **补锚点**：部落聊天页、社交页、训练日预览页、商店各子标签现在都返回 unknown，
   只能靠自愈兜底。用 MFA 工具箱或 VSCode 插件截一屏、裁个稳定特征块放进 `image/anchors/`，
   再在 `recover.json` 或新的 pipeline 文件里加判据。
   **回检区分度**：目标页 ≈ 1.00、其它页 < 0.3 才算合格。
3. **迁日常任务**（`daily.py` 674 行）：商店免费项 + 部落捐赠。
   这一块会用到白字掩码（见第四节），先做 5.2 的 `green_mask` 小实验再决定 A/B 方案。
   商店滚动到底的判据（旧版看「画面还在不在动」）在 pipeline 里没有等价物
   （`wait_freezes` 是「等」静止，语义相反），要留在 Agent。
4. **打包发布**：参考 `MaaPracticeBoilerplate` 的 `.github/workflows/install.yml`，
   附便携式 Python 并改 `interface.json` 里 agent 的 `exec` 字段。

---

## 七、别丢掉的既有经验

这几条是旧版踩出来的、**框架无关**的结论，改代码时别改回去：

1. **状态判定必须「模板 + 颜色」双重确认**。只用颜色占比一定会误判 ——
   实测卡组页底部导航有一片亮蓝，被误判成结算页的蓝色「确定」按钮，程序就去点了卡组页的导航。
2. **判定顺序按「误判代价」排**。结算排第一，因为误判会让它点错按钮（左边紧邻「再来一场」，点错直接再开一局）。
3. **绝不按返回键兜底**。返回键会弹出游戏自己的「要退出吗」对话框，越「恢复」越乱。要重置就用 force-stop。
4. **「认不出来」≠「卡住」**。加载/开宝箱动画都属于「认不出来但画面一直在变」，那是正常的；
   只看时间的话冷启动（13 秒）会被无限重启。
5. **导航「找不到」≠「不存在」**。选中态的图标会加宽并位移，跟未选中态模板对不上 ——
   这时正确动作是**判到达**，不是按返回键。
6. **新坐标一律程序化量取 + 画框人眼复核**，不要肉眼估（实测偏差能到 100px）。
7. **每个写死坐标都要在注释里写清「这个数是量出来的、换分辨率要重量」**。
8. **模板必须从模拟器原生截图裁**，不要用手机截图缩放（缩放过的文字模板匹配会掉很多）。
9. **「点了没反应」是最难查的一类失败**（坐标落在两行按钮中间的空隙上，点了等于没点还不报错）。
10. **静态检查通过 ≠ 能跑**。`py_compile` 全绿、常量都在、模块导入 OK，真跑第一次还是炸过。
