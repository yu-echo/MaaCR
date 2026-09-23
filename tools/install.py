#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装发布包：把仓库拼成一个能直接双击运行的 `install/` 目录。

GitHub Actions 的 install 工作流会调它；本地也能手动跑，出包前先看一眼结果。

用法：
    python tools/install.py v0.1.0

前置条件（工作流会准备好；本地手动跑的话自己备齐）：
  · deps/           MaaFramework 的 MAA-win-x86_64 发布包**已解压**在这里（要有 bin/）
  · install/        MFAAvalonia 的 win-x64 发布包**已平铺**在这里（要有 MFAAvalonia.exe）
  · install/python/ 自带 Python，由 tools/ci/setup_embed_python.py 装好

脚本做四件事：
  1. 把 deps/ 里的 MaaFramework 原生库摆成 MFAAvalonia 认得的 .NET 布局；
  2. 复制 assets/resource 与 assets/interface.json；
  3. 复制 agent/、tools/、docs/、README、LICENSE、logo；
  4. **改写 install/interface.json 里那几个跟「文件在哪」有关的字段** —— 见 fix_paths()。

只做「复制 + 改一行 JSON」，不下载任何东西；下载都在工作流 / ci 脚本里。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Windows 的 stdout 默认按系统代码页编码：CI 的 windows runner 是 cp1252，
# 打一行中文就 UnicodeEncodeError 把打包脚本打死（实测踩过）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 复用 tools/validate.py 里的 JSONC 解析器（它已经在 CI 里跑着，没必要再抄一份）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import load_jsonc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DEPS = ROOT / "deps"
INSTALL = ROOT / "install"

# 只发 Windows：preflight 是 Windows + MuMu 专属，模板与坐标也绑死 720x1280 竖屏。
RID = "win-x64"

# 从 deps/bin 挑原生库时要丢掉的东西（与 MaaPracticeBoilerplate 一致）：
# 调试单元、Thrift/RPC/Http 控制单元、Node 插件、PiCli —— 发布包都用不上。
DROP_NATIVE = ("*MaaDbgControlUnit*", "*MaaThriftControlUnit*", "*MaaRpc*",
               "*MaaHttp*", "plugins", "*.node", "*MaaPiCli*")

# 复制代码目录时要丢掉的开发期杂物
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def die(msg: str) -> None:
    print("✗ %s" % msg, file=sys.stderr)
    sys.exit(1)


def copy_dir(src: Path, dst: Path, ignore=None, required: bool = True) -> None:
    rel = src.relative_to(ROOT)
    if not src.is_dir():
        if required:
            die("缺少 %s —— 发布包少了它跑不起来。" % rel)
        print("  · 跳过（没这个目录）：%s" % rel)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
    print("  · %s  ->  %s" % (rel, dst.relative_to(ROOT)))


# ==================== 1. MaaFramework 原生库 ====================

def install_deps() -> None:
    bin_dir = DEPS / "bin"
    if not bin_dir.is_dir():
        die("deps/bin 不存在。要先把 MaaFramework 的 MAA-<os>-<arch> 发布包解压到 deps/ 下。")

    # MFAAvalonia 是 .NET 程序，靠 runtimes/<rid>/native 找 MaaFramework 的原生库。
    #
    # 先把目标目录整个删掉再铺 —— MFAAvalonia 的包里自带一份 native 库，直接合并的话，
    # 名字撞上的会被我们覆盖，但**只在它那边有的文件会留下来**，两套 MaaFramework 的
    # dll 混在一起是最难查的一类问题（踩不到就没事，踩到了表现为莫名其妙的崩溃）。
    # 工作流里虽然也删过一次，但这条正确性归 install.py 管，不该指望调用方。
    native = INSTALL / "runtimes" / RID / "native"
    if native.exists():
        shutil.rmtree(native)
        print("  · 清掉旧的 %s（避免和自带的那份混版本）" % native.relative_to(ROOT))
    copy_dir(bin_dir, native, ignore=shutil.ignore_patterns(*DROP_NATIVE))
    # Agent 子进程通信要用的二进制；某些版本的发布包里没有这个目录
    copy_dir(DEPS / "share" / "MaaAgentBinary", INSTALL / "libs" / "MaaAgentBinary",
             required=False)
    copy_dir(bin_dir / "plugins", INSTALL / "plugins" / RID, required=False)


# ==================== 2. 资源 + 4. 改写 interface.json ====================

def install_resource(version: str) -> None:
    copy_dir(ASSETS / "resource", INSTALL / "resource")
    src = ASSETS / "interface.json"
    if not src.is_file():
        die("找不到 %s。" % src.relative_to(ROOT))
    shutil.copy2(src, INSTALL / "interface.json")
    print("  · assets/interface.json  ->  install/interface.json")
    fix_paths(version)


