---
name: mcd-muscle-coach
description: >
  麦门增肌师。当用户想知道「在麦当劳怎么吃才能补足蛋白质」「健身期间麦当劳有没有能吃的」
  「练后吃什么」「还差多少克蛋白该怎么补」「麦当劳哪个餐品蛋白高、热量低」
  「我的麦当劳优惠券怎么用最划算」「哪张券蛋白性价比高」时使用。
  基于麦当劳 MCP 的官方营养成分与实时菜单价格，用穷举求解在给定蛋白缺口下
  最省钱／最低热量的餐品组合，并结合卡包券算出券后每克蛋白的真实成本，
  生成可视化报告。
  This skill should be used when a user wants to hit a protein target using McDonald's China
  menu items, asks which items are high-protein or low-calorie, which coupon gives the cheapest
  protein, or needs a post-workout meal plan.
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
- 「我想增肌，练后想吃够蛋白」
- 「30 块钱在麦当劳最多能买到多少蛋白？」
- 「我在麦当劳都吃了什么？那些单子蛋白够吗？」
- 「我卡包里的券哪张最划算？」
- 「早餐时段在麦当劳吃什么蛋白最够？」
- 「帮我跑一遍我自己的麦当劳数据」（本地工具模式）

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
python scripts/build_orders.py      # 可选：历史订单 + 营养对齐 -> data/orders.json
python scripts/build_coupons.py     # 可选：卡包券/门店券 + 营养对齐 -> data/coupons.json
```

`build_orders.py` 需要 `data/orders_raw.json`（`order-list` 的原始返回，orderId 已脱敏）。
需要拉取用户自己的订单时：

```bash
python scripts/mcd_client.py call order-list > data/orders_raw.json
```

`build_coupons.py` 需要 `data/coupons_raw.json`（`query-my-coupons` 与 `query-store-coupons`
的原始返回）。拉取方式见 `references/mcp-tools.md`。

需要刷新实时价格时，先用 MCP 客户端拉取：

```bash
export MCD_MCP_TOKEN="..."
python scripts/mcd_client.py call query-meals '{"storeCode":"3450032","orderType":1,"beType":1}'
python scripts/mcd_client.py call list-nutrition-foods
```

用 `query-nearby-stores` 与 `delivery-query-stores` 解析用户所在位置的门店编码，
再据此拉取该门店的实时菜单——**不同门店价格和供应状态不同，不要跨门店套用。**

### 第 2.5 步：用户想看「自己的」面板时，用本地工具模式

静态面板展示的是构建时的快照（我们的账号）。当用户说「用我自己的数据跑一遍」时，
启动本地工具服务而不是手工替换数据：

```bash
python scripts/serve.py          # 打开 http://127.0.0.1:8765，页面上填 Token 连接
```

服务在本机代理全部 MCP 调用（菜单 / 订单 / 券），把结果写进页面并整页刷新。
**不要让用户把 Token 发到对话里**——那是给本地页面填的，Agent 不需要也不应该经手。
安全设计细节见 `MCP_INTEGRATION.md` 与 `tests/test_serve.py`。

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
node tests/check_page.mjs            # 生成后务必自检一次
```

面板包含十三块：你的账号（双模式入口）、缺口/预算双模式求解器（含预算边际收益曲线）、
真实订单体检、限时券 × 蛋白效率（含一周券日历）、早餐增肌窗口、双排行榜、
蛋白质量榜（钠/钙/脂肪负荷）、蛋白×热量散点图、帕累托前沿、点法对比表、
品类战力榜、一周补给计划、分享卡片导出。

回答「哪张券最划算」时，直接引用 `data/coupons.json` 的结论：
可确定口径的券给出券后 g/元 或 ¥/g（含区间），无法对齐营养表的券如实说明并给出依据。

## 必须遵守的约束

1. **单餐蛋白上限 45 g。** 不要为了补齐一个很大的缺口而推荐 1500 kcal 的一餐——
   那不是增肌是增脂。超出的缺口要明确告诉用户「留给后面几餐」，并给出还要吃几餐。
