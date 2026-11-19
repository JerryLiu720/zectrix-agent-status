#!/usr/bin/env python3
"""zectrix-report — 让任何 agent 用一行命令更新状态屏数据。

示例：
    zectrix-report --active --elapsed 12
    zectrix-report --idle --spend 0.42 --messages 128
    zectrix-report --model claude-sonnet-4 --balance 88.8 --granted 8.8
    zectrix-report --reply "重构完成，测试全过" --role assistant
    zectrix-report --inc-messages 1 --week 3,7,2,9,0,5,12

数据写到 config.json 的 stats_file（默认 ~/zectrix-stats.json），
配合 agent_status.py 的 "source": "json" 使用。
"""
import argparse
import json
import os
import sys
import tempfile
import time

DEFAULT_STATS = "~/zectrix-stats.json"
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


def load_config(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def stats_path(cli_path=None):
    if cli_path:
        return os.path.expanduser(cli_path)
    env = os.environ.get("ZECTRIX_STATS_FILE")
    if env:
        return os.path.expanduser(env)
    cfg = load_config(DEFAULT_CONFIG)
    for s in (cfg.get("sources") or []):
        if (s or {}).get("type") == "json" and s.get("path"):
            return os.path.expanduser(s["path"])
    return os.path.expanduser(cfg.get("stats_file") or DEFAULT_STATS)


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description="update the Zectrix status screen stats file")
    ap.add_argument("--file", help="stats 文件路径（默认读 config.json 的 stats_file）")
    ap.add_argument("--model")
    ap.add_argument("--balance")
    ap.add_argument("--granted")
    ap.add_argument("--spend", type=float, help="今日花费（绝对值）")
    ap.add_argument("--inc-spend", type=float, help="今日花费增量")
    ap.add_argument("--messages", type=int, help="今日消息数（绝对值）")
    ap.add_argument("--inc-messages", type=int, help="今日消息数增量")
    ap.add_argument("--memory", type=int)
    ap.add_argument("--skills", type=int)
    ap.add_argument("--week", help="近 7 天消息数，逗号分隔，如 3,7,2,9,0,5,12")
    ap.add_argument("--reply", help="最近一条回复内容")
    ap.add_argument("--role", default="assistant", choices=["assistant", "user", "tool"])
    ap.add_argument("--active", action="store_true", help="标记为正在处理")
    ap.add_argument("--idle", action="store_true", help="标记为空闲")
    ap.add_argument("--elapsed", type=float, help="本轮已运行秒数")
    ap.add_argument("--cron-json", help="定时任务 JSON 数组")
    ap.add_argument("--battery", type=int)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    path = stats_path(a.file)
    d = load(path)
    now = time.time()

    if a.model:
        d["model"] = a.model
    if a.balance is not None:
        d["balance"] = str(a.balance)
    if a.granted is not None:
        d["granted"] = str(a.granted)
    if a.spend is not None:
        d["spend_today"] = round(a.spend, 4)
    if a.inc_spend is not None:
        d["spend_today"] = round(float(d.get("spend_today") or 0) + a.inc_spend, 4)
    if a.messages is not None:
        d["messages_today"] = a.messages
    if a.inc_messages is not None:
        d["messages_today"] = int(d.get("messages_today") or 0) + a.inc_messages
    if a.memory is not None:
        d["memory_count"] = a.memory
    if a.skills is not None:
        d["skill_count"] = a.skills
    if a.week:
        try:
            vals = [int(x) for x in a.week.replace(" ", "").split(",") if x != ""]
            if len(vals) == 7:
                d["week"] = vals
            else:
                print("warning: --week 需要 7 个整数，已忽略", file=sys.stderr)
        except ValueError:
            print("warning: --week 解析失败，已忽略", file=sys.stderr)
    if a.cron_json:
        try:
            d["cron"] = json.loads(a.cron_json)
        except Exception as e:
            print(f"warning: --cron-json 解析失败: {e}", file=sys.stderr)
    if a.battery is not None:
        d["battery"] = a.battery
    if a.active:
        d["active"] = True
        d["elapsed"] = float(a.elapsed or 0)
    elif a.idle:
        d["active"] = False
        d["elapsed"] = 0
    elif a.elapsed is not None:
        d["elapsed"] = float(a.elapsed)
    if a.reply is not None:
        msg = {"role": a.role, "content": a.reply, "ts": now}
        d["last_reply"] = msg
        recent = d.get("recent") or []
        recent.insert(0, msg)
        d["recent"] = recent[:5]

    save(path, d)
    if not a.quiet:
        print(path)


if __name__ == "__main__":
    main()
