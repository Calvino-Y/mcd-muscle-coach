#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把麦当劳 MCP 的历史订单，整理成「你实际点了什么」的体检数据集。

数据来源（全部真实，零编造）：
  * 订单      tool: order-list           -> data/orders_raw.json
  * 营养成分  tool: list-nutrition-foods -> data/nutrition_raw.txt

与 scripts/build_yearbook.py（年报项目）的差别：
  年报关注「你是个什么样的人」，这里关注「你实际吃进去多少蛋白和热量、
  离你自己的增肌目标差多远、按算法重下能省多少钱」。
  所以这里输出的是逐单明细，每一单都带上餐品级的营养对齐结果。

诚实原则：
  订单里只有一部分单品能在官方营养表里找到对应条目。找不到的就标记为
  未匹配，并给出该单的营养覆盖率——宁可用一个标注了覆盖率的偏小数字，
  也不填一个编出来的数字。
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORDERS = ROOT / "data" / "orders_raw.json"
NUTRITION = ROOT / "data" / "nutrition_raw.txt"
OUT = ROOT / "data" / "orders.json"

TIME_BUCKETS = [
    ("早餐", 5, 10), ("午餐", 10, 14), ("下午茶", 14, 17),
    ("晚餐", 17, 21), ("夜宵", 21, 25),
]
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse_nutrition() -> dict[str, dict]:
    table: dict[str, dict] = {}
    for line in NUTRITION.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("[", "{")):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 9:
            continue
        try:
            num = [float(x) for x in parts[2:]]
        except ValueError:
            continue
        table[parts[0]] = {
            "energyKcal": num[1], "protein": num[2], "fat": num[3],
            "carbs": num[4], "sodium": num[5], "calcium": num[6],
        }
    return table


def bucket_of(hour: int) -> str:
    for name, lo, hi in TIME_BUCKETS:
        if lo <= hour < hi:
            return name
    return "深夜"


def main() -> int:
    raw = json.loads(ORDERS.read_text(encoding="utf-8"))
    orders = raw["orders"]
    nutrition = parse_nutrition()

    rows: list[dict] = []
    matched_total = unmatched_total = 0
    all_time_qty: dict[str, int] = {}

    for seq, o in enumerate(orders, 1):
        dt = datetime.strptime(o["createTime"], "%Y-%m-%d %H:%M:%S")
        items, kcal, protein, fat, sodium = [], 0.0, 0.0, 0.0, 0.0
        m_qty = u_qty = 0

        for prod in o["orderProductList"]:
            # 有套餐组成就走子项；纯单品自身就是一条明细
            subs = prod.get("comboItemList") or [
                {"name": prod["productName"], "quantity": prod["quantity"]}
            ]
            for sub in subs:
                name, qty = sub["name"], int(sub["quantity"])
                all_time_qty[name] = all_time_qty.get(name, 0) + qty
                row = nutrition.get(name)
                if row:
                    m_qty += qty
                    kcal += row["energyKcal"] * qty
                    protein += row["protein"] * qty
                    fat += row["fat"] * qty
                    sodium += row["sodium"] * qty
                    items.append({
                        "name": name, "qty": qty, "matched": True,
                        "protein": row["protein"] * qty,
                        "kcal": round(row["energyKcal"] * qty),
                        "sodium": round(row["sodium"] * qty),
                    })
                else:
                    u_qty += qty
                    items.append({"name": name, "qty": qty, "matched": False,
                                  "protein": 0, "kcal": 0, "sodium": 0})

        matched_total += m_qty
        unmatched_total += u_qty
        total_qty = m_qty + u_qty
        amount = float(o["realTotalAmount"])

        rows.append({
            "seq": seq,
            "orderId": o["orderId"],
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
            "weekday": WEEKDAY_CN[dt.weekday()],
            "hour": dt.hour,
            "bucket": bucket_of(dt.hour),
            "store": o["storeName"],
            "amount": round(amount, 1),
            "items": items,
            "protein": round(protein, 1),
            "kcal": round(kcal),
            "fat": round(fat, 1),
            "sodium": round(sodium),
            "matchedQty": m_qty,
            "unmatchedQty": u_qty,
            "coverage": round(m_qty / total_qty * 100) if total_qty else 0,
        })

    # 按时间正序，便于阅读
    rows.sort(key=lambda r: (r["date"], r["time"]))

    total_protein = sum(r["protein"] for r in rows)
    total_kcal = sum(r["kcal"] for r in rows)
    total_spend = sum(r["amount"] for r in rows)
    total_items = matched_total + unmatched_total
    rich = [r for r in rows if r["protein"] >= 30]
    best = max(rows, key=lambda r: r["protein"]) if rows else None

    payload = {
        "source": {
            **raw.get("source", {}),
            "nutritionTool": "list-nutrition-foods",
            "orderTool": "order-list",
            "orderCount": len(rows),
        },
        "period": {"first": rows[0]["date"], "last": rows[-1]["date"]},
        "summary": {
            "orderCount": len(rows),
            "totalSpend": round(total_spend, 1),
            "avgPerOrder": round(total_spend / len(rows), 1) if rows else 0,
            "totalProtein": round(total_protein, 1),
            "totalKcal": round(total_kcal),
            "avgProteinPerOrder": round(total_protein / len(rows), 1) if rows else 0,
            "avgKcalPerOrder": round(total_kcal / len(rows)) if rows else 0,
            "costPerProtein": round(total_spend / total_protein, 2) if total_protein else None,
            "proteinRichOrders": len(rich),
            "itemCount": total_items,
            "matchedQty": matched_total,
            "unmatchedQty": unmatched_total,
            "coverage": round(matched_total / total_items * 100) if total_items else 0,
            "bestOrderSeq": best["seq"] if best else None,
            "bestOrderProtein": best["protein"] if best else 0,
            "topItem": (max(all_time_qty.items(), key=lambda kv: kv[1])[0]
                        if all_time_qty else None),
            "topItemQty": (max(all_time_qty.values()) if all_time_qty else 0),
        },
        "orders": rows,
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    s = payload["summary"]
    print(f"已写入 {OUT.relative_to(ROOT)}")
    print(f"  订单 {s['orderCount']} 笔 · 花费 ¥{s['totalSpend']} · 覆盖 {payload['period']['first']}–{payload['period']['last']}")
    print(f"  已匹配蛋白 {s['totalProtein']} g · 热量 {s['totalKcal']} kcal · 营养覆盖率 {s['coverage']}%")
    print(f"  平均每单蛋白 {s['avgProteinPerOrder']} g · 每克蛋白成本 ¥{s['costPerProtein']}")
    print(f"  蛋白 ≥30 g 的订单：{s['proteinRichOrders']}/{s['orderCount']} 笔")
    print(f"  最常点：{s['topItem']} ×{s['topItemQty']}")
    print()
    for r in rows:
        flag = "达标" if r["protein"] >= 30 else ("偏低" if r["protein"] < 20 else "及格")
        print(f"  #{r['seq']:<2} {r['date']} {r['weekday']} {r['bucket']:<4} "
              f"¥{r['amount']:>5.1f}  蛋白 {r['protein']:>5.1f}g  热量 {r['kcal']:>4}  "
              f"[{flag}] 覆盖 {r['coverage']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
