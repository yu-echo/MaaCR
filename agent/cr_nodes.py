# -*- coding: utf-8 -*-
"""Agent 节点：把识别与决策注册成 MaaFramework 的 Custom 识别 / Custom 动作。

分工原则（本次重构的核心）：
  · **能用 JSON 表达的，全部搬去 pipeline** —— 界面锚点匹配、颜色校验、
    双重确认（And）、多阶段模板、导航定位、重启游戏、候选卡面落盘。
    好处是这些能被通用 UI 与 MaaDebugger 可视化调试。
  · **框架表达不了的，留在这里**，比如：
    - 几何计算：「最右被点亮列 ÷ 满条宽」读圣水、血条宽度算血量；
    - 带形状约束的找色：底部确认按钮要过滤长宽比；
    - 多值联合决策：手牌 + 圣水 + 破塔判定 -> 出牌，是同一个原子决策；
    - 自愈阶梯：三段式的计数与「与」判据，拆成 pipeline 分支要多写好几个识别，
      而逻辑本身是一段互斥的 if/elif，留在代码里更好维护；
    - 连续扫描循环：商店领免费项、部落捐赠是「扫一屏 -> 领掉这一屏**所有**目标
      -> 看终止信号 -> 慢滑一屏」，中间带着跨屏去重集合与连续空屏计数 ——
      详见 `cr_daily` 的模块文档串（那里列了四条不能拆的硬原因）。

注册名统一加 `CR.` 前缀，一眼能和 pipeline 里的内置算法区分开。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import cr_config as C
import cr_strategy
from cr_daily import Daily
from cr_nav import Nav
from cr_stuck import StuckWatcher
from cr_vision import (BATTLE, Scene, Templates, find_bottom_button,
                       read_crowns, read_elixir, read_enemy_towers, read_hand)

ROOT = Path(__file__).resolve().parent.parent      # 仓库根
DEBUG_DIR = ROOT / "debug"
CAND_DIR = DEBUG_DIR / "candidates"
SHOT_DIR = DEBUG_DIR / "shots"


# ==================== 运行期状态 ====================

class _State:
    """一次 Agent 进程内的运行状态。

    ⚠️ 状态放模块级单例而不是实例属性：AgentServer 每次调用都新建 Context，
    但注册的 Custom 类实例是复用的；用模块级单例最不容易踩「计数被重置」的坑。
    代价是同一进程内只能跑一个任务链 —— 通用 UI 的多实例会各起一个 Agent 进程，
    所以这一点成立（README 里记了这一条约束）。
    """

    def __init__(self):
        self.tpl = None
        self.nav = None
        self.stuck = StuckWatcher()
        self.task_id = None
        self.dry = False
        self.min_elixir = C.MIN_ELIXIR
        self.donate_rounds = C.DONATE_ROUNDS
        self.target_matches = 1
        self.matches_done = 0
        self.three_crown = 0
        self.battle_t0 = None
        self.last_play = 0.0
        self.last_battle = None
        self.mined = set()
        # 未知界面三段式自愈的计数（认出来过就归零，见 tick_unknown）
        self.home_tries = 0
        self.overlay_taps = 0
        self.game_restarts = 0
        self._last_unknown = None
        self._boot_ts = time.time()

    # ---- 惰性初始化 ----

    def ensure(self):
        if self.tpl is None:
            self.tpl = Templates()
            self.nav = Nav(self.tpl, confirm_tap=find_bottom_button,
                           log=lambda m: _log("  [nav] %s" % m))
            _log("载入模板：%s" % self.tpl.summary())
        return self

    # ---- 任务级重置 ----

    def bind_task(self, task_detail):
        """换了一个任务就把**任务级**状态复位。

        用 task_id 判定最可靠：同一任务链里 task_id 不变，通用 UI 重新点一次
        执行会拿到新 task_id。

        ⚠️ 复位的范围是**任务级**的两类东西：
          · 局数 / 自愈计数这类累加器；
          · `dry` / `min_elixir` / `donate_rounds` 这些**由节点参数写入**的开关。
            它们必须在换任务时回到默认值，否则会从上一个任务粘过来 ——
            因为 `_apply_param` 只在参数出现时才改它。Agent 进程在通用 UI 里是
            **跨多次运行存活**的，于是「先开着演练模式跑一次、关掉再跑一次」
            第二次仍然一个都不点 —— 而 README 恰好推荐用户按这个顺序上手。
        """
        tid = getattr(task_detail, "task_id", None)
        if tid is None or tid == self.task_id:
            return
        self.task_id = tid
        self.matches_done = 0
        self.three_crown = 0
        self.battle_t0 = None
        self.last_battle = None
        self.mined = set()
        self.home_tries = self.overlay_taps = self.game_restarts = 0
        self.stuck.reset()
        # 节点参数回到配置默认值；接下来这个任务的节点会把它自己的值填回来
        self.dry = False
        self.min_elixir = C.MIN_ELIXIR
        self.donate_rounds = C.DONATE_ROUNDS

    def tick_unknown(self):
        """每进入一次「未知界面」调一次，必要时归零三段式计数。

        语义说明：旧版是主循环里看到非 unknown 就立刻归零。新框架的 next 分发
        没有「每轮必过」的钩子，所以改成按时间间隔判定 —— 两轮 unknown 之间
        隔了超过 UNKNOWN_RESET_GAP 秒，就认为中途认出来过（认出来会走一段
        post_delay 再进行下一轮）。这是本次移植里**唯一一处语义近似**，
        需要实机验证。
        """
        now = time.time()
        if self._last_unknown is not None and now - self._last_unknown > C.UNKNOWN_RESET_GAP:
            self.home_tries = self.overlay_taps = self.game_restarts = 0
        self._last_unknown = now


_ST = _State()


# ==================== 小工具 ====================

def _log(msg):
    print("[MaaCR %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def _param(raw):
    """把 custom_*_param 解析成 dict。空 / 非法一律当空 dict，不抛错。"""
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _as_int(val, default):
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


def _hit(detail, box):
    """识别命中 -> AnalyzeResult；未命中 -> box=None。"""
    return CustomRecognition.AnalyzeResult(box=box, detail=detail)


def _miss(detail):
    return CustomRecognition.AnalyzeResult(box=None, detail=detail)


def _roi_xywh(x0y0x1y1):
    x0, y0, x1, y1 = x0y0x1y1
    return [x0, y0, x1 - x0, y1 - y0]


class MaaDriver:
    """把 maa 的 Context 适配成 cr_nav / cr_daily 认识的最小接口（shot / tap）。

    这样它们不直接依赖框架，能拿存下来的帧做离线自检。
    """

    def __init__(self, ctx, dry=False):
        self.ctx = ctx
        self.dry = dry

    def shot(self):
        """当前画面 —— **真实重新截一帧**，不是 `cached_image`。

        ⚠️ 为什么不能用 `controller.cached_image`：它是「**上一次识别时**留下的那一帧」。
        在自定义动作里连着调两次会拿到同一张图，而日常任务的商店流程**正是靠
        「相邻两帧有没有差别」判有没有滑到底**（见 `cr_daily.claim_shop_free`）——
        拿缓存帧会让第一屏就判成「画面静止 / 到底」，整条流程直接空转结束。

        框架自带的 `post_screencap()` 是显式重新截图，且 `CR.Boot` 里已经在用同一套
        调用（`post_screencap().wait().get()`）。截帧失败时退回缓存帧：
        比抛异常中断整条流程强，但日志要留痕。
        """
        try:
            img = self.ctx.tasker.controller.post_screencap().wait().get()
            if img is not None:
                return img
        except Exception as exc:
            _log("  重新截帧失败，退回缓存帧：%s" % exc)
        return self.ctx.tasker.controller.cached_image

    def tap(self, x, y):
        if self.dry:
            _log("  （演练模式，跳过点击 (%d,%d)）" % (int(x), int(y)))
            return
        self.ctx.tasker.controller.post_click(int(x), int(y)).wait()

    def swipe(self, x1, y1, x2, y2, ms=300):
        if self.dry:
            _log("  （演练模式，跳过滑动）")
            return
        self.ctx.tasker.controller.post_swipe(int(x1), int(y1), int(x2), int(y2),
                                              int(ms)).wait()

    def key(self, code):
        if self.dry:
            return
        self.ctx.tasker.controller.post_click_key(int(code)).wait()

    def stop_app(self, package=C.CR_PKG):
        self.ctx.tasker.controller.post_stop_app(package).wait()

    def start_app(self, package=C.CR_PKG):
        self.ctx.tasker.controller.post_start_app(package).wait()


def _apply_param(state, argv):
    """每个节点进来的标准起手：① 换了任务就复位；② 把节点参数写进运行状态。

    「复位」和「应用参数」必须在同一个函数里、并按这个顺序 —— 复位会把
    `dry` / `min_elixir` / `donate_rounds` 打回默认值，紧接着应用本节点的参数
    把它们设成该任务该有的值。分开写就很容易漏掉某一边。

    参数键名在两类节点上不同（识别是 `custom_recognition_param`、动作是
    `custom_action_param`），所以两个都看，谁有值用谁。返回解析出来的 dict，
    少数需要读参数的节点直接用返回值。
    """
    state.bind_task(getattr(argv, "task_detail", None))
    param = _param(getattr(argv, "custom_action_param", None)
                   or getattr(argv, "custom_recognition_param", None))
    if "dry_run" in param:
        state.dry = bool(param["dry_run"])
    if "min_elixir" in param:
        state.min_elixir = _as_int(param["min_elixir"], state.min_elixir)
    if "donate_rounds" in param:
        state.donate_rounds = _as_int(param["donate_rounds"], state.donate_rounds)
    return param


def _daily(state):
    """按当前运行状态现造一个 `cr_daily.Daily`。

    刻意**不缓存**实例：`dry` 是每个节点都可能被 pipeline 参数改的，
    缓存一份就要记得处处同步，漏一次就是「演练模式下真的点了」这类吓人的 bug。
    构造它没有 I/O（模板早就装在 `state.tpl` 里了），现造最省心。
    """
    return Daily(state.tpl, state.nav, log=_log, dry=state.dry,
                 bottom=find_bottom_button)


def _foreground_pkg(context):
    """当前前台窗口的包名；查不到返回 None。

    为什么要它：**分界线在「前台是不是游戏」，不在「画面认不认得出来」**。
    画面认不出来有很多种正常情况（加载动画、开宝箱动画），但「前台不是游戏」
    只有一种含义 —— 我们跑到别的地方去了，这时必须停下，绝不能在模拟器桌面上乱点。

    ⚠️ dumpsys window 的 `mCurrentFocus=` 格式各版本略有差异，所以解析写得宽容一点：
       拿不到就返回 None（当「不确定」处理），不要让解析失败变成误判。
    """
    try:
        out = context.tasker.controller.post_shell("dumpsys window").wait().get()
    except Exception:
        return None
    for line in (out or "").splitlines():
        s = line.strip()
        if s.startswith("mCurrentFocus=") and "{" in s:
            token = s.split(" ", 1)[-1].strip()
            inner = token.split("{", 1)[-1].rstrip("}")
            parts = inner.split(" ")
            if len(parts) >= 2 and "/" in parts[1]:
                return parts[1].split("/", 1)[0]
    return None


def _analyze_battle(frame, tpl):
    """对战中画面的量化读数：圣水 + 手牌 + 敌塔血量。

    返回 (Scene, 圣水条左端是否连续亮)。left_lit 单独返回是因为判「是不是在对战中」
    要用它，而 Scene 里没有这个字段（它是判据、不是读数）。
    """
    elixir, frac, left_lit = read_elixir(frame)
    scene = Scene(BATTLE, elixir, frac, read_hand(frame, tpl), read_enemy_towers(frame))
    return scene, left_lit


def _mine_unknown(frame, scene, state):
    """把「认不出来的手牌槽」裁下来存盘，供人工确认后补进 cr_config.CARDS。

    为什么需要它：同一张牌有普通形态和精英形态两套素材，对战时会交替出现。
    只要某个形态没被录进 CARDS，轮到它那一轮就永远认不出来。
    与其靠猜，不如让它在实战里自己冒出来。

    ⚠️ 存的是**游戏真实渲染的像素**。AI 生成的卡面图没用 ——
       模板匹配要求逐像素对上，画得再像也匹配不上。
    """
    if len(state.mined) >= 60:
        return
    have = {h.slot for h in scene.hand}
    w, h = C.HAND_CARD_WH
    for i, (cx, cy) in enumerate(C.HAND_SLOTS):
        if i in have:
            continue
        px, py = cx - w // 2, cy - h // 2
        if px < 0 or py < 0 or px + w > frame.shape[1] or py + h > frame.shape[0]:
            continue
        crop = frame[py:py + h, px:px + w]
        import hashlib
        digest = hashlib.md5(crop.tobytes()).hexdigest()[:8]
        if digest in state.mined:
            continue
        state.mined.add(digest)
        CAND_DIR.mkdir(parents=True, exist_ok=True)
        fp = CAND_DIR / ("slot%d_%s.png" % (i + 1, digest))
        cv2.imwrite(str(fp), crop)
        _log("  · 捡到未登记的卡面 -> %s（认一下是哪个形态，放进 image/cards/ 并写进 cr_config.CARDS）"
             % fp.name)


# ==================== 自定义识别 ====================

@AgentServer.custom_recognition("CR.MatchesReached")
class MatchesReached(CustomRecognition):
    """已打够指定局数 -> 命中，让 pipeline 执行 StopTask 收工。

    对应旧版 bot.py 的 `while matches_done < args.matches`。
    计数放在 Agent 里而不是用节点的 max_hit：因为结算节点的 max_hit 用完只会
    被跳过，next 会落到「未知界面恢复」去，那样反而会开始乱点。
    """

    def analyze(self, context, argv):
        st = _ST.ensure()
        param = _apply_param(st, argv)
        st.target_matches = _as_int(param.get("matches"), st.target_matches)

        reached = st.matches_done >= st.target_matches
        detail = {"matches_done": st.matches_done, "target": st.target_matches,
                  "three_crown": st.three_crown}
        if reached:
            _log("已打满 %d 局（其中三冠 %d 局），收工" % (st.target_matches, st.three_crown))
            return _hit(detail, _roi_xywh(C.HAND_ROI))
        return _miss(detail)


@AgentServer.custom_recognition("CR.InBattle")
class InBattle(CustomRecognition):
    """判「当前在对战中」，并把这一帧的量化读数缓存下来给出牌动作复用。

    ⚠️ 判据是「与」而不是「或」，这是实测踩出来的：
       光靠「圣水条区域一片洋红」判对战**不够** —— 开宝箱界面整屏都是紫粉色，
       会让圣水条区域全亮，程序就会去点手牌槽和竞技场。
       所以要求**手牌区至少认出 2 张牌**；只有「认出 1 张 且 圣水条左端亮」
       时才放宽（应付个别卡面没录进模板的情况）。
    """

    def analyze(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)

        frame = argv.image
        scene, left_lit = _analyze_battle(frame, st.tpl)
        ok = (len(scene.hand) >= C.BATTLE_MIN_CARDS
              or (len(scene.hand) >= 1 and left_lit))

        if not ok:
            st.last_battle = None
            return _miss({"hand": len(scene.hand)})

        if st.battle_t0 is None:
            st.battle_t0 = time.time()
            _log("进入对战")
        st.last_battle = scene
        return _hit(
            {"elixir": scene.elixir, "hand": [str(c) for c in scene.hand],
             "towers": {k: round(v, 2) for k, v in scene.tower_hp.items()}},
            _roi_xywh(C.HAND_ROI),
        )


# ==================== 自定义动作 ====================

@AgentServer.custom_action("CR.PlayCards")
class PlayCards(CustomAction):
    """一次完整的出牌决策：读局面 -> 选牌 -> 点手牌槽 -> 点落点。

    为什么做成**一个**动作而不是「识别 + 点击」两个节点：
    手牌、圣水、敌塔血量是同一个原子决策的三个输入，拆开要在节点间传递状态，
    反而更复杂。旧版的 strategy.choose() 因此可以整体搬过来。
    """

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        frame = context.tasker.controller.cached_image
        drv = MaaDriver(context, st.dry)

        # 复用 CR.InBattle 刚算过的那一帧结果（同一帧，不必再算一遍）
        scene = st.last_battle
        if scene is None:
            scene, _ = _analyze_battle(frame, st.tpl)
        st.last_battle = scene
        _mine_unknown(frame, scene, st)

        info = "对战中 圣水=%d/10 敌塔[L%.2f R%.2f] 手牌=%s" % (
            scene.elixir, scene.tower_hp.get("left", -1.0),
            scene.tower_hp.get("right", -1.0), scene.hand)

        now = time.time()
        if now - st.last_play < C.PLAY_COOLDOWN:
            _log(info + " -> 冷却中")
            return True

        pick = cr_strategy.choose(scene, st.min_elixir)
        if pick is None:
            _log(info + " -> 不符合出牌条件，等圣水")
            return True

        slot, cid, spot, (x, y) = pick
        _log("%s -> 出 %s 到 %s(%d,%d)" % (info, cr_strategy.describe(cid), spot, x, y))
        drv.tap(*C.HAND_SLOTS[slot])
        time.sleep(0.35)          # 让手牌先选中，再点落点
        drv.tap(x, y)
        st.last_play = time.time()
        return True


@AgentServer.custom_action("CR.OnResult")
class OnResult(CustomAction):
    """结算：数皇冠 -> 记账 -> 点「确定」。

    点哪里用**识别框中心**（argv.box 就是 anchors/result_confirm.png 命中的位置，
    也就是「确定」按钮本身），不再写死坐标 —— 实测该按钮框正是
    (377,1121,190,56)，中心 (472,1149)，与旧版写死的 RESULT_CONFIRM_TAP 一致。
    """

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        frame = context.tasker.controller.cached_image
        drv = MaaDriver(context, st.dry)

        mine, theirs = read_crowns(frame)
        st.matches_done += 1
        if mine >= 3:
            st.three_crown += 1
        dur = 0.0 if st.battle_t0 is None else time.time() - st.battle_t0
        st.battle_t0 = None
        st.last_battle = None

        _log("第 %d 局结算：我方 %d 冠 / 对方 %d 冠%s，对战耗时 %.0f 秒 -> 点「确定」"
             % (st.matches_done, mine, theirs, "  ★三冠★" if mine >= 3 else "", dur))

        # 失败时留一张图，便于事后核对（框架的 save_on_error 只管任务失败）
        try:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(SHOT_DIR / ("result_%02d.png" % st.matches_done)), frame)
        except Exception as exc:                      # 存图失败不该中断流程
            _log("  （结算截图没存上：%s）" % exc)

        box = argv.box
        x, y = C.RESULT_CONFIRM_TAP
        if box is not None and len(box) == 4 and box[2] > 0 and box[3] > 0:
            x, y = int(box[0] + box[2] // 2), int(box[1] + box[3] // 2)
        drv.tap(x, y)
        return True


@AgentServer.custom_action("CR.TapOverlay")
class TapOverlay(CustomAction):
    """全屏弹层（开宝箱那种多阶段循环动画）：有底部确认按钮就点确认，否则点屏幕中心推进。

    为什么按颜色找而不是写死坐标：各界面「确定」位置都不一样
    （结算页 (472,1149)、卡牌详情面板 (239,1257)、宝箱结算在底部中间），
    而它们**都是亮蓝色**，找「底部最大的蓝色块」更稳。
    """

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        frame = context.tasker.controller.cached_image
        target = find_bottom_button(frame) or C.CENTER_TAP
        _log("全屏弹层（宝箱等）-> 点 %s" % (target,))
        MaaDriver(context, st.dry).tap(*target)
        return True


@AgentServer.custom_action("CR.GoMain")
class GoMain(CustomAction):
    """回主界面：点底部导航「对战」，走 cr_nav 的四段容错。"""

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        _log("回主界面（底部导航「对战」）")
        st.nav.go_main(MaaDriver(context, st.dry))
        return True


# ==================== 日常任务 ====================
#
# 这两个动作各自包**一整段扫描循环**，pipeline 那边只是一进一出两个节点。
# 为什么循环不能拆成节点（四条硬原因：白字掩码、一屏多目标、「画面静止」判据、
# 跨屏去重与计数），写在 cr_daily 的模块文档串里，别在这里重复。


@AgentServer.custom_action("CR.ClaimShopFree")
class ClaimShopFree(CustomAction):
    """商店：领每日免费项。"""

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        n = _daily(st).claim_shop_free(MaaDriver(context, st.dry))
        _log("商店免费项：本次领到 %d 处" % n)
        # ⚠️ 一个都没领到**也算成功**：今天可能本来就领完了（第一屏就是「已收集！」），
        #    那是正常收工不是失败。真正的失败（导航不到商店页）在 cr_daily 里已经
        #    单独打了 ⚠️ 日志，靠它排查就够，不必让框架把任务标红。
        return True


@AgentServer.custom_action("CR.ClanDonate")
class ClanDonate(CustomAction):
    """部落：把聊天里能捐的请求捐掉。"""

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        n = _daily(st).clan_donate(MaaDriver(context, st.dry), st.donate_rounds)
        _log("部落捐赠：本次捐出 %d 次" % n)
        return True


def _restart_game(drv):
    """重启游戏：force-stop 再拉起来。

    为什么用重启而不是按返回键（用户明确要求「超过十秒认不出来重启游戏」）：
    旧版实测**返回键会弹出游戏自己的「要退出《部落冲突：皇室战争》吗？」对话框**，
    于是界面上又多一个没人处理的弹窗，再按返回键只会更乱 —— 越「恢复」越乱。
    force-stop 是干净且确定的动作。
    """
    _log("重启游戏：force-stop -> 重新拉起")
    try:
        drv.stop_app()
    except Exception as exc:
        _log("  force-stop 失败：%s（还是尝试重新拉起）" % exc)
    time.sleep(3)
    drv.start_app()
    time.sleep(3)


@AgentServer.custom_action("CR.UnknownRecover")
class UnknownRecover(CustomAction):
    """「未知界面」的三段式自愈 —— 按**代价从低到高**依次尝试。

        ① 底部导航条还在 -> 点「对战」回主界面（子页面卡住的正解，最便宜）
        ② 没有导航条     -> 当全屏弹层处理：点底部确认按钮 / 屏幕中心推进
        ③ 认不出来 **且画面也定格了**够久 -> 重启游戏（最贵但最确定）

    为什么整段留在一个动作里而不是拆成三个 pipeline 分支：
    这三段是**互斥的 if/elif**，且各自带计数器（试满几次就降级）。
    拆成分支要靠 3~4 个自定义识别去表达「该轮到哪一段了」，
    计数器还得在 Agent 侧另存一份 —— 拆完更难读，不划算。
    """

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        frame = context.tasker.controller.cached_image
        drv = MaaDriver(context, st.dry)

        st.tick_unknown()
        st.stuck.feed(frame, True)
        waited = st.stuck.unknown_secs

        # ① 首选：先看底部导航条还在不在。
        #    在  => 这是个主标签页（商店/社交/卡牌/战绩），点「对战」就能回主界面。
        #           这才是「卡在子页面」的正解 —— 比盲目点屏幕安全得多
        #           （旧版实测：盲目点会在商店页反复戳底部商店图标）。
        if st.home_tries < C.HOME_MAX_TRIES and st.nav.nav_visible(frame):
            st.home_tries += 1
            _log("界面未知，但底部导航还在（多半是商店/社交这类子页）"
                 "-> 点「对战」回主界面（第 %d/%d 次）"
                 % (st.home_tries, C.HOME_MAX_TRIES))
            st.nav.go_main(drv)
            return True

        # ② 认不出来的界面，当「全屏弹层」处理：每点一次换一屏。
        #    严格限次，免得在真卡住时乱点。
        if st.overlay_taps < C.OVERLAY_MAX_TAPS:
            st.overlay_taps += 1
            target = find_bottom_button(frame) or C.CENTER_TAP
            _log("界面未知（%.0fs）-> 按全屏弹层处理，点 %s（第 %d/%d 次）"
                 % (waited, target, st.overlay_taps, C.OVERLAY_MAX_TAPS))
            drv.tap(*target)
            return True

        # ③ 认不出来 + 画面也定格了够久 -> 判定真卡住，重启游戏（最贵但最确定）
        if st.stuck.stuck:
            if st.game_restarts >= C.GAME_MAX_RESTARTS:
                _log("未知界面反复出现、已经重启 %d 次游戏，停止以免乱点" % st.game_restarts)
                context.tasker.post_stop()
                return False
            st.game_restarts += 1
            _log("-> 重启游戏（第 %d/%d 次）" % (st.game_restarts, C.GAME_MAX_RESTARTS))
            _restart_game(drv)
            st.home_tries = st.overlay_taps = 0
            st.stuck.reset()
            return True

        if waited > C.UNKNOWN_GIVEUP_SECS:
            _log("未知界面持续超过 %.0f 秒，停止以免乱点" % C.UNKNOWN_GIVEUP_SECS)
            context.tasker.post_stop()
            return False

        return True


@AgentServer.custom_action("CR.Boot")
class Boot(CustomAction):
    """任务开头的环境检查：屏要亮着，游戏要在前台。

    三件事（对应旧版 startup.bring_up 的职责）：

      ① **屏幕常亮**。模拟器闲置一会儿会自动熄屏，这时 screencap 拿到的帧几乎全黑，
         **所有模板匹配都变成 0.00** —— 看起来像「模板全坏了/路径不对」，
         是旧版踩过的最隐蔽的坑之一。
      ② **把游戏调到前台**，并**等到它真的出现在前台**再往下走。
         不能只喊一声就完事：游戏冷启动要十几秒，这段时间里抓到的全是启动画面，
         主循环会把它当「未知界面」去乱点。
      ③ **分界线在「前台是不是游戏」，不在「画面认不认得出来」**。
         前台不是游戏就停下报错，**绝不在模拟器桌面上乱点**。

    返回 False 时动作视为失败，next 链会断在这里（本节点不设 on_error）——
    这正是我们要的「停下」。
    """

    def run(self, context, argv):
        st = _ST.ensure()
        _apply_param(st, argv)
        ctrl = context.tasker.controller

        # ① 屏幕常亮：模拟器恒为「充电中」，所以 stayon 一直有效
        try:
            ctrl.post_shell("svc power stayon true").wait()
        except Exception as exc:
            _log("  svc power stayon 失败（继续）：%s" % exc)

        if not st.dry:
            try:
                frame = ctrl.post_screencap().wait().get()
            except Exception as exc:
                _log("  抓帧失败：%s" % exc)
                frame = None
            if frame is not None and float(frame.mean()) < 20.0:
                _log("  屏幕是黑的，发 WAKEUP 唤醒")
                MaaDriver(context, False).key(224)      # KEYCODE_WAKEUP
                time.sleep(1.5)

        # 游戏装没装
        try:
            out = ctrl.post_shell("pm list packages %s" % C.CR_PKG).wait().get()
            if C.CR_PKG not in (out or ""):
                _log("⚠️ 这台设备上没装国服皇室战争（%s），停下" % C.CR_PKG)
                return False
        except Exception as exc:
            _log("  pm list packages 查询失败（继续）：%s" % exc)

        # ② 把游戏调到前台并等它就位
        pkg = _foreground_pkg(context)
        if pkg == C.CR_PKG:
            _log("皇室战争已经在前台")
        else:
            _log("正在把皇室战争调到前台 ...（当前前台 %s）" % pkg)
            ctrl.post_start_app(C.CR_PKG).wait()
            deadline = time.time() + C.GAME_FRONT_WAIT
            while time.time() < deadline:
                time.sleep(3)
                pkg = _foreground_pkg(context)
                if pkg == C.CR_PKG:
                    _log("皇室战争已到前台")
                    break

        # ③ 分界线：前台不是游戏就停下，绝不在别的地方乱点
        if _foreground_pkg(context) != C.CR_PKG:
            _log("⚠️ 等不到皇室战争到前台（当前 %s）—— 停下，不在别的界面上乱点"
                 % _foreground_pkg(context))
            return False

        _log("环境检查完成（%s）" % ("演练模式" if st.dry else "正常模式"))
        return True
