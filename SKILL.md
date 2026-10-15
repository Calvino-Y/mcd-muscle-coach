---
name: mcd-muscle-coach
description: >
  麦门增肌师。当用户想知道「在麦当劳怎么吃才能补足蛋白质」「健身期间麦当劳有没有能吃的」
  「练后吃什么」「还差多少克蛋白该怎么补」「麦当劳哪个餐品蛋白高、热量低」时使用。
  基于麦当劳 MCP 的官方营养成分与实时菜单价格，用穷举求解在给定蛋白缺口下
  最省钱／最低热量的餐品组合，并生成可视化报告。
  This skill should be used when a user wants to hit a protein target using McDonald's China
  menu items, asks which items are high-protein or low-calorie, or needs a post-workout meal plan.
agent_created: true
license: MIT
---

# 麦门增肌师

用麦当劳的官方营养数据，解决一个具体问题：**今天还差 N 克蛋白质，这一顿该怎么点。**

## 什么时候用这个 Skill

触发场景（用户说人话时就是这些）：

- 「我今天还差 40 克蛋白，麦当劳能补吗？」
- 「练完之后在麦当劳吃什么？」
- 「增肌期能吃麦当劳吗，会不会白练？」
- 「麦当劳哪个汉堡蛋白最高、热量最低？」
- 「我想增肌，但不想吃水煮鸡胸」

## 核心概念

两个指标，缺一不可：

| 指标 | 计算方式 | 回答的问题 |
|---|---|---|
| 蛋白性价比 | 蛋白 ÷ 价格 (g/元) | 预算有限时怎么点 |
| 蛋白密度 | 蛋白 ÷ 热量 × 100 (g/100kcal) | 增肌不想增脂时怎么点 |

**这两个指标经常给出相反的答案**——最便宜的往往脂肪最高。所以本 Skill 从不只给一个方案，
而是同时给出「最省钱」和「最清淡」两条路线，由用户决定。

## 工作流

### 第 1 步：确认前提条件

需要环境变量 `MCD_MCP_TOKEN`（麦当劳 MCP Token，在 https://open.mcd.cn/mcp 免费激活）。
若缺失，告知用户申请方式，不要尝试用估算数据替代。

### 第 2 步：取数

```bash
python scripts/build_dataset.py     # 解析营养数据 + 合并价格 -> data/menu.json
```

需要刷新实时价格时，先用 MCP 客户端拉取：

```bash
export MCD_MCP_TOKEN="..."
python scripts/mcd_client.py call query-meals '{"storeCode":"3450032","orderType":1,"beType":1}'
python scripts/mcd_client.py call list-nutrition-foods
```

用 `query-nearby-stores` 与 `delivery-query-stores` 解析用户所在位置的门店编码，
再据此拉取该门店的实时菜单——**不同门店价格和供应状态不同，不要跨门店套用。**

### 第 3 步：求解

```bash
python scripts/coach.py --weight 72 --factor 1.8 --consumed 40
python scripts/coach.py --weight 72 --factor 2.0 --consumed 40 --mode lean
python scripts/coach.py --weight 72 --factor 1.8 --consumed 40 --json
```

参数含义：

- `--weight` 体重 kg
- `--factor` 每公斤体重目标蛋白：休息日 1.6，训练日 2.0–2.2，增肌冲刺 2.4
- `--consumed` 今天已经吃进去的蛋白克数
- `--mode` `budget` 最省钱 / `lean` 最低热量
- `--meal-cap` 单餐蛋白上限，默认 45 g
- `--kcal-cap` 本餐热量上限，默认 900 kcal

### 第 4 步：输出

文字回答必须包含：**点了什么、多少钱、补了多少蛋白、热量多少、还剩多少缺口留给后面的餐次**。

需要可视化时生成报告页：

```bash
python scripts/render_dashboard.py   # -> docs/index.html
```

## 必须遵守的约束

1. **单餐蛋白上限 45 g。** 不要为了补齐一个很大的缺口而推荐 1500 kcal 的一餐——
   那不是增肌是增脂。超出的缺口要明确告诉用户「留给后面几餐」，并给出还要吃几餐。
2. **区分「没涨价」和「没数据」。** 价格缺失的餐品只参与蛋白密度排名，
   绝不参与成本优化，也绝不用估算价格冒充真实价格。
3. **不要伪造数据。** 所有数字必须来自 `data/menu.json`（它由 MCP 真实返回生成）。
   如果数据缺失，直接说缺什么。
4. **这是营养参考，不是医疗建议。** 涉及肾病、代谢疾病、孕期、未成年人的提问，
   明确说明本工具不适用，建议咨询专业医师或注册营养师。
5. **不要替用户下单。** 本 Skill 只负责算清楚该点什么；下单是用户的决定。

## 常见坑

- **饮料会污染蛋白密度榜**：小杯美式是 1 g 蛋白 / 10 kcal，比值 10.0 看起来很高，
  纯属数学噪声。`data/menu.json` 里用 `proteinSource` 字段（蛋白 ≥ 8 g）把它过滤掉了，
  自定义查询时请沿用这个门槛。
- **同名餐品营养值不同**：`麦乐鸡5块` 与 `麦乐鸡4块`、`中薯条` 与 `大薯条`
  都是独立条目，别混用。
- **价格是门店级的**：换门店后必须重新调用 `query-meals`。

## 参考

- MCP 工具参数与调用示例：`references/mcp-tools.md`
- 完整数据字段说明：`MCP_INTEGRATION.md`
- 求解器与网页的一致性由 `tests/test_solver_parity.mjs` 保证，改动求解逻辑后请重跑对拍
