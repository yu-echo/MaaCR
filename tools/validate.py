#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目自检：把「静默失效」的几类问题在跑之前就抓出来。

为什么需要它：MaaFramework 的资源项目里，下面这些问题**不会报错**，只会让某条
分支永远不命中、然后表现为「卡在某个界面」或者「明明有这个节点却从不执行」，
排查起来极其费时：

  1. pipeline 里 template 指向的图片不存在（或路径写错）—— 识别永远 0.00；
  2. next / on_error 指向的节点名拼错 —— 链断在那里，任务直接结束；
  3. pipeline 里用了 Custom 识别/动作名，但 agent 侧没注册 ——
     走到该节点直接失败；
  4. interface.json 里的 entry 指向不存在的节点 —— 点「开始」什么也不发生；
  5. interface.json 的 pipeline_override 覆盖了不存在的节点名 —— 覆盖静默无效，
     表现为「这个选项点了没用」。

用法（仓库根目录）：
    python tools/validate.py
退出码 0 = 全部通过；1 = 有问题（会逐条列出）。

只依赖标准库 —— 这样 CI 里不用装任何东西就能跑。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
RESOURCE = ASSETS / "resource"
PIPELINE = RESOURCE / "pipeline"
IMAGE = RESOURCE / "image"
AGENT = ROOT / "agent"

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


# ==================== JSON / JSONC 解析 ====================

def strip_jsonc(text: str) -> str:
    """去掉 // 与 /* */ 注释，但别碰字符串里的（URL 的 // 会被误伤）。

    注意：只处理注释，不做别的容错 —— 语法错还是要老实暴露出来。
    """
    out = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:          # 转义序列整体跳过
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_jsonc(path: Path):
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first:
        try:
            return json.loads(strip_jsonc(raw))
        except json.JSONDecodeError as exc:
            fail("%s 不是合法 JSON：%s" % (path.relative_to(ROOT), exc))
            note("（原样解析时是：%s）" % first)
            return None


# ==================== 收集 pipeline 节点 ====================

def load_pipelines():
    """返回 (nodes, node_to_file)。nodes 是所有 pipeline 节点的合并视图。"""
    nodes = {}
    node_to_file = {}
    if not PIPELINE.is_dir():
        fail("找不到 %s" % PIPELINE.relative_to(ROOT))
        return nodes, node_to_file
    files = sorted(PIPELINE.rglob("*.json"))
    if not files:
        fail("%s 下没有任何 .json" % PIPELINE.relative_to(ROOT))
    for f in files:
        # 以 . 开头的文件/目录框架不会读取 —— 这里同步忽略，免得自检与运行不一致
        if any(part.startswith(".") for part in f.relative_to(PIPELINE).parts):
            continue
        data = load_jsonc(f)
        if not isinstance(data, dict):
            continue
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        for name, body in data.items():
            if name.startswith("$"):
                continue
            if name in nodes:
                fail("节点名重复：%s（%s 与 %s）" % (name, node_to_file[name], rel))
            nodes[name] = body if isinstance(body, dict) else {}
            node_to_file[name] = rel
    return nodes, node_to_file


# ==================== 各专项检查 ====================

TEMPLATE_KEYS = ("template",)


def check_templates(nodes, node_to_file):
    """pipeline 引用的每张模板图都要真的存在。"""
    checked = 0
    for name, body in nodes.items():
        for key in TEMPLATE_KEYS:
            val = body.get(key)
            if val is None:
                continue
            items = val if isinstance(val, list) else [val]
            for item in items:
                if not isinstance(item, str):
                    continue
                checked += 1
                target = IMAGE / item
                if not target.is_file():
                    fail("%s 的 template 找不到图片：%s\n      （应为 %s）"
                         % (name, item, target.relative_to(ROOT)))
    return checked


def walk_recognition_blocks(body):
    """把节点里所有「识别定义」子块（含 And/Or 内联项）都吐出来。"""
    yield body
    for key in ("all_of", "any_of"):
        for sub in body.get(key) or []:
            if isinstance(sub, dict):
                yield sub


def check_refs(nodes, node_to_file):
    """next / on_error / target / roi(字符串形式) 引用的节点名都要存在。"""
    refs = 0
    for name, body in nodes.items():
        for key in ("next", "on_error"):
            val = body.get(key)
            if val is None:
                continue
            items = val if isinstance(val, list) else [val]
            for item in items:
                raw = item.get("name") if isinstance(item, dict) else item
                if not isinstance(raw, str):
                    continue
                refs += 1
                target = raw
                if target.startswith("[JumpBack]"):
                    target = target[len("[JumpBack]"):]
                if target.startswith("[Anchor]"):
                    continue                      # 锚点是运行期解析的，静态查不了
                if target not in nodes:
                    fail("%s 的 %s 指向不存在的节点：%s" % (name, key, raw))

        for block in walk_recognition_blocks(body):
            # roi / target 写成字符串时是「引用另一个节点名」
            for key in ("roi", "target"):
                val = block.get(key)
                if isinstance(val, str) and not val.startswith("[Anchor]"):
                    refs += 1
                    if val not in nodes:
                        fail("%s 的 %s 引用了不存在的节点：%s" % (name, key, val))
    return refs


