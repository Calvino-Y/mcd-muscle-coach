#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MCP 拉到的原始数据整理成菜单数据集 data/menu.json。

数据来源（全部来自麦当劳 MCP 的真实返回，零人工编造）：
  * 营养数据  tool: list-nutrition-foods   -> data/nutrition_raw.txt（原始响应快照）
  * 价格数据  tool: query-meals            -> PRICES 表（下方，逐条抄自真实菜单返回）

价格缺失的餐品保留 ``price: null``，它们仍会参与「蛋白密度（g/100kcal）」
排名，只是不参与「蛋白性价比（g/元）」排名——我们不用估算数字冒充真实价格。
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "nutrition_raw.txt"
OUT = ROOT / "data" / "menu.json"

# 门店：麦当劳成都万达餐厅 (storeCode=3450032)，到店自取场景，采样时间 2026-10-15
STORE = {"storeCode": "3450032", "storeName": "麦当劳成都万达餐厅", "beType": 1}

# 进「蛋白密度榜」的最低门槛：蛋白 < 8g 的餐品（饮料、小食）不参与排名，
# 否则「1g 蛋白 / 10kcal」的冰美式会以 10.0 的比值霸榜，那是数学噪声不是营养学。
MIN_PROTEIN_G = 8.0

# 餐品编码 -> (菜单名, 现价)。同一餐品在营养表里的名称可能略有差异，用 ALIASES 对齐。
PRICES: dict[str, tuple[str, float]] = {
    "1100": ("巨无霸", 25.5),
    "1120": ("双层吉士汉堡", 23.0),
    "1106": ("培根蔬萃双层牛堡", 24.5),
    "4648": ("不素之霸双层牛堡", 26.5),
    "1440": ("麦辣鸡腿汉堡", 22.5),
    "1406": ("板烧鸡腿堡", 23.5),
    "1450": ("麦香鸡", 17.0),
    "1600": ("麦香鱼", 22.5),
    "9900003586": ("双层深海鳕鱼堡", 24.0),
    "1401": ("麦乐鸡5块", 14.0),
    "1700": ("麦辣鸡翅-2块", 15.0),
    "520445": ("薄皮焦香V翅", 16.0),
    "521156": ("那么大鸡排", 14.0),
    "9900005432": ("麦麦脆汁鸡-带骨里脊", 15.0),
    "4437": ("大杯玉米杯", 13.0),
    "4810": ("中薯条", 13.5),
    "6102": ("苹果片", 7.0),
    "515837": ("圆筒冰淇淋", 5.0),
    "9900008745": ("草莓新地", 12.0),
    "9900008754": ("奥利奥麦旋风", 15.5),
    "521950": ("蓝莓爆爆珠麦旋风", 16.5),
    "9900008751": ("可乐中杯", 9.5),
    "3010": ("雪碧中杯", 9.5),
    "520689": ("小杯鲜萃咖啡", 9.5),
    "3755": ("纯牛奶（盒装）", 10.5),
    "510488": ("冰燕麦奶中杯", 21.0),
    "507409": ("热奶铁中杯", 13.9),
    "6362": ("100%苹果汁", 11.5),
    "9900015602": ("大堡口福三件套", 22.9),
    "9900009245": ("牛气满满套餐", 35.0),
    "9900009242": ("“苹板”支撑Pro套餐", 39.5),
    "9900011123": ("“辣”么快乐套餐", 24.0),
    "9900011126": ("酥脆无双套餐", 20.0),
    "9900016076": ("“我就喜欢”鸡薯双全盒", 15.9),
    "9900016078": ("蘸酱麦麦脆汁鸡", 11.9),
    "9900016079": ("蘸酱脆皮鸡柳", 11.9),
    "9900016308": ("蘸酱脆皮鸡块8块", 19.9),
}

# 营养表里的名字 -> 需要额外挂上的价格（营养名与菜单名不一致时的桥接）
ALIASES = {
    "麦乐鸡5块": "麦乐鸡5块",
    "麦辣鸡翅-2块": "麦辣鸡翅-2块",
    "那么大鸡排": "那么大鸡排",
    "麦麦脆汁鸡-带骨里脊": "麦麦脆汁鸡-带骨里脊",
    "大杯玉米杯": "大杯玉米杯",
    "中薯条": "中薯条",
    "圆筒冰淇淋": "圆筒冰淇淋",
    "草莓新地": "草莓新地",
    "奥利奥麦旋风": "奥利奥麦旋风",
    "可乐中杯": "可乐中杯",
    "雪碧中杯": "雪碧中杯",
    "小杯鲜萃咖啡": "小杯鲜萃咖啡",
    "纯牛奶（盒装）": "纯牛奶（盒装）",
    "热奶铁中杯": "热奶铁中杯",
    "100%苹果汁": "100%苹果汁",
}

BREAKFAST_KEYS = ("麦满分", "营养卷", "粥", "厚松饼", "炒双蛋", "薯饼", "油条")
DRINK_KEYS = ("可乐", "雪碧", "咖啡", "牛奶", "奶铁", "燕麦奶", "红茶", "果汁", "朱古力",
              "豆浆", "美式", "玛奇朵", "卡布奇诺", "抹茶牛奶", "黑巧", "雪冰", "怡泉",
              "阳光橙", "苹果汁", "纯悦", "柠檬红茶")
CHICKEN_KEYS = ("鸡", "翅", "脆皮", "香肠", "鳕鱼")
DESSERT_KEYS = ("冰淇淋", "新地", "麦旋风", "派", "拉明顿", "阿芙佳朵", "圆筒")


