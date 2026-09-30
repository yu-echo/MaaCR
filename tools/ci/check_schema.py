# -*- coding: utf-8 -*-
"""用 `deps/tools/` 下的官方 JSON Schema 校验 interface.json 与 pipeline。

和 `validate.py` 分工不同：
  · `validate.py`  查**引用完整性**（模板图在不在、next 指向的节点存不存在…）
  · 本脚本          查**字段合法性**（字段名拼错、类型不对、枚举值不在允许范围…）

两者都通过，才说明「这份 JSON 框架真的能读」。

用法（**仓库根**）：
    python tools/ci/check_schema.py
退出码 0 = 通过；1 = 有不合规处。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import jsonschema
    from jsonschema import validators
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7
except ImportError:
    print("x 需要依赖：python -m pip install jsonschema referencing")
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "deps" / "tools"
ASSETS = ROOT / "assets"

# ⚠️ MFAAvalonia 的**扩展**字段：ProjectInterface V2 协议本身没有，官方 schema 自然不认。
#    但它是我们**有意在用**的（「日常循环」任务的重复次数控件，见 interface.json 里的注释），
#    所以校验前把它剔除，避免 CI 长期红着一条「已知且正当」的差异。
UI_EXT_KEYS = ("repeatable", "repeat_count")


def prune_ui_extensions(doc: dict) -> dict:
    for t in doc.get("task", []):
        if isinstance(t, dict):
            for k in UI_EXT_KEYS:
                t.pop(k, None)
    return doc


def strip_jsonc(text: str) -> str:
    """只切字符串外的 // 注释（pipeline 是 JSONC，直接的 json.loads 会失败）。"""
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


def build_registry() -> Registry:
    """把所有官方 schema 装进 registry，这样 schema 之间的 $ref 能互相解析。"""
    resources = []
    for p in sorted(SCHEMAS.glob("*.schema.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        resources.append((p.name, Resource.from_contents(data, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


def main() -> int:
    if not SCHEMAS.is_dir():
        print(f"x 找不到 schema 目录：{SCHEMAS}")
        return 2

    registry = build_registry()
    validator_cls = validators.validator_for(
        json.loads((SCHEMAS / "interface.schema.json").read_text(encoding="utf-8")))
    validator_cls = validators.extend(validator_cls)

    problems: list[str] = []

    def check_one(schema_name: str, target: Path, label: str, prune: bool = False) -> None:
        schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
        v = validator_cls(schema, registry=registry)
        try:
            doc = json.loads(strip_jsonc(target.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            problems.append(f"{label} 不是合法 JSON：{exc}")
            return
        if prune:
            doc = prune_ui_extensions(doc)
        errs = sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))
        for e in errs:
            where = "/".join(str(x) for x in e.absolute_path) or "(root)"
            problems.append(f"{label} @ {where}：{e.message}")

    # interface.json（剔除 MFAAvalonia 的扩展字段后再校验）
    check_one("interface.schema.json", ASSETS / "interface.json",
              "assets/interface.json", prune=True)

    # pipeline：每个文件都按 pipeline.schema.json 校验
    pipe_dir = ASSETS / "resource" / "pipeline"
    files = sorted(pipe_dir.glob("*.json"))
    for f in files:
        check_one("pipeline.schema.json", f, f"assets/resource/pipeline/{f.name}")

    print(f"校验了 1 个 interface.json + {len(files)} 个 pipeline 文件")
    if problems:
        print(f"\nx 发现 {len(problems)} 处不合规：")
        for p in problems[:40]:
            print("  ✗", p)
        if len(problems) > 40:
            print(f"  …还有 {len(problems) - 40} 处")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