def fix_paths(version: str) -> None:
    """改写 interface.json 里跟「文件在哪」有关的字段 —— 发布包唯一必须改的地方。

    MFAAvalonia（v2.16.1 源码确认）对这几个字段的解析基准**不一样**，一张表说清：

      | 字段             | 相对谁解析                              |
      |------------------|-----------------------------------------|
      | agent.child_exec | 数据目录（= MFAAvalonia.exe 所在目录）   |
      | agent.child_args | 同上                                    |
      | pretask.exec     | 数据目录 / resource/base                 |
      | pretask.args     | pretask 的工作目录（同样是 resource/base）|

    发布包里「数据目录」就是 install/，于是：

      child_exec   -> python/python.exe          自带 Python（由 ci 脚本装好）
      child_args   -> agent/main.py
      pretask.exec -> ../../python/python.exe    从 resource/base 往上两层回到 install/
      pretask.args -> ../../tools/preflight.py

    最后一个尤其容易弄错：pretask.exec 是**相对 resource/base** 的，
    而 agent 的字段是相对 install/ 的，两者差两层。
    """
    path = INSTALL / "interface.json"
    data = load_jsonc(path)
    if not isinstance(data, dict):
        die("读不出 %s，没法改写路径。" % path.relative_to(ROOT))

    data["version"] = version

    agent = data.setdefault("agent", {})
    agent["child_exec"] = "python/python.exe"
    agent["child_args"] = ["-u", "agent/main.py"]

    tasks = data.get("pretask")
    tasks = tasks if isinstance(tasks, list) else ([tasks] if tasks else [])
    if not tasks:
        die("interface.json 里没有 pretask —— 「环境准备」是发布包的必要环节，别删。")
    for pt in tasks:
        pt["exec"] = "../../python/python.exe"
        pt["args"] = ["../../tools/preflight.py"]
    print("  · 改写 interface.json：agent -> python/python.exe / pretask -> ../../python/python.exe")

    # 注释不保留：发布包里的 interface.json 是给 MFAAvalonia 读的，
    # 该说明的东西留在仓库的 assets/interface.json 与 docs/zh_cn/3.1-打包发布.md。
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


# ==================== 3. 代码与杂物 ====================

def install_agent() -> None:
    copy_dir(ROOT / "agent", INSTALL / "agent", ignore=COPY_IGNORE)


def install_tools() -> None:
    copy_dir(ROOT / "tools", INSTALL / "tools",
             ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ci",
                                           "install-deps-win.bat"))


def install_chores() -> None:
    # logo.png 也得带上：README 头部引用了 ./logo.png，漏了的话包里的 README 会挂个碎图
    for name in ("README.md", "LICENSE", "logo.png"):
        src = ROOT / name
        if not src.is_file():
            die("缺少 %s —— 发布包里要带上它。" % name)
        shutil.copy2(src, INSTALL / name)
        print("  · %s" % name)

    # 界面图标：interface.json 的 icon 字段按「数据目录」解析，发布时数据目录就是包根，
    # 所以它必须落在包根下（开发时数据目录是 assets/，文件就在 assets/icon.png）。
    # 漏了不会报错，MFAAvalonia 会静默用回自己内嵌的图标 —— 表现为「换了 logo 界面里没变」。
    icon_src = ROOT / "assets" / "icon.png"
    if not icon_src.is_file():
        die("缺少 assets/icon.png —— interface.json 的 icon 字段要用它。")
    shutil.copy2(icon_src, INSTALL / "icon.png")
    print("  · assets/icon.png  ->  install/icon.png（界面图标）")

    # 装 .NET 运行时的小脚本：MFAAvalonia 不是自包含发布，少了 .NET 10 桌面运行时会起不来
    bat = ROOT / "tools" / "install-deps-win.bat"
    if not bat.is_file():
        die("缺少 tools/install-deps-win.bat。")
    shutil.copy2(bat, INSTALL / bat.name)
    print("  · tools/%s  ->  install/%s" % (bat.name, bat.name))

    # 文档也带上：README 里指向 docs/ 的链接在发布包里点得开
    copy_dir(ROOT / "docs" / "zh_cn", INSTALL / "docs" / "zh_cn")


# ==================== 5. 出包后自证 ====================

# 出包这一层最容易「看起来成功了，装出来却跑不起来」，所以逐条点一遍。
# 有些是「跑起来的必要条件」，有些是「缺了会静默降级」——两种都列上：
# 尤其 resource/base 那一条，它里面只有一个 .gitkeep，一旦打包/上传环节把隐藏文件
# 丢掉，空目录也不会被存下来，pretask 的工作目录就没了。
MUST_EXIST = (
    "MFAAvalonia.exe",
    "interface.json",
    "resource/pipeline/main.json",
    "resource/base",
    "agent/main.py",
    "tools/preflight.py",
    "python/python.exe",
    "runtimes/win-x64/native",
    # 缺了不会报错，界面会静默用回 MFAAvalonia 自带的图标
    "icon.png",
)


def verify_layout() -> None:
    missing = [rel for rel in MUST_EXIST if not (INSTALL / rel).exists()]
    if missing:
        for rel in missing:
            print("  ✗ 少了 %s" % rel)
        die("发布包不完整 —— 上面这些是跑起来的必要条件，别就这么发出去。")
    print("  · 关键路径 %d 项都在" % len(MUST_EXIST))


# ==================== 入口 ====================

def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools/install.py <版本号>")
        print("例如：python tools/install.py v0.1.0")
        return 1
    version = sys.argv[1]

    if not (INSTALL / "MFAAvalonia.exe").is_file():
        die("install/MFAAvalonia.exe 不在。工作流会先把 MFAAvalonia 的 win-x64 发布包"
            "平铺到 install/，再调这个脚本。")

    INSTALL.mkdir(parents=True, exist_ok=True)
    print("组装 MaaCR 发布包 %s" % version)

    print("[1/4] MaaFramework 原生库")
    install_deps()
    print("[2/4] 资源与 interface.json")
    install_resource(version)
    print("[3/4] Agent 与工具")
    install_agent()
    install_tools()
    print("[4/4] 说明文件")
    install_chores()

    print("[检查] 出包后自证")
    verify_layout()

    print("\n完成：%s" % INSTALL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
