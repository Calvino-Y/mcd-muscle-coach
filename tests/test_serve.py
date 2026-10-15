#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地工具模式 scripts/serve.py 的端到端测试。

这个进程持有用户的 MCP Token，所以这里不测「功能跑通」就完事，重点测安全闸门：

  1. 正常路径：从页面里取会话密钥（真实浏览器就是这么拿的），带上它才能调接口
  2. 没有密钥         -> 401
  3. 错误的密钥       -> 401
  4. 跨站 Origin      -> 403
  5. Host 头伪造      -> 403（防 DNS rebinding）
  6. 预检 OPTIONS     -> 403（本服务不对外提供跨域）
  7. 响应里绝不能出现 Token 明文
  8. 未连接账号时调业务接口 -> 409，而不是 500 崩掉

用法： python tests/test_serve.py
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  PASS  {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}  {detail}")


def request(path: str, key: str | None = None, origin: str | None = None,
            host: str | None = None, method: str = "GET",
            body: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, method=method)
    if key:
        req.add_header("X-McMuscle-Key", key)
    if origin:
        req.add_header("Origin", origin)
    if host:
        # urllib 不允许随便改 Host，用底层 dict 覆盖
        req.add_unredirected_header("Host", host)
        req.host = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:                                  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    proc = subprocess.Popen(
        [PY, "scripts/serve.py", "--no-browser", "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    try:
        # 等服务起来
        ready = False
        for _ in range(60):
            code, _body = request("/")
            if code == 200:
                ready = True
                break
            time.sleep(0.25)
        if not ready:
            print("服务未能在 15 秒内启动")
            return 2

        print("安全闸门")
        code, page = request("/")
        m = re.search(r"window\.__LOCAL__=(\{.*?\});</script>", page, re.S)
        check("GET / 返回页面并注入 window.__LOCAL__", code == 200 and bool(m),
              f"code={code}")
        key = ""
        if m:
            key = json.loads(m.group(1))["sessionKey"]

        code, body = request("/api/status")
        check("无密钥访问 /api/status -> 401", code == 401, f"code={code}")

        code, body = request("/api/status", key="wrong-key")
        check("错误密钥 -> 401", code == 401, f"code={code}")

        code, body = request("/api/status", key=key)
        ok = code == 200 and '"mode": "local"' in body.replace('"mode":"local"', '"mode": "local"')
        check("正确密钥 -> 200 且 mode=local", ok, f"code={code} body={body[:120]}")

        code, _ = request("/api/status", key=key, origin="https://evil.example.com")
        check("跨站 Origin -> 403", code == 403, f"code={code}")

        code, _ = request("/api/status", key=key, host="attacker.example.com")
        check("Host 头伪造 -> 403（防 DNS rebinding）", code == 403, f"code={code}")

        code, _ = request("/api/status", key=key, method="OPTIONS")
        check("预检 OPTIONS -> 403", code == 403, f"code={code}")

        code, _ = request("/api/status", key=key, origin=f"http://127.0.0.1:{PORT}")
        check("同源 Origin -> 放行", code == 200, f"code={code}")

        print("\n未连接账号时的行为")
        for name in ("menu", "orders", "coupons"):
            code, body = request(f"/api/{name}", key=key)
            good = code == 409 and "Token" in body
            check(f"/api/{name} -> 409 并提示填 Token", good, f"code={code} body={body[:100]}")

        print("\nToken 泄漏检查")
        leak = re.search(r"\b(?:ghp_|github_pat_|mcd_)[A-Za-z0-9_]{10,}", page)
        check("页面内没有 Token 形态的字符串", leak is None, str(leak.group(0)[:12]) if leak else "")
        code, body = request("/api/status", key=key)
        leak2 = re.search(r"\b(?:ghp_|github_pat_|mcd_)[A-Za-z0-9_-]{10,}", body)
        check("/api/status 不回显 Token", leak2 is None,
              leak2.group(0)[:12] if leak2 else body[:120])

        print("\n静态页面兼容性")
        # 服务端只是「多注入了一个 window.__LOCAL__」，页面本身必须仍是完整的静态页面：
        # 数据层用 LIVE 接管写法、求解器标记齐备（求解器是单一权威，不能被服务端替换）。
        page_ok = (
            'id="orderList"' in page
            and re.search(r"let\s+DATA\s*=\s*\(LIVE && LIVE\.menu\)", page) is not None
            and re.search(r"let\s+ORDERS\s*=\s*\(LIVE && LIVE\.orders\)", page) is not None
            and "/* ---SOLVER-BEGIN--- */" in page
            and page.rstrip().endswith("</html>")
        )
        check("注入后的页面仍是完整可渲染的页面", page_ok)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if failures:
        print(f"{failures} 项失败")
        return 1
    print("全部通过：本地工具模式的安全闸门与降级行为符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
