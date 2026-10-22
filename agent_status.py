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
BASE = os.environ.get("ZECTRIX_BASE") or os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "ui_state.json")
BAL_CACHE = os.path.join(BASE, ".balance_cache.json")
PAGES = ["概览", "统计", "日程", "日志"]

# ---------------- 配置：支持接入任意助手 ----------------
CONFIG_PATH = os.path.join(BASE, "config.json")
STATS = {}            # 外部助手提供的统计数据（source=json 时生效）
CFG = {}              # config.json 内容
STATS_MTIME = 0

def load_config():
    try:
        return json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception:
        return {}

def refresh_stats():
    """读取外部统计数据文件（其他助手只需按格式写这个 JSON）"""
    global STATS, STATS_MTIME, CFG
    cfg = load_config()
    CFG = cfg
    if cfg.get("source") != "json":
        return cfg
    path = os.path.expanduser(cfg.get("stats_file", "~/zectrix-stats.json"))
    try:
        mtime = os.path.getmtime(path)
        if mtime != STATS_MTIME:
            STATS = json.load(open(path, encoding="utf-8"))
            STATS_MTIME = mtime
    except Exception:
        pass
    return cfg

def sget(key, default=None):
    """从外部统计数据取值（无则返回 default）"""
    return STATS.get(key, default)

DEMO = False   # True = 当前渲染的是示例数据
VERSION = "0.1.0"
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
    v = sget("model")
    if v: return v
    try:
        cfg = open(os.path.join(H, "config.yaml"), encoding="utf-8").read()
        m = re.search(r"^model:\s*\n\s+provider:\s*(\S+)\s*\n\s+default:\s*(\S+)", cfg, re.M)
        return m.group(2) if m else "—"
    except Exception:
        return "—"

def count_facts():
    v = sget("memory_count")
    if v is not None: return v
    try:
        return db(os.path.join(H, "memory_store.db")).execute("select count(*) from facts").fetchone()[0]
    except Exception:
        return 0

def count_skills():
    v = sget("skill_count")
    if v is not None: return v
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

def battery():
    """设备电量与充电状态（由 watch 定期写入 battery.txt）"""
    v = sget("battery")
    if v is not None: return int(v), bool(sget("charging", False))
    try:
        s = open(os.path.join(BASE, "battery.txt")).read().strip()
        parts = s.split(",")
        pct = int(parts[0])
        charging = len(parts) > 1 and parts[1].strip() == "1"
        return pct, charging
    except Exception:
        return None, False

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
    v = sget("last_reply")
    if v: return v
    try:
        row = db(os.path.join(H, "state.db")).execute(
            """select role, content, timestamp from messages
               where role='assistant' and content is not null and length(trim(content))>0
               order by timestamp desc limit 1""").fetchone()
        return {"role": row[0], "content": row[1] or "", "ts": float(row[2] or 0)} if row else None
    except Exception:
        return None

def recent_msgs(n=3):
    v = sget("recent")
    if v: return list(v)[:n]
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
    v = sget("messages_today")
    if v is not None: return v
    try:
        start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return db(os.path.join(H, "state.db")).execute(
            "select count(*) from messages where timestamp >= ?", (start,)).fetchone()[0]
    except Exception:
        return 0

def cron_jobs():
    v = sget("cron")
    if v is not None: return v
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
    v = sget("balance")
    if v is not None: return str(v), str(sget("granted", "0.00")), 0.0
    try:
        if os.path.exists(BAL_CACHE):
            c = json.load(open(BAL_CACHE))
            if time.time() - c.get("t", 0) < ttl:
                return c["total"], c["granted"], time.time() - c.get("t", 0)
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
        return total, granted, 0.0
    except Exception:
        return "—", "—", None

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

def daily_spend(total_str):
    """今日花费 = 当日余额下降量（与 DeepSeek 后台口径一致）
    首次运行当天只能从启动时刻开始计，返回 (金额, 起始时间戳)"""
    v = sget("spend_today")
    if v is not None: return float(v), None
    try:
        bal = float(total_str)
    except Exception:
        return None, None
    path = os.path.join(BASE, ".balance_daily.json")
    today = datetime.date.today().isoformat()
    try:
        d = json.load(open(path))
    except Exception:
        d = {}
    if d.get("date") != today:
        d = {"date": today, "start": bal, "since": time.time()}
    elif bal > float(d.get("start", bal)) + 0.005:      # 充值 → 重置基线
        d = {"date": today, "start": bal, "since": time.time()}
    else:
        d.setdefault("since", time.time())
    try:
        json.dump(d, open(path, "w"))
    except Exception:
        pass
    return max(0.0, float(d["start"]) - bal), d.get("since")

