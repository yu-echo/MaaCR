#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给发布包装一份「自带 Python」—— 用户不用装 Python 就能跑。

为什么必须自带：Agent（agent/main.py）和 pretask（tools/preflight.py）都要 Python，
而且依赖 MaaFw / opencv-python / numpy。指望用户自己装 + `pip install`，
等于把发布包的门槛抬到「会配 Python 环境」—— 那就不叫发布包了。

用的是**官方 embed 版**：不写注册表、不改系统 PATH、不碰用户已装的 Python。

三个步骤，中间那个是 embed 版最经典的坑：
  1. 下 python-<ver>-embed-amd64.zip，解到 <install_dir>/python/；
  2. 打开 pythonXX._pth，把 `import site` 放开并补上 Lib\\site-packages ——
     embed 版默认**不跑 site.py**，所以 pip 装完的东西 import 不到，
     表现是「明明装了却说 ModuleNotFoundError」。很多人卡在这里；
  3. 下 get-pip.py 用它跑一遍装上 pip，再装 agent/requirements.txt。

用法：
    python tools/ci/setup_embed_python.py install [Python 版本]

环境变量：
    MAACR_USE_CN_MIRROR=1   优先走国内镜像下 embed 包
                            （国内直连 python.org 可能慢到像卡死，实测过）
    PIP_INDEX_URL=...       给 pip 换源。这是 pip 自己的变量，本脚本不干预，
                            只想换源的话设它就够了，例如
                            PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

只有 Windows 有意义（embed-amd64 是 Windows 专用包），但脚本本身跨平台。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

# ★ 必须放在最前面：CI 用的 windows runner 控制台是 cp1252，
#   本脚本第一行日志就是中文，不做这一步会 UnicodeEncodeError 直接崩 ——
#   而且是崩在「下载」之前，表现成「这个源不行」，很容易误判成网络问题（实测踩过）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent

# 3.11 是 embed 包最成熟、轮子最齐的一档；opencv-python / numpy 在它上面都有现成
# win_amd64 轮子，不用现场编译。
DEFAULT_PY_VER = "3.11.9"

