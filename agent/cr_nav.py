# -*- coding: utf-8 -*-
"""底部导航：靠**模板匹配**找图标再点，以及「回主界面」这一个动作。

为什么要单独抽出来：
  · 底部导航的图标会**整体位移**（选中项加宽，把其它图标往右挤；
    实测收藏从 x176 挪到 x290），所以**绝不能写死坐标**；
  · 「回主界面」在对战任务和日常任务里都要用，抄两份迟早会不一致。

设计：查询方法（find / nav_visible）**只吃帧**，动作方法（goto）吃一个 driver。
这样 nav 既能实机跑，也能拿存下来的帧做离线自检 —— 不直接依赖框架。

⚠️ **绝不按返回键兜底**：实测返回键会弹出游戏自己的
   「要退出《部落冲突：皇室战争》吗？」对话框，界面上又多一个没人处理的弹窗，
   越「恢复」越乱。要重置就用 force-stop 重启游戏。
"""

from __future__ import annotations

import time

import cv2
import numpy as np

import cr_config as C


class Nav:
    def __init__(self, tpl, confirm_tap=None, log=print):
        """tpl: cr_vision.Templates 实例（取 .nav）
        confirm_tap: 可选回调 `frame -> (x, y) | None`，用来找「底部确认按钮」。

        为什么要 confirm_tap（用户要求「导航栏变成确认也要兼容」）：
        有些页面**底部导航栏的位置被换成了一个「确定」按钮** ——
        部落聊天页（"请求换卡 / 友谊战 + 确定"输入条）、训练日预览页都是这样。
        这些页面点「确定」才是出路，不能判成「找不到导航就卡住」。
        传 `cr_vision.find_bottom_button` 进来即可（nav 不直接依赖 vision，保持分层干净）。
        """
        self.tpls = tpl.nav
        self.confirm_tap = confirm_tap
        self.log = log

    def names(self):
        return sorted(self.tpls)

    # ---------------- 查询（纯函数，只吃帧）----------------

    def find(self, frame, name):
        """在底部导航带里找某个图标，返回 (x, y, 匹配度) 或 None。

        ⚠️ **先把画面裁到导航带再匹配**，不要「先全图取最佳再看在不在带内」——
        后者只要画面别处有相似图案，全局最佳就落在带外、整个模板被丢掉，
        日志报「没找到 (0.00)」，而图标明明就在那儿（旧版实测在商店页因此
        丢掉社交图标，导致整条流程静默跑错目标）。
        """
        ts = self.tpls.get(name) or []
        if not ts:
            return None
        y0, y1 = C.NAV_BAND
        band = frame[y0:y1, :]
        if band.size == 0:
            return None
        best = None
        for t in ts:
            if t.shape[0] > band.shape[0] or t.shape[1] > band.shape[1]:
                continue
            res = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if best is None or mx > best[0]:
                best = (float(mx), int(loc[0] + t.shape[1] // 2),
                        int(y0 + loc[1] + t.shape[0] // 2))
        if best is None or best[0] < C.NAV_MATCH_THRESHOLD:
            return None
        return best[1], best[2], best[0]

    def nav_visible(self, frame):
        """底部导航条**在不在**（不看具体是哪个图标，任何一个能对上就算在）。

        ⚠️ 实测：**选中的那个标签，图标会加宽并位移**（主界面上「对战」就是选中态，
        两边还多出 ◀▶ 箭头），跟未选中态的模板**根本对不上**。
        所以「找不到图标」有两种完全不同的含义，必须区分开：
          · 导航条在、目标对不上 -> 目标就是当前选中页，**已经到达**
          · 连导航条都看不见     -> 全屏弹层 / 被输入条盖住
        """
        for name in self.tpls:
            if self.find(frame, name) is not None:
                return True
        return False

    # ---------------- 动作（吃 driver）----------------

    def tap(self, drv, name, wait=2.5):
        """找得到就点，返回是否点了。找不到返回 False，**绝不瞎点**。"""
        hit = self.find(drv.shot(), name)
        if hit is None:
            self.log("底部导航「%s」没找到，跳过" % name)
            return False
        x, y, score = hit
        self.log("点底部导航「%s」(%d,%d) 匹配度 %.2f" % (name, x, y, score))
        drv.tap(x, y)
        time.sleep(wait)
        return True

    def goto(self, drv, name, tries=3):
        """★容错版导航★：去某个底部标签页。返回是否成功（或本来就在）。

        四种情况分别处理（⚠️ 第 2、3 种最容易做错）：

          1. 找到目标图标            -> 点它，成功；
          2. **导航条在、目标对不上** -> 目标**就是当前选中的那一页**（选中态图标
             加宽位移），已经在这一页了，**直接算到达**。
             这里要是「找不到就按返回键」，会把好好的页面按走 ——
             旧版实测就被按进了「第1个训练日」预览页。
          3. **导航条位置被换成了「确定」按钮** -> 点它往下走。
             部落聊天页就是「输入条 + 确定」盖住了导航栏，点确定能退出聊天、
             露出导航栏（用户明确要求兼容这种）。
          4. 既没导航条也没确认按钮 -> 放弃（返回 False），交给上层决定要不要重启游戏。
        """
        for i in range(tries + 1):
            f = drv.shot()
            hit = self.find(f, name)
            if hit is not None:
                self.log("点底部导航「%s」(%d,%d) 匹配度 %.2f" % (name, hit[0], hit[1], hit[2]))
                drv.tap(hit[0], hit[1])
                time.sleep(2.5)
                return True

            if self.nav_visible(f):
                self.log("导航条在，但「%s」对不上模板 —— 多半已经就在这一页（选中态），算到达"
                         % name)
                return True

            btn = self.confirm_tap(f) if self.confirm_tap else None
            if btn is not None:
                self.log("  底部没有导航栏，但有个「确定」按钮 %s -> 点它往下走（%d/%d）"
                         % ((btn[0], btn[1]), i + 1, tries))
                drv.tap(btn[0], btn[1])
                time.sleep(2.5)
                continue

            self.log("  看不见底部导航条、也没有「确定」按钮，放弃这条路径")
            break
        self.log("  没能导航到「%s」" % name)
        return False

    def go_main(self, drv, tries=2):
        """回主界面（点底部导航「对战」）。返回是否成功（或本来就在）。"""
        return self.goto(drv, C.NAV_HOME, tries=tries)