def week_counts():
    """最近 7 天每天的消息数（含今天），用于柱状图"""
    v = sget("week")
    if v: return v
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

def turn_state():
    """返回 (是否在处理, 本轮已运行秒数)。依据 Hermes 的 session_turn_leases。
    租约存在且未过期 = 正在跑一轮；否则空闲。"""
    if "active" in STATS: return bool(STATS["active"]), float(STATS.get("elapsed", 0))
    try:
        c = db(os.path.join(H, "state.db"))
        row = c.execute("""select acquired_at, expires_at from session_turn_leases
                           order by rowid desc limit 1""").fetchone()
        if row:
            acq, exp = float(row[0] or 0), float(row[1] or 0)
            now = time.time()
            if exp > now and now - acq < 1800:
                return True, now - acq
    except Exception:
        pass
    return False, 0.0

def is_active():
    m = last_msg()
    return bool(m and (time.time() - m["ts"]) < 120)

# ---------------- 渲染 ----------------
def render(out, page=0):
    refresh_stats()
    page = page % len(PAGES)
    img = Image.new("L", (W, HT), 255)
    d = ImageDraw.Draw(img)

    # 顶栏
    d.rectangle([0, 0, W, 34], fill=0)
    d.text((10, 7), str(CFG.get("assistant_name", "HERMES")).upper(), font=font(18), fill=255)
    now = datetime.datetime.now().strftime("%m-%d %H:%M")

    # 右上角：电量图标（实心比例 + 百分比），从右往左排
    pct, charging = battery()
    icon_w, icon_h, iy = 24, 10, 11
    ix = W - 9 - icon_w
    d.rounded_rectangle([ix, iy, ix + icon_w - 5, iy + icon_h], radius=2, outline=255, width=1)
    d.rounded_rectangle([ix + icon_w - 4, iy + 4, ix + icon_w - 2, iy + icon_h - 4], radius=1, fill=255)
    if pct is not None:
        fw = int((icon_w - 7) * max(0, min(pct, 100)) / 100)
        if fw > 0:
            d.rounded_rectangle([ix + 2, iy + 2, ix + 1 + fw, iy + icon_h - 2], radius=1, fill=255)

    bx = ix - 10
    if pct is not None and pct <= 20 and not charging:
        d.text((bx - d.textlength("!", font=font(14)), 8), "!", font=font(14), fill=255)
        bx -= 12
    d.text((bx - d.textlength(now, font=font(14)), 9), now, font=font(14), fill=255)
    # 顶栏不再放灯：时间右对齐到底


    # 页标题
    d.text((10, 40), f"{page + 1}/{len(PAGES)}  {PAGES[page]}", font=font(14), fill=90)

    # 右上角：连接状态（与页标题同一行）
    _ltxt, _lok = link_status()
    _f = font(11)
    _tw = d.textlength(_ltxt, font=_f)
    _r = 4
    _cx = W - 10 - _tw - 5 - _r
    _cy = 48
    if _lok:
        d.ellipse([_cx - _r, _cy - _r, _cx + _r, _cy + _r], fill=0)
    else:
        d.ellipse([_cx - _r, _cy - _r, _cx + _r, _cy + _r], outline=0, width=2)
    d.text((W - 10 - _tw, 42), _ltxt, font=_f, fill=90)

    d.line([10, 60, W - 10, 60], fill=170)

    y = 68
    def line(label, value, big=False, dim=False):
        nonlocal y
        d.text((12, y), label, font=font(14), fill=110)
        while d.textlength(value, font=font(19 if big else 16)) > W - 24 and len(value) > 4:
            value = value[:-2] + "…"
        d.text((12, y + 16), value, font=font(19 if big else 16), fill=70 if dim else 0)
        y += 16 + (26 if big else 22)

    if page == 0:
        # 仪表盘：当前进度 → 模型 → 花费/余额 → 最近消息
        active, elapsed = turn_state()
        bal, granted, bage = balance()
        cny, since = daily_spend(bal)
        m = last_reply()

        # 当前进度（最上面）：真实租约 → 处理中 + 本轮耗时
        d.text((16, 66), "当前进度", font=font(11), fill=125)
        prog = "正在处理" if active else "空闲·等待指令"
        d.text((16, 80), prog, font=font(28), fill=0)
        if active:
            secs = int(elapsed)
            sub = f"本轮 {secs // 60} 分 {secs % 60} 秒" if secs >= 60 else f"本轮 {secs} 秒"
        else:
            sub = f"上次回复 {ago(m['ts'])}" if m else "暂无回复"
        d.text((16, 120), sub, font=font(11, bold=False), fill=120)

        # 右侧：模型（小标题在上、名称放大，下方补今日消息数）
        mdl = model_name()
        f_lbl, f_mdl = font(11), font(20)
        while d.textlength(mdl, font=f_mdl) > 170 and len(mdl) > 4:
            mdl = mdl[:-2] + "…"
        mx = W - 16 - d.textlength(mdl, font=f_mdl)
        d.text((mx, 64), "模型", font=f_lbl, fill=125)
        d.text((mx, 82), mdl, font=f_mdl, fill=0)
        sub = f"今日 {today_msg_count()} 条消息"
        sx = min(mx, W - 16 - d.textlength(sub, font=font(11)))
        d.text((sx, 112), sub, font=font(11), fill=125)

        d.line([16, 138, W - 16, 138], fill=210)

        # 花费 / 余额
        slab = "今日花费"
        if since:
            midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            if since - midnight > 600:
                slab += " · " + datetime.datetime.fromtimestamp(since).strftime("%H:%M") + " 起"
        d.text((16, 146), slab, font=font(11, bold=False), fill=125)
        d.text((16, 162), (f"¥{cny:,.2f}" if cny is not None else "—"), font=font(29), fill=0)

        bx = 232
        blabel = "账户余额"
        if bage is not None and bage >= 60:
            blabel += f" · {int(bage // 60)} 分钟前"
        elif bage is not None:
            blabel += " · 刚刚"
        d.text((bx, 146), blabel, font=font(11, bold=False), fill=125)
        d.text((bx, 162), f"¥{bal}", font=font(29), fill=0)
        # 赠金：右侧，底部与余额数字的墨迹底部对齐
        gtxt = f"赠金 ¥{granted}"
        gb = d.textbbox((0, 0), gtxt, font=font(10))
        nb = d.textbbox((0, 0), f"¥{bal}", font=font(29))
        gy = 162 + nb[3] - gb[3]
        d.text((W - 16 - d.textlength(gtxt, font=font(10)), gy), gtxt, font=font(10), fill=125)

        d.line([16, 204, W - 16, 204], fill=210)

        # 最近消息（最多两行）
        d.text((16, 210), "最近消息", font=font(10, bold=False), fill=125)
        if m:
            body = clean_text(m["content"], 64)
            lines = wrap_lines(d, body, 14, W - 32, 2)
            d.text((16, 224), f"{ago(m['ts'])} · {lines[0]}", font=font(14), fill=0)
            if len(lines) > 1:
                d.text((16, 242), lines[1], font=font(14), fill=0)
        else:
            d.text((16, 224), "暂无记录", font=font(14), fill=110)

    elif page == 1:
        # 统计：近 7 日消息
        d.text((16, 68), "近 7 日消息", font=font(14), fill=110)
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
        d.text((16, 241), f"今日 {today_msg_count()} 条", font=font(14), fill=0)
        d.text((150, 241), f"记忆 {count_facts()}", font=font(14), fill=0)
        d.text((276, 241), f"技能 {count_skills()}", font=font(14), fill=0)

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
            txt = clean_text(m["content"], 46)
            if len(txt) > 46:
                txt = txt[:46] + "…"
            line(f"{role} · {ago(m['ts'])}", txt)

    # 底栏
    d.line([10, HT - 30, W - 10, HT - 30], fill=160)
    for i in range(len(PAGES)):
        cx = 16 + i * 14
        d.ellipse([cx, HT - 22, cx + 7, HT - 15], fill=0 if i == page else 200)
    hint = f"v{VERSION} · " + ("示例数据 · " if DEMO else "") + "↑↓ 翻页"
    hf = font(11)
    while d.textlength(hint, font=hf) > W - 90 and hf.size > 8:
        hf = font(hf.size - 1)
    d.text((W - 14 - d.textlength(hint, font=hf), HT - 24), hint, font=hf, fill=110)

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

