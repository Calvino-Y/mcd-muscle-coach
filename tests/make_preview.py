#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 README 用的面板预览图（docs/preview-full.png 长图 + docs/preview-top.png 头图）。

为什么单独做成脚本而不是手工截：
  面板高度跟着数据走（这版加了券 / 早餐 / 帕累托 / 分享卡四个板块，高度从
  10198px 涨到一万多），手工截图很容易截到一半或者留一大片空白。
  这里先量真实高度，再按量到的高度截，最后把底部纯白多余部分裁掉。

依赖：headless Chrome/Edge + Pillow（只在生成预览图时需要，运行本项目不需要）。
用法： python tests/make_preview.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "index.html"
FULL = ROOT / "docs" / "preview-full.png"
TOP = ROOT / "docs" / "preview-top.png"

WIDTH = 1440
TOP_HEIGHT = 2050          # 与上一版头图保持一致的高度
BG = (255, 255, 255)       # 页面 --bg:#ffffff
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

# 把量到的尺寸写进 DOM —— JS 变量不会出现在 --dump-dom 的输出里
METRICS_PROBE = """<script>
window.addEventListener("load",function(){
  setTimeout(function(){
    var d=document.createElement("div");d.id="__metrics";
    d.textContent="METRICS::"+Math.ceil(document.documentElement.scrollHeight);
    document.body.appendChild(d);
  },1400);
});
</script>"""


def find_browser() -> str | None:
    for p in BROWSERS:
        if pathlib.Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")


def measure(browser: str) -> int:
    """返回页面真实高度（CSS px）。"""
    probe = ROOT / "docs" / "_metrics.html"
    html = SRC.read_text(encoding="utf-8")
    probe.write_text(html.replace("<script>", METRICS_PROBE + "<script>", 1),
                     encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", f"--window-size={WIDTH},1000",
             "--virtual-time-budget=9000", "--dump-dom", probe.as_uri()],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=180)
        m = re.search(r"METRICS::(\d+)", proc.stdout or "")
    finally:
        probe.unlink(missing_ok=True)
    if not m:
        raise SystemExit("量不到页面高度：metrics 探针没有回值")
    return int(m.group(1))


def shoot(browser: str, height: int, out: pathlib.Path) -> None:
    # 多给 240px 余量，避免把最后一行字切掉；裁白阶段会再收回来
    subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--hide-scrollbars", f"--window-size={WIDTH},{height + 240}",
         "--virtual-time-budget=9000",
         f"--screenshot={out}", SRC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
        timeout=240, check=True)


def crop_bottom(path: pathlib.Path) -> tuple[int, int]:
    """裁掉底部连续纯白行，返回最终尺寸。"""
    from PIL import Image

    im = Image.open(path).convert("RGB")
    px = im.load()
    w, h = im.size
    last = h - 1
    while last > 0:
        row = [px[x, last] for x in range(0, w, 7)]
        if any(abs(c[0] - BG[0]) + abs(c[1] - BG[1]) + abs(c[2] - BG[2]) > 12 for c in row):
            break
        last -= 1
    if last < h - 1:
        im = im.crop((0, 0, w, last + 24))
    im.save(path)
    return im.size


def make_top(path: pathlib.Path, height: int) -> tuple[int, int]:
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    top = im.crop((0, 0, w, min(height, h)))
    top.save(TOP)
    return top.size


def main() -> int:
    browser = find_browser()
    if not browser:
        print("找不到 Chrome/Edge，无法生成预览图")
        return 0

    h = measure(browser)
    print(f"页面高度 {h} px")
    shoot(browser, h, FULL)
    print(f"已截图 {FULL.name}")

    size = crop_bottom(FULL)
    print(f"裁白后 {FULL.name}: {size[0]}x{size[1]}")

    tsize = make_top(FULL, TOP_HEIGHT)
    print(f"{TOP.name}: {tsize[0]}x{tsize[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
