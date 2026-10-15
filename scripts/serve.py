#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门增肌师 · 本地工具模式。

静态页面（GitHub Pages 上的 demo）展示的是「我的」数据快照，别人看了没有代入感。
这个脚本把同一份页面变成「用你自己账号」的工具：

    python scripts/serve.py

然后浏览器打开 http://127.0.0.1:8765 ，在页面上填入你自己的麦当劳 MCP Token，
页面就会实时拉取**你自己门店**的菜单价格、**你自己**的历史订单和优惠券，
并在浏览器里用同一套求解器重算全部板块。

为什么必须是本地服务，而不是纯静态页面？
    实测 https://mcp.mcd.cn 的响应里没有 Access-Control-Allow-Origin，
    浏览器跨域请求会被直接拦下。所以需要一个本机进程代你调用 MCP。
    好处是 Token 只存在这台机器上，不经过任何第三方。

安全设计（这个进程持有你的 MCP Token，所以按「持有凭据的本地服务」对待）：
  * 只绑定 127.0.0.1，拒绝监听 0.0.0.0
  * 校验 Host 头，防 DNS rebinding
  * 拒绝任何带跨站 Origin 的请求；不返回任何 CORS 头，
    因此其它网页既发不出请求，也读不到响应
  * /api/* 必须带上本次启动随机生成的会话密钥，密钥只注入到本机页面里
  * Token 只保存在进程内存，不落盘、不回显、不写日志
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import build_coupons as bc                                          # noqa: E402
import build_dataset as bd                                          # noqa: E402
import build_orders as bo                                           # noqa: E402
from mcd_client import DEFAULT_ENDPOINT, McpError, McdMcpClient      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "index.html"

KEY_HEADER = "X-McMuscle-Key"
SESSION_KEY = secrets.token_urlsafe(24)
LOCK = threading.Lock()

STATE: dict = {
    "client": None,
    "store": None,
    "connectedAt": None,
    "calls": 0,
    "tools": [],
}

WEEKDAY_CHARS = "一二三四五六日"


# --------------------------------------------------------------------------- 工具

def extract_json(text: str, required: tuple[str, ...] = ("data", "success", "orders")) -> dict | None:
    """MCP 工具返回的是「字段说明 + 原始 JSON」，这里把 JSON 部分挖出来。

    不能简单地找第一个 "{"：说明文档里也可能出现花括号。所以逐个 "{" 试解析，
    并且要求解出来的对象确实含有关键字段。
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and any(k in obj for k in required):
            return obj
    return None


def parse_validity(text: str) -> dict:
    """解析券的有效期文案，例：

    「2026-10-12 10:30-2026-10-16 23:59 周一、二、三、四、五 10:30-23:59」

    这里要处理「周一、二、三」这种中文省略写法——不能只取第一个星期几，
    否则会把一张只在工作日可用的券误判成只在周一可用。
    """
    dates = re.findall(r"(\d{4}-\d{2}-\d{2})", text)
    times = re.findall(r"(\d{2}:\d{2})", text)
    weekdays: list[str] = []
    m = re.search(rf"周([{WEEKDAY_CHARS}](?:、[{WEEKDAY_CHARS}])*)", text)
    if m:
        for seg in m.group(1).split("、"):
            seg = seg.strip()
            if seg and seg[-1] in WEEKDAY_CHARS:
                wd = "周" + seg[-1]
                if wd not in weekdays:
                    weekdays.append(wd)
    return {
        "dateFrom": dates[0] if dates else "",
        "dateTo": dates[1] if len(dates) > 1 else (dates[0] if dates else ""),
        "timeFrom": times[-2] if len(times) >= 2 else "",
        "timeTo": times[-1] if len(times) >= 2 else "",
        "weekdays": weekdays,
    }


def parse_my_coupons(text: str) -> list[dict]:
    """query-my-coupons 返回的是 Markdown 卡片，按字段名逐条抽取。"""
    coupons: list[dict] = []
    for block in re.split(r"\n(?=##\s)", text):
        title_m = re.search(r"^##\s+(.+?)\s*$", block, re.M)
        if not title_m:
            continue
        price_m = re.search(r"\*\*优惠\*\*:\s*¥\s*([\d.]+)", block)
        valid_m = re.search(r"\*\*有效期\*\*:\s*(.+?)\s*$", block, re.M)
        tag_m = re.search(r"\*\*标签\*\*:\s*(.+?)\s*$", block, re.M)

        title = title_m.group(1).strip()
        validity = parse_validity(valid_m.group(1)) if valid_m else {
            "dateFrom": "", "dateTo": "", "timeFrom": "", "timeTo": "", "weekdays": []}
        entry = {
            "title": title,
            "couponPrice": float(price_m.group(1)) if price_m else None,
            "channels": [s.strip() for s in tag_m.group(1).split("、") if s.strip()] if tag_m else [],
            "validText": valid_m.group(1).strip() if valid_m else "",
            **validity,
        }
        if entry["couponPrice"] is not None:
            coupons.append(entry)
    return coupons


def build_live_coupons(client: McdMcpClient, store_code: str | None) -> dict:
    """在线拉券，并复用 build_coupons 的映射与诚实标注逻辑。"""
    my_text = client.call_tool("query-my-coupons", {"page": "1", "pageSize": "200"})
    my_coupons = parse_my_coupons(my_text)

    store_coupons: list[dict] = []
    if store_code:
        try:
            sc_text = client.call_tool("query-store-coupons", {
                "storeCode": store_code, "orderType": 1, "beType": 1})
            sc_json = extract_json(sc_text)
            for c in (sc_json or {}).get("data", []) or []:
                store_coupons.append({
                    "title": c.get("title"),
                    "couponId": c.get("couponId"),
                    "tradeDateTime": c.get("tradeDateTime"),
                    "productName": (c.get("products") or [{}])[0].get("productName"),
                })
        except McpError:
            store_coupons = []

    raw = {"myCoupons": my_coupons, "storeCoupons": store_coupons, "claimable": []}
    by_name = {it["name"]: it for it in json.loads(
        (ROOT / "data" / "menu.json").read_text(encoding="utf-8"))["items"]}

    board = bc.build_board(raw, by_name)          # type: ignore[arg-type]
    calendar = bc.build_calendar(board)
    return {
        "source": {"tool": "query-my-coupons + query-store-coupons",
                   "storeCode": store_code, "live": True},
        "board": board,
        "calendar": calendar,
        "claimable": [],
        "storeCoupons": store_coupons,
        "summary": {
            "couponCount": len(board),
            "computable": sum(1 for r in board if r["gPerYuanLo"] is not None),
            "unmatched": sum(1 for r in board if r["gPerYuanLo"] is None),
            "breakfastCount": sum(1 for r in board if r["timeFrom"] and r["timeFrom"] < "12:00"),
            "daysWithCoupon": sum(1 for d in calendar if d["entries"]),
            "daysWithBreakfastCoupon": sum(
                1 for d in calendar if any(e["timeFrom"] < "12:00" for e in d["entries"])),
            "claimableCount": 0,
        },
    }


def client_or_raise() -> McdMcpClient:
    with LOCK:
        client = STATE["client"]
    if client is None:
        raise McpError("还没有连接账号。请先在页面上填入 MCP Token，"
                       "或启动时设置环境变量 MCD_MCP_TOKEN。")
    return client


def call(tool: str, args: dict) -> str:
    client = client_or_raise()
    with LOCK:
        STATE["calls"] += 1
    return client.call_tool(tool, args)


# --------------------------------------------------------------------------- 路由

def route_menu(query: dict) -> dict:
    store_code = query.get("storeCode", [None])[0] or (STATE["store"] or {}).get("storeCode")
    nutrition_text = call("list-nutrition-foods", {})
    rows = bd.parse_nutrition_text(nutrition_text)
    if not rows:
        raise McpError("list-nutrition-foods 没有返回可解析的营养数据")

    live: dict[str, float] = {}
    if store_code:
        meals_text = call("query-meals", {
            "storeCode": store_code, "orderType": 1, "beType": 1})
        live = bd.live_prices_from_meals(extract_json(meals_text, ("data", "success")) or {})

    bd.assemble(rows, live)
    store = {"storeCode": store_code, "storeName": (STATE["store"] or {}).get("storeName"),
             "beType": 1}
    return bd.build_payload(rows, store=store,
                            captured_at=time.strftime("%Y-%m-%d %H:%M:%S"), live=live)


def route_orders(query: dict) -> dict:
    raw = extract_json(call("order-list", {}), ("orders", "data"))
    if not raw:
        raise McpError("order-list 返回里没有找到订单数据")
    if "orders" not in raw and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    nutrition_text = call("list-nutrition-foods", {})
    table = bo.nutrition_table(nutrition_text)
    return bo.build_order_set(raw, table)


def route_stores(query: dict) -> dict:
    search_type = int(query.get("searchType", ["2"])[0])
    args: dict = {"searchType": search_type, "beType": 1}
    if search_type == 2:
        args["city"] = query.get("city", [""])[0]
        args["keyword"] = query.get("keyword", [""])[0]
    text = call("query-nearby-stores", args)
    payload = extract_json(text, ("data", "success")) or {}
    stores = []
    for s in payload.get("data", []) or []:
        if not isinstance(s, dict):
            continue
        stores.append({
            "storeCode": s.get("storeCode"),
            "storeName": s.get("storeName"),
            "address": s.get("address"),
            "distance": s.get("distance"),
            "reservation": s.get("reservation"),
        })
    return {"raw": text, "stores": stores, "message": payload.get("message")}


def route_coupons(query: dict) -> dict:
    store_code = query.get("storeCode", [None])[0] or (STATE["store"] or {}).get("storeCode")
    return build_live_coupons(client_or_raise(), store_code)


def route_connect(body: dict) -> dict:
    token = (body.get("token") or "").strip() or os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        raise McpError("没有拿到 MCP Token")
    client = McdMcpClient(token=token)
    tools = [t.get("name") for t in client.list_tools()]
    with LOCK:
        STATE["client"] = client
        STATE["connectedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        STATE["tools"] = tools
        if body.get("storeCode"):
            STATE["store"] = {"storeCode": body["storeCode"], "storeName": body.get("storeName")}
    return {"connected": True, "toolCount": len(tools), "tools": tools,
            "connectedAt": STATE["connectedAt"],
            "tokenHint": token[:4] + "…" + token[-4:] if len(token) > 10 else "…"}


ROUTES = {
    "menu": route_menu,
    "orders": route_orders,
    "stores": route_stores,
    "coupons": route_coupons,
}


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "McMuscle/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:      # 不把 Token 之类的细节写进日志
        sys.stderr.write("  %s %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------------------------------------------------------------- 安全闸门
    def _guard(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            self._json(403, {"error": "只接受来自本机的请求"})
            return False

        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}",
                   f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            self._json(403, {"error": "拒绝跨站请求"})
            return False

        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/") and self.headers.get(KEY_HEADER) != SESSION_KEY:
            self._json(401, {"error": "缺少或错误的本地会话密钥，请从本工具打开的页面访问"})
            return False
        return True

    # ---------------------------------------------------------------- 响应helper
    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:
        if not self._guard():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            if not PAGE.exists():
                self._html("<h1>还没有生成页面</h1><p>请先运行 "
                           "<code>python scripts/render_dashboard.py</code></p>")
                return
            html = PAGE.read_text(encoding="utf-8")
            inject = ("<script>window.__LOCAL__=" + json.dumps({
                "sessionKey": SESSION_KEY,
                "port": self.server.server_port,
                "endpoint": DEFAULT_ENDPOINT,
            }, ensure_ascii=False) + ";</script>")
            if "<head>" in html:
                html = html.replace("<head>", "<head>\n" + inject, 1)
            else:
                html = inject + html
            self._html(html)
            return

        if path == "/api/status":
            with LOCK:
                connected = STATE["client"] is not None
                store = STATE["store"]
                tools = STATE["tools"]
                calls = STATE["calls"]
            self._json(200, {
                "mode": "local", "connected": connected, "store": store,
                "toolCount": len(tools), "apiCalls": calls,
                "endpoint": DEFAULT_ENDPOINT,
                "envToken": bool(os.environ.get("MCD_MCP_TOKEN")),
            })
            return

        if path.startswith("/api/"):
            name = path[len("/api/"):]
            fn = ROUTES.get(name)
            if not fn:
                self._json(404, {"error": f"未知接口 {name}"})
                return
            if STATE["client"] is None and not (name == "menu" and os.environ.get("MCD_MCP_TOKEN")):
                self._json(409, {"error": "尚未连接账号，请先在页面上填入 MCP Token"})
                return
            try:
                self._json(200, fn(query))
            except McpError as exc:
                self._json(502, {"error": str(exc)})
            except Exception as exc:                                   # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        self._json(404, {"error": "not found"})

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:
        if not self._guard():
            return
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except json.JSONDecodeError:
            self._json(400, {"error": "请求体不是合法 JSON"})
            return

        if path == "/api/connect":
            try:
                self._json(200, route_connect(body))
            except McpError as exc:
                self._json(502, {"error": str(exc)})
            return

        if path == "/api/disconnect":
            with LOCK:
                STATE["client"] = None
                STATE["tools"] = []
                STATE["connectedAt"] = None
            self._json(200, {"connected": False})
            return

        self._json(404, {"error": "not found"})

    # 明确拒绝预检：本服务不对外提供跨域访问
    def do_OPTIONS(self) -> None:
        self._json(403, {"error": "本服务不支持跨域访问"})


# --------------------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="麦门增肌师 · 本地工具模式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Token 申请：https://open.mcd.cn/mcp\n"
               "也可以先用 export MCD_MCP_TOKEN=... 设置好，启动后在页面点「连接」。")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="", help="麦当劳 MCP Token（不传则用环境变量 MCD_MCP_TOKEN）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args(argv)

    if args.token:
        os.environ["MCD_MCP_TOKEN"] = args.token

    if not PAGE.exists():
        print(f"找不到 {PAGE}，请先运行： python scripts/render_dashboard.py")
        return 2

    env_token = bool(os.environ.get("MCD_MCP_TOKEN"))
    host = "127.0.0.1"          # 刻意写死：这个进程持有你的 MCP Token，不允许对外监听

    try:
        httpd = ThreadingHTTPServer((host, args.port), Handler)
    except OSError as exc:
        print(f"端口 {args.port} 起不来（{exc}）。换一个： python scripts/serve.py --port 8899")
        return 2

    url = f"http://{host}:{args.port}/"
    print("=" * 62)
    print("  麦门增肌师 · 本地工具模式")
    print("=" * 62)
    print(f"  地址        {url}")
    print(f"  MCP 端点    {DEFAULT_ENDPOINT}")
    print(f"  环境变量    {'已检测到 MCD_MCP_TOKEN' if env_token else '未设置，请在页面上填入 Token'}")
    print(f"  会话密钥    {SESSION_KEY[:8]}…（本次启动随机生成，仅注入本机页面）")
    print()
    print("  只监听 127.0.0.1；Token 只保存在本进程内存里，不落盘、不上传")
    print("  Ctrl+C 停止")
    print("=" * 62)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
