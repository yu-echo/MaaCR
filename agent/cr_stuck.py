# -*- coding: utf-8 -*-
"""卡住检测：判断「是不是真卡住了」。

判据是**两个条件的与**：**认不出来** 且 **画面也定格了**，持续够久。

⚠️「画面也定格」这个附加条件很关键（旧版实测，别删）：
   游戏的**加载动画**、**开宝箱动画**都属于「认不出来但画面一直在变」，
   那是正常的，不能当卡住 —— 否则冷启动（实测要 13 秒）会被无限重启。

只有「认不出来 + 画面也不动了」才是真卡住。这时最干净的做法是**重启游戏**，
而不是接着盲点屏幕或按返回键（实测按返回键会弹出「要退出游戏吗？」对话框）。

移植说明：
  旧版由 bot.py 主循环每轮 `watch.feed(frame, state == UNKNOWN)` 显式喂帧。
  新框架里主循环变成了 pipeline 的 next 分发，没有「每轮必过」的钩子，
  所以这里改成**自动判定重置**：两轮 unknown 之间隔了超过 UNKNOWN_RESET_GAP 秒
  就认为中途认出来过（因为认出来会走一段 post_delay 再做下一轮），计数归零。
  ⇒ 这是本次移植里语义有一处近似的地方，需要实机验证（见 docs/zh_cn/develop/migration.md）。
"""

from __future__ import annotations

import time

import numpy as np

import cr_config as C


class StuckWatcher:
    def __init__(self, after=None, diff=None, reset_gap=None):
        self.after = C.GAME_RESTART_AFTER if after is None else after
        self.diff = C.STUCK_FRAME_DIFF if diff is None else diff
        self.reset_gap = C.UNKNOWN_RESET_GAP if reset_gap is None else reset_gap
        self.reset()

    def reset(self):
        self.unknown_secs = 0.0
        self.still_secs = 0.0
        self._unknown_since = None
        self._still_since = None
        self._last_tick = None
        self._prev = None

    def feed(self, frame, unknown=True):
        """喂一帧，更新 unknown_secs / still_secs。"""
        now = time.time()

        # 距上一轮 unknown 隔太久 -> 中间多半认出来过，重置
        if self._last_tick is not None and now - self._last_tick > self.reset_gap:
            self.reset()
        self._last_tick = now

        if not unknown:
            self.reset()
            return

        if self._unknown_since is None:
            self._unknown_since = now

        moved = 999.0
        if self._prev is not None and self._prev.shape == frame.shape:
            # astype(int16)：uint8 直接相减会**下溢回绕**，差值全乱
            moved = float(np.abs(frame.astype(np.int16) - self._prev.astype(np.int16)).mean())
        self._prev = frame

        if moved >= self.diff:
            self._still_since = None
        elif self._still_since is None:
            self._still_since = now

        self.unknown_secs = now - self._unknown_since
        self.still_secs = 0.0 if self._still_since is None else now - self._still_since

    @property
    def stuck(self):
        return self.still_secs >= self.after


def frame_diff(prev, cur):
    """两帧的平均绝对差。滚动到底判据 / 点击前后是否变化都用它。

    ⚠️ astype(int16) 不能省：uint8 直接相减会下溢回绕。
    """
    if prev is None or cur is None or prev.shape != cur.shape:
        return 999.0
    return float(np.abs(cur.astype(np.int16) - prev.astype(np.int16)).mean())
