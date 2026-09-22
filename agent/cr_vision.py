# -*- coding: utf-8 -*-
"""视觉层：只读画面，判断当前在哪个界面、读圣水、认手牌、量塔血、数皇冠。

与旧版（crbot/vision.py）的区别：
  · 输入从「自己截图的 Device」变成「外部传进来的 frame（BGR ndarray）」——
    截图现在归 MaaFramework 管，识别层不该碰设备，这一层因此变成纯函数集合；
  · 锚点匹配那部分**搬去了 pipeline**（TemplateMatch/ColorMatch 能表达），
    这里只留框架表达不了的**几何计算**。

保留的原则（旧版踩出来的，别改）：
  · 只读屏幕，不点任何东西 —— 出问题时才能一眼分清「是识别错了」还是「是点击错了」；
  · 三个量化指标都不用 OCR：「宽度就是数值」（圣水条最右点亮列 / 塔血条宽度）+ 金色色块计数。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

import cr_config as C

LOGIN = "login"
MAIN = "main"
MATCHING = "matching"
BATTLE = "battle"
RESULT = "result"
DECK = "deck"
CHEST = "chest"
UNKNOWN = "unknown"


# ==================== 基础工具 ====================

def frac_in(frame, box, hsv_range):
    """box 区域里落在色域内的像素占比。box 是 (x0,y0,x1,y1)。"""
    x0, y0, x1, y1 = box
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    lo, hi = hsv_range
    mask = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), lo, hi)
    return float(mask.mean()) / 255.0


def white_mask(img):
    """把图转成「白色像素掩码」——整个识别层最有用的一招。

    游戏 UI 文字都是「白字 + 深色描边」，**在任何底色上都是白的**。
    所以匹配前把画面和模板**都先转成白色掩码**再比，等于把背景整个忽略掉。

    实测收益（旧版记录）：
      · 商店「免费」/「已收集！」：正确位置 1.000，14 张对照截图次高分全部 < 0.60，零误报；
      · 部落「捐赠」按钮：灰按钮 0.997 / **绿按钮 0.898**。
        如果用原色整按钮模板，绿按钮只有 **0.822**，会被 0.85 阈值直接丢掉。

    ⚠️ 阈值必须够严（V≥225 且 S≤40）：宽松的「接近白就算」会把浅灰底（V≈195）
       整张卡算成白，掩码变成实心块，匹配就没意义了。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array(C.WHITE_TEXT_LO), np.array(C.WHITE_TEXT_HI))


def masks_are_blank(mask):
    """掩码几乎是空的 —— 拿它做匹配只会得到一堆假阳性，直接放弃。"""
    return int(mask.sum()) < 255 * 20


# ==================== 数据结构 ====================

@dataclass
class HandCard:
    slot: int
    cid: str
    score: float

    def __repr__(self):
        return "槽%d=%s(%.2f)" % (self.slot + 1, self.cid, self.score)


@dataclass
class Scene:
    state: str
    elixir: int
    elixir_frac: float
    hand: list = field(default_factory=list)
    tower_hp: dict = field(default_factory=dict)


# ==================== 模板加载 ====================

class Templates:
    """从 image/ 加载模板图。加载失败一律抛错，**不静默跳过** ——
    模板缺一张，对应的识别就会永远认不出来，这种错比崩溃更难查。"""

    SUBDIRS = ("cards", "anchors", "nav", "shop", "clan")

    def __init__(self, image_root=None):
        import cr_config

        self.root = image_root or cr_config.image_root()
        self.cards = {}
        for cid in C.CARDS:
            self.cards[cid] = self._load("cards", cid + ".png")

        self.anchors = {}
        for name in self._list("anchors"):
            self.anchors[name] = self._load("anchors", name + ".png")

        self.nav = {}
        for name in self._list("nav"):
            # 同一导航项可有多个状态模板：shop.png（未选中）/ shop__sel.png（选中态）
            self.nav.setdefault(name.split("__")[0], []).append(
                self._load("nav", name + ".png"))

        self.shop = {n: self._load("shop", n + ".png") for n in self._list("shop")}
        self.clan = {n: self._load("clan", n + ".png") for n in self._list("clan")}

    def _dir(self, sub):
        return self.root / sub

    def _list(self, sub):
        d = self._dir(sub)
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.png"))

    def _load(self, sub, filename):
        path = self._dir(sub) / filename
        img = cv2.imread(str(path))
        if img is None:
            raise FileNotFoundError("模板缺失或读不出来：%s" % path)
        return img

    def summary(self):
        return "cards=%d anchors=%d nav=%d shop=%d clan=%d" % (
            len(self.cards), len(self.anchors),
            sum(len(v) for v in self.nav.values()), len(self.shop), len(self.clan))


