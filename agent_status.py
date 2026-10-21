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
PAGES = ["概览", "统计", "日程", "日志"]
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

def link_status():
    """读取 watch 写的 conn.txt 心跳，判断设备连接状态"""
    try:
        ts = float(open(os.path.join(BASE, "conn.txt")).read().strip())
        age = time.time() - ts
        if age < 30:
            return "已连接", True
        return f"{int(age // 60)} 分钟前", False
    except Exception:
        return "未连接", False

def last_reply():
    """最后一条助手回复（不是用户消息）"""
    try:
        row = db(os.path.join(H, "state.db")).execute(
            """select role, content, timestamp from messages
               where role='assistant' and content is not null and length(trim(content))>0
               order by timestamp desc limit 1""").fetchone()
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

def wrap_text(d, text, fnt, max_w, max_lines=2):
    """按像素宽度折行，超出用省略号"""
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=fnt) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and sum(len(x) for x in lines) < len(text):
        last = lines[-1]
        while d.textlength(last + "…", font=fnt) > max_w and len(last) > 1:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines

def today_cost(rate=7.1):
    """今日花费：优先 actual_cost_usd，否则 estimated_cost_usd（美元）"""
    try:
        c = db(os.path.join(H, "state.db"))
        start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        r = c.execute("""select coalesce(sum(case when actual_cost_usd > 0 then actual_cost_usd
                                                  else estimated_cost_usd end), 0)
                         from session_model_usage where last_seen >= ?""", (start,)).fetchone()
        usd = float(r[0] or 0)
        return usd, usd * rate
    except Exception:
        return 0.0, 0.0

def week_counts():
    """最近 7 天每天的消息数（含今天），用于柱状图"""
    try:
        c = db(os.path.join(H, "state.db"))
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - datetime.timedelta(days=6)
        rows = dict(c.execute(
            """select date(timestamp,'unixepoch','localtime') d, count(*)
               from messages where timestamp >= ? group by d""", (start.timestamp(),)).fetchall())
        return [rows.get((start + datetime.timedelta(days=i)).strftime("%Y-%m-%d"), 0) for i in range(7)]
    except Exception:
        return [0] * 7

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
    now = datetime.datetime.now().strftime("%m-%d %H:%M")
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
        # 仪表盘：模型 / 进度 / 花费 / 余额 / 连接 / 时间
        active = is_active()
        usd, cny = today_cost()
        bal, granted = balance()
        ltxt, lok = link_status()
        m = last_reply()

        # 模型 + 进度
        d.text((16, 66), "模型", font=font(11), fill=125)
        mdl = model_name()
        while d.textlength(mdl, font=font(19)) > 250 and len(mdl) > 4:
            mdl = mdl[:-2] + "…"
        d.text((16, 82), mdl, font=font(19), fill=0)

        d.text((16, 112), "当前进度", font=font(11), fill=125)
        if active:
            prog, sub = "正在处理", (f"最近活动 {ago(m['ts'])}" if m else "")
        else:
            prog, sub = "空闲 · 等待指令", (f"上次活动 {ago(m['ts'])}" if m else "")
        d.text((16, 128), prog, font=font(19), fill=0)
        d.text((16, 152), sub, font=font(10, bold=False), fill=125)

        d.line([16, 172, W - 16, 172], fill=210)

        # 花费 / 余额
        d.text((16, 180), "今日花费", font=font(11), fill=125)
        d.text((16, 196), f"¥{cny:,.2f}", font=font(26), fill=0)
        d.text((16, 228), f"≈ ${usd:.2f}", font=font(10, bold=False), fill=125)

        bx = 232
        d.text((bx, 180), "账户余额", font=font(11), fill=125)
        d.text((bx, 196), f"¥{bal}", font=font(26), fill=0)
        d.text((bx, 228), f"赠金 ¥{granted}", font=font(10, bold=False), fill=125)

        # 页脚上一行：连接状态 + 最近回复首句
        d.line([16, 244, W - 16, 244], fill=210)
        d.text((16, 250), "●" if lok else "○", font=font(11), fill=0 if lok else 140)
        d.text((30, 250), ltxt, font=font(11), fill=110)
        if m:
            body = re.sub(r"[*_`#>\s]+", " ", m["content"] or "").strip()[:15]
            d.text((118, 250), f"最近 {ago(m['ts'])} · {body}…", font=font(11, bold=False), fill=110)

    elif page == 1:
        # 统计：近 7 日消息
        d.text((16, 68), "近 7 日消息", font=font(13), fill=110)
        wc = week_counts()
        RX, base_y, max_h = 22, 198, 96
        bw, gap = 36, 14
        mx = max(wc) or 1
        for i, v in enumerate(wc):
            x = RX + i * (bw + gap)
            h = max(3, int(v / mx * max_h))
            top = base_y - h
            if i == 6:
                d.rectangle([x, top, x + bw, base_y], fill=0)
            else:
                d.rectangle([x, top, x + bw, base_y], outline=0, width=2)
                for yy in range(top + 3, base_y - 2, 5):
                    d.line([x + 2, yy, x + bw - 2, yy], fill=205, width=1)
            label = str(v)
            d.text((x + bw / 2 - d.textlength(label, font=font(11, bold=False)) / 2, top - 15),
                   label, font=font(11, bold=False), fill=90)
        d.line([RX - 8, base_y, RX + 7 * (bw + gap) - gap + 4, base_y], fill=0, width=2)
        for i, wd in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            d.text((RX + i * (bw + gap) + bw / 2 - 5, base_y + 6), wd, font=font(11, bold=False), fill=120)

        d.line([10, 234, W - 10, 234], fill=200)
        d.text((16, 242), f"今日 {today_msg_count()} 条", font=font(13), fill=0)
        d.text((148, 242), f"记忆 {count_facts()}", font=font(13), fill=0)
        d.text((272, 242), f"技能 {count_skills()}", font=font(13), fill=0)

    elif page == 2:
        today = datetime.datetime.now()
        wd = "一二三四五六日"[today.weekday()]
        line("今天", today.strftime("%Y-%m-%d") + f"  周{wd}", big=True)
        jobs = cron_jobs()
        if not jobs:
            line("定时任务", "无")
        for j in jobs[:3]:
            line(j["name"][:16], f"{fmt_next(j['next'])}  ({j['schedule']})")

    else:
        for m in recent_msgs(3):
            role = {"user": "我", "assistant": "AI", "tool": "工具"}.get(m["role"], m["role"])
            txt = re.sub(r"\s+", " ", m["content"] or "").strip()
            txt = re.sub(r"[*_`#>]+", "", txt).strip()      # 去掉 markdown 符号
            txt = re.sub(r"^[-\s]+", "", txt)
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
                try:
                    open(os.path.join(BASE, "active.txt"), "w").write("1" if is_active() else "0")
                except Exception:
                    pass
                render(a.out, read_page() if a.page is None else a.page)
            except Exception as e:
                print("render error:", e, flush=True)
            time.sleep(a.interval)
    else:
        p = read_page() if a.page is None else a.page
        print(render(a.out, p), os.path.getsize(a.out), "B")
