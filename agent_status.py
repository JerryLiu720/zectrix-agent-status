#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zectrix Agent 状态屏 —— 多页渲染器

用法：
  python3 agent_status.py                      # 渲染当前页（ui_state.json）到 status.png
  python3 agent_status.py --page 2             # 渲染指定页
  python3 agent_status.py --daemon             # 常驻：每 2 秒重绘（数据自动更新）

页面：
  0 概览（状态 / 今日消息 / 最近活动 / 下次任务）
  1 日程（今天 + cron 倒计时）
  2 余额（DeepSeek 余额 / 赠金 / 模型）
  3 日志（最近 3 条消息摘要）

按键（watch.rs 处理）：上/下 翻页，确认 立即刷新
"""
import os, sys, json, sqlite3, glob, argparse, datetime, re, time, urllib.request

H = os.path.expanduser("~/.hermes")
W, HT = 400, 300
BASE = os.path.expanduser("~/zectrix-sdk")
STATE = os.path.join(BASE, "ui_state.json")
BAL_CACHE = os.path.join(BASE, ".balance_cache.json")
PAGES = ["概览", "日程", "余额", "日志"]
_last_png = None   # 内容去重：没变化就不写文件，避免墨水屏频繁刷新

from PIL import Image, ImageDraw, ImageFont

# ---------------- 工具 ----------------
def font(sz, bold=True):
    # 实测：PingFang.ttc 在本机 Pillow 下 "cannot open resource"，必须用 Hiragino
    for p, idx in [("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
                   ("/System/Library/Fonts/STHeiti Light.ttc", 0)]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=idx)
            except Exception:
                pass
    return ImageFont.load_default()

def db(path):
    return sqlite3.connect(path)

def model_name():
    try:
        cfg = open(os.path.join(H, "config.yaml"), encoding="utf-8").read()
        m = re.search(r"^model:\s*\n\s+provider:\s*(\S+)\s*\n\s+default:\s*(\S+)", cfg, re.M)
        return m.group(2) if m else "—"
    except Exception:
        return "—"

def count_facts():
    try:
        return db(os.path.join(H, "memory_store.db")).execute("select count(*) from facts").fetchone()[0]
    except Exception:
        return 0

def count_skills():
    try:
        return len([p for p in glob.glob(os.path.join(H, "skills/**/SKILL.md"), recursive=True)
                    if "/.archive/" not in p])
    except Exception:
        return 0

def last_msg():
    try:
        row = db(os.path.join(H, "state.db")).execute(
            "select role, content, timestamp from messages order by timestamp desc limit 1").fetchone()
        return {"role": row[0], "content": row[1] or "", "ts": float(row[2] or 0)} if row else None
    except Exception:
        return None

def recent_msgs(n=3):
    try:
        rows = db(os.path.join(H, "state.db")).execute(
            """select role, content, timestamp from messages
               where role in ('user','assistant')
                 and content is not null and length(trim(content)) > 12
               order by timestamp desc limit ?""", (n,)).fetchall()
        return [{"role": r[0], "content": r[1], "ts": float(r[2] or 0)} for r in rows]
    except Exception:
        return []

def today_msg_count():
    try:
        start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return db(os.path.join(H, "state.db")).execute(
            "select count(*) from messages where timestamp >= ?", (start,)).fetchone()[0]
    except Exception:
        return 0

def cron_jobs():
    try:
        d = json.load(open(os.path.join(H, "cron/jobs.json"), encoding="utf-8"))
        jobs = d if isinstance(d, list) else d.get("jobs", [])
        out = []
        for j in jobs:
            if not j.get("enabled", True):
                continue
            out.append({"name": j.get("name", "任务"),
                        "next": j.get("next_run") or j.get("next_run_at"),
                        "schedule": (j.get("schedule") or {}).get("display", "")})
        out.sort(key=lambda x: x["next"] or "9999")
        return out
    except Exception:
        return []

def balance(ttl=600):
    try:
        if os.path.exists(BAL_CACHE):
            c = json.load(open(BAL_CACHE))
            if time.time() - c.get("t", 0) < ttl:
                return c["total"], c["granted"]
    except Exception:
        pass
    try:
        env = {}
        for line in open(os.path.join(H, ".env"), encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                     headers={"Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}"})
        d = json.load(urllib.request.urlopen(req, timeout=8))
        b = (d.get("balance_infos") or [{}])[0]
        total, granted = b.get("total_balance", "—"), b.get("granted_balance", "—")
        json.dump({"total": total, "granted": granted, "t": time.time()}, open(BAL_CACHE, "w"))
        return total, granted
    except Exception:
        return "—", "—"

def ago(ts):
    if not ts:
        return "—"
    mins = int((time.time() - ts) / 60)
    if mins < 1:
        return "刚刚"
    if mins < 60:
        return f"{mins} 分钟前"
    if mins < 1440:
        return f"{mins // 60} 小时前"
    return f"{mins // 1440} 天前"

def fmt_next(iso):
    if not iso:
        return "—"
    try:
        t = datetime.datetime.fromisoformat(iso)
    except Exception:
        return iso
    delta = (t - datetime.datetime.now(t.tzinfo)) if t.tzinfo else (t - datetime.datetime.now())
    mins = int(delta.total_seconds() // 60)
    if mins < 0:
        return t.strftime("%m-%d %H:%M")
    if mins < 60:
        return f"{mins} 分钟后"
    if mins < 1440:
        return f"{mins // 60} 小时后"
    return f"{mins // 1440} 天后"

def is_active():
    m = last_msg()
    return bool(m and (time.time() - m["ts"]) < 120)

# ---------------- 渲染 ----------------
def render(out, page=0):
    page = page % len(PAGES)
    img = Image.new("L", (W, HT), 255)
    d = ImageDraw.Draw(img)

    # 顶栏
    d.rectangle([0, 0, W, 34], fill=0)
    d.text((10, 7), "HERMES", font=font(18), fill=255)
    now = datetime.datetime.now().strftime("%m-%d %H时")
    d.text((W - 26 - d.textlength(now, font=font(14)), 9), now, font=font(14), fill=255)
    d.ellipse([W - 16, 13, W - 8, 21], fill=255 if is_active() else 120)

    # 页标题
    d.text((10, 40), f"{page + 1}/{len(PAGES)}  {PAGES[page]}", font=font(14), fill=90)
    d.line([10, 60, W - 10, 60], fill=170)

    y = 68
    def line(label, value, big=False, dim=False):
        nonlocal y
        d.text((12, y), label, font=font(13), fill=110)
        while d.textlength(value, font=font(19 if big else 16)) > W - 24 and len(value) > 4:
            value = value[:-2] + "…"
        d.text((12, y + 16), value, font=font(19 if big else 16), fill=70 if dim else 0)
        y += 16 + (26 if big else 22)

    if page == 0:
        line("状态", "● 任务进行中" if is_active() else "○ 空闲", big=True)
        line("今日消息", f"{today_msg_count()} 条")
        m = last_msg()
        line("最近活动", ago(m["ts"]) if m else "—")
        jobs = cron_jobs()
        if jobs:
            line(jobs[0]["name"][:16], f"{fmt_next(jobs[0]['next'])}   {jobs[0]['schedule']}")
        else:
            line("下次定时", "无")
        line("记忆 / 技能", f"{count_facts()} facts · {count_skills()} skills", dim=True)

    elif page == 1:
        today = datetime.datetime.now()
        wd = "一二三四五六日"[today.weekday()]
        line("今天", today.strftime("%Y-%m-%d") + f"  周{wd}", big=True)
        jobs = cron_jobs()
        if not jobs:
            line("定时任务", "无")
        for j in jobs[:3]:
            line(j["name"][:16], f"{fmt_next(j['next'])}  ({j['schedule']})")

    elif page == 2:
        bal, granted = balance()
        line("DeepSeek 余额", f"¥{bal}", big=True)
        line("其中赠金", f"¥{granted}")
        line("模型", model_name())
        line("记忆 / 技能", f"{count_facts()} · {count_skills()}")

    else:
        for m in recent_msgs(3):
            role = {"user": "我", "assistant": "AI", "tool": "工具"}.get(m["role"], m["role"])
            txt = re.sub(r"\s+", " ", m["content"] or "").strip()
            if len(txt) > 46:
                txt = txt[:46] + "…"
            line(f"{role} · {ago(m['ts'])}", txt)

    # 底栏
    d.line([10, HT - 30, W - 10, HT - 30], fill=160)
    for i in range(len(PAGES)):
        cx = 16 + i * 14
        d.ellipse([cx, HT - 22, cx + 7, HT - 15], fill=0 if i == page else 200)
    hint = "↑↓ 翻页"
    d.text((W - 14 - d.textlength(hint, font=font(12)), HT - 24), hint, font=font(12), fill=110)

    import io
    global _last_png
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    if data == _last_png:            # 内容没变 → 不写，避免无意义刷屏
        return out
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)             # 原子替换：watch 不会读到半张图
    _last_png = data
    return out

def read_page():
    # watch.rs 写纯文本页码（零依赖）；兼容旧的 ui_state.json
    for path, kind in [(os.path.join(BASE, "ui_state.txt"), "txt"), (STATE, "json")]:
        try:
            if kind == "txt":
                return int(open(path).read().strip()) % len(PAGES)
            return int(json.load(open(path)).get("page", 0)) % len(PAGES)
        except Exception:
            continue
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, "status.png"))
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--activity", help="(兼容旧参数，忽略)")
    a = ap.parse_args()

    if a.daemon:
        while True:
            try:
                render(a.out, read_page() if a.page is None else a.page)
            except Exception as e:
                print("render error:", e, flush=True)
            time.sleep(a.interval)
    else:
        p = read_page() if a.page is None else a.page
        print(render(a.out, p), os.path.getsize(a.out), "B")
