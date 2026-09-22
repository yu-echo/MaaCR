# -*- coding: utf-8 -*-
"""日常任务：商店免费项 + 部落捐赠。

从旧版 `daily.py` 搬过来。**判据、阈值、动作顺序一个都没改** —— 它们是实测出来的，
每条都能在旧版注释里找到「踩过一次才写成这样」的记录。改的只有三处：

  · 设备操作从 `self.d.tap/swipe` 换成传进来的 driver（沿用 `cr_nav` 的约定：
    查询吃帧、动作吃 driver，于是本模块能拿存下来的帧做离线自检）；
  · 启动那一段（旧版 `startup.bring_up`：开模拟器 / 等游戏就位）由 pipeline 的
    `CR.Boot` 节点负责，本模块不管；
  · 「收尾回主界面」从 `main()` 里提到 pipeline 做成 `日常收尾回主界面` 节点 ——
    它是界面级动作，放在流程图上能一眼看见，比埋在代码末尾好。

为什么整段扫描循环留在 Agent，不拆成 pipeline 节点（四条都是硬伤，逐条对照
`docs/zh_cn/develop/migration.md` 第四节）：

  1. 「免费」「已收集！」「捐赠」都要**白字掩码**匹配：画面与模板**都要**先二值化成
     「是不是白像素」再比。框架的 `TemplateMatch` 只有 `green_mask`，它只盖**模板侧**、
     且官方文档明确写着「应仅遮盖干扰区域，避免过度涂抹导致主体边缘特征丢失」——
     而我们的做法恰恰是「除了字，其余全盖掉」，正撞在那句警告上。
  2. 商店一屏上要**一次领掉所有**可见免费项，而 pipeline 一个节点只消费一个识别框。
  3. 「滑到底」的判据是「**画面还在不在动**」，而 `wait_freezes` 是「**等**它不动」，
     语义正好相反。
  4. 每屏的去重集合（`seen`）、连续空屏计数都是**跨屏状态**，pipeline 里没有地方安放。

于是分工是：pipeline 负责「进任务 / 收尾」这类界面级动作，本模块负责一段连续的扫描循环。
"""

from __future__ import annotations

import time

import cv2
import numpy as np

import cr_config as C
from cr_vision import find_bottom_button, find_white_text, frac_in, sat_val_of

# 商店内容区（分类行与子标签行是固定的，不随内容滚动，所以排除掉它们）
_SHOP_ROI = (0, C.SHOP_GRID_TOP, C.FRAME_W, C.SHOP_GRID_BOTTOM)
# 部落聊天内容区（排除顶栏与底部输入条）
_CLAN_ROI = (0, C.CLAN_CHAT_TOP, C.FRAME_W, C.CLAN_CHAT_BOTTOM)


