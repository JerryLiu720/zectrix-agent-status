#!/usr/bin/env python3
"""把 Zectrix 上报 hook 装进 Claude Code（~/.claude/settings.json）。

用法：
    python3 scripts/install_claude_hooks.py            # 安装/更新
    python3 scripts/install_claude_hooks.py --remove   # 卸载

会先备份 settings.json，只增删本项目的 hook，不动其它配置。
"""
import argparse
import json
import os
import shutil
import sys
import time

SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_code_hook.py")
CMD = f'python3 "{HOOK}"'
EVENTS = ["UserPromptSubmit", "PreToolUse", "Stop"]


def load():
    try:
        return json.load(open(SETTINGS, encoding="utf-8"))
    except Exception:
        return {}


def is_ours(entry):
    return any(CMD in (h.get("command") or "") for h in entry.get("hooks", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(SETTINGS) and not a.remove:
        print(f"未找到 {SETTINGS}，先在终端运行一次 claude 完成初始化", file=sys.stderr)
        return 1

    data = load()
    if not a.remove:
        shutil.copy(SETTINGS, SETTINGS + f".bak.{time.strftime('%Y%m%d_%H%M%S')}")

    hooks = data.setdefault("hooks", {})
    for ev in EVENTS:
        entries = [e for e in hooks.get(ev, []) if not is_ours(e)]
        if not a.remove:
            entry = {"hooks": [{"type": "command", "command": CMD}]}
            if ev == "PreToolUse":
                entry = {"matcher": "*", **entry}
            entries.append(entry)
        if entries:
            hooks[ev] = entries
        else:
            hooks.pop(ev, None)

    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(("已卸载" if a.remove else "已安装") + f"：{', '.join(EVENTS)}")
    print(f"hook: {HOOK}")


if __name__ == "__main__":
    sys.exit(main())
