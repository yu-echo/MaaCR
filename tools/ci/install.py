# -*- coding: utf-8 -*-
"""组装 MaaCR 发布包 —— CI 与本地共用同一个脚本，避免两处实现漂移。

产出两种形态（架构只有 x86_64：本项目依赖 MuMu 模拟器，它只有 x86_64 Windows 版）：

    <out>/MaaCR-win-x86_64-<ver>-MFAA/     图形界面版（MFAAvalonia）
    <out>/MaaCR-win-x86_64-<ver>-PiCLI/    纯命令行版（MaaPiCli 形态）

用法（**仓库根**）：
    python tools/ci/install.py --version v1.0.0 \\
        --mfaa ./MFA --maa ./deps --out ./install

  --mfaa  MFAAvalonia 的 win-x64 发布包（已解压）目录
  --maa   MaaFramework 的 MAA-win-x86_64 包（已解压）目录，取它的 bin/ 当 PiCLI

两种形态里放的**项目资源完全相同**（resource / interface.json / README / docs），
区别只在「外层壳子」：
  - MFAA：MFAAvalonia 本体 + 预置的实例配置（否则首次打开是空任务列表）
  - PiCLI：MaaPiCli.exe + 它的 dll（不预置设备配置 —— 那是**本机相关**的，
           必须由用户自己跑一次交互模式生成，见 docs/zh_cn/1.1-快速开始.md）

⚠️ 组装完的目录**不要**先双击开一次再打包：MFAAvalonia 首次启动会删掉
   `MaaAgentBinary/`、新建空 `agent/`，并写出 `backup/temp/logs/debug/`，
   打出来的就是「已经被改过」的包。本脚本末尾会自检这一点。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "assets"
INSTANCE_ID = "a0b1c2d3"          # 固定值，方便比对
PRESET_NAME = "日常一条龙"

# MFAAvalonia 首次启动产生的「本机痕迹」——出现在包里就说明这个目录被打开过。
# ⚠️ `config/` 与 `appsettings.json` **故意不在**名单里：它们是我们**有意预置**的。
POLLUTION = ["agent", "backup", "temp", "logs", "debug"]
# 外壳里用不到的东西（本项目纯 JSON，没有 Python 运行时）
SHELL_JUNK = ["python", "tools"]


def strip_jsonc(text: str) -> str:
    """只切字符串外的 // 注释，不误伤 https:// 与字符串里的 //。"""
    out = []
    for line in text.split("\n"):
        in_str = esc = False
        cut = None
        for i, ch in enumerate(line):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str and ch == "/" and line[i + 1:i + 2] == "/":
                cut = i
                break
        out.append(line[:cut] if cut is not None else line)
    return "\n".join(out)


