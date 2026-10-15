#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 dashboard-template.html 里的板块序号（sec-tag 的 <i>N</i>）按出现顺序重新编号。

新增/删除板块后手工维护序号一定会漏，所以做成脚本：单一事实来源是「在文档里的先后顺序」。
用法： python scripts/renumber_sections.py [--check]
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "dashboard-template.html"

PATTERN = re.compile(r'(<div class="sec-tag"><i>)(\d+)(</i>)')


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    html = TEMPLATE.read_text(encoding="utf-8")

    counter = {"n": 0}

    def repl(m: re.Match) -> str:
        counter["n"] += 1
        return f"{m.group(1)}{counter['n']}{m.group(3)}"

    new = PATTERN.sub(repl, html)
    total = counter["n"]

    if new == html:
        print(f"{total} 个板块，序号已经是连续的")
        return 0

    if check_only:
        print(f"{total} 个板块的序号不连续，请运行： python scripts/renumber_sections.py")
        return 1

    TEMPLATE.write_text(new, encoding="utf-8", newline="\n")
    print(f"已重新编号 {total} 个板块（按文档顺序 1..{total}）")
    for m in PATTERN.finditer(new):
        print(f"  {m.group(2):>2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
