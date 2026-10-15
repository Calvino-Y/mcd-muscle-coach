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

### `query-my-coupons` / `query-store-coupons` — 卡包券与门店券（「限时券 × 蛋白效率」板块）

- **输入**：`query-my-coupons` 无参数（当前账号卡包）；`query-store-coupons` 传门店参数
- **返回**：券名 / 券 ID / 有效期与时段文本 / 优惠方式 / 门店范围
- **在本项目中的角色**：把券从「省几块钱」翻译成「每克蛋白多少钱」。
  中薯条买一送一算下来 **0.59 g/元**；火腿扒堡早餐两件套把每克蛋白压到 **¥0.47–0.71**，
  低于菜单原价冠军（那么大鸡排 ¥0.58/克）——这是不用券的数据根本看不出来的结论。
- **解析器**：`scripts/build_coupons.py`（有效期文本解析见 `parse_validity`，
  能对齐「周一、二、三」这类中文省略写法）
- **诚实口径**：`data/coupons.json` 里每张券都带 `confidence`（deterministic / range /
  partial / unmatched）与 `basis` 字段。8 张券里 3 张在营养表里没有对应条目，标为
  unmatched 并写明原因；配餐有浮动的给区间。**不拿相近餐品凑数。**

### `order-list` — 历史订单（「你的真实订单体检」板块）

- **输入**：无参数（返回当前登录账号的近期订单）
- **返回**：`orderId / createTime / storeCode / storeName / orderStatus / realTotalAmount / orderProductList`
- **在本项目中的角色**：把「理论上该怎么点」和「你实际点了什么」放在同一张桌子上对比。
  每一单都按官方营养表逐件对齐，算出该单的蛋白/热量/钠，以及营养覆盖率。
- **解析器**：`scripts/build_orders.py`
- **隐私处理**：仓库里的 `data/orders_raw.json` 已把 `orderId` 全部替换为 `ORD-0001` 形式的占位符，
  原始订单号不随仓库公开；`storeName` 是公开的门店名称。
- **已知局限**：该 Tool 只返回近期订单（当前快照 10 笔），不是全年账单，页面如实标注区间。

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

order-list
        │  得到历史订单（orderId 已脱敏）
        ▼
build_orders.py           逐单拆套餐 -> 子项，按名称对齐营养表，
        │                 输出每单蛋白/热量/钠 与 营养覆盖率
        ▼
data/orders.json  ──▶  注入同一个面板，「你的真实订单体检」板块

query-my-coupons / query-store-coupons
        │  得到卡包券 + 门店券（名称 / 时段 / 优惠方式）
        ▼
build_coupons.py          逐券对齐营养表，置信度分级（deterministic /
        │                 range / partial / unmatched），聚合一周券日历
        ▼