def categorise(name: str) -> str:
    if any(k in name for k in BREAKFAST_KEYS):
        return "breakfast"
    if any(k in name for k in DRINK_KEYS):
        return "drink"
    if any(k in name for k in DESSERT_KEYS):
        return "dessert"
    if name.endswith(("三件套", "四件套", "套餐", "小食盘", "随心选", "随心配")):
        return "combo"
    if any(k in name for k in ("薯条", "玉米杯", "苹果片", "鸡块", "鸡球")):
        return "side"
    if any(k in name for k in CHICKEN_KEYS):
        return "chicken"
    if any(k in name for k in ("堡", "卷")):
        return "burger"
    return "other"


def parse_nutrition_text(text: str) -> list[dict]:
    """解析「名称,描述,kJ,kcal,蛋白,脂肪,碳水,钠,钙」九列文本。

    注意：描述列不一定是 null，曼哈顿写法有「能量约鲈鱼1条」这类文案，
    所以不能靠 "null," 过滤，只能靠「后七列必须都是数字」来判定有效行。

    接受字符串而非路径，是为了让本地工具模式 scripts/serve.py 能直接吃
    MCP 的实时返回——同一份解析逻辑，不在两个地方各写一遍。
    """
    rows: list[dict] = []
    for line in text.splitlines():
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
        rows.append({
            "name": parts[0],
            "energyKj": num[0],
            "energyKcal": num[1],
            "protein": num[2],
            "fat": num[3],
            "carbs": num[4],
            "sodium": num[5],
            "calcium": num[6],
        })
    return rows


def parse_nutrition(path: pathlib.Path) -> list[dict]:
    return parse_nutrition_text(path.read_text(encoding="utf-8"))


def price_table(live: dict[str, float] | None = None) -> dict[str, tuple[str, float]]:
    """菜单名 / 别名 -> (餐品编码, 价格)。

    ``live`` 是「餐品编码 -> 实时价格」，来自 query-meals。传入时会覆盖静态表里的
    价格——本地工具模式就是靠这一点，换门店、换一天重新拉一次菜单即可拿到
    当地当天的真实价格，不需要改代码。
    """
    table: dict[str, tuple[str, float]] = {}
    for code, (menu_name, price) in PRICES.items():
        p = (live or {}).get(code, price)
        table[menu_name] = (code, p)
        if menu_name in ALIASES:
            table[ALIASES[menu_name]] = (code, p)
    return table


def assemble(rows: list[dict], live: dict[str, float] | None = None) -> list[dict]:
    """给营养行挂上 code / price / category，并计算全部派生指标。"""
    table = price_table(live)
    for row in rows:
        hit = table.get(row["name"])
        row["code"] = hit[0] if hit else None
        row["price"] = hit[1] if hit else None
        row["category"] = categorise(row["name"])

    # 派生指标：全部由真实字段计算，不做任何假设
    for row in rows:
        kcal, protein = row["energyKcal"], row["protein"]
        row["proteinPer100kcal"] = round(protein / kcal * 100, 2) if kcal > 0 else 0.0
        row["proteinPerYuan"] = round(protein / row["price"], 2) if row["price"] else None
        row["kcalPerYuan"] = round(kcal / row["price"], 1) if row["price"] else None
        # 小杯美式是 1g 蛋白 / 10kcal，比值被人为放大到 10.0，属于数学噪声。
        # 只有「蛋白量本身有意义的餐品」才配进排行榜，否则排名会被饮料霸榜。
        row["proteinSource"] = protein >= MIN_PROTEIN_G and kcal >= 50
    return rows


def live_prices_from_meals(payload: dict) -> dict[str, float]:
    """从 query-meals 的返回里抽出「餐品编码 -> 现价」。"""
    out: dict[str, float] = {}
    for code, meal in (payload.get("data", {}).get("meals") or {}).items():
        price = meal.get("currentPrice")
        if price in (None, ""):
            continue
        try:
            out[code] = float(price)
        except (TypeError, ValueError):
            continue
    return out


def build_payload(rows: list[dict], store: dict | None = None,
                  captured_at: str = "", live: dict[str, float] | None = None) -> dict:
    return {
        "source": {
            "nutritionTool": "list-nutrition-foods",
            "priceTool": "query-meals",
            "store": store or STORE,
            "capturedAt": captured_at,
            "livePriced": bool(live),
            "totalItems": len(rows),
        },
        "items": rows,
    }


def main() -> int:
    rows = parse_nutrition(RAW)
    if not rows:
        raise SystemExit(f"未能从 {RAW} 解析出任何营养数据")

    assemble(rows)
    dataset = build_payload(rows, captured_at="2026-10-15")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    priced = [r for r in rows if r["price"]]
    print(f"已写入 {OUT.relative_to(ROOT)}：共 {len(rows)} 项，其中有真实价格的 {len(priced)} 项")
    print("\n蛋白密度 TOP 10（g / 100kcal，仅统计蛋白≥8g 的餐品）:")
    pool = [r for r in rows if r["proteinSource"]]
    for r in sorted(pool, key=lambda x: -x["proteinPer100kcal"])[:10]:
        print(f"  {r['name']:<28} {r['protein']:>5.0f}g  {r['energyKcal']:>5.0f}kcal  "
              f"{r['proteinPer100kcal']:>5.2f}")
    print("\n蛋白性价比 TOP 10（g / 元，仅含已采集价格）:")
    for r in sorted([r for r in priced if r["proteinSource"]], key=lambda x: -x["proteinPerYuan"])[:10]:
        print(f"  {r['name']:<28} {r['protein']:>5.0f}g  ¥{r['price']:>5.1f}  "
              f"{r['proteinPerYuan']:>5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
