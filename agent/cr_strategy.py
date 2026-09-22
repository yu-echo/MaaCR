# -*- coding: utf-8 -*-
"""策略层：给定「手牌 + 圣水 + 敌方塔血量」，决定出哪张牌、丢到哪。

这个文件一般不用动 —— 要改策略请改 cr_config.py。
放在这里的是「怎么算」，cr_config.py 里的是「算成什么」。

移植说明：本模块**几乎零改动**从旧版 crbot/strategy.py 搬过来。
能这么省事是因为旧版把「决定」集中在 strategy.py、把「数值」集中在 config.py，
`choose(scene)` 本身是纯函数（输入识别结果、输出决策），不碰设备也不碰文件。

当前策略（推三冠向）：
  一路主攻。没破塔 -> 在本路桥头放（己方半场，推过去打塔）；
  破了塔   -> 落点切到敌方半场深位，继续往国王塔方向压，直到三冠。
"""

import random

import cr_config as C


def _cost(cid):
    return C.CARDS.get(cid, {}).get("cost", C.UNKNOWN_COST)


def _lane_broken(scene, lane):
    """这一路的敌方公主塔是否已经被打掉。血条消失/极窄 => 破了。"""
    hp = (scene.tower_hp or {}).get(lane, 1.0)
    return hp < C.TOWER_BROKEN_FRAC


def _variants(cid):
    """同一张牌可能有「普通形态 + 精英形态」两套素材，返回全部相关 id。

    这样 cr_config.PRIORITY 里只需要写普通形态那一个 id，
    精英形态会自动跟着一起找 —— 免得换卡组时漏掉一整套图。
    """
    out = [cid]
    for k, v in C.CARDS.items():
        if v.get("same_as") == cid:
            out.append(k)
    return out


def _spot_of(cid, scene):
    """选落点。

    优先级：
      1) SPOT_OVERRIDE 里给这张牌单独指定的
      2) 主攻那一路的塔已破 -> 用敌方半场深位（这是拿三冠的关键）
      3) 否则用本路桥头（己方半场）
    """
    lane = C.MAIN_LANE
    if cid in C.SPOT_OVERRIDE:
        name = C.SPOT_OVERRIDE[cid]
    elif _lane_broken(scene, lane):
        name = C.DEEP_SPOT.get(lane, C.LANE_SPOT[lane])
    else:
        name = C.LANE_SPOT[lane]

    x, y = C.SPOTS[name]
    jx, jy = C.SPOT_JITTER
    return name, (x + random.randint(-jx, jx), y + random.randint(-jy, jy))


def choose(scene, min_elixir=None):
    """决定这一手出什么。

    返回 (slot, cid, spot_name, (x, y))；没有可出的牌就返回 None。
    """
    if not scene.hand:
        return None

    floor = C.MIN_ELIXIR if min_elixir is None else int(min_elixir)
    by_id = {h.cid: h for h in scene.hand}

    # 1) 按 PRIORITY 顺序，找第一张「在手 + 圣水够」的
    #    同一张牌的两个形态（普通/精英）任一在手都算命中
    for cid in C.PRIORITY:
        hit = next((by_id[v] for v in _variants(cid) if v in by_id), None)
        if hit is None or scene.elixir < max(floor, _cost(hit.cid)):
            continue
        name, xy = _spot_of(hit.cid, scene)
        return hit.slot, hit.cid, name, xy

    # 2) 兜底
    if C.FALLBACK == "random":
        ok = [h for h in scene.hand
              if scene.elixir >= max(floor, _cost(h.cid))]
        if ok:
            h = random.choice(ok)
            name, xy = _spot_of(h.cid, scene)
            return h.slot, h.cid, name, xy

    return None


def describe(cid):
    meta = C.CARDS.get(cid, {})
    return "%s(%s费)" % (meta.get("label", cid), meta.get("cost", "?"))
