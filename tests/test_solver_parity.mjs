/**
 * 前后端求解器对拍测试。
 *
 * 用法：
 *   python scripts/export_parity_fixture.py   # 生成 Python 端基准
 *   node tests/test_solver_parity.mjs         # 让 JS 端回答同样的问题并逐条比对
 *
 * 这段测试直接从 assets/dashboard-template.html 里把求解器代码抽出来跑，
 * 所以它测的就是网页上真正在跑的那份代码，不是复制品。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEMPLATE = path.join(ROOT, 'assets', 'dashboard-template.html');
const DATASET = path.join(ROOT, 'data', 'menu.json');
const FIXTURE = path.join(ROOT, 'tests', 'parity_fixture.json');

const html = fs.readFileSync(TEMPLATE, 'utf8');
const start = html.indexOf('/* ---SOLVER-BEGIN--- */');
const end = html.indexOf('/* ---SOLVER-END--- */');
if (start < 0 || end < 0) {
  console.error('模板里找不到求解器标记，无法抽取代码');
  process.exit(2);
}
const solverSource = html.slice(start + '/* ---SOLVER-BEGIN--- */'.length, end);

const menu = JSON.parse(fs.readFileSync(DATASET, 'utf8'));
const fixture = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));

const factory = new Function(`
  const DATA = ${JSON.stringify(menu)};
  ${solverSource}
  return { solve, CFG, CANDIDATES };
`);
const { solve, CFG, CANDIDATES } = factory();

function signature(plan) {
  if (!plan) return null;
  return {
    items: plan.items.map(i => `${i.name}x${i.qty}`).sort(),
    totalPrice: Math.round(plan.totalPrice * 10) / 10,
    totalProtein: Math.round(plan.totalProtein * 10) / 10,
    totalKcal: Math.round(plan.totalKcal),
  };
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let failures = 0;
console.log(`候选解 ${CANDIDATES.length} 个 · 对拍 ${fixture.scenarios.length} 个场景\n`);

for (const sc of fixture.scenarios) {
  const { weight, factor, consumed, mode } = sc.input;
  const target = Math.round(weight * factor);
  const remaining = Math.round((target - consumed) * 10) / 10;
  const mealGap = Math.round(Math.max(0, Math.min(remaining, CFG.MEAL_CAP)) * 10) / 10;

  const checks = [
    ['mealProtein', mealGap, sc.mealProtein],
    ['mealsNeeded', remaining > 0 ? Math.ceil(remaining / CFG.MEAL_CAP) : 0, sc.mealsNeeded],
    ['budget', signature(solve(mealGap, 'budget')), sc.budget],
    ['lean', signature(solve(mealGap, 'lean')), sc.lean],
  ];

  const bad = checks.filter(([, got, want]) => !same(got, want));
  const label = `${weight}kg x${factor} -${consumed}g [${mode}]`;
  if (bad.length === 0) {
    console.log(`  PASS  ${label}  缺口 ${mealGap}g -> ${sc[mode].items.join(' + ')}`);
  } else {
    failures++;
    console.log(`  FAIL  ${label}`);
    for (const [name, got, want] of bad) {
      console.log(`        ${name}\n          期望 ${JSON.stringify(want)}\n          实际 ${JSON.stringify(got)}`);
    }
  }
}

console.log('');
if (failures) {
  console.error(`${failures} 个场景对拍失败：前端与 Python 求解结果不一致`);
  process.exit(1);
}
console.log('全部通过：前端求解器与 scripts/coach.py 输出完全一致');