class Daily:
    def __init__(self, tpl, nav, log=print, dry=False, bottom=None):
        """tpl: cr_vision.Templates；nav: cr_nav.Nav；bottom: 可选，找「底部确认按钮」的回调。

        bottom 默认用 cr_vision.find_bottom_button（本模块的默认参数不能写函数，
        所以在这里兜一下）。
        """
        self.tpl = tpl
        self.nav = nav
        self.log = log
        self.dry = dry
        self.bottom = bottom or find_bottom_button

    # ==================== 通用小动作 ====================

    def tap_bottom_confirm(self, drv):
        """屏幕底部有蓝色确认按钮就点它（领奖 / 退出聊天都用得上）。返回是否点了。

        ⚠️ 只在**该退出的时候**调它一次。各界面「确定」位置都不一样，所以按颜色
        「找底部最大的蓝色块」而不是写死坐标（见 cr_vision.find_bottom_button）。
        """
        btn = self.bottom(drv.shot())
        if btn is None:
            return False
        self.log("  点底部确认 %s" % (btn,))
        drv.tap(*btn)
        time.sleep(2.0)
        return True

    # ==================== 商店：免费项 / 已收集 ====================

    def free_card_spots(self, frame):
        """找「免费」价格标签，返回**卡片身体**的可点坐标列表。

        ⚠️ 判据是「免费」这两个**字**，不是颜色（用户明确说过：免费项不一定是绿卡，
        但价格那里一定写着「免费」）。先后用「圣水条洋红」和「绿底卡片」当判据都误判过。

        返回值故意从「文字」挪到「卡身」（往上 `FREE_LABEL_DY`）：文字在卡片底部，
        直接点文字容易点到卡片下沿或网格缝隙 —— 「点了没反应」就是这么来的。
        """
        hits = find_white_text(frame, self.tpl.shop["free_label"], roi=_SHOP_ROI,
                               threshold=C.FREE_LABEL_THRESHOLD,
                               scales=C.FREE_LABEL_SCALES, nms_dist=C.NMS_DIST)
        return [(x, y + C.FREE_LABEL_DY) for x, y, _ in hits]

    def collected_spots(self, frame):
        """找「已收集！」标签，返回文字中心坐标列表（不偏移 —— 它只用来判「要不要停」）。

        用户明确要求：**看到「已收集」就可以停止扫描**。商店列表实测有 37~55 屏，
        全翻完纯属白跑。
        """
        return [(x, y) for x, y, _ in find_white_text(
            frame, self.tpl.shop["collected_label"], roi=_SHOP_ROI,
            threshold=C.COLLECTED_LABEL_THRESHOLD, nms_dist=C.NMS_DIST)]

    def free_confirm_spot(self, frame):
        """弹窗里那个绿色「免费！」按钮，返回 (x, y, 匹配度)；没有就返回 None。

        这里用**原色**匹配、不走白字掩码，是有意的：弹窗是固定的深色面板，底色不会变，
        原色匹配在 0.85 阈值上很稳；而白字掩码会把绿底一起丢掉，反而少了一半判据。
        """
        tpl = self.tpl.shop["free_confirm"]
        res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx < C.SHOP_FREE_CONFIRM_THRESHOLD:
            return None
        return (int(loc[0] + tpl.shape[1] // 2), int(loc[1] + tpl.shape[0] // 2), float(mx))

    def tap_free_confirm(self, drv):
        """弹窗里的绿色「免费！」按钮，**确认存在**才点。返回是否点了。

        为什么非要先确认：点完卡片到弹窗出现之间有 1~2 秒。这期间如果因为卡了 / 点偏了
        没弹出窗，盲点固定坐标会按到隔壁那张「500 金币」的卡上 —— 那是要花资源的。
        所以坚持「先认出再点」。
        """
        hit = self.free_confirm_spot(drv.shot())
        if hit is None:
            self.log("  没找到「免费！」确认按钮（要 %.2f 以上）"
                     % C.SHOP_FREE_CONFIRM_THRESHOLD)
            return False
        x, y, score = hit
        self.log("  点「免费！」确认按钮 (%d,%d) 匹配度 %.2f" % (x, y, score))
        drv.tap(x, y)
        return True

    def claim_shop_free(self, drv):
        """商店：把今天还没领的免费项领掉，返回领到的处数。

        大流程（顺序都是踩出来的，别调）：

          ① **先看当前屏，再导航**。反过来的话，点底部「商店」会把页面滚回顶部，
             正好把屏幕上的免费项滑走，再检查就什么都找不到；
          ② 逐屏：领掉本屏所有「免费」-> 再看有没有「已收集！」-> 没有就慢滑一屏。
        """
        self.log("=== 商店：领免费项 ===")
        claimed = 0
        seen = set()

        def claim_visible(f, tag):
            """把当前画面上能看到的「免费」都领掉，返回本轮真领到几个。

            `seen` 是**去重集合**：一张卡点了没弹窗时，不记下它就会在同一屏上反复点
            同一张卡，永远出不去（这正是「点了没反应」那一类失败的后果）。
            """
            fresh = [(x, y) for (x, y) in self.free_card_spots(f)
                     if all(abs(x - sx) > C.NMS_DIST or abs(y - sy) > C.NMS_DIST
                            for sx, sy in seen)]
            if not fresh:
                return 0
            self.log("%s 发现 %d 处「免费」 %s" % (tag, len(fresh), fresh[:3]))
            n = 0
            for x, y in fresh:
                seen.add((x, y))
                self.log("  点卡身领 (%d,%d)" % (x, y))
                if self.dry:
                    n += 1
                    continue
                drv.tap(x, y)
                time.sleep(C.SHOP_CARD_WAIT)
                if self.tap_free_confirm(drv):
                    n += 1
                    time.sleep(C.SHOP_CLAIM_WAIT)   # 等宝石飞入 + 顶部横幅走完
                else:
                    # 没弹窗：可能这张已经被领过了（卡片会变成「已收集！」，
                    # 那时「免费」两字已经没了，本来就不会再命中），也可能只是点偏了。
                    # 总之**不算领到**，顺手把可能的弹窗收掉。
                    self.log("  这张卡没弹出「免费！」确认窗，跳过")
                    self.tap_bottom_confirm(drv)
                    time.sleep(1.0)
            return n

        def saw_collected(f, tag):
            """看到「已收集！」= 今天的免费项已经领过了 -> 该停了。

            ⚠️ 调用顺序必须是**先尝试领、再看已收集**：万一同屏既有没领的免费项、
            又有已收集的卡，先领掉再停才不会漏。
            """
            hits = self.collected_spots(f)
            if hits:
                self.log("%s 看到「已收集！」%s -> 今天的免费项已经领过了，停止扫描"
                         % (tag, hits[:2]))
            return bool(hits)

        first = drv.shot()
        claimed += claim_visible(first, "当前屏")
        if saw_collected(first, "当前屏"):
            self.log("商店完成：共领 %d 处（当前屏就是已收集状态，直接停）" % claimed)
            return claimed

        # 容错版导航：底部导航被弹层 / 输入条盖住时会点「确定」清理再试，
        # 不会因为一次没匹配到就整条流程退出。
        if not self.nav.goto(drv, "shop"):
            self.log("⚠️ 没能导航到商店页，结束商店流程")
            return claimed

        # 回到「礼物 -> 超值推荐」的内容顶部，再从那里慢速下滑。
        # 商店顶部两行导航（分类图标行 / 子标签行）**固定不随内容滚动**，所以这两下
        # 坐标可以写死；坐标本身是实测的 —— 子标签是 y≈272，不是 232，
        # 232 落在两行中间的空隙上，点了等于没点（这个坑踩过）。
        self.log("点「礼物」分类图标 %s 回到特惠" % (C.SHOP_CAT_GIFT,))
        drv.tap(*C.SHOP_CAT_GIFT)
        time.sleep(2.0)
        self.log("点「超值推荐」标签 %s 回到内容顶部" % (C.SHOP_TAB_ULTRA,))
        drv.tap(*C.SHOP_TAB_ULTRA)
        time.sleep(3.0)

        idle = 0
        stuck = 0
        step = -1                      # 万一 SHOP_SCROLL_STEPS 配成 0，日志也能打「共滑 0 屏」
        reason = "跑满 %d 屏上限" % C.SHOP_SCROLL_STEPS
        prev = drv.shot()
        for step in range(C.SHOP_SCROLL_STEPS):
            f = drv.shot()
            # 「到底」判据：画面还在不在动（不是猜屏数）。
            # 实测滑到底后帧间平均差从 ~45 掉到 ~0.2，区分度极大。
            # ⚠️ 用 int16 相减：uint8 相减会回绕（255-0 变成 1），差值的量级就废了。
            moved = float(np.abs(f.astype(np.int16) - prev.astype(np.int16)).mean())
            prev = f
            if moved < C.SCROLL_STUCK_DIFF:
                stuck += 1
                if stuck >= C.SCROLL_STUCK_LIMIT:
                    self.log("第 %d 屏画面已静止（差 %.2f），判定到底，结束"
                             % (step + 1, moved))
                    reason = "滑到底"
                    break
            else:
                stuck = 0

            got = claim_visible(f, "第 %d 屏" % (step + 1))
            claimed += got
            if got:
                idle = 0
            else:
                idle += 1
                if step % 3 == 0:
                    self.log("第 %d 屏没有「免费」（连续 %d 屏）" % (step + 1, idle))
                if idle >= C.SHOP_IDLE_LIMIT:
                    self.log("连续 %d 屏没找到「免费」，结束商店流程" % idle)
                    reason = "连续 %d 屏没找到" % idle
                    break

            # 领完之后再看「已收集」—— 看到就说明今天这条已经完事了，停止扫描。
            # 放在 claim_visible 之后，是为了不跳过同屏还没领的免费项。
            if saw_collected(f, "第 %d 屏" % (step + 1)):
                reason = "看到「已收集」"
                break

            x1, y1, x2, y2, ms = C.SHOP_SCROLL
            drv.swipe(x1, y1, x2, y2, ms)
            time.sleep(C.SHOP_SCROLL_WAIT)

        self.log("商店完成：共领 %d 处（共滑 %d 屏，结束原因：%s）" % (claimed, step + 1, reason))
        return claimed

    # ==================== 部落：捐赠 ====================

    def donate_buttons(self, frame):
        """在部落聊天区里找出**所有**「捐赠」按钮，并标出每个能不能捐。

        返回 [(x, y, 可捐?, 匹配度, 绿色占比), ...]，按画面从上到下。

        ⚠️ 三个关键点，都是实测出来的（用户报的 bug）：

        1) **必须找全部，不能只取评分最高的那一个。**
           聊天里可能同时有「自己发起的请求」（按钮灰的、捐不了）和「别人的请求」
           （按钮**亮绿色**、可以捐）。原实现只取最优，正好撞上灰的那个 ->
           判「不可捐」直接收工 -> 一个都没捐出去。

        2) **匹配必须忽略按钮底色。**
           模板是从灰按钮上裁的，绿按钮底色完全不同：拿整按钮做原色匹配，
           绿按钮只有 **0.822**（低于 0.85 阈值，会被直接丢掉）。改用白字掩码后，
           「捐赠」两个字在任何底色上都是白的：同一个位置灰 **0.997** / 绿 **0.898**，
           两个都稳稳命中。

        3) **可捐判据是「按钮底色的饱和度」，不是绿色占比。**
           实测同一帧里两个按钮：自己发起的（捐不了）底色纯灰 S=0.0，
           别人的（可捐）亮绿 S=142.3，区分度极大。绿色占比只写进日志方便对照。
        """
        tpl_btn = self.tpl.clan["donate_btn"]      # 整按钮：只用来量尺寸
        tpl_lab = self.tpl.clan["donate_label"]    # 只有「捐赠」两字：真正拿去匹配的
        bh, bw = tpl_btn.shape[:2]

        hits = find_white_text(frame, tpl_lab, roi=_CLAN_ROI,
                               threshold=C.DONATE_BTN_THRESHOLD,
                               nms_dist=C.DONATE_NMS_DIST)

        out = []
        for cx, cy, score in sorted(hits, key=lambda h: h[1]):      # 从上到下
            # 由文字中心反推按钮框（文字在按钮里居中）
            x, y = cx - bw // 2, cy - bh // 2
            # 取按钮**内侧**（避开圆角描边）算底色
            box = (max(x + 12, 0), max(y + 9, 0), bw - 24, bh - 18)
            if box[2] <= 0 or box[3] <= 0:
                continue
            sat, _ = sat_val_of(frame, box)
            green = frac_in(frame, box, C.H_GREEN)
            out.append((cx, cy, sat > C.DONATE_LIT_SAT, round(score, 3), round(green, 2)))
        return out

    def clan_donate(self, drv, rounds):
        """部落：把聊天里能捐的请求捐掉，返回捐了几次。

        ⚠️ 不能假定「一定要先从底部导航进社交」：在部落聊天子页里，底部导航条被
        输入条（请求换卡 / 友谊战…）和「确定」盖住，导航模板匹配只有 0.00。
        -> 用容错版 goto（找不到会点「确定」清理界面再试），全部失败才退回「直接看当前屏」。
        """
        self.log("=== 部落：捐赠（上限 %d 次）===" % rounds)
        if self.dry:
            self.log("  （演练模式：导航这几下也不会点，仍停在原页面）")
        if self.nav.goto(drv, "social"):
            time.sleep(1.0)
            self.log("点「聊天」入口 %s" % (C.CLAN_CHAT_TAP,))
            drv.tap(*C.CLAN_CHAT_TAP)
            time.sleep(3.0)
        else:
            self.log("导航不到社交页，直接在当前屏找「捐赠」按钮")

        done = 0
        for look in range(C.DONATE_LOOK_SCREENS + 1):
            hits = self.donate_buttons(drv.shot())
            lit = [h for h in hits if h[2]]
            self.log("第 %d 屏：看到 %d 个「捐赠」按钮，其中可捐(亮绿) %d 个、捐不了 %d 个"
                     % (look + 1, len(hits), len(lit), len(hits) - len(lit)))

            for (x, y, _lit, score, green) in lit:
                if done >= rounds:
                    break
                self.log("  点可捐按钮 (%d,%d)（匹配 %.2f / 绿色占比 %.2f）-> 直接捐出"
                         % (x, y, score, green))
                drv.tap(x, y)
                time.sleep(C.DONATE_TAP_WAIT)   # 等捐赠动画走完、按钮变灰
                done += 1

            if done >= rounds:
                self.log("已捐到设定上限 %d 次，停" % rounds)
                break
            if look < C.DONATE_LOOK_SCREENS:
                self.log("  这一屏没有别的可捐请求了，往上翻一层找（%d/%d）"
                         % (look + 1, C.DONATE_LOOK_SCREENS))
                drv.swipe(360, 300, 360, 800, 800)   # 往下拖 = 聊天记录往上翻
                time.sleep(1.5)

        # 退出：点底部「确定」（用户明确说过「捐完点确认退出」）。
        # ⚠️ 只在**全部捐完之后**点这一次 —— 点绿色按钮就已经捐出了，
        #    每捐一次就点「确定」等于捐完一次就退出聊天，永远捐不了第二次。
        if self.tap_bottom_confirm(drv):
            self.log("已点「确定」退出捐赠")
        self.log("捐赠完成：共捐 %d 次" % done)
        return done
