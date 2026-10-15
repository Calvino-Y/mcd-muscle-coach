#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门增肌师 · 核心引擎。

解决的问题：
    你今天还差 N 克蛋白质没吃够，在麦当劳里怎么买最划算？

为什么需要代码而不是让大模型口算：
    「组合最优」是一个带约束的整数规划。模型口算会漏掉「双份小食拼起来比
    一份大套餐更划算」这类解。这里用穷举求解，结果可复现、可验证。

用法::

    python scripts/coach.py --weight 70 --factor 1.8 --consumed 40
    python scripts/coach.py --weight 70 --factor 2.0 --consumed 40 --mode lean
    python scripts/coach.py --weight 70 --factor 1.8 --consumed 40 --json
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MENU = ROOT / "data" / "menu.json"

MAX_ITEMS = 3        # 一顿最多点几种不同的东西（再多就不像人话了）
MAX_QTY = 2          # 组合里同一样最多点两份
MAX_SINGLE_QTY = 6   # 只点一样时最多能点几份（要覆盖「一份单品管饱」的场景）
PROTEIN_FLOOR = 5    # 单份蛋白低于 5g 的不参与凑蛋白（牛奶 7g 保留，可乐 0g 剔除）

DEFAULT_MEAL_CAP = 45.0   # 单餐建议最多补多少克蛋白（再多，热量代价会失控）
DEFAULT_KCAL_CAP = 900.0  # 补蛋白这一餐的热量上限


def load_items() -> list[dict]:
    data = json.loads(MENU.read_text(encoding="utf-8"))
    return data["items"]


def build_pool(items: list[dict]) -> list[dict]:
    """只保留「有真实价格 + 蛋白量有意义 + 不是纯饮料」的餐品。"""
    pool = [
        it for it in items
        if it.get("price") and it["protein"] >= PROTEIN_FLOOR and it["category"] != "drink"
    ]
    return sorted(pool, key=lambda x: -x["proteinPerYuan"])


def _combos(pool: list[dict]):
    """生成候选解。

    关键点：``size == 1`` 时放开份数上限（到 MAX_SINGLE_QTY），
    否则「那么大鸡排 ×4」这种最优解根本不在搜索空间里，
    求解器会输给它自己的对照组——那是算法 bug，不是真实结论。
    """
    for size in range(1, MAX_ITEMS + 1):
        for group in itertools.combinations(pool, size):
            limit = MAX_SINGLE_QTY if size == 1 else MAX_QTY
            for qtys in itertools.product(range(1, limit + 1), repeat=size):
                yield size, list(zip(group, qtys))


def _evaluate(combo) -> dict:
    return {
        "items": [
            {
                "name": it["name"], "qty": q, "price": it["price"],
                "protein": it["protein"], "energyKcal": it["energyKcal"],
                "fat": it["fat"], "sodium": it["sodium"],
                "code": it.get("code"),
            }
            for it, q in combo
        ],
        "totalPrice": round(sum(it["price"] * q for it, q in combo), 1),
        "totalProtein": round(sum(it["protein"] * q for it, q in combo), 1),
        "totalKcal": round(sum(it["energyKcal"] * q for it, q in combo)),
        "totalFat": round(sum(it["fat"] * q for it, q in combo), 1),
        "totalSodium": round(sum(it["sodium"] * q for it, q in combo)),
    }


def solve(gap_g: float, pool: list[dict], mode: str = "budget",
          kcal_cap: float | None = None) -> dict | None:
    """在满足蛋白缺口的前提下求全局最优解。

    mode="budget": 总价最低（省钱）
    mode="lean"  : 总热量最低（增肌不想增脂）
    """
    if gap_g <= 0:
        return None

    best = None
    for _size, combo in _combos(pool):
        cand = _evaluate(combo)
        if cand["totalProtein"] < gap_g:
            continue
        if kcal_cap and cand["totalKcal"] > kcal_cap:
            continue
        # budget 以总价为主、热量为辅；lean 反之。用元组比较天生就是字典序最优。
        key = (cand["totalPrice"], cand["totalKcal"]) if mode == "budget" \
            else (cand["totalKcal"], cand["totalPrice"])
        if best is None or key < best[0]:
            best = (key, cand)

    if best is None:
        return None

    result = best[1]
    result["proteinPerYuan"] = round(result["totalProtein"] / result["totalPrice"], 2)
    result["proteinPer100kcal"] = round(result["totalProtein"] / result["totalKcal"] * 100, 2)
    result["overshoot"] = round(result["totalProtein"] - gap_g, 1)
    result["itemCount"] = len(result["items"])
    return result