def clean_text(s, limit=None):
    """去掉 markdown 符号与字体不支持的 emoji，避免出现方块"""
    s = re.sub(r"[*_`#>]+", "", s or "")
    s = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\uFE0F\u200D]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[-\s]+", "", s)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s

def wrap_lines(d, text, size, max_w, max_lines=2):
    """按像素宽度折行，最多 max_lines 行，超出用省略号。"""
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font(size)) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    elif cur and lines:
        lines[-1] = lines[-1][:-1] + "…"
    return lines or [""]

def enable_demo():
    """把数据源替换为示例值：用于生成截图、给没有 Hermes 的人预览"""
    global DEMO
    DEMO = True
    global model_name, today_cost, balance, count_facts, count_skills
    global week_counts, cron_jobs, last_reply, today_msg_count, link_status, turn_state, recent_msgs

    now = time.time()
    model_name = lambda: "deepseek-v4"
    today_cost = lambda rate=7.1: (0.86, 0.86 * rate)
    daily_spend = lambda s: (6.12, time.time() - 3600)
    balance = lambda ttl=600: ("42.00", "12.00", 180.0)
    count_facts = lambda: 186
    count_skills = lambda: 34
    week_counts = lambda: [312, 118, 26, 0, 141, 9, 274]
    cron_jobs = lambda: [
        {"name": "每周记忆抽取", "next": (datetime.datetime.now() + datetime.timedelta(days=3)).isoformat(), "schedule": "0 23 * * 0"},
        {"name": "每月体检", "next": (datetime.datetime.now() + datetime.timedelta(days=10)).isoformat(), "schedule": "0 23 1 * *"},
    ]
    last_reply = lambda: {"role": "assistant", "content": "已经把最近 7 天的对话整理成摘要，放在第 2 页。", "ts": now - 95}
    today_msg_count = lambda: 274
    link_status = lambda: ("已连接", True)
    turn_state = lambda: (True, 42.0)
    recent_msgs = lambda n=3: [
        {"role": "assistant", "content": "已经把最近 7 天的对话整理成摘要。", "ts": now - 95},
        {"role": "user", "content": "帮我看一下这周的账单。", "ts": now - 260},
        {"role": "assistant", "content": "本周支出比上周少了一些。", "ts": now - 300},
    ]
    print("（示例数据模式）")

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

