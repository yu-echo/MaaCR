#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动前准备（ProjectInterface V2 的 pretask）。

在通用 UI 建立控制器**之前**跑，做两件事：

  ① **安全闸门**：确认目标是本地模拟器，不是插着的真机。
     为什么必须有这一条：旧版实测（2026-09-21）开发机插着的**真机上装了同一个
     国服皇室战争包**，所以「按包名挑设备」根本区分不开 —— 一旦端口全断而程序
     回退到「第一台在线设备」，就会去操作真机。旧版的做法是「只认 127.0.0.1
     端口，宁可报错也不点错设备」。交给框架之后这层保护会消失（框架只按 serial
     连，不关心那是不是模拟器），所以必须在这里重建。
     确实想在真机上跑，设 MAACR_ALLOW_REMOTE=1 显式放行。

  ② **把模拟器拉起来**：没在跑就自己调 MuMuManager 启动，并轮询等 adb 认到它。
     旧版要人工先点开 MuMu 才能跑脚本，这一步把它省掉。

按 PI 协议，本脚本**非零退出会让通用 UI 中止启动** —— 正好当闸门用。

用法（通用 UI 会自动调用；也可以手动跑来自检）：
    python tools/preflight.py
    python tools/preflight.py --check     只检查，不启动模拟器
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Windows 的 stdout 默认按系统代码页编码：中文 Windows 是 GBK 能扛住，
# 英文 / 西欧 Windows 是 cp1252，打一行中文就 UnicodeEncodeError 把脚本打死。
# 本脚本是被 MFAAvalonia 以子进程拉起来的，崩在这一步会表现成「环境准备直接失败」，
# 而真正的错误信息反而看不到 —— 所以先把这个隐患掐掉。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent

CR_PKG = "com.tencent.tmgp.supercell.clashroyale"

# MuMu 的 adb 端口会变：实测过 16384 失效改成 7555 / 5555。
MUMU_PORTS = (16384, 7555, 5555)

MUMU_MANAGER_CANDIDATES = (
    r"E:\Game\MuMuPlayer\nx_main\MuMuManager.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
    r"D:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
    r"E:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
    r"C:\Program Files\MuMuPlayer-12.0\shell\MuMuManager.exe",
)

MUMU_VM_INDEX = int(os.environ.get("MUMU_VM_INDEX", "0"))
MUMU_BOOT_TIMEOUT = int(os.environ.get("MUMU_BOOT_TIMEOUT", "180"))


def log(msg):
    print("[preflight] %s" % msg, flush=True)


# ==================== ① 安全闸门 ====================

def configured_targets():
    """从 PI_CONTROLLER 与常见环境变量里，尽量挖出「这次要连哪台设备」。

    PI v2.5+ 会注入 PI_CONTROLLER（当前选中控制器的完整对象，单行 JSON）。
    拿不到就直接返回空 —— 宁可放过，也不要因为解析不出来就误拦。
    """
    found = []

    raw = os.environ.get("PI_CONTROLLER")
    if raw:
        try:
            ctrl = json.loads(raw)
        except ValueError:
            ctrl = None
        if isinstance(ctrl, dict):
            stack = [ctrl]
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                        elif isinstance(v, str) and (
                            k.lower() in ("adb", "serial", "address", "device", "path")
                            or ":" in v
                        ):
                            found.append(v)
                elif isinstance(obj, list):
                    stack.extend(obj)

    for key in ("ANDROID_SERIAL", "MAA_ADB_SERIAL"):
        val = os.environ.get(key)
        if val:
            found.append(val)

    return [f for f in dict.fromkeys(found) if f]


def check_local_only():
    """目标必须是本地模拟器。返回 True = 放行。"""
    if os.environ.get("MAACR_ALLOW_REMOTE"):
        log("⚠️ MAACR_ALLOW_REMOTE 已设置 —— 跳过「只认本地模拟器」检查，自行确认目标设备！")
        return True

    targets = configured_targets()
    if not targets:
        log("看不到本次要连哪个设备（PI_CONTROLLER 里没有地址），跳过这项检查。")
        log("  提示：在通用 UI 里选设备时请选 MuMu 的 127.0.0.1:<端口>，")
        log("        不要选插着的真机 —— 真机上装的是同一个包，点了照样能跑，")
        log("        但驱动的是你的手机。")
        return True

    remote = [t for t in targets if not _is_local(t)]
    if remote:
        log("✗ 拒绝启动：目标设备不是本地模拟器 -> %s" % remote)
        log("  本项目的模板与坐标都是按 MuMu 的 720x1280 量的，跑在真机上没有意义；")
        log("  旧版还实测过开发机上的真机装了同一个国服包，很容易点错设备。")
        log("  确实要在真机上跑：设环境变量 MAACR_ALLOW_REMOTE=1。")
        return False

    log("目标设备检查通过：%s" % targets)
    return True


def _is_local(target: str) -> bool:
    """127.0.0.1 / localhost / emulator-* 都算本地。"""
    t = target.strip().lower()
    if t.startswith("127.0.0.1") or t.startswith("localhost"):
        return True
    if t.startswith("emulator-"):
        return True
    # 形如 127.0.0.1:16384
    if ":" in t:
        host = t.rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")
    return False


