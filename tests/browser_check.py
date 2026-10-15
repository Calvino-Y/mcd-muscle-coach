#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用无头浏览器真跑一遍生成的面板，抓「解析通过但执行即抛错」类问题。

为什么必须要它：
  tests/check_page.mjs 只能验证语法。这个项目踩过一次坑——脚本顶层写了
  `const top`，与浏览器全局 window.top 冲突，整段脚本在解析阶段就静默失效，
  页面看起来正常、控制台一片安静，但所有动态内容都是空的。
  另外 canvas 绘制失败这类问题，也只有真跑一遍才能发现。

做法：
  在页面主脚本之前注入一个错误探针，把错误和自检结果写进 DOM
  （JS 变量不会出现在 --dump-dom 的输出里，所以必须落到 DOM 上），
  再用 --dump-dom 把渲染后的 DOM 抓回来逐项断言。

用法： python tests/browser_check.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "index.html"
PROBE_TARGET = ROOT / "docs" / "_probe.html"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

# 探针：错误监听 + 加载后自检（canvas 是否真的画上去了）
PROBE = """<script>
window.__errs=[];
window.addEventListener("error",function(e){
  var d=document.createElement("div");d.id="__errbox";
  d.textContent="ERRBOX::"+e.message+" @line"+e.lineno;
  document.body.appendChild(d);
});
window.addEventListener("load",function(){
  setTimeout(function(){
    var d=document.createElement("div");d.id="__sharebox";
    var msg="NO_CANVAS";
    try{
      var c=document.getElementById("shareCanvas");
      if(c){
        var g=c.getContext("2d");
        var px=g.getImageData(4,4,1,1).data;
        msg = px[3] > 0 ? "PAINTED" : "BLANK";
      }
    }catch(err){ msg="ERR:"+err.message; }
    d.textContent="SHAREBOX::"+msg;
    document.body.appendChild(d);
  }, 900);
});
</script>"""

# 渲染后必须出现真实内容的容器。
# 判据是「起始标签之后不是紧跟一个闭合标签」——纯文本内容（如 cpNote）也算已渲染。
CHECK_IDS = [
    # 原有板块
    "orderSum", "orderList", "orderFoot", "ordInsight",
    "qBody", "qNote", "rankDensity", "rankValue",
    "catBody", "weekDays", "weekSum", "curve", "scatter", "oTotals", "oRows",
    # 新增板块
    "liveGrid", "cpSum", "cpCal", "cpList", "cpNote",
    "cpRatio", "cpInsight", "cpInsightTitle",
    "bfSum", "bfBody", "bfNote",
    "parTiers", "parBody", "parRatio", "parDominated",
]


def find_browser() -> str | None:
    for p in BROWSERS:
        if pathlib.Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")


def main() -> int:
    browser = find_browser()
    if not browser:
        print("找不到可用的 Chrome/Edge，跳过浏览器检查")
        return 0

    html = SRC.read_text(encoding="utf-8")
    if html.count("<script>") != 1:
        print(f"预期页面里只有一个 <script>，实际 {html.count('<script>')} 个，注入点不可靠")
        return 2
    PROBE_TARGET.write_text(html.replace("<script>", PROBE + "<script>", 1),
                            encoding="utf-8", newline="\n")

    try:
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--virtual-time-budget=9000",
             "--no-sandbox", "--dump-dom", PROBE_TARGET.as_uri()],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=180,
        )
        dom = proc.stdout or ""
    finally:
        PROBE_TARGET.unlink(missing_ok=True)

    if len(dom) < 5000:
        print(f"dump-dom 输出异常（{len(dom)} 字符）")
        print(dom[:600])
        return 2

    failures = 0

    err = re.search(r"ERRBOX::(.*?)</div>", dom)
    if err:
        failures += 1
        print(f"  FAIL  浏览器端未捕获错误：{err.group(1)}")
    else:
        print("  PASS  浏览器端无未捕获错误")

    for node_id in CHECK_IDS:
        m = re.search(rf'id="{node_id}"[^>]*>(?!\s*</)', dom, re.S)
        if not m:
            failures += 1
            print(f"  FAIL  {node_id} 是空的（脚本可能中途抛错）")
            continue
        sample = re.sub(r"<[^>]+>", " ", dom[m.end():m.end() + 400])
        sample = re.sub(r"\s+", " ", sample).strip()
        print(f"  PASS  {node_id}：{sample[:56]}...")

    share = re.search(r"SHAREBOX::(\S+?)</div>", dom)
    if not share:
        failures += 1
        print("  FAIL  分享卡 canvas 自检没有结果")
    elif share.group(1) == "PAINTED":
        print("  PASS  分享卡 canvas 已实际绘制（不是空白）")
    else:
        failures += 1
        print(f"  FAIL  分享卡 canvas 未绘制：{share.group(1)}")

    # 注意：不能在整个 DOM 里数 class="cal-col"——页面里的 JS 源码本身含有
    # 模板字符串 `class="cal-col${...}"`，会被一起数进去。所以限定在 cpCal 区域内数。
    cal_block = re.search(r'id="cpCal"[\s\S]*?(?=</section>)', dom)
    cols = len(re.findall(r'class="cal-col', cal_block.group(0))) if cal_block else 0
    if cols == 7:
        print("  PASS  券日历 7 列齐备")
    else:
        failures += 1
        print(f"  FAIL  券日历列数 {cols}，预期 7")

    slots = len(re.findall(r'class="slot', cal_block.group(0))) if cal_block else 0
    print(f"  INFO  券日历时段格 {slots} 个")

    rows = len(re.findall(r"<tr", dom))
    print(f"  INFO  页面表格行合计 {rows}")

    print()
    if failures:
        print(f"{failures} 项未通过")
        return 1
    print("浏览器端渲染检查全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