def claim_single_instance():
    """同一目录只允许一个 daemon：避免重复进程抢设备"""
    lock = os.path.join(BASE, ".daemon.lock")
    try:
        pid = int(open(lock).read().strip())
        if pid != os.getpid():
            os.kill(pid, 0)          # 进程还在 → 直接退出
            print(f"已有 daemon 在运行（pid {pid}），本次退出")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
    open(lock, "w").write(str(os.getpid()))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, "status.png"))
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--activity", help="(兼容旧参数，忽略)")
    ap.add_argument("--demo", action="store_true", help="用示例数据渲染（截图/他人试用）")
    ap.add_argument("--selftest", action="store_true", help="渲染全部页面并校验尺寸")
    a = ap.parse_args()

    if a.demo or (not a.selftest and not os.path.exists(os.path.join(H, "state.db"))):
        enable_demo()

    if a.selftest:
        import tempfile
        ok = True
        for i in range(len(PAGES)):
            out = os.path.join(tempfile.gettempdir(), f"zectrix_selftest_{i}.png")
            render(out, i)
            with Image.open(out) as im:
                good = im.size == (W, HT)
            ok = ok and good and os.path.getsize(out) > 1000
            print(f"  page {i+1} {PAGES[i]}: {'OK' if good else 'FAIL'} ({os.path.getsize(out)} B)")
        print("selftest", "通过" if ok else "失败")
        raise SystemExit(0 if ok else 1)

    if a.daemon:
        claim_single_instance()
        # 页码响应优先：无论传什么间隔，最多 0.5 秒检查一次（渲染内容不变则不落盘）
        delay = min(max(a.interval, 0.2), 0.5)
        while True:
            try:
                try:
                    # 确认键请求：清余额缓存 + 强制重绘
                    freq = os.path.join(BASE, "force.req")
                    if os.path.exists(freq):
                        os.remove(freq)
                        try:
                            os.remove(BAL_CACHE)
                        except Exception:
                            pass
                        globals()["_last_png"] = None      # 绕过内容去重
                        print("强制刷新：已清缓存，重绘中", flush=True)
                    open(os.path.join(BASE, "active.txt"), "w").write("1" if turn_state()[0] else "0")
                    open(os.path.join(BASE, "pages.txt"), "w").write(str(len(PAGES)))
                except Exception:
                    pass
                render(a.out, read_page() if a.page is None else a.page)
            except Exception as e:
                print("render error:", e, flush=True)
            time.sleep(delay)
    else:
        p = read_page() if a.page is None else a.page
        print(render(a.out, p), os.path.getsize(a.out), "B")
