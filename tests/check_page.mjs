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
for (const token of ['/*__DATA__*/', '/*__ORDERS__*/', '__DATA__', '__ORDERS__']) {
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

// 3. 数据注入
console.log('\n3. 数据注入');
const dataMatch = html.match(/const DATA = (\{[\s\S]*?\});\r?\nconst ORDERS = (\{[\s\S]*?\});\r?\n/);
if (!dataMatch) {
  fail('无法从页面里解析出 DATA / ORDERS');
} else {
  try {
    const data = JSON.parse(dataMatch[1]);
    const orders = JSON.parse(dataMatch[2]);
    pass(`DATA 合法：${data.items.length} 项餐品`);
    pass(`ORDERS 合法：${orders.summary.orderCount} 笔订单，覆盖率 ${orders.summary.coverage}%`);
    const priced = data.items.filter(i => i.price).length;
    if (priced === 0) fail('没有任何餐品带价格，成本优化会失效');
    else pass(`带真实价格的餐品 ${priced} 项`);
  } catch (e) {
    fail(`注入的 JSON 解析失败: ${e.message}`);
  }
}

// 4. 关键结构
console.log('\n4. 关键节点');
const REQUIRED_IDS = [
  'weight', 'factor', 'consumed', 'budget', 'askSeg', 'modeSeg',
  'oRows', 'oTotals', 'oVs', 'rankDensity', 'rankValue',
  'qBody', 'scatter', 'curve', 'catBody', 'weekDays', 'weekSum',
  'orderSum', 'orderList', 'orderFoot', 'ordInsight',
];
const missing = REQUIRED_IDS.filter(id => !html.includes(`id="${id}"`));
if (missing.length) fail(`缺少节点: ${missing.join(', ')}`);
else pass(`${REQUIRED_IDS.length} 个关键节点齐备`);

const sections = (html.match(/<section/g) || []).length;
pass(`内容分块 ${sections} 个`);

console.log('');
if (failures) {
  console.error(`${failures} 项检查未通过`);
  process.exit(1);
}
console.log('页面自检全部通过');