def single_item_baseline(gap_g: float, pool: list[dict], mode: str = "budget") -> dict | None:
    """对照组：不许组合，只能反复点同一样，最少要花多少钱 / 多少热量。"""
    best = None
    for it in pool:
        n = int(-(-gap_g // it["protein"]))  # 向上取整
        if n <= 0:
            continue
        cand = {
            "name": it["name"], "qty": n,
            "price": round(it["price"] * n, 1),
            "protein": round(it["protein"] * n, 1),
            "energyKcal": round(it["energyKcal"] * n),
        }
        key = (cand["price"], cand["energyKcal"]) if mode == "budget" \
            else (cand["energyKcal"], cand["price"])
        if best is None or key < best[0]:
            best = (key, cand)
    return best[1] if best else None


def analyse(weight_kg: float, factor: float, consumed_g: float,
            mode: str = "budget",
            meal_cap: float = DEFAULT_MEAL_CAP,
            kcal_cap: float | None = DEFAULT_KCAL_CAP) -> dict:
    items = load_items()
    pool = build_pool(items)
    target = round(weight_kg * factor)
    remaining = round(target - consumed_g, 1)

    # 这一餐能吃下多少？缺口再大，单餐也是有上限的：
    # 硬把 90g 蛋白塞进一顿，代价是 1500+ kcal，那不是增肌是增脂。
    # 超出单餐上限的部分，留给后面的餐次。
    meal_gap = round(max(0.0, min(remaining, meal_cap)), 1)
    meals_needed = int(-(-max(remaining, 0) // meal_cap)) if remaining > 0 else 0

    budget_plan = solve(meal_gap, pool, mode="budget", kcal_cap=kcal_cap)
    lean_plan = solve(meal_gap, pool, mode="lean", kcal_cap=kcal_cap)
    plan = budget_plan if mode == "budget" else lean_plan
    baseline = single_item_baseline(meal_gap, pool, mode=mode)

    result = {
        "input": {"weightKg": weight_kg, "proteinFactor": factor,
                  "consumedProtein": consumed_g, "mode": mode,
                  "mealCap": meal_cap, "kcalCap": kcal_cap},
        "target": {"targetProtein": target,
                   "remainingProtein": remaining,
                   "mealProtein": meal_gap,
                   "mealsNeeded": meals_needed,
                   "splitAcrossMeals": remaining > meal_cap},
        "plan": plan,
        "budgetPlan": budget_plan,
        "leanPlan": lean_plan,
        "baseline": baseline,
        "savings": None,
        "headToHead": None,
    }

    # 同样是补足这一餐的缺口：最省钱的方案 vs 最清淡的方案，差多少？
    if budget_plan and lean_plan and budget_plan != lean_plan:
        result["headToHead"] = {
            "priceDelta": round(lean_plan["totalPrice"] - budget_plan["totalPrice"], 1),
            "kcalDelta": budget_plan["totalKcal"] - lean_plan["totalKcal"],
            "fatDelta": round(budget_plan["totalFat"] - lean_plan["totalFat"], 1),
        }

    if plan and baseline and mode == "budget":
        save = round(baseline["price"] - plan["totalPrice"], 1)
        result["savings"] = {
            "yuan": save,
            "percent": round(save / baseline["price"] * 100) if baseline["price"] else 0,
            "kcal": baseline["energyKcal"] - plan["totalKcal"],
        }
    return result


def render_cli(res: dict) -> None:
    inp, tgt, plan, base = res["input"], res["target"], res["plan"], res["baseline"]
    mode_cn = "最省钱" if inp["mode"] == "budget" else "最低热量"
    print(f"\n体重 {inp['weightKg']:g} kg × {inp['proteinFactor']:g} g/kg"
          f" = 每日目标 {tgt['targetProtein']} g 蛋白")
    print(f"今日已摄入 {inp['consumedProtein']:g} g → 全天还差 {tgt['remainingProtein']:g} g")

    if tgt["splitAcrossMeals"]:
        print(f"单餐最多补 {inp['mealCap']:g} g，建议分 {tgt['mealsNeeded']} 餐吃完，"
              f"本餐先补 {tgt['mealProtein']:g} g\n")
    else:
        print()

    if not plan:
        print("缺口已经补齐，不需要再点。")
        return

    print(f"本餐推荐（{mode_cn}）：")
    for it in plan["items"]:
        print(f"  · {it['name']} ×{it['qty']}   ¥{it['price'] * it['qty']:>5.1f}"
              f"   蛋白 {it['protein'] * it['qty']:>4.0f}g   热量 {it['energyKcal'] * it['qty']:>4.0f}kcal")
    print(f"\n  合计 ¥{plan['totalPrice']}   蛋白 {plan['totalProtein']}g"
          f"   热量 {plan['totalKcal']}kcal   脂肪 {plan['totalFat']}g   钠 {plan['totalSodium']}mg")
    print(f"  蛋白性价比 {plan['proteinPerYuan']} g/元   蛋白密度 {plan['proteinPer100kcal']} g/100kcal")

    if base and res["savings"] and res["savings"]["yuan"] > 0:
        print(f"\n对照：只单点「{base['name']}」×{base['qty']} 要 ¥{base['price']}")
        print(f"组合方案省下 ¥{res['savings']['yuan']}（{res['savings']['percent']}%），"
              f"少吃 {res['savings']['kcal']} kcal")

    h2h = res.get("headToHead")
    if h2h and res["budgetPlan"] and res["leanPlan"]:
        b, l = res["budgetPlan"], res["leanPlan"]
        bn = " + ".join(f"{i['name']}×{i['qty']}" for i in b["items"])
        ln = " + ".join(f"{i['name']}×{i['qty']}" for i in l["items"])
        print("\n同一个蛋白缺口的两种解法：")
        print(f"  最省钱  ¥{b['totalPrice']:>5.1f}   {b['totalKcal']:>4.0f}kcal   {bn}")
        print(f"  最清淡  ¥{l['totalPrice']:>5.1f}   {l['totalKcal']:>4.0f}kcal   {ln}")
        print(f"  → 多花 ¥{h2h['priceDelta']} 可以少摄入 {h2h['kcalDelta']} kcal"
              f"、少 {h2h['fatDelta']} g 脂肪")


def main() -> int:
    ap = argparse.ArgumentParser(description="麦门增肌师 · 蛋白质补齐方案求解器")
    ap.add_argument("--weight", type=float, required=True, help="体重 kg")
    ap.add_argument("--factor", type=float, default=1.8,
                    help="每公斤体重目标蛋白克数：休息日 1.6，训练日 2.0～2.2")
    ap.add_argument("--consumed", type=float, default=0, help="今天已经吃进去的蛋白克数")
    ap.add_argument("--mode", choices=["budget", "lean"], default="budget")
    ap.add_argument("--meal-cap", type=float, default=DEFAULT_MEAL_CAP,
                    help=f"单餐最多补多少克蛋白，默认 {DEFAULT_MEAL_CAP:g}")
    ap.add_argument("--kcal-cap", type=float, default=DEFAULT_KCAL_CAP,
                    help=f"本餐热量上限 kcal，默认 {DEFAULT_KCAL_CAP:g}，设 0 表示不限")
    ap.add_argument("--json", action="store_true", help="输出 JSON，供渲染器消费")
    args = ap.parse_args()

    kcal_cap = args.kcal_cap if args.kcal_cap and args.kcal_cap > 0 else None
    res = analyse(args.weight, args.factor, args.consumed, args.mode,
                  args.meal_cap, kcal_cap)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        render_cli(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
