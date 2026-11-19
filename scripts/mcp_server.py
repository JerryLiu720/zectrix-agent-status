#!/usr/bin/env python3
"""zectrix-mcp — 把状态屏暴露成一个 MCP server。

任何支持 MCP 的 agent（Claude Code / Cursor / Codex…）都能直接调用：

    display_status(title, body, ttl)   在屏幕上显示一条通知
    clear_status()                     立即清掉通知

注册（Claude Code）：
    claude mcp add zectrix -- python3 <repo>/scripts/mcp_server.py

协议：MCP over stdio，JSON-RPC 2.0，一行一条消息。
"""
import json
import os
import sys
import time

BASE = os.environ.get("ZECTRIX_BASE") or os.path.expanduser("~/zectrix-sdk")
NOTIFY = os.path.join(BASE, "notify.json")
SERVER_INFO = {"name": "zectrix-screen", "version": "1.0.0"}
PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "display_status",
        "description": "Show a notification on the Zectrix e-ink status screen. Replaces the current notification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short headline (<= 40 chars)"},
                "body": {"type": "string", "description": "One line of detail (<= 64 chars)"},
                "ttl": {"type": "integer", "description": "Seconds before it disappears", "default": 300},
            },
            "required": ["title"],
        },
    },
    {
        "name": "clear_status",
        "description": "Remove the current notification from the screen.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(mid, result):
    send({"jsonrpc": "2.0", "id": mid, "result": result})


def err(mid, code, message):
    send({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


def write_notify(title, body="", ttl=300):
    os.makedirs(BASE, exist_ok=True)
    tmp = NOTIFY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"title": title, "body": body, "ts": time.time(), "ttl": int(ttl)}, f, ensure_ascii=False)
    os.replace(tmp, NOTIFY)


def handle(req):
    mid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        ok(mid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return
    elif method == "ping":
        ok(mid, {})
    elif method == "tools/list":
        ok(mid, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "display_status":
            write_notify(args.get("title", ""), args.get("body", ""), args.get("ttl", 300))
            ok(mid, {"content": [{"type": "text", "text": f"displayed: {args.get('title','')}"}]})
        elif name == "clear_status":
            try:
                os.remove(NOTIFY)
            except FileNotFoundError:
                pass
            ok(mid, {"content": [{"type": "text", "text": "cleared"}]})
        else:
            err(mid, -32602, f"unknown tool: {name}")
    else:
        err(mid, -32601, f"method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        try:
            handle(req)
        except Exception as e:
            err(req.get("id"), -32603, str(e))


if __name__ == "__main__":
    main()