def check_custom_names(nodes):
    """pipeline 里用的 Custom 名，agent 侧必须注册过。"""
    src = ""
    if AGENT.is_dir():
        for f in sorted(AGENT.rglob("*.py")):
            src += f.read_text(encoding="utf-8", errors="replace")
    if not src:
        fail("读不到 agent/ 下的任何 Python 源码，无法校验 Custom 名")
        return 0, 0

    registered_reco = set(re.findall(r'custom_recognition\(\s*["\']([^"\']+)["\']', src))
    registered_act = set(re.findall(r'custom_action\(\s*["\']([^"\']+)["\']', src))

    used_reco = set()
    used_act = set()
    for name, body in nodes.items():
        for block in walk_recognition_blocks(body):
            if block.get("recognition") == "Custom" or "custom_recognition" in block:
                cn = block.get("custom_recognition")
                if cn:
                    used_reco.add(cn)
                    if cn not in registered_reco:
                        fail("%s 用到未注册的自定义识别：%s" % (name, cn))
        if body.get("action") == "Custom" or "custom_action" in body:
            ca = body.get("custom_action")
            if ca:
                used_act.add(ca)
                if ca not in registered_act:
                    fail("%s 用到未注册的自定义动作：%s" % (name, ca))

    for cn in sorted(registered_reco - used_reco):
        note("已注册但 pipeline 没用到（可能是留给后续任务的）：自定义识别 %s" % cn)
    for cn in sorted(registered_act - used_act):
        note("已注册但 pipeline 没用到（可能是留给后续任务的）：自定义动作 %s" % cn)
    return len(used_reco), len(used_act)


def check_interface(nodes):
    """interface.json 的 entry / pipeline_override 节点名都要存在。"""
    iface_path = ASSETS / "interface.json"
    if not iface_path.is_file():
        fail("找不到 %s" % iface_path.relative_to(ROOT))
        return

    data = load_jsonc(iface_path)
    if not isinstance(data, dict):
        return

    if data.get("interface_version") != 2:
        fail("interface.json 的 interface_version 必须是 2，当前是 %r"
             % data.get("interface_version"))

    for t in data.get("task") or []:
        entry = t.get("entry")
        if not entry:
            fail("任务「%s」没有 entry" % t.get("name"))
            continue
        if entry not in nodes:
            fail("任务「%s」的 entry 指向不存在的节点：%s" % (t.get("name"), entry))

    def scan_overrides(where, ov):
        if not isinstance(ov, dict):
            return
        for node_name in ov:
            if node_name not in nodes:
                fail("%s 的 pipeline_override 覆盖了不存在的节点：%s" % (where, node_name))

    for key in ("option",):
        for opt_name, opt in (data.get(key) or {}).items():
            where = "选项「%s」" % opt_name
            scan_overrides(where, opt.get("pipeline_override"))
            for case in opt.get("cases") or []:
                scan_overrides("%s 的选项值「%s」" % (where, case.get("name")),
                               case.get("pipeline_override"))
    for t in data.get("task") or []:
        scan_overrides("任务「%s」" % t.get("name"), t.get("pipeline_override"))
    for ctrl in data.get("controller") or []:
        scan_overrides("控制器「%s」" % ctrl.get("name"), ctrl.get("pipeline_override"))
    for res in data.get("resource") or []:
        scan_overrides("资源「%s」" % res.get("name"), res.get("pipeline_override"))

    # 选项被 task / setting 引用时必须真的存在
    defined = set((data.get("option") or {}).keys())
    for t in data.get("task") or []:
        for o in t.get("option") or []:
            if o not in defined:
                fail("任务「%s」引用了未定义的选项：%s" % (t.get("name"), o))
    for s in data.get("setting") or []:
        for o in s.get("option") or []:
            if o not in defined:
                fail("setting「%s」引用了未定义的选项：%s" % (s.get("name"), o))

    # agent / pretask 里写的路径都要真的存在（相对 interface.json 所在目录解析）
    agent = data.get("agent")
    if agent:
        if not (agent or {}).get("child_exec"):
            fail("interface.json 的 agent 缺少 child_exec")
        for a in (agent or {}).get("child_args") or []:
            _check_rel_path("agent 的 child_args", a)

    for pt in _as_list(data.get("pretask")):
        if not isinstance(pt, dict):
            fail("interface.json 的 pretask 项不是对象：%r" % (pt,))
            continue
        if not pt.get("exec"):
            fail("interface.json 的 pretask 缺少 exec")
        for a in pt.get("args") or []:
            _check_rel_path("pretask「%s」的 args" % (pt.get("name") or pt.get("exec")), a)


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _check_rel_path(where, raw):
    """只检查看起来是「仓库内文件」的路径：带 ./ ../ 或 .py 结尾。

    刻意不去校验 "python" 这种 PATH 里的可执行文件名。
    """
    if not isinstance(raw, str):
        return
    looks_like_path = raw.startswith(("./", "../")) or raw.endswith(".py")
    if not looks_like_path:
        return
    target = (ASSETS / raw).resolve()
    if not target.is_file():
        fail("%s 指向不存在的文件：%s\n      （相对 interface.json 解析，即 %s）"
             % (where, raw, target))


def main() -> int:
    print("MaaCR 项目自检")
    print("=" * 60)

    nodes, node_to_file = load_pipelines()
    print("pipeline 文件节点数：%d" % len(nodes))

    n_tpl = check_templates(nodes, node_to_file)
    print("检查模板引用：%d 处" % n_tpl)

    n_ref = check_refs(nodes, node_to_file)
    print("检查节点引用：%d 处" % n_ref)

    n_reco, n_act = check_custom_names(nodes)
    print("检查 Custom 注册：识别 %d 个 / 动作 %d 个" % (n_reco, n_act))

    check_interface(nodes)
    print("检查 interface.json")

    print("=" * 60)
    for n in notes:
        print("· %s" % n)
    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  ✗ %s" % p)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
