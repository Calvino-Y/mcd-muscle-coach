# 麦当劳 MCP 工具速查

> 官方仓库：<https://github.com/M-China/mcd-mcp-server> · Token 申请：<https://open.mcd.cn/mcp>

## 本项目用到的

### `list-nutrition-foods`

```
入参：无
返回：158 项餐品的 productName / energyKj / energyKcal / protein /
      fat / carbohydrate / sodium / calcium
```

- 描述列不一定是 `null`，解析时要靠「后七列全是数字」判定有效行
- 含大量重复条目（如 `麦乐鸡4块` / `麦乐鸡5块`），按名称精确匹配，不要模糊匹配

### `query-meals`

```
入参：
  storeCode       必填
  orderType       1=到店（含自提+得来速）  2=外送（含麦乐送+团餐）
  beType          1=到店自提  2=麦乐送  5=得来速  6=企业团餐
  beCode          得来速/外送/团餐必传，与 storeCode 配对
  reservationDate 预约场景必传，格式 yyyy-MM-dd HH:mm
返回：categories[]（分类与餐品编码）+ meals（code -> 名称/图片/现价/划线价/优惠类型）
```

beType 与 orderType 的对应关系（官方约定）：

| beType | 场景 | orderType | beCode |
|---|---|---|---|
| 1 | 到店自提 | 1 | 不传 |
| 5 | 得来速 | 1 | 必传 |
| 2 | 麦乐送 | 2 | 必传 |
| 6 | 企业团餐 | 2 | 必传 |

### `query-nearby-stores`

```
入参：searchType(1=收藏餐厅,2=按位置)  city  keyword  beType(1/5)
返回：门店列表，含 storeCode / beCode（beType=5 时）
```

### `calculate-price` / `create-order`（可选链路）

结算校验与下单，返回支付链接。**本项目默认不代下单**，Skill 定义里明确要求先征得用户确认。

## 项目未用到、但同一 Server 提供的

`delivery-query-addresses` `delivery-create-address` `delivery-query-stores`
`query-meal-assistance` `query-store-coupons` `query-meal-detail`
`cancel-order` `query-order` `order-list` `campaign-calendar`
`available-coupons` `auto-bind-coupons` `query-my-coupons` `query-my-account`
`mall-points-products` `mall-product-detail` `mall-create-order`
`mall-order-list` `mall-order-detail` `now-time-info` `query-lottery-info`
`draw-lottery` `query-my-prizes` `query-party-city` `query-party-store`
`query-partystore-date` `query-partystore-session` `party-order-create`

## 通用注意事项

- 限流 600 次/分钟，超限返回 429
- 401 = Token 无效/过期/未提供
- 价格、供应状态均为门店级实时数据，跨门店不可复用