data/coupons.json ──▶  注入同一个面板，「限时券 × 蛋白效率」板块
```

三条链路在面板里汇合：`menu.json` 回答「该怎么点」，`orders.json` 回答「你实际点了什么」，
`coupons.json` 回答「券能不能让这个答案更便宜」——三者用同一个求解器对比：
「你平均每单花 ¥24.6 确认到 7.5 g 蛋白，同样的钱算法能买到 28 g；而一张 ¥9.9 的早餐券
能把每克蛋白压到 ¥0.47」。

## 3.5 本地工具模式（`scripts/serve.py`）

静态面板的数据是构建时的快照。要让**每个用户跑自己的数据**，本项目提供一个零依赖的
本地代理服务：

```
浏览器(http://127.0.0.1:8765)
      │  页面上填 Token，点连接
      ▼
serve.py（本机进程，只绑 127.0.0.1）
      │  代理 MCP 调用：query-meals / order-list / query-my-coupons ...
      ▼
https://mcp.mcd.cn（Token 只存在于本机内存）
```

**为什么必须有这一层**：实测 `https://mcp.mcd.cn` 的响应**不带 CORS 头**
（`OPTIONS`/`POST` 均返回 403 且无 `Access-Control-Allow-Origin`），浏览器无法直连。
这恰好是正确的设计——Token 不该交给浏览器保管。serve.py 因此承担了双重职责：
替浏览器调 MCP，以及**不把 Token 泄漏给任何人**：

- 只绑定 `127.0.0.1`；校验 `Host` 头（防 DNS rebinding）；拒绝跨站 `Origin`
- 每次启动生成随机会话密钥，`/api/*` 必须携带 `X-McMuscle-Key` → 否则 401
- Token 只存内存，不落盘、不回显；页面注入前做 Token 形态泄漏扫描
- 求解器**不下放**到服务端：页面继续用自己那份 JS 求解器（单一权威），服务端只供数据
- 端到端验证：`python tests/test_serve.py`（安全闸门 13 项 + 降级行为）

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

## 4.5 数据字段说明（`data/coupons.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `source` | obj | 快照元信息：采样时间 / 门店 / 使用到的 MCP 工具 |
| `summary` | obj | 聚合结论：券总数 / 可算数 / 无法对齐数 / 早餐可用数 / 最优券与其 g/元区间 |
| `board[].title` | str | 券名（原样来自 MCP 返回） |
| `board[].couponPrice` | float | 券价（元） |
| `board[].weekdays[]` / `timeFrom` / `timeTo` | list/str | 由有效期文本解析出的可用星期与时段 |
| `board[].confidence` | str | deterministic（单值可算）/ range（区间）/ partial（部分可算）/ unmatched（无法对齐） |
| `board[].basis` | str | 该结论的推算依据（对齐到哪个营养条目、为什么是区间） |
| `board[].proteinLo` / `proteinHi` | float | 券内餐品的蛋白区间 |
| `board[].gPerYuanLo` / `gPerYuanHi` | float | 券后 g/元 区间（unmatched 时为 null） |
| `board[].candidates[]` | list | 参与推算的营养条目明细（可追溯） |
| `calendar[]` | list | 按星期聚合的一周券日历：`weekday` + `entries[]`（券 / 价格 / 时段 / 置信度） |
| `claimable` | list | 当前可领但未领的门店券（MCP 原样字段） |

## 5. 业务价值

**把麦当劳从「增肌禁忌」变成「可计算的蛋白质补给站」。**

- 对健身人群：给出可执行的「今天还差多少克、这一顿点什么」，而不是一句「少吃油炸」。
- 对麦当劳：把营养数据的透明度变成复购理由——用户越容易算清楚，越敢在减脂期下单。
  券链路还额外回答了「券怎么和营养目标配合」：¥9.9 的早餐两件套能把每克蛋白压到
  ¥0.47，比菜单上任何原价单品都低——这是把优惠券从「促销工具」变成「营养工具」。
- 对 MCP 生态：示范了「营养数据 + 实时价格 + 历史订单 + 卡包券」四条 Tool 链路怎么
  对齐成一个可优化的决策问题，并用同一套求解器做「理想 vs 现实」的对照；
  `serve.py` 进一步示范了「CORS 不放行时，怎么安全地让每个用户跑自己的数据」。
  这是单纯查询类 Skill 做不到的。

## 6. 可复现性与验证

- `data/nutrition_raw.txt` 是 `list-nutrition-foods` 的**原始响应快照**，任何人重跑同一 Tool 都应得到一致数据。
- `data/coupons_raw.json` 是 `query-my-coupons` / `query-store-coupons` / `available-coupons`
  的原始快照，`data/coupons.json` 由 `scripts/build_coupons.py` 生成，每条结论可追溯。
- `data/menu.json` 由 `scripts/build_dataset.py` 从快照生成，构建过程无人工干预。
- 前端求解器与 Python 求解器的一致性由 `tests/test_solver_parity.mjs` 保证（12 个场景逐字段对拍）。
- `serve.py` 的安全闸门由 `tests/test_serve.py` 端到端验证（Host/Origin/密钥/Token 泄漏/降级）。

```bash
python scripts/export_parity_fixture.py && node tests/test_solver_parity.mjs
```