# ==================== 圣水 ====================

def read_elixir(frame):
    """用「洋红条从左边铺到哪」算圣水，返回 (圣水数, 占比, 左端是否连续亮)。

    两个关键点（都是实测踩出来的）：
    1) 白字（"10 最多:10"）会盖在条上打出空洞，所以取**最右侧被点亮的列**
       来算宽度，而不是数像素个数 —— 空洞不影响最右边界。
    2) 额外返回 left_lit：条子最左端是否也是洋红。圣水是从左往右铺的，
       所以对战中左端一定亮；别的界面（比如卡组页底部导航）虽然也有
       一片紫色，但左端不会连续亮 —— 用它把误判挡掉。
    """
    x0, y0, x1, y1 = C.ELIXIR_BAR
    band = frame[y0:y1 + 1, x0:x1 + 1]
    if band.size == 0:
        return 0, 0.0, False
    mask = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV), *C.H_MAGENTA)
    cols = (mask > 0).sum(axis=0)
    lit = cols >= 2
    idx = np.nonzero(lit)[0]
    if len(idx) == 0:
        return 0, 0.0, False
    frac = min(max((int(idx.max()) + 1) / float(mask.shape[1]), 0.0), 1.0)
    left_lit = bool(len(lit) >= 20 and lit[:20].all())
    return int(round(frac * C.ELIXIR_FULL)), frac, left_lit


# ==================== 手牌 ====================

def read_hand(frame, tpl):
    """在手牌栏区域里逐张模板匹配，每个槽位保留相似度最高的那张。

    为什么留在 Agent 而不是拆成 4 个 pipeline 识别节点：
    识别出「哪个槽是哪张牌」只解决一半问题 —— 出牌决策还需要**整体局面**
    （手牌里还有什么、圣水够不够、哪路塔破了）。拆成节点后框架只知道单槽结果，
    反而要多传状态。所以手牌 + 圣水 + 塔血 + 决策做成同一个原子决策。
    """
    x0, y0, x1, y1 = C.HAND_ROI
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    best = {}
    for cid, t in tpl.cards.items():
        th, tw = t.shape[:2]
        if th > roi.shape[0] or tw > roi.shape[1]:
            continue
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx < C.MATCH_THRESHOLD:
            continue
        cx = loc[0] + tw // 2 + x0
        cy = loc[1] + th // 2 + y0
        slot = slot_of(cx, cy)
        if slot is None:
            continue
        if slot not in best or mx > best[slot][1]:
            best[slot] = (cid, float(mx))
    return [HandCard(s, c, v) for s, (c, v) in sorted(best.items())]


def slot_of(cx, cy):
    """把命中中心吸附到最近的手牌槽。"""
    tol_x, tol_y = C.HAND_SLOT_TOL
    for i, (sx, sy) in enumerate(C.HAND_SLOTS):
        if abs(cx - sx) <= tol_x and abs(cy - sy) <= tol_y:
            return i
    return None


# ==================== 敌方塔血量 ====================

def read_enemy_towers(frame):
    """量敌方两座公主塔血条的宽度，换算成血量比例（0~1）。

    血条是粉色的，**宽度就是血量**，所以取最右侧被点亮的列即可
    （血条上的白色数字会打出空洞，空洞不影响 min/max）。
    血条整个消失 = 塔已破 = 返回 0。
    """
    out = {}
    for lane, (x0, y0, x1, y1) in C.ENEMY_TOWER_BARS.items():
        band = frame[y0:y1, x0:x1]
        if band.size == 0:
            out[lane] = 1.0
            continue
        mask = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV), *C.H_TOWER_PINK)
        cols = (mask > 0).sum(axis=0)
        idx = np.nonzero(cols >= 3)[0]
        w = 0 if len(idx) == 0 else int(idx.max()) + 1
        out[lane] = min(w / float(C.ENEMY_TOWER_FULL_W), 1.0)
    return out


# ==================== 结算皇冠 ====================

