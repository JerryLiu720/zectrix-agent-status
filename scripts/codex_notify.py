#!/usr/bin/env python3
"""Codex 的 notify 回调 → 写入 zectrix 状态文件。

在 ~/.codex/config.toml 里加：
    notify = ["/usr/bin/python3", "/path/to/scripts/codex_notify.py"]

Codex 会把事件 JSON 作为最后一个参数传进来。
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from claude_code_hook import _bump_today  # noqa: E402

STATS = os.path.expanduser("~/zectrix-stats.json")


def load():
    try:
        return json.load(open(STATS, encoding="utf-8"))
    except Exception:
        return {}


def save(d):
    tmp = STATS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATS)


def codex_model():
    try:
        txt = open(os.path.expanduser("~/.codex/config.toml"), encoding="utf-8").read()
        m = re.search(r'^\s*model\s*=\s*"([^"]+)"', txt, re.M)
        return m.group(1) if m else ""
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2:
        return 0
    try:
        ev = json.loads(sys.argv[-1])
    except Exception:
        return 0
    d = load()
    kind = ev.get("type") or ""
    now = time.time()
    if kind == "agent-turn-complete":
        _bump_today(d)
        text = (ev.get("last-assistant-message") or "").strip()
        if text:
            msg = {"role": "assistant", "content": text[:500], "ts": now}
            d["last_reply"] = msg
            recent = [m for m in (d.get("recent") or []) if m.get("content") != msg["content"]]
            d["recent"] = [msg] + recent[:4]
        d["active"] = False
        d["elapsed"] = 0
        mdl = codex_model()
        if mdl:
            d["model"] = mdl
    elif kind in ("approval-requested", "agent-turn-start"):
        d["active"] = True
    save(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
