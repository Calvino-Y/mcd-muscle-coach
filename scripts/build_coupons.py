#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/coupons_raw.json 解析成可计算、可展示的 data/coupons.json。

这一模块存在的唯一理由，是把「券」变成「蛋白质」。
但券面信息是不完整的——券名只是营销文案，不是 SKU。所以这里的核心纪律是：

    能确定性对齐的，给出单值；
    能给出上下界的，给出区间并写明理由；
    营养表里根本没有对应条目的，标成「无法对齐」，绝不拿相近餐品替换。

宁可让页面上出现「这张券算不出来」，也不给一个看起来漂亮但站不住的数字。
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "coupons_raw.json"
DATASET = ROOT / "data" / "menu.json"
OUT = ROOT / "data" / "coupons.json"

WEEK_ORDER = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ---------------------------------------------------------------------------
# 券名 -> 餐品的映射表。每条都必须写清「依据」，因为这是整个板块可信度的来源。
#
# candidates 的语义：
#   1 个候选          -> 可给单值
#   多个候选          -> 只能给区间（券面信息不足以区分）
#   空列表            -> 无法对齐，页面如实显示「算不出来」
# ---------------------------------------------------------------------------
MAPPING: dict[str, dict] = {
    "中薯条买一送一": {
        "confidence": "deterministic",
        "basis": "券名本身就是「买一送一」，对应菜单里的中薯条 ×2，成分没有歧义。",
        "candidates": [["中薯条", "中薯条"]],
    },
    "王牌小食拼": {
        "confidence": "unmatched",
        "basis": "券面没有标注这个拼盘包含哪几件餐品，无法逐件对齐官方营养表。不猜。",
        "candidates": [],
    },
    "火腿扒堡早餐两件套": {
        "confidence": "range",
        "basis": "官方营养表里与「火腿扒堡」对应的条目有两个（火腿扒麦满分 / 双层火腿扒麦满分），"
                 "券面没有指明是哪一种，因此只能给区间。",
        "candidates": [["火腿扒麦满分"], ["双层火腿扒麦满分"]],
    },
    "巧克力味厚松饼猪柳蛋套餐": {
        "confidence": "partial",
        "basis": "套餐里的猪柳蛋能对齐营养表的「猪柳蛋麦满分」，但「巧克力味厚松饼」在营养表里"
                 "没有条目，所以这个数字是套餐蛋白质的下界。",
        "candidates": [["猪柳蛋麦满分"]],
    },
    "芝香脆鸡扒堡早餐两件套": {
        "confidence": "unmatched",
        "basis": "官方营养表里没有「芝香脆鸡扒堡」这个条目，不做近似替换。",
        "candidates": [],
    },
    "高达芝士蛋堡早餐两件套": {
        "confidence": "unmatched",
        "basis": "官方营养表里没有「高达芝士蛋堡」这个条目，不做近似替换。",
        "candidates": [],
    },
}

CONF_LABEL = {
    "deterministic": "可确定",
    "range": "区间",
    "partial": "下界",
    "unmatched": "无法对齐",
}


def load_items() -> dict[str, dict]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    return {it["name"]: it for it in data["items"]}


def score_candidate(names: list[str], by_name: dict[str, dict]) -> dict | None:
    """把一组餐品名换算成蛋白/热量。任一条目缺营养数据则整体作废。"""
    items, protein, kcal, fat, sodium = [], 0.0, 0.0, 0.0, 0.0
    for n in names:
        it = by_name.get(n)
        if not it:
            return None
        items.append({"name": n, "protein": it["protein"], "energyKcal": it["energyKcal"]})
        protein += it["protein"]
        kcal += it["energyKcal"]
        fat += it["fat"]
        sodium += it["sodium"]
    return {
        "items": items,
        "protein": round(protein, 1),
        "energyKcal": round(kcal),
        "fat": round(fat, 1),
        "sodium": round(sodium),
    }