def write_interface(dst_root: Path, version: str) -> dict:
    """interface.json 去注释 + 改写 version，写到包根（必须与 exe 同层）。"""
    text = strip_jsonc((ASSETS / "interface.json").read_text(encoding="utf-8"))
    data = json.loads(text)
    data["version"] = version
    (dst_root / "interface.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    return data


def sync_project_files(dst_root: Path) -> None:
    """把项目资源覆盖进包：resource / README / docs / 使用说明。"""
    src_res = ASSETS / "resource"
    dst_res = dst_root / "resource"
    if dst_res.exists():
        shutil.rmtree(dst_res)
    shutil.copytree(src_res, dst_res)

    shutil.copy(REPO / "README.md", dst_root / "README.md")

    dst_docs = dst_root / "docs"
    if dst_docs.exists():
        shutil.rmtree(dst_docs)
    shutil.copytree(REPO / "docs", dst_docs)

    readme_txt = REPO / "使用说明.md"
    if readme_txt.is_file():
        shutil.copy(readme_txt, dst_root / "使用说明.md")


def preset_instance(dst_root: Path, iface: dict) -> None:
    """预置实例配置 —— 不做的话，全新解压的包首次打开必定是空任务列表。

    原因（2026-09-25 从 MFAAvalonia 源码定位）：目录里没有任何实例配置时，
    它基于 preset 建初始实例，但那次 ApplyPreset 跑在「任务模板还没加载」之前，
    按任务名查不到就跳过 ⇒ 6 个任务全被丢弃、实例写成 CurrentTasks: []；
    后面那条补救分支又因为 ViewModel == null 被跳过。
    """
    tasks = iface["task"]
    opts = iface["option"]

    def build_option(name: str) -> dict:
        spec = opts.get(name) or {}
        cases = [c["name"] for c in spec.get("cases", [])]
        dc = spec.get("default_case")
        item = {"name": name, "index": 0}
        # ⚠️ index 是「选中项在 cases 里的下标」，一律写 0 会悄悄改掉默认值
        #    （例如「要请求的卡牌」默认是第 40 项「电击法术」）
        if isinstance(dc, str) and dc in cases:
            item["index"] = cases.index(dc)
        if spec.get("type") == "checkbox" and isinstance(dc, list):
            item["selected_cases"] = list(dc)
        if spec.get("type") == "input":
            item["data"] = {i["name"]: i.get("default", "") for i in spec.get("inputs", [])}
        return item

    items = []
    for t in tasks:
        it = {k: t[k] for k in ("name", "entry", "description", "default_check") if k in t}
        if "option" in t:
            it["option"] = [build_option(o) for o in t["option"]]
        items.append(it)

    entry_of = {t["name"]: t["entry"] for t in tasks}
    current = [f"{t['name']}<|||>{entry_of[t['name']]}" for t in tasks]

    cfg_dir = dst_root / "config"
    (cfg_dir / "instances").mkdir(parents=True, exist_ok=True)
    (cfg_dir / "instances" / f"{INSTANCE_ID}.json").write_text(json.dumps({
        "CurrentControllerName": iface["controller"][0]["name"],
        "Resource": iface["resource"][0]["name"],
        "InstanceName": PRESET_NAME,
        "CurrentTasks": current,
        "TaskItems": items,
        "InstancePresetKey": PRESET_NAME,
        "CurrentController": 2,
        "ResourceOptionItems": {
            f"__Setting__{s['name']}": [{"name": o, "index": 0} for o in s.get("option", [])]
            for s in iface.get("setting", [])
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # config.json 一起预置：否则 config.template.json 的生效条件（目录里无配置）会被破坏。
    # ⚠️ 别写 `UI.LiveView.EnableLiveView` —— MFAAvalonia 会重写这个文件并丢掉不认识的键。
    (cfg_dir / "config.json").write_text(json.dumps({
        "CurrentLanguage": "zh-CN", "ColorTheme": "Blue", "BaseTheme": "Light",
        "EnableEdit": False, "UI.HasCompletedFirstUseTutorial": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (dst_root / "appsettings.json").write_text(json.dumps({
        "Instances.List": INSTANCE_ID,
        "Instances.Order": INSTANCE_ID,
        "Instances.LastActive": INSTANCE_ID,
        "Instances.LastActiveName": PRESET_NAME,
        "NoAutoStart": "False",
        "AnnouncementInfo.DoNotShowAgain": "True",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  · 预置实例 {INSTANCE_ID}.json（{len(current)} 个任务）")


def _resolve_root(d: Path, markers: tuple[str, ...]) -> Path:
    """上游压缩包解压后**可能多一层套娃**（如 `MFAAvalonia-vX-win-x64/`）。
    这里自动下钻到「含 marker 的那一层」；找不到就原样返回。"""
    if any((d / m).exists() for m in markers):
        return d
    for child in sorted(d.iterdir()) if d.is_dir() else []:
        if child.is_dir() and any((child / m).exists() for m in markers):
            return child
    return d


def build_mfaa(mfaa_dir: Path, out_root: Path, version: str) -> Path:
    dst = out_root / f"MaaCR-win-x86_64-{version}-MFAA"
    if dst.exists():
        shutil.rmtree(dst)
    print(f"· 组装 {dst.name}")
    src = _resolve_root(mfaa_dir, ("MFAAvalonia.exe",))
    shutil.copytree(src, dst)
    for junk in SHELL_JUNK:
        p = dst / junk
        if p.exists():
            shutil.rmtree(p)
            print(f"  · 移除外壳里的 {junk}/")
    sync_project_files(dst)
    iface = write_interface(dst, version)
    preset_instance(dst, iface)
    return dst


def build_picli(maa_dir: Path, out_root: Path, version: str) -> Path:
    dst = out_root / f"MaaCR-win-x86_64-{version}-PiCLI"
    if dst.exists():
        shutil.rmtree(dst)
    print(f"· 组装 {dst.name}")
    # MaaPiCli 在官方主包的 bin/ 下；**整棵复制**（不只是顶层 dll）——
    # 它还可能依赖同级的 MaaAgentBinary/ 等子目录，少一个就静默退出。
    src = _resolve_root(maa_dir, ("bin", "MaaPiCli.exe"))
    src = src / "bin" if (src / "bin").is_dir() else src
    shutil.copytree(src, dst)
    n = sum(1 for _ in dst.rglob("*") if _.is_file())
    print(f"  · 复制 MaaPiCli 运行时（{src.name}/，{n} 个文件）")
    sync_project_files(dst)
    write_interface(dst, version)
    return dst


def make_gbk_zip(dst_root: Path, zip_path: Path) -> None:
    """打 zip：文件名写成 **GBK 字节、不设 UTF-8 标志位**（与历代包一致，中文 Windows 解压最稳）。

    ⚠️ Python 的 zipfile 只肯写「UTF-8 + 0x800 标志位」，这里做两处改造：
      1) `ZipInfo.filename` 用「GBK 字节按 cp437 解码」的 str 承载；
      2) 临时禁掉 `_sanitize_filename` —— 它会把 GBK 里合法的 0x5C
         （汉字第二字节可以是 0x5C）当成路径分隔符替换掉，弄坏文件名。
    """
    orig_sanitize = zipfile._sanitize_filename
    orig_encode = zipfile.ZipInfo._encodeFilenameFlags
    zipfile._sanitize_filename = lambda name: name
    zipfile.ZipInfo._encodeFilenameFlags = lambda self: (self.filename.encode("cp437"), 0)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(dst_root.rglob("*")):
                arc = str(p.relative_to(dst_root.parent)).replace("\\", "/")
                if p.is_dir():
                    zi = zipfile.ZipInfo((arc + "/").encode("gbk").decode("cp437"))
                    zi.flag_bits = 0
                    zi.compress_type = zipfile.ZIP_STORED
                    zi.external_attr = (0o40775 << 16) | 0x10
                    z.writestr(zi, b"")
                else:
                    zi = zipfile.ZipInfo(arc.encode("gbk").decode("cp437"))
                    zi.flag_bits = 0
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(zi, p.read_bytes())
    finally:
        zipfile._sanitize_filename = orig_sanitize
        zipfile.ZipInfo._encodeFilenameFlags = orig_encode


def self_check(pkg: Path) -> bool:
    ok = True
    py = list(pkg.rglob("*.py"))
    print(f"  包内 .py：{len(py)}" + ("  ✓" if not py else f"  ✗ {py[:3]}"))
    ok &= not py
    bad = [n for n in POLLUTION if (pkg / n).exists()]
    print(f"  首次启动痕迹：{bad or '无'}" + ("  ✓" if not bad else "  ✗"))
    ok &= not bad
    for must in ("interface.json", "resource"):
        exists = (pkg / must).exists()
        print(f"  {must}：{'存在  ✓' if exists else '缺失  ✗'}")
        ok &= exists
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="写进 interface.json 的版本号，如 v1.0.0")
    ap.add_argument("--mfaa", help="MFAAvalonia win-x64 发布包（已解压）目录")
    ap.add_argument("--maa", help="MaaFramework MAA-win-x86_64（已解压）目录，取 bin/ 当 PiCLI")
    ap.add_argument("--out", default="install", help="输出根目录（默认 ./install）")
    ap.add_argument("--no-zip", action="store_true", help="只组装，不打 zip")
    a = ap.parse_args()

    if not a.mfaa and not a.maa:
        print("x 至少要给一个 --mfaa 或 --maa")
        return 2

    out_root = Path(a.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    made: list[Path] = []
    if a.mfaa:
        made.append(build_mfaa(Path(a.mfaa).resolve(), out_root, a.version))
    if a.maa:
        made.append(build_picli(Path(a.maa).resolve(), out_root, a.version))

    print("\n=== 自检 ===")
    all_ok = True
    for pkg in made:
        print(f"[{pkg.name}]")
        all_ok &= self_check(pkg)

    if not a.no_zip and all_ok:
        print("\n=== 打包 ===")
        for pkg in made:
            zp = out_root / f"{pkg.name}.zip"
            make_gbk_zip(pkg, zp)
            print(f"  {zp.name}  {zp.stat().st_size / 1024 / 1024:.1f} MB")
    elif not all_ok:
        print("\nx 自检没过，拒绝打包")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
