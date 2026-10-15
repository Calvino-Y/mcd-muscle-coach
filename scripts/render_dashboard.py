#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/menu.json 注入 assets/dashboard-template.html，产出 docs/index.html。

这个脚本让可视化面板变成「可复现的构建产物」：
换一个门店、换一天的价格，重跑一次就能得到一份属于你自己的增肌面板。
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "dashboard-template.html"
DATASET = ROOT / "data" / "menu.json"
OUT = ROOT / "docs" / "index.html"

KEEP = ("name", "code", "category", "energyKcal", "protein", "fat", "carbs",
        "sodium", "calcium", "price", "proteinPer100kcal", "proteinPerYuan",
        "proteinSource")


def main() -> int:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    slim = {
        "source": data["source"],
        "items": [{k: it[k] for k in KEEP if k in it} for it in data["items"]],
    }
    payload = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))

    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DATA__*/" not in html:
        raise SystemExit("模板里找不到 /*__DATA__*/ 占位符")
    html = html.replace("/*__DATA__*/", payload)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    size_kb = len(html.encode("utf-8")) / 1024
    print(f"已生成 {OUT.relative_to(ROOT)}（{len(slim['items'])} 项餐品，{size_kb:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