def build_board(raw: dict, by_name: dict[str, dict]) -> list[dict]:
    board: list[dict] = []
    for c in raw["myCoupons"]:
        title = c["title"]
        rule = MAPPING.get(title)
        price = c["couponPrice"]

        row = {
            "title": title,
            "couponPrice": price,
            "weekdays": c["weekdays"],
            "timeFrom": c["timeFrom"],
            "timeTo": c["timeTo"],
            "dateFrom": c["dateFrom"],
            "dateTo": c["dateTo"],
            "channels": c["channels"],
            "confidence": rule["confidence"] if rule else "unmatched",
            "basis": rule["basis"] if rule else "未登记的券，不做推断。",
            "candidates": [],
            "proteinLo": None, "proteinHi": None,
            "kcalLo": None, "kcalHi": None,
            "gPerYuanLo": None, "gPerYuanHi": None,
            "kcalPer100gProteinLo": None,
        }

        if rule:
            scored = [s for s in (score_candidate(cand, by_name) for cand in rule["candidates"]) if s]
            row["candidates"] = scored
            if scored:
                lo = min(scored, key=lambda s: s["protein"])
                hi = max(scored, key=lambda s: s["protein"])
                row.update({
                    "proteinLo": lo["protein"], "proteinHi": hi["protein"],
                    "kcalLo": min(s["energyKcal"] for s in scored),
                    "kcalHi": max(s["energyKcal"] for s in scored),
                    "gPerYuanLo": round(lo["protein"] / price, 2),
                    "gPerYuanHi": round(hi["protein"] / price, 2),
                    # 每 100g 蛋白附带多少热量：越低越「干净」
                    "kcalPer100gProteinLo": round(
                        min(s["energyKcal"] for s in scored) / hi["protein"] * 100),
                })
        row["confidenceLabel"] = CONF_LABEL.get(row["confidence"], row["confidence"])
        board.append(row)
    return board


def build_calendar(board: list[dict]) -> list[dict]:
    """按星期聚合，形成「一周券日历」。"""
    days = []
    for wd in WEEK_ORDER:
        entries = [r for r in board if wd in r["weekdays"]]
        entries.sort(key=lambda r: r["timeFrom"])
        days.append({
            "weekday": wd,
            "entries": [{
                "title": r["title"],
                "couponPrice": r["couponPrice"],
                "timeFrom": r["timeFrom"],
                "timeTo": r["timeTo"],
                "gPerYuanLo": r["gPerYuanLo"],
                "gPerYuanHi": r["gPerYuanHi"],
                "confidence": r["confidence"],
                "confidenceLabel": r["confidenceLabel"],
                "dateFrom": r["dateFrom"],
            } for r in entries],
        })
    return days


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    by_name = load_items()

    board = build_board(raw, by_name)
    calendar = build_calendar(board)

    counted = [r for r in board if r["gPerYuanLo"] is not None]
    breakfast = [r for r in board if r["timeFrom"] < "12:00"]
    best = max(counted, key=lambda r: r["gPerYuanHi"]) if counted else None

    menu = json.loads(DATASET.read_text(encoding="utf-8"))
    priced = [i for i in menu["items"] if i.get("price") and i["protein"] >= 5]
    menu_best = max(priced, key=lambda i: i["proteinPerYuan"]) if priced else None

    summary = {
        "couponCount": len(board),
        "computable": len(counted),
        "unmatched": len(board) - len(counted),
        "breakfastCount": len(breakfast),
        "daysWithCoupon": sum(1 for d in calendar if d["entries"]),
        "daysWithBreakfastCoupon": sum(
            1 for d in calendar if any(e["timeFrom"] < "12:00" for e in d["entries"])),
        "claimableCount": len(raw.get("claimable", [])),
        "bestCouponTitle": best["title"] if best else None,
        "bestCouponGPerYuanHi": best["gPerYuanHi"] if best else None,
        "bestCouponGPerYuanLo": best["gPerYuanLo"] if best else None,
        "menuBestName": menu_best["name"] if menu_best else None,
        "menuBestGPerYuan": menu_best["proteinPerYuan"] if menu_best else None,
    }

    payload = {
        "source": {**raw["source"], "nutritionTool": "list-nutrition-foods"},
        "board": board,
        "calendar": calendar,
        "claimable": raw.get("claimable", []),
        "summary": summary,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"已写入 {OUT.relative_to(ROOT)}：{summary['couponCount']} 张券，"
          f"其中 {summary['computable']} 张能算出蛋白/{summary['unmatched']} 张无法对齐")
    print(f"早餐时段券 {summary['breakfastCount']} 张，"
          f"一周里 {summary['daysWithBreakfastCoupon']} 天存在早餐窗口")
    if best:
        print(f"券后最高：{best['title']} ¥{best['couponPrice']} -> "
              f"{best['gPerYuanLo']} ~ {best['gPerYuanHi']} g/元")
    if menu_best:
        print(f"菜单原价最高：{menu_best['name']} -> {menu_best['proteinPerYuan']} g/元")
    print("\n逐张券：")
    for r in board:
        span = (f"{r['gPerYuanLo']}~{r['gPerYuanHi']} g/元"
                if r["gPerYuanLo"] is not None else "—")
        print(f"  [{r['confidenceLabel']:<5}] ¥{r['couponPrice']:>5} "
              f"{r['title'][:20]:<22} {'/'.join(r['weekdays']):<16} "
              f"{r['timeFrom']}-{r['timeTo']}  {span}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