EMBED_OFFICIAL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
# 国内镜像：官方源在国内实测能连上但传输极慢，镜像是一秒级响应
EMBED_MIRRORS = (
    "https://mirrors.huaweicloud.com/python/{v}/python-{v}-embed-amd64.zip",
    "https://registry.npmmirror.com/-/binary/python/{v}/python-{v}-embed-amd64.zip",
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

UA = {"User-Agent": "MaaCR-install"}
# 单次网络操作的上限。设太小会把「慢但在传」的下载误杀，设太大又会出现
# 「看着像卡死」。60 秒没有新数据才算它死了。
NET_TIMEOUT = 60


def log(msg: str) -> None:
    print("[python] %s" % msg, flush=True)


def die(msg: str) -> None:
    print("✗ %s" % msg, file=sys.stderr)
    sys.exit(1)


def embed_urls(ver: str):
    """返回要依次尝试的 embed 包地址。"""
    official = EMBED_OFFICIAL.format(v=ver)
    mirrors = [u.format(v=ver) for u in EMBED_MIRRORS]
    if os.environ.get("MAACR_USE_CN_MIRROR"):
        return mirrors + [official]
    return [official] + mirrors


def download(url: str, dst: Path) -> None:
    """下载并**实时打进度** —— 不打印的话，慢的时候用户会以为卡死了。"""
    log("下载 %s" % url)
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    done = 0
    last_report = 0.0
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp, open(dst, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            now = time.time()
            if now - last_report >= 3:      # 每 3 秒报一次，别刷屏
                last_report = now
                if total:
                    log("  %5.1f / %.1f MB（%.0f KB/s）"
                        % (done / 1048576, total / 1048576,
                           done / 1024 / max(now - t0, 0.001)))
                else:
                    log("  %.1f MB" % (done / 1048576))
    log("  -> %s（%.1f MB，耗时 %.0fs）"
        % (dst.name, dst.stat().st_size / 1048576, time.time() - t0))


def download_first(urls, dst: Path) -> None:
    """依次尝试，第一个成功的算数。"""
    errors = []
    for url in urls:
        try:
            download(url, dst)
            return
        except Exception as exc:
            errors.append("%s -> %s: %s" % (url, type(exc).__name__, exc))
            log("  这个源不行，换下一个")
    die("所有源都下不下来：\n  " + "\n  ".join(errors))


def patch_pth(py_dir: Path) -> None:
    """放开 `import site` 并补上 site-packages —— 不做这步，装进去的包 import 不到。"""
    pths = sorted(py_dir.glob("python*._pth"))
    if not pths:
        die("没找到 pythonXX._pth。embed 包的结构跟预期不一样，别硬往下走。")
    pth = pths[0]

    keep = []
    for line in pth.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # 官方给的 ._pth 里有一行独立说明注释（`# Uncomment to run site.main() ...`）
        # 和一行被注释掉的 `#import site`，两行都丢掉 ——
        # `._pth` 的每一行都会被当成 sys.path 的一项，留着注释就是留条垃圾路径。
        if not stripped or stripped.startswith("#"):
            continue
        # `import site` 是这里的指令行，最后统一加一次，避免重复
        if stripped == "import site":
            continue
        keep.append(stripped)

    if not any("site-packages" in line for line in keep):
        keep.append("Lib\\site-packages")
    keep.append("import site")

    pth.write_text("\n".join(keep) + "\n", encoding="utf-8")
    log("改写 %s -> %s" % (pth.name, " | ".join(keep)))


def run(exe: Path, args, cwd: Path | None = None) -> None:
    log("运行 %s %s" % (exe.name, " ".join(str(a) for a in args)))
    subprocess.run([str(exe)] + [str(a) for a in args], cwd=cwd, check=True)


def main() -> int:
    install_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "install").resolve()
    py_ver = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PY_VER
    py_dir = install_dir / "python"

    if py_dir.exists():
        log("清掉旧的 %s" % py_dir)
        shutil.rmtree(py_dir)
    py_dir.mkdir(parents=True)

    exe = py_dir / "python.exe"
    with tempfile.TemporaryDirectory() as tmp_raw:
        tmp = Path(tmp_raw)

        zip_path = tmp / "python-embed.zip"
        download_first(embed_urls(py_ver), zip_path)

        log("解压到 %s" % py_dir)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(py_dir)

        patch_pth(py_dir)

        if not exe.is_file():
            die("解压后没有 %s —— embed 包结构跟预期不一样。" % exe)

        # embed 版不带 pip，得用官方引导脚本装一个
        get_pip = tmp / "get-pip.py"
        download(GET_PIP_URL, get_pip)
        run(exe, [get_pip, "--no-warn-script-location"])

    req = ROOT / "agent" / "requirements.txt"
    if not req.is_file():
        die("找不到 %s。" % req.relative_to(ROOT))
    run(exe, ["-m", "pip", "install", "--no-warn-script-location",
              "--disable-pip-version-check", "-r", req])

    # 装完立刻验一次：这一步才是「真的能用」，pip 没报错不算数。
    # ⚠️ 两个坑叠在一起，实测在 CI 上翻过车：
    #   1) import 名是 `maa`，不是 PyPI 上的包名 `MaaFw` —— 写 `import MaaFw` 会误报成
    #      「装了却 import 不到」，然后跑去瞎折腾 ._pth；
    #   2) 这一行是**另一个进程**（自带的 Python），上面那段 reconfigure 管不到它。
    #      它默认还是 cp1252，打印中文会 UnicodeEncodeError —— 所以：
    #      `-X utf8` 强制它走 UTF-8，打印内容也只用 ASCII。
    run(exe, ["-X", "utf8", "-c",
              "import maa, cv2, numpy;"
              "print('[ok] bundled python: maa=%s cv2=%s numpy=%s'"
              " % (maa.__file__, cv2.__version__, numpy.__version__))"])

    log("就绪：%s" % exe)
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(NET_TIMEOUT)
    sys.exit(main())
