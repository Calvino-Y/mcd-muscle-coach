/**
 * 页面自检：生成 docs/index.html 之后跑一遍。
 *
 *   node tests/check_page.mjs
 *
 * 检查三件事：
 *   1. 模板占位符是否都替换干净（没有残留的 /*__DATA__*\/ 之类）
 *   2. 每一段内联脚本能否通过语法解析
 *   3. 页面结构是否完整（关键节点 id 都在）
 *
 * 为什么需要它：这个项目踩过一次坑——脚本顶层写了 `const top`，
 * 与浏览器全局的 window.top 冲突，整段脚本在解析阶段就静默失效，
 * 页面看起来正常但所有动态内容都是空的，而且控制台没有任何报错。
 * 纯语法检查抓不到那类问题，但占位符/结构检查能兜住大部分同类事故。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = path.join(ROOT, 'docs', 'index.html');

const html = fs.readFileSync(PAGE, 'utf8');
let failures = 0;
const fail = (msg) => { failures++; console.log(`  FAIL  ${msg}`); };
const pass = (msg) => console.log(`  PASS  ${msg}`);

console.log(`检查 ${path.relative(ROOT, PAGE)}（${(html.length / 1024).toFixed(1)} KB）\n`);

// 1. 占位符
console.log('1. 占位符替换');
for (const token of ['/*__DATA__*/', '/*__ORDERS__*/', '/*__COUPONS__*/',
                     '__DATA__', '__ORDERS__', '__COUPONS__']) {
  if (html.includes(token)) fail(`残留占位符 ${token}`);
}
if (!failures) pass('没有残留占位符');

// 2. 内联脚本语法
console.log('\n2. 内联脚本语法');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length === 0) {
  fail('没有找到内联脚本');
} else {
  scripts.forEach((src, i) => {
    try {
      new Function(src);
      pass(`第 ${i + 1} 段（${src.length} 字符）语法正常`);
    } catch (e) {
      fail(`第 ${i + 1} 段语法错误: ${e.message}`);
    }
  });
}

// 2b. 求解器标记必须在，否则对拍测试抽不到代码
if (html.includes('/* ---SOLVER-BEGIN--- */') && html.includes('/* ---SOLVER-END--- */')) {
  pass('求解器标记完整（对拍测试能抽到代码）');
} else {
  fail('求解器标记缺失，会静默让对拍测试失效');
}

// 3. 数据注入
//    数据声明的形态是： let DATA = (LIVE && LIVE.menu) || {…};
//    这里按行取等号右边的内容再 JSON.parse，比跨行正则稳。
console.log('\n3. 数据注入');
const grab = (name) => {
  const re = new RegExp(
    `^let\\s+${name}\\s*=\\s*\\(LIVE && LIVE\\.[a-zA-Z]+\\)\\s*\\|\\|\\s*(.*);\\r?$`, 'm');
  const m = html.match(re);
  return m ? m[1] : null;
};

let data = null, orders = null, coupons = null;
try {
  const rawData = grab('DATA'), rawOrders = grab('ORDERS'), rawCoupons = grab('COUPONS');
  if (!rawData || !rawOrders || !rawCoupons) {
    fail('无法从页面里解析出 DATA / ORDERS / COUPONS');
  } else {
    data = JSON.parse(rawData);
    orders = JSON.parse(rawOrders);
    coupons = JSON.parse(rawCoupons);
    pass(`DATA 合法：${data.items.length} 项餐品`);
    pass(`ORDERS 合法：${orders.summary.orderCount} 笔订单，营养覆盖率 ${orders.summary.coverage}%`);
    pass(`COUPONS 合法：${coupons.summary.couponCount} 张券，其中 ${coupons.summary.computable} 张能算出蛋白`);

    const priced = data.items.filter(i => i.price).length;
    if (priced === 0) fail('没有任何餐品带价格，成本优化会失效');
    else pass(`带真实价格的餐品 ${priced} 项`);

    const bf = data.items.filter(i => i.category === 'breakfast');
    const bfPriced = bf.filter(i => i.price);
    pass(`早餐餐品 ${bf.length} 项（带价格 ${bfPriced.length} 项）`);

    const withCalcium = data.items.filter(i => i.calcium > 0).length;
    if (withCalcium === 0) fail('钙字段全为 0，钙负荷榜会失效');
    else pass(`带钙数据的餐品 ${withCalcium} 项`);

    const days = coupons.calendar.filter(d => d.entries.length).length;
    if (days === 0) fail('券日历里没有任何可用日');
    else pass(`券日历覆盖 ${days} 天`);

    const unmatched = coupons.board.filter(r => r.gPerYuanLo === null);
    if (unmatched.length && unmatched.some(r => !r.basis)) {
      fail('有券标成「无法对齐」却没写明依据');
    } else {
      pass(`诚实标注：${unmatched.length} 张券标为无法对齐，且都写了依据`);
    }
  }
} catch (e) {
  fail(`注入的 JSON 解析失败: ${e.message}`);
}

// 4. 关键结构
console.log('\n4. 关键节点');
const REQUIRED_IDS = [
  'weight', 'factor', 'consumed', 'budget', 'askSeg', 'modeSeg',
  'oRows', 'oTotals', 'oVs', 'rankDensity', 'rankValue',
  'qBody', 'scatter', 'curve', 'catBody', 'weekDays', 'weekSum',
  'orderSum', 'orderList', 'orderFoot', 'ordInsight',
  'liveGrid', 'cpSum', 'cpCal', 'cpList', 'cpNote', 'cpRatio', 'cpInsight',
  'bfSum', 'bfBody', 'bfNote', 'parTiers', 'parBody', 'parRatio', 'parDominated',
  'shareCanvas', 'shareText', 'dlPng', 'copyText', 'qSeg',
];
const missing = REQUIRED_IDS.filter(id => !html.includes(`id="${id}"`));
if (missing.length) fail(`缺少节点: ${missing.join(', ')}`);
else pass(`${REQUIRED_IDS.length} 个关键节点齐备`);

const sections = (html.match(/<section/g) || []).length;
if (sections < 13) fail(`板块数只有 ${sections}，预期至少 13`);
else pass(`内容分块 ${sections} 个`);

// 5. 本地模式的注入点必须存在，否则 serve.py 无法把页面切到实时模式
console.log('\n5. 本地工具模式挂载点');
if (html.includes('window.__LOCAL__')) pass('页面读取 window.__LOCAL__（serve.py 的注入点）');
else fail('页面没有读取 window.__LOCAL__，本地模式会失效');
if (html.includes("sessionStorage.getItem('mcmuscle.live')")) {
  pass('支持用 sessionStorage 里的实时数据重新初始化');
} else {
  fail('缺少实时数据接管逻辑');
}

console.log('');
if (failures) {
  console.error(`${failures} 项检查未通过`);
  process.exit(1);
}
console.log('页面自检全部通过');
