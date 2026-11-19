#!/usr/bin/env python3
"""Claude Code hook → Zectrix 状态屏。

在 ~/.claude/settings.json 里注册（可用 scripts/install_claude_hooks.py 自动完成）：

  UserPromptSubmit / PreToolUse → 标记"正在处理"，并累加今日消息数
  Stop                          → 标记"空闲"，从 transcript 取最后一条回复与模型名

始终 exit 0：状态屏上报失败绝不能影响 Claude Code 本体。
"""
import datetime
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import zectrix_report as zr
except Exception:
    zr = None


def log_err(msg):
    try:
        p = os.path.expanduser("~/.zectrix-hook-error.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} {msg}\n")
    except Exception:
        pass



def _bump_today(d):
    """今日消息 +1，并维护近 7 天数组（跨天自动滚动）。"""
    today = datetime.date.today()
    last = d.get("date")
    week = list(d.get("week") or [0] * 7)
    if len(week) != 7:
        week = [0] * 7
    if last != today.isoformat():
        try:
            delta = (today - datetime.date.fromisoformat(last)).days
            week = (week[delta:] + [0] * delta) if 0 < delta < 7 else [0] * 7
        except Exception:
            week = [0] * 7
        d["messages_today"] = 0
        d["date"] = today.isoformat()
    d["messages_today"] = int(d.get("messages_today") or 0) + 1
    week[today.weekday()] = d["messages_today"]
    d["week"] = week


def deepseek_balance():
    """读取 DeepSeek 余额（与 Hermes 同一个账户）；失败返回 (None, None)。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        try:
            for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    if not key:
        return None, None
    try:
        req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                     headers={"Authorization": f"Bearer {key}"})
        d = json.load(urllib.request.urlopen(req, timeout=5))
        b = (d.get("balance_infos") or [{}])[0]
        return b.get("total_balance"), b.get("granted_balance")
    except Exception:
        return None, None

def last_assistant(transcript_path):
    """从 Claude Code 的 JSONL transcript 里取最后一条助手文本和模型名。"""
    text, model = "", ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("type") != "assistant":
                    continue
                msg = e.get("message") or {}
                if msg.get("model"):
                    model = msg["model"]
                blocks = msg.get("content") or []
                if isinstance(blocks, str):
                    text = blocks
                else:
                    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                    joined = "".join(parts).strip()
                    if joined:
                        text = joined
    except Exception as e:
        log_err(f"transcript: {e}")
    return text, model


def main():
    if zr is None:
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    event = payload.get("hook_event_name") or payload.get("hook_event") or ""
    path = zr.stats_path()
    d = zr.load(path)

    try:
        # 余额最多 5 分钟查一次，避免每个 hook 都打接口
        if time.time() - float(d.get("balance_ts") or 0) > 300:
            bal, granted = deepseek_balance()
            if bal is not None:
                d["balance"] = str(bal)
                d["granted"] = str(granted if granted is not None else "0.00")
                d["balance_ts"] = time.time()

        if event in ("UserPromptSubmit", "PreToolUse"):
            d["active"] = True
            d.setdefault("elapsed", 0)
            if event == "UserPromptSubmit":
                _bump_today(d)
                d["elapsed"] = 0
        elif event == "Stop":
            d["active"] = False
            d["elapsed"] = 0
            text, model = last_assistant(payload.get("transcript_path", ""))
            if model:
                d["model"] = model
            if text:
                msg = {"role": "assistant", "content": text[:400], "ts": time.time()}
                d["last_reply"] = msg
                recent = d.get("recent") or []
                recent.insert(0, msg)
                d["recent"] = recent[:5]
        elif event == "SessionStart":
            d["active"] = False
        else:
            return
        zr.save(path, d)
    except Exception as e:
        log_err(f"{event}: {e}")


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