def read_crowns(frame):
    """数结算界面的金冠，返回 (我方, 对方)。金冠=已拿，蓝枕=没拿。

    理论上可以拆成 6 个纯 ColorMatch 节点（每方 3 个固定皇冠位），
    但这里的「形态学闭运算 + 连通域计数」是实测验证过零误报的，
    换成 6 个独立判据等于用确定换不确定 —— 先原样保留。
    """
    out = {}
    x0, x1 = C.RESULT_BAND_X
    for who, (y0, y1) in C.RESULT_CROWN_ROWS.items():
        band = frame[y0:y1, x0:x1]
        if band.size == 0:
            out[who] = 0
            continue
        gold = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV), *C.H_CROWN_GOLD)
        gold = cv2.morphologyEx(gold, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(gold, 8)
        out[who] = sum(1 for i in range(1, n) if stats[i][4] > C.CROWN_MIN_BLOB)
    return int(out.get("mine", 0)), int(out.get("enemy", 0))


# ==================== 底部确认按钮 ====================

def find_bottom_button(frame):
    """在屏幕底部找最大的蓝色圆角按钮，返回中心坐标；没有就返回 None。

    为什么按颜色找而不是写死坐标：各个界面的「确定」位置都不一样
    （结算页在 (472,1149)、卡牌详情面板在 (239,1257)、宝箱结算在底部中间），
    写死要维护一堆坐标，而它们**都是亮蓝色**，找「底部最大的蓝色块」更稳。

    ⚠️ 这里没法用 pipeline 的 ColorMatch 顶替：ColorMatch 的 order_by=Area
       能拿到最大块，但**给不出「长宽比 1.5~9」这个形状约束**，
       而那条正是用来把别的蓝色 UI 排除掉的。
    """
    y0, y1 = C.BOTTOM_BUTTON_BAND
    band = frame[y0:y1, :]
    if band.size == 0:
        return None
    mask = cv2.inRange(cv2.cvtColor(band, cv2.COLOR_BGR2HSV), *C.H_BLUE)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    lo, hi = C.BOTTOM_BTN_ASPECT
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < C.BOTTOM_BTN_MIN_AREA or w < C.BOTTOM_BTN_MIN_W:
            continue
        if not (lo <= w / max(h, 1) <= hi):
            continue
        if best is None or area > best[0]:
            best = (area, x, y + y0, w, h)
    if best is None:
        return None
    _, x, y, w, h = best
    # 转成 python int：stats 里是 numpy int32，直接进日志会打成 np.int32(359) 很难看
    return int(x + w // 2), int(y + h // 2)


# ==================== 白字模板匹配 ====================

def find_white_text(frame, template, roi=None, threshold=0.78, scales=(1.0,),
                    nms_dist=60, limit=None):
    """在 frame 里找白字模板，返回 [(x, y, score)]（按分数降序，已做非极大值抑制）。

    模板必须**从模拟器原生截图裁**（不要用手机截图缩放），缩放过的文字模板
    匹配会掉很多。

    scales：不同区块的卡片大小不一样，字号会有差异，给一组缩放兜底。
    """
    tpl_mask = white_mask(template)
    if masks_are_blank(tpl_mask):
        return []
    th, tw = tpl_mask.shape[:2]

    if roi is None:
        area, oy = frame, 0
    else:
        x0, y0, x1, y1 = roi
        area, oy = frame[y0:y1, x0:x1], y0
    if area.size == 0 or th > area.shape[0] or tw > area.shape[1]:
        return []

    frame_mask = white_mask(area)
    hits = []
    for s in scales:
        if s == 1.0:
            t, fm = tpl_mask, frame_mask
        else:
            t = cv2.resize(tpl_mask, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
            if t.shape[0] > area.shape[0] or t.shape[1] > area.shape[1]:
                continue
            fm = frame_mask
        res = cv2.matchTemplate(fm, t, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.nonzero(res >= threshold)
        for y, x in zip(ys, xs):
            hits.append((float(res[y, x]), int(x), int(y), t.shape[1], t.shape[0]))

    hits.sort(reverse=True)
    keep = []
    for sc, x, y, w, h in hits:
        if all(abs(x - kx) > nms_dist or abs(y - ky) > nms_dist for _, kx, ky, _, _ in keep):
            keep.append((sc, x, y, w, h))
            if limit and len(keep) >= limit:
                break
    return [(x + w // 2, y + oy + h // 2, sc) for sc, x, y, w, h in keep]


def sat_val_of(frame, box):
    """box 区域的平均饱和度 / 亮度。用来判「捐赠按钮亮着还是灭的」。"""
    x, y, w, h = box
    patch = frame[y:y + h, x:x + w]
    if patch.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean()), float(hsv[:, :, 2].mean())
