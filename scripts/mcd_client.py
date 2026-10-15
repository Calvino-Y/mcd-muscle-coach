#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦当劳中国 MCP Server（Streamable HTTP）极简客户端。

这个文件是「麦门增肌师」与麦当劳 MCP 之间的唯一通道。
它只做三件事：握手、列工具、调工具。没有第三方依赖，只用标准库。

用法::

    export MCD_MCP_TOKEN="你的 MCP Token"      # Windows: set MCD_MCP_TOKEN=...
    python scripts/mcd_client.py list
    python scripts/mcd_client.py call list-nutrition-foods

Token 申请地址：https://open.mcd.cn/mcp
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
TOKEN_ENV = "MCD_MCP_TOKEN"
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """MCP 调用失败。"""


class McdMcpClient:
    """麦当劳 MCP Server 的最小可用客户端。

    MCP 的 Streamable HTTP 传输要求：
      * POST 到接入地址，Accept 同时声明 application/json 与 text/event-stream
      * 首次 initialize 后，服务端可能下发 Mcp-Session-Id，后续请求必须回传
      * 响应可能是纯 JSON，也可能是 SSE（``data: {...}``），两种都要能解析
    """

    def __init__(self, token: str | None = None, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: int = 40) -> None:
        self.token = (token or os.environ.get(TOKEN_ENV, "")).strip()
        if not self.token:
            raise McpError(
                f"未找到 MCP Token。请先设置环境变量 {TOKEN_ENV}，"
                "Token 可在 https://open.mcd.cn/mcp 控制台激活领取。"
            )
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._seq = 0
        self._session: str | None = None
        self._initialized = False

    # ---------------------------------------------------------------- 传输层

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _post(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                session = resp.headers.get("Mcp-Session-Id")
                if session:
                    self._session = session
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            hint = {
                401: "MCP Token 无效、已过期或未提供。",
                429: "触发限流（600 次/分钟），请降低请求频率。",
            }.get(exc.code, "")
            raise McpError(f"HTTP {exc.code} {hint} {detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"网络不可达：{exc.reason}") from exc

        return body

    @staticmethod
    def _decode(body: str) -> dict:
        """兼容纯 JSON 与 SSE（text/event-stream）两种响应形态。"""
        text = body.strip()
        if not text:
            return {}
        if text.startswith("{") or text.startswith("["):
            return json.loads(text)
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    return json.loads(chunk)
        raise McpError(f"无法解析的响应体：{text[:200]}")

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            payload["params"] = params
        result = self._decode(self._post(payload))
        if "error" in result:
            err = result["error"]
            raise McpError(f"{err.get('code')}: {err.get('message')}")
        return result.get("result", {})

    # ---------------------------------------------------------------- 协议层

    def initialize(self) -> dict:
        if self._initialized:
            return {}
        info = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-muscle-coach", "version": "1.0.0"},
        })
        # 按 MCP 规范发一条 initialized 通知（无需等待响应）
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpError:
            pass
        self._initialized = True
        return info

    def list_tools(self) -> list[dict]:
        self.initialize()
        return self._rpc("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """调用工具并把返回内容拼成纯文本。"""
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        parts = []
        for block in result.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "resource":
                parts.append(json.dumps(block.get("resource", {}), ensure_ascii=False))
        text = "\n".join(p for p in parts if p)
        if result.get("isError"):
            raise McpError(f"工具 {name} 返回错误：{text[:400]}")
        return text


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"list", "call"}:
        print(__doc__)
        return 2

    client = McdMcpClient()
    if argv[1] == "list":
        for tool in client.list_tools():
            print(f"- {tool.get('name')}: {(tool.get('description') or '').splitlines()[0]}")
        return 0

    if len(argv) < 3:
        print("用法: python scripts/mcd_client.py call <tool-name> [json-args]")
        return 2
    args = json.loads(argv[3]) if len(argv) > 3 else {}
    print(client.call_tool(argv[2], args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
