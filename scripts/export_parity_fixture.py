#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成对拍基准：把所有测试场景的 Python 端结果导出成 JSON。

前端（docs/index.html 内嵌的 JS 求解器）与后端（scripts/coach.py）是两套独立实现。
只要两边的答案不一致，用户就会在网页和命令行看到不同的推荐——所以必须对拍。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from coach import DEFAULT_KCAL_CAP, DEFAULT_MEAL_CAP, analyse  # noqa: E402

OUT = ROOT / "tests" / "parity_fixture.json"

# (体重, 蛋白系数, 已摄入, 模式)
SCENARIOS = [
    (72, 1.8, 40, "budget"), (72, 1.8, 40, "lean"),
    (60, 1.6, 75, "budget"), (60, 1.6, 75, "lean"),
    (80, 2.2, 20, "lean"),   (80, 2.2, 20, "budget"),
    (55, 1.4, 0, "budget"),  (95, 2.0, 120, "budget"),
    (68, 2.4, 95, "lean"),   (100, 1.6, 60, "budget"),
    (50, 2.0, 30, "lean"),   (88, 1.7, 145, "budget"),
]


def signature(plan: dict | None) -> dict | None:
    """把方案压成一个可比较的签名（与 JS 端的输出格式严格对应）。"""
    if not plan:
        return None
    return {
        "items": sorted(f"{i['name']}x{i['qty']}" for i in plan["items"]),
        "totalPrice": round(plan["totalPrice"], 1),
        "totalProtein": round(plan["totalProtein"], 1),
        "totalKcal": round(plan["totalKcal"]),
    }


def main() -> int:
    records = []
    for weight, factor, consumed, mode in SCENARIOS:
        res = analyse(weight, factor, consumed, mode,
                      DEFAULT_MEAL_CAP, DEFAULT_KCAL_CAP)
        records.append({
            "input": {"weight": weight, "factor": factor,
                      "consumed": consumed, "mode": mode},
            "mealProtein": res["target"]["mealProtein"],
            "mealsNeeded": res["target"]["mealsNeeded"],
            "budget": signature(res["budgetPlan"]),
            "lean": signature(res["leanPlan"]),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "mealCap": DEFAULT_MEAL_CAP,
        "kcalCap": DEFAULT_KCAL_CAP,
        "scenarios": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {len(records)} 个场景 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