# ==================== adb / 模拟器 ====================

def find_adb():
    """找 adb：优先 PATH，其次常见安装位置。找不到返回 None。"""
    exe = shutil.which("adb")
    if exe:
        return exe
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe",
        Path(r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe"),
        Path(r"E:\Game\MuMuPlayer\shell\adb.exe"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def adb_devices(adb):
    try:
        out = subprocess.run([adb, "devices"], capture_output=True, timeout=20,
                             text=True, errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in (out or "").splitlines()[1:]:
        line = line.strip()
        if line and "\t" in line:
            serial, state = line.split("\t", 1)
            rows.append((serial.strip(), state.strip()))
    return rows


def mumu_is_up(adb):
    """已经连上的 MuMu（127.0.0.1:<端口>）有没有一台是 device 状态。"""
    for serial, state in adb_devices(adb):
        if state == "device" and _is_local(serial) and ":" in serial:
            return serial
    return None


def find_mumu_manager():
    env = os.environ.get("MUMU_MANAGER")
    cands = [env] if env else []
    cands += list(MUMU_MANAGER_CANDIDATES)
    for raw in cands:
        if not raw:
            continue
        p = Path(raw)
        if p.is_file():
            return str(p)
    return None


def ensure_emulator(adb, only_check=False):
    """确保模拟器在跑。返回 True = 可以继续。"""
    if mumu_is_up(adb):
        log("模拟器已经在跑：%s" % mumu_is_up(adb))
        return True

    # 试着直连候选端口（模拟器开着但 adb 没连上的情况很常见）
    for port in MUMU_PORTS:
        want = "127.0.0.1:%d" % port
        try:
            subprocess.run([adb, "connect", want], capture_output=True, timeout=15,
                           text=True, errors="replace")
        except (OSError, subprocess.SubprocessError):
            continue
    time.sleep(1.5)
    if mumu_is_up(adb):
        log("模拟器已经在跑：%s" % mumu_is_up(adb))
        return True

    if only_check:
        log("模拟器没在运行（--check 模式，不启动）")
        return False

    mgr = find_mumu_manager()
    if mgr is None:
        log("模拟器没在运行，而且没找到 MuMuManager.exe，没法自动启动。")
        log("  办法一：手动点开 MuMu 模拟器，再跑一次。")
        log("  办法二：把 MuMuManager.exe 的路径设进环境变量 MUMU_MANAGER。")
        log("         它通常在这个目录：<MuMu安装目录>\\nx_main\\MuMuManager.exe")
        return False

    log("模拟器没在运行，正在启动 MuMu（实例 %d）..." % MUMU_VM_INDEX)
    try:
        # MuMuManager 的 control 是「下发指令」，它自己不保证等模拟器起来就返回，
        # 所以超时不算失败 —— 后面的轮询会自己去等 adb。
        subprocess.run([mgr, "control", "-v", str(MUMU_VM_INDEX), "launch"],
                       capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        pass
    except OSError as exc:
        log("启动 MuMu 失败：%s" % exc)
        return False

    t0 = time.time()
    while time.time() - t0 < MUMU_BOOT_TIMEOUT:
        time.sleep(5)
        for port in MUMU_PORTS:
            try:
                subprocess.run([adb, "connect", "127.0.0.1:%d" % port],
                               capture_output=True, timeout=15, text=True, errors="replace")
            except (OSError, subprocess.SubprocessError):
                pass
        up = mumu_is_up(adb)
        if up:
            log("模拟器已就绪：%s（启动耗时 %.0f 秒）" % (up, time.time() - t0))
            return True
        log("  +%3.0fs 等模拟器起来 ..." % (time.time() - t0))

    log("等了 %.0f 秒模拟器还是没起来。请手动确认 MuMu 能不能正常启动。" % MUMU_BOOT_TIMEOUT)
    return False


def game_installed(adb, serial):
    try:
        out = subprocess.run([adb, "-s", serial, "shell", "pm", "list", "packages", CR_PKG],
                             capture_output=True, timeout=20, text=True,
                             errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return CR_PKG in (out or "")


def main() -> int:
    only_check = "--check" in sys.argv
    log("MaaCR 启动前准备%s" % ("（--check 模式）" if only_check else ""))

    if not check_local_only():
        return 1

    adb = find_adb()
    if adb is None:
        log("⚠️ 找不到 adb。模拟器生命周期没法自动管，交给通用 UI 自己连设备。")
        log("  （这不是致命问题：如果你已经手动连好设备，继续即可。）")
        return 0
    log("adb：%s" % adb)

    if not ensure_emulator(adb, only_check=only_check):
        log("✗ 模拟器不可用，中止启动。")
        return 1

    serial = mumu_is_up(adb)
    installed = game_installed(adb, serial)
    if installed is False:
        log("✗ 这台模拟器上没装国服皇室战争（%s），中止启动。" % CR_PKG)
        return 1
    if installed:
        log("国服皇室战争已安装 ✓")

    log("准备完成，交给通用 UI 连接设备。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