2. **区分「没涨价」和「没数据」。** 价格缺失的餐品只参与蛋白密度排名，
   绝不参与成本优化，也绝不用估算价格冒充真实价格。
3. **不要伪造数据。** 所有数字必须来自 `data/menu.json`（它由 MCP 真实返回生成）。
   如果数据缺失，直接说缺什么。
4. **券的三态标注。** 券能对齐营养表就给单值；配餐存在浮动就给区间并写明推算依据；
   对不上就标「无法对齐」并说明原因。**绝不拿相近餐品替换去凑一个好看的数。**
5. **这是营养参考，不是医疗建议。** 涉及肾病、代谢疾病、孕期、未成年人的提问，
   明确说明本工具不适用，建议咨询专业医师或注册营养师。
6. **不要替用户下单。** 本 Skill 只负责算清楚该点什么；下单是用户的决定。

## 常见坑

- **饮料会污染蛋白密度榜**：小杯美式是 1 g 蛋白 / 10 kcal，比值 10.0 看起来很高，
  纯属数学噪声。`data/menu.json` 里用 `proteinSource` 字段（蛋白 ≥ 8 g）把它过滤掉了，
  自定义查询时请沿用这个门槛。
- **同名餐品营养值不同**：`麦乐鸡5块` 与 `麦乐鸡4块`、`中薯条` 与 `大薯条`
  都是独立条目，别混用。
- **价格是门店级的**：换门店后必须重新调用 `query-meals`。
- **订单里的餐品经常对不上营养表**：用户实际点的东西（套餐、新品、限定款）很多不在
  `list-nutrition-foods` 里。当前快照覆盖率只有 55%。未匹配的一律计 0 并标注覆盖率，
  绝不拿相近餐品估算填充——否则「订单体检」会变成编故事。
- **券也一样对不上**：8 张券里有 3 张在营养表里没有对应条目（拼盘类、早餐限定堡类）。
  「火腿扒堡早餐两件套」这类配餐有浮动的券给区间而不是单值，`data/coupons.json` 里
  每张券都写了 `confidence` 与 `basis`。
- **券的时段文本要人肉核一遍**：`query-my-coupons` 返回的是「周一、二、三 10:30–23:59」
  这类中文省略写法，解析逻辑在 `scripts/build_coupons.py::parse_validity`，改动前先看快照。
- **浏览器不能直连 MCP**：`https://mcp.mcd.cn` 不带 CORS 头（实测 403）。任何
  「让网页直接调 MCP」的想法都走不通，必须走 `scripts/serve.py` 的本地代理。
- **改了面板模板必须跑两类检查**：`node tests/check_page.mjs` 抓占位符/语法/结构问题，
  `python tests/browser_check.py` 抓「语法正确但执行即抛错」的问题（本项目踩过：脚本顶层
  `const top` 与 `window.top` 冲突，整段脚本静默失效，页面全空但控制台无报错）。
- **改了 serve.py 必须跑 `python tests/test_serve.py`**：它持有用户 Token，安全闸门
  （Host/Origin/密钥/Token 泄漏）任何一条退化都是事故，不能靠肉眼 review。
- **改了求解器必须重跑对拍**：网页里的 JS 求解器被 `/* ---SOLVER-BEGIN--- */` 标记包裹，
  `tests/test_solver_parity.mjs` 原样抽取执行——不要动这两个标记。
- **Windows 下 `write_text` 会把 `\n` 写成 `\r\n`**：生成 HTML 时务必传 `newline="\n"`，
  否则同一份模板在不同平台产出字节不一致，下游按 `\n` 写的正则会失配。

## 参考

- MCP 工具参数与调用示例：`references/mcp-tools.md`
- 完整数据字段说明：`MCP_INTEGRATION.md`
- 本地工具模式（用户自己的数据）：`python scripts/serve.py`，安全设计见 README「本地工具模式」一节
- 求解器与网页的一致性由 `tests/test_solver_parity.mjs` 保证，改动求解逻辑后请重跑对拍
