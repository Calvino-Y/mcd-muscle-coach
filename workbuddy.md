# WorkBuddy 开发记录 · workbuddy.md

本项目（麦门增肌师 / mcd-muscle-coach）使用 **WorkBuddy** 完成创意构思、开发与调试，
用于申请麦当劳程序员创意开发大赛的 WorkBuddy 专项奖励。

## 开发环境

- 工具：WorkBuddy（Agent 模式）
- 麦当劳 MCP：通过 WorkBuddy 自定义连接器接入 `https://mcp.mcd.cn`（Streamable HTTP + Bearer Token）
- 本地运行时：Python 3.13、Node.js 22（均为 WorkBuddy 托管版本，未污染系统环境）

## 开发过程

### 1. 赛题分析（用 WorkBuddy 联网检索 + MCP 实测）

- 让 WorkBuddy 抓取大赛官方仓库与 `mcd-mcp-server` 仓库，梳理出**必须提交的文件清单**、
  **报名 Issue 格式**、**按 Star 数排名**、**2026-10-25 23:59 截止**等硬约束
- 拉取官方 `RANKING.md` 排行榜，统计已报名项目的赛道分布

### 2. 用真实数据找赛道空白（关键一步）

让 WorkBuddy 实际调用麦当劳 MCP，拿到一手数据：

- `query-my-account` → 看到自己已过期 1537.8 积分（这个数字后来成了另一个项目的开场）
- `list-nutrition-foods` → 158 项餐品的完整营养数据
- `query-meals` → 成都万达门店的实时菜单与价格

结合排行榜结论：**省钱比价类 ≥ 8 个项目、卡路里类 ≥ 6 个、MBTI 类 ≥ 6 个，全部饱和**；
而「蛋白效率 / 增肌」方向为 0。据此确定「麦门增肌师」方向，
而不是跟着官方示例去做第 9 个省钱助手。

### 3. 数据管线

- WorkBuddy 起草 `scripts/mcd_client.py`：纯标准库实现的 MCP Streamable HTTP 客户端，
  处理 `Mcp-Session-Id` 会话回传、JSON 与 SSE 双格式响应
- 起草 `scripts/build_dataset.py`：解析营养原始响应、对齐菜单价格、派生指标
- **实测修正**：第一版解析器靠 `"null,"` 过滤行，导致 4 条「能量约鲈鱼1条」这类
  非空描述的餐品被漏掉（160 → 155）。WorkBuddy 主动发现并改成「后七列必须全为数字」
  的判定，修正为 158 项
- **实测修正**：小杯美式「1g 蛋白 / 10kcal」比值 10.0，会把蛋白密度榜霸占成饮料榜。
  加入 `proteinSource`（蛋白 ≥ 8g 且热量 ≥ 50kcal）门槛过滤

### 4. 求解器

- 起草 `scripts/coach.py`：带约束穷举搜索
- **实测修正**：初版搜索空间不含「单品重复多份」，导致组合方案（¥58）输给了
  它自己的对照组（¥56）——这是算法 bug，不是真实结论。修复为
  `size==1` 时放开份数上限到 6
- **产品层修正**：修复后一度推荐「一顿 1540 kcal 补 90g 蛋白」。数学上对，
  营养上是错的。加入单餐蛋白上限 45g / 热量上限 900kcal，
  并让工具主动提示「缺口分几餐补」

### 5. 可视化

- WorkBuddy 起草 `assets/dashboard-template.html`：深色健身风格面板，
  含蛋白缺口计算器（实时求解）、双排行榜、蛋白×热量散点图
- 性能优化：把 4150 个候选组合的枚举从「每次拖动滑块都算」改为「页面加载时算一次」
- 用无头 Chrome 实测截图确认渲染效果

### 6. 前后端一致性测试（本项目最较真的部分）

网页里的 JS 求解器与命令行的 Python 求解器是两套独立实现。为避免「网页和命令行
给出不同答案」，WorkBuddy 设计了对拍方案：

- `scripts/export_parity_fixture.py` 导出 Python 端 12 个场景的基准
- `tests/test_solver_parity.mjs` 从 HTML 模板里**原样抽出**求解器代码执行并逐字段比对
- 实测结果：12/12 全部一致

### 7. 修复过的真实 Bug

