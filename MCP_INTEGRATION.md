# MCP 集成说明 · MCP_INTEGRATION

本文说明本项目实际使用的麦当劳 MCP Server、每个 Tool 的用途、调用流程，以及这些数据带来的业务价值。

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | `Authorization: Bearer <MCP_TOKEN>` 请求头 |
| Token 获取 | https://open.mcd.cn/mcp → 手机号登录 → 控制台激活 |
| 限流 | 600 次/分钟，超限返回 429 |

客户端实现见 `scripts/mcd_client.py`，仅用 Python 标准库 `urllib`，零第三方依赖。

**实现要点**（踩过的坑，写下来省得下一个人再踩）：

- 请求头必须同时声明 `Accept: application/json, text/event-stream`，只声明 `application/json` 会拿不到响应。
- `initialize` 成功后，服务端可能通过响应头下发 `Mcp-Session-Id`，**后续所有请求都要原样带回**，否则会话失效。
- 响应可能是纯 JSON，也可能是 SSE（`data: {...}` 逐行），客户端两种都要能解。
- `initialize` 之后按规范补一条 `notifications/initialized` 通知（无 id、无需等待响应）。

## 2. 使用的 Tool 及用途

### `list-nutrition-foods` — 营养成分（本项目的数据地基）

- **输入**：无参数
- **返回**：158 项餐品的 `productName / energyKj / energyKcal / protein / fat / carbohydrate / sodium / calcium`
- **在本项目中的角色**：蛋白密度（g/100kcal）与蛋白性价比（g/元）的分子来源
- **解析器**：`scripts/build_dataset.py::parse_nutrition`

注意：描述列不一定是 `null`，存在「能量约鲈鱼1条」这类文案，所以解析时**不能**按 "null," 过滤行，必须靠「后七列全部可解析为数字」来判定有效行。

### `query-meals` — 实时菜单与价格

- **输入**：`storeCode`（必填）、`orderType`（1 到店 / 2 外送）、`beType`、`beCode`（得来速/外送必传）、`reservationDate`（预约场景）
- **返回**：`categories[]`（分类与餐品编码）、`meals`（code → 名称/图片/现价/划线价/优惠类型）
- **在本项目中的角色**：蛋白性价比的分母来源。**没有它，"一克蛋白多少钱" 就无从谈起**
- **关键约束**：价格是门店级的。换门店必须重新调用

### `query-nearby-stores` / `delivery-query-stores` — 门店解析

- **输入**：`searchType`、`city`、`keyword`、`beType`（1 到店自提 / 5 得来速 / 2 外送）
- **返回**：门店列表，含 `storeCode` 与 `beCode`
- **在本项目中的角色**：把用户说的「我在 XX 附近」翻译成 `storeCode`，供 `query-meals` 使用

### `calculate-price` / `create-order` — 结算与下单（可选链路）

- 本项目的默认行为是**算清楚该点什么，然后把下单这个动作交还给用户**。
- 若用户明确要求代下单，可继续调用 `calculate-price` 校验金额（含优惠券），再 `create-order` 生成支付链接。Skill 定义里明确写了：**未经用户确认不得调用**。

## 3. 调用流程

```
query-nearby-stores (beType=1)
        │  得到 storeCode
        ▼
query-meals (storeCode, orderType=1, beType=1)
        │  得到 code -> currentPrice 映射
        ▼
list-nutrition-foods
        │  得到 name -> 营养字段 映射
        ▼
build_dataset.py          按名称对齐两份数据，派生
        │                 proteinPer100kcal / proteinPerYuan / proteinSource
        ▼
data/menu.json
        │
        ├─▶ coach.py      穷举 4150 个候选组合，求「蛋白≥缺口」下
        │                 总价最低 / 总热量最低
        └─▶ render_dashboard.py   生成 docs/index.html 可视化面板
```

## 4. 数据字段说明（`data/menu.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 餐品名（来自营养表） |
| `code` | str \| null | 餐品编码（来自菜单，未匹配到则为 null） |
| `price` | float \| null | 现价（元）。**null 表示未采集到，不代表免费** |
| `energyKcal` / `protein` / `fat` / `carbs` / `sodium` / `calcium` | float | 官方营养字段，原样透传 |
| `proteinPer100kcal` | float | 蛋白 ÷ 热量 × 100 |
| `proteinPerYuan` | float \| null | 蛋白 ÷ 价格，价格缺失时为 null |
| `proteinSource` | bool | 蛋白 ≥ 8g 且热量 ≥ 50kcal。用于过滤「1g 蛋白/10kcal」这类数学噪声 |
| `category` | str | breakfast / burger / chicken / side / dessert / drink / combo / other |

## 5. 业务价值

**把麦当劳从「增肌禁忌」变成「可计算的蛋白质补给站」。**

- 对健身人群：给出可执行的「今天还差多少克、这一顿点什么」，而不是一句「少吃油炸」。
- 对麦当劳：把营养数据的透明度变成复购理由——用户越容易算清楚，越敢在减脂期下单。
- 对 MCP 生态：示范了「营养数据 + 实时价格」两条 Tool 链路怎么对齐成一个可优化的决策问题，这是单纯查询类 Skill 做不到的。

## 6. 可复现性与验证

- `data/nutrition_raw.txt` 是 `list-nutrition-foods` 的**原始响应快照**，任何人重跑同一 Tool 都应得到一致数据。
- `data/menu.json` 由 `scripts/build_dataset.py` 从快照生成，构建过程无人工干预。
- 前端求解器与 Python 求解器的一致性由 `tests/test_solver_parity.mjs` 保证（12 个场景逐字段对拍）。

```bash
python scripts/export_parity_fixture.py && node tests/test_solver_parity.mjs
```