| Bug | 根因 | 修复 |
|---|---|---|
| 营养表少解析 4 条 | 靠 `"null,"` 过滤行 | 改为按「后七列全为数字」判定 |
| 组合方案比单点贵 | 搜索空间不含单品重复多份 | `size==1` 放开到 6 份 |
| 推荐一顿 1540 kcal | 无单餐上限 | 加入 45g 蛋白 / 900kcal 上限 |
| 蛋白密度榜被饮料霸占 | 比值数学噪声 | `proteinSource` 门槛 |
| `check_page.mjs` 解析不到 DATA | 数据层改成 `let DATA = (LIVE && …) \|\| {…}` 后跨行正则失配 | 改为按行正则 + 单行 `JSON.parse` |
| 浏览器检查误报「券日历 8 列」 | 在整个 DOM 里数 `class="cal-col"`，把 JS 源码里的模板字符串也数了进去 | 限定在 `id="cpCal"` 区域内计数 |
| `test_serve.py` 误报 Token 泄漏 | 断言命中了布尔字段名 `envToken` | 改为检测真实 Token 形态的正则 |

### 8. 第二阶段：从「一个 HTML」到「每个人都能用」（本地工具模式）

用户提出「能不能做成不只一个 html 大家看，而是每个人直接使用的东西」。WorkBuddy
先做了关键实测：直接用 `curl` 探测 `https://mcp.mcd.cn` 的 CORS 行为，确认响应
**不带 `Access-Control-Allow-Origin`**（403）——浏览器直连 MCP 这条路被官方设计堵死，
而这恰好是正确的安全设计（Token 不该进浏览器）。据此确定双模式架构：

- **静态演示模式**（GitHub Pages）：构建时注入快照，保持零门槛体验
- **本地工具模式**（`scripts/serve.py`）：零依赖标准库 HTTP 服务只绑 `127.0.0.1`，
  代理 MCP 调用，页面填自己的 Token 后实时拉取自己的门店/菜单/订单/卡包券

几个关键设计决策：

- **数据接管用「写 sessionStorage + 整页刷新」而不是就地替换**：派生指标、候选解、
  图表全是脚本加载时算好的，就地替换必然留下半旧状态；整页重新初始化保证每一层同源
- **求解器不下放服务端**：`/* ---SOLVER-BEGIN--- */` 标记包裹的 JS 求解器仍是单一权威，
  serve.py 只供数据——避免了「两处求解逻辑悄悄分叉」的整类 bug
- **安全闸门做成测试而非注释**：`tests/test_serve.py` 从注入页面里取会话密钥
  （模拟真实浏览器路径），逐条验证 401/403/409 与 Token 泄漏扫描
- **诚实标注扩展到券**：8 张券里 3 张在营养表无对应条目 → `data/coupons.json`
  逐券写 `confidence`（deterministic/range/partial/unmatched）与 `basis` 依据，
  页面标「无法对齐」而不是拿相近餐品凑数

新增五个板块（限时券×蛋白效率、早餐窗口、帕累托前沿、分享卡片、你的账号入口），
其中挖出的新结论：**券后每克蛋白最低 ¥0.47（火腿扒堡早餐两件套），低于菜单原价冠军
那么大鸡排的 ¥0.58**；帕累托前沿 15 项候选只剩 6 项，**巨无霸被双层深海鳕鱼堡全面支配**。

### 9. 验证链（四条，全绿后才推送）

```bash
node tests/check_page.mjs            # 页面自检：占位符/语法/数据/结构/挂载点（158 项/10 单/8 券/40 节点/13 板块）
node tests/test_solver_parity.mjs    # 前后端求解器 12 场景逐字段对拍
python tests/test_serve.py           # serve.py 安全闸门 13 项端到端
python tests/browser_check.py        # 无头 Chrome 真跑页面：30 个节点渲染 + canvas 像素自检
python tests/make_preview.py         # 重新量页面高度并生成 README 预览图
```

## 使用 WorkBuddy 的价值

1. **连接器直接调 MCP**：不用自己搭 MCP Client 调试环境，对话里就能实测每个 Tool
2. **托管运行时**：Python/Node 版本隔离，不污染系统
3. **联网 + 本地执行混合**：既能查赛规又能跑测试
4. **最有价值的不是写代码，是发现「算法对了但产品错了」**：1540 kcal 那个问题，
   单看代码永远发现不了，是让 WorkBuddy 站在营养学视角审视输出才暴露的
5. **先实测再定架构**：「能不能让网页直接调 MCP」没有靠猜——一条 `curl` 实测 CORS
   就排除了纯静态方案，避免了给 `serve.py` 写完才发现浏览器根本连不上的返工

## 复现本记录

本文件为人工整理的开发过程摘要。WorkBuddy 会话中的完整对话与工具调用记录
可在 WorkBuddy 会话历史中导出。
