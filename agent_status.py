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

H = os.environ.get("ZECTRIX_HOME") or os.path.expanduser("~/.hermes")
W, HT = 400, 300
BASE = os.environ.get("ZECTRIX_BASE") or os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "ui_state.json")
BAL_CACHE = os.path.join(BASE, ".balance_cache.json")
PAGE_KEYS = ["overview", "stats", "schedule", "log"]

# ---------------- 配置：支持接入任意助手 ----------------
CONFIG_PATH = os.path.join(BASE, "config.json")
STATS = {}            # 主数据源（兼容旧的 source/stats_file）
CFG = {}              # config.json 内容
STATS_MTIME = 0
SOURCES = []          # 多数据源：[{label, type, path, data}]
PRIMARY = "hermes"    # 主数据源：hermes 或 json（sget 读主源）
_DATA_CACHE = {}      # path -> {"mtime": float, "data": dict}

# ---------------- 多语言（config.json: "lang": "zh" | "en"） ----------------
STRINGS = {
    "zh": {
        "overview": "概览", "stats": "统计", "schedule": "日程", "log": "日志",
        "current": "当前进度", "working": "正在处理", "idle": "空闲·等待指令",
        "turn_min": "本轮 {m} 分 {s} 秒", "turn_sec": "本轮 {s} 秒",
        "last_reply": "上次回复 {ago}", "no_reply": "暂无回复",
        "model": "模型", "msgs_today": "今日 {n} 条消息",
        "spent_today": "今日花费", "since": " · {t} 起",
        "balance": "账户余额", "min_ago": " · {n} 分钟前", "just_now": " · 刚刚",
        "credit": "赠金 ¥{v}", "credit_na": "赠金 —", "recent": "最近消息", "no_records": "暂无记录",
        "last7": "近 7 日消息", "today_n": "今日 {n} 条", "mem": "记忆 {n}", "skills": "技能 {n}",
        "today": "今天", "date_wd": "  {wd}", "cron": "定时任务", "none": "无",
        "role_user": "我", "role_ai": "AI", "role_tool": "工具",
        "paging": "↑↓ 翻页", "demo": "示例数据 · ",
        "connected": "已连接", "disconnected": "未连接",
        "ago_just": "刚刚", "ago_min": "{n} 分钟前", "ago_hour": "{n} 小时前", "ago_day": "{n} 天前",
        "next_min": "{n} 分钟后", "next_hour": "{n} 小时后", "next_day": "{n} 天后",
        "week_short": ["一", "二", "三", "四", "五", "六", "日"],
        "week_full": ["一", "二", "三", "四", "五", "六", "日"],
        "week_sun": ["日", "一", "二", "三", "四", "五", "六"],
        "cron_workday": "工作日 {t}", "cron_weekday": "每周{wd} {t}",
        "cron_monthly": "每月 {d} 日 {t}", "cron_daily": "每天 {t}",
        "cron_every_min": "每 {n} 分钟", "cron_every_hour": "每 {n} 小时",
        "selftest_pass": "通过", "selftest_fail": "失败",
        "notice": "通知", "low_balance": "! 余额偏低 ¥{v}", "src_stale": "数据源 {n} 分钟未更新",
        "agent_working": "{label} · 正在处理", "agent_done": "{label} · {ago}完成",
    },
    "en": {
        "overview": "Overview", "stats": "Stats", "schedule": "Schedule", "log": "Log",
        "current": "CURRENT", "working": "Working", "idle": "Idle",
        "turn_min": "Turn {m}m {s}s", "turn_sec": "Turn {s}s",
        "last_reply": "Last reply {ago}", "no_reply": "No replies yet",
        "model": "MODEL", "msgs_today": "{n} msgs today",
        "spent_today": "TODAY SPENT", "since": " · since {t}",
        "balance": "BALANCE", "min_ago": " · {n} min ago", "just_now": " · just now",
        "credit": "Credit ¥{v}", "credit_na": "Credit —", "recent": "RECENT", "no_records": "No messages",
        "last7": "Last 7 days", "today_n": "Today {n}", "mem": "Mem {n}", "skills": "Skills {n}",
        "today": "Today", "date_wd": ", {wd}", "cron": "Cron", "none": "None",
        "role_user": "Me", "role_ai": "AI", "role_tool": "Tool",
        "paging": "↑↓ pages", "demo": "demo · ",
        "connected": "Online", "disconnected": "Offline",
        "ago_just": "just now", "ago_min": "{n} min ago", "ago_hour": "{n} h ago", "ago_day": "{n} d ago",
        "next_min": "in {n} min", "next_hour": "in {n} h", "next_day": "in {n} d",
        "week_short": ["M", "T", "W", "T", "F", "S", "S"],
        "week_full": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "week_sun": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "cron_workday": "Weekdays {t}", "cron_weekday": "{wd} {t}",
        "cron_monthly": "Monthly on {d}, {t}", "cron_daily": "Daily {t}",
        "cron_every_min": "every {n} min", "cron_every_hour": "every {n} h",
        "selftest_pass": "passed", "selftest_fail": "failed",
        "notice": "NOTICE", "low_balance": "! Low balance ¥{v}", "src_stale": "Source idle {n} min",
        "agent_working": "{label} · working", "agent_done": "{label} · done {ago}",
    },
}

def LANG():
    lg = (CFG.get("lang") or "zh").lower()
    return lg if lg in STRINGS else "zh"

def T(key, **kw):
    s = STRINGS[LANG()].get(key) or STRINGS["zh"].get(key, key)
    return s.format(**kw) if kw else s

def page_titles():
    return [T(k) for k in PAGE_KEYS]

def load_config():
    try:
        return json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception:
        return {}

def _json_sources(cfg):
    """把配置解析成 json 数据源列表；旧配置（source/stats_file）等价于只有一个源。"""
    out = []
    srcs = cfg.get("sources")
    if isinstance(srcs, list) and srcs:
        for s in srcs:
            if (s or {}).get("type") == "json" and s.get("path"):
                out.append({"type": "json",
                            "path": os.path.expanduser(s["path"]),
                            "label": s.get("label") or os.path.basename(s["path"])})
        return out
    if cfg.get("source") == "json":
        p = os.path.expanduser(cfg.get("stats_file", "~/zectrix-stats.json"))
        out.append({"type": "json", "path": p, "label": cfg.get("label") or "JSON"})
    return out

def assistant_label():
    """顶栏名字：配置优先；否则按主源决定。"""
    name = CFG.get("assistant_name")
    if name:
        return str(name)
    if PRIMARY == "hermes":
        return "HERMES"
    for s in (CFG.get("sources") or []):
        if (s or {}).get("path"):
            return str(s.get("label") or "AGENT")
    return "HERMES"

def effective_config():
    """没有 sources/source 时自动判断：有 Hermes 用 Hermes，否则用 ~/zectrix-stats.json。"""
    cfg = load_config()
    if not cfg.get("sources") and not cfg.get("source"):
        if os.path.exists(os.path.join(H, "state.db")):
            cfg = dict(cfg, sources=[{"type": "hermes"}])
        else:
            p = os.path.expanduser("~/zectrix-stats.json")
            if os.path.exists(p):
                cfg = dict(cfg, sources=[{"type": "json", "path": p, "label": "Agent"}])
    return cfg

def _primary_from_cfg(cfg):
    srcs = cfg.get("sources")
    if isinstance(srcs, list) and srcs:
        for s in srcs:
            if (s or {}).get("type") == "hermes":
                return "hermes"
            if (s or {}).get("type") == "json":
                return "json"
    return "json" if cfg.get("source") == "json" else "hermes"

def refresh_stats():
    """读取所有 json 数据源；主源由 sources 里的顺序决定（默认 Hermes）。"""
    global STATS, STATS_MTIME, CFG, SOURCES, PRIMARY
    cfg = effective_config()
    CFG = cfg
    srcs = _json_sources(cfg)
    for s in srcs:
        p = s["path"]
        try:
            m = os.path.getmtime(p)
            c = _DATA_CACHE.get(p)
            if not c or c["mtime"] != m:
                c = {"mtime": m, "data": json.load(open(p, encoding="utf-8"))}
                _DATA_CACHE[p] = c
            s["data"] = c["data"]
        except Exception:
            s["data"] = {}
    SOURCES = srcs
    PRIMARY = _primary_from_cfg(cfg)
    STATS = {} if PRIMARY == "hermes" else (srcs[0]["data"] if srcs else {})
    return cfg

def sget(key, default=None):
    """从外部统计数据取值（无则返回 default）"""
    return STATS.get(key, default)

DEMO = False   # True = 当前渲染的是示例数据
VERSION = "1.1.0"
_last_png = None   # 内容去重：没变化就不写文件，避免墨水屏频繁刷新

from PIL import Image, ImageDraw, ImageFont

# ---------------- 工具 ----------------
def font(sz, bold=True):
    # 实测：PingFang.ttc 在本机 Pillow 下 "cannot open resource"，必须用 Hiragino
    for p, idx in [("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
                   ("/System/Library/Fonts/STHeiti Light.ttc", 0),
                   # Linux（CI / 服务器）
                   ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
                   ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0),
                   ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=idx)
            except Exception:
                pass
    return ImageFont.load_default()

def db(path):
    return sqlite3.connect(path)

def multi_source_label():
    """配置了 2 个以上数据源时，返回主源名字；单源返回空串。"""
    srcs = CFG.get("sources") or []
    if len(srcs) < 2:
        return ""
    if PRIMARY == "hermes":
        return "Hermes"
    return str((srcs[0] or {}).get("label") or "Agent")

def source_age():
    """主源最后一次写入距今秒数。"""
    ts = []
    if PRIMARY == "hermes":
        p = os.path.join(H, "state.db")
        if os.path.exists(p):
            ts.append(os.path.getmtime(p))
    else:
        for s in SOURCES[:1]:
            try:
                ts.append(os.path.getmtime(s["path"]))
            except Exception:
                pass
    return (time.time() - max(ts)) if ts else None

def model_name():
    v = sget("model")
    if v: return v
    if PRIMARY != "hermes": return "—"
    try:
        cfg = open(os.path.join(H, "config.yaml"), encoding="utf-8").read()
        m = re.search(r"^model:\s*\n\s+provider:\s*(\S+)\s*\n\s+default:\s*(\S+)", cfg, re.M)
        return m.group(2) if m else "—"
    except Exception:
        return "—"

def count_facts():
    v = sget("memory_count")
    if v is not None: return v
    if PRIMARY != "hermes": return 0
    try:
        return db(os.path.join(H, "memory_store.db")).execute("select count(*) from facts").fetchone()[0]
    except Exception:
        return 0

def count_skills():
    v = sget("skill_count")
    if v is not None: return v
    if PRIMARY != "hermes": return 0
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
            return T("connected"), True
        return ago(ts), False
    except Exception:
        return T("disconnected"), False

def _noise(s):
    """网关/系统注入的消息不适合上屏（JSON 元数据、压缩提示等）。"""
    t = (s or "").lstrip()
    return (t.startswith("Gateway message origin")
            or t.startswith("[IMPORTANT:")
            or t.startswith("[CONTEXT COMPACTION")
            or t.startswith("[INTERNAL NOTIFICATION")
            or t.startswith("[OUT-OF-BAND")
            or t.startswith("[ASYNC DELEGATION")
            or t.startswith("[System:")
            or t.startswith("MEDIA:"))

def last_reply():
    """最后一条助手回复（不是用户消息）"""
    v = sget("last_reply")
    if v: return v
    if PRIMARY != "hermes": return None
    try:
        rows = db(os.path.join(H, "state.db")).execute(
            """select role, content, timestamp from messages
               where role='assistant' and content is not null and length(trim(content))>0
               order by timestamp desc limit 8""").fetchall()
        for row in rows:
            if not _noise(row[1]):
                return {"role": row[0], "content": row[1] or "", "ts": float(row[2] or 0)}
        return None
    except Exception:
        return None

def recent_msgs(n=3):
    v = sget("recent")
    if v: return list(v)[:n]
    if PRIMARY != "hermes": return []
    try:
        rows = db(os.path.join(H, "state.db")).execute(
            """select role, content, timestamp from messages
               where role in ('user','assistant')
                 and content is not null and length(trim(content)) > 12
               order by timestamp desc limit ?""", (n * 4,)).fetchall()
        out = []
        for r in rows:
            if _noise(r[1]):
                continue
            out.append({"role": r[0], "content": r[1], "ts": float(r[2] or 0)})
            if len(out) >= n:
                break
        return out
    except Exception:
        return []

def today_msg_count():
    v = sget("messages_today")
    if v is not None: return v
    if PRIMARY != "hermes": return 0
    try:
        start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return db(os.path.join(H, "state.db")).execute(
            "select count(*) from messages where timestamp >= ?", (start,)).fetchone()[0]
    except Exception:
        return 0

WEEK_CN = ["日", "一", "二", "三", "四", "五", "六"]

def cron_text(expr):
    """把常见 cron 写成中文；不认识的规则原样返回。"""
    parts = (expr or "").split()
    if len(parts) != 5:
        return expr or ""
    mi, hh, dom, mon, dow = parts
    if not (mi.isdigit() and hh.isdigit()):
        if mi.startswith("*/") and hh == "*":
            return T("cron_every_min", n=mi[2:])
        if mi.isdigit() and hh.startswith("*/"):
            return T("cron_every_hour", n=hh[2:])
        return expr
    t = f"{int(hh):02d}:{int(mi):02d}"
    if dow == "1-5" and dom == "*" and mon == "*":
        return T("cron_workday", t=t)
    if dow.isdigit() and dom == "*" and mon == "*":
        return T("cron_weekday", wd=T("week_sun")[int(dow) % 7], t=t)
    if dom.isdigit() and dow == "*" and mon == "*":
        return T("cron_monthly", d=int(dom), t=t)
    if dom == "*" and dow == "*" and mon == "*":
        return T("cron_daily", t=t)
    return expr

def cron_jobs():
    v = sget("cron")
    if v is not None: return v
    if PRIMARY != "hermes": return []
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
    if PRIMARY != "hermes": return "—", "—", None
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
        return T("ago_just")
    if mins < 60:
        return T("ago_min", n=mins)
    if mins < 1440:
        return T("ago_hour", n=mins // 60)
    return T("ago_day", n=mins // 1440)

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
        return T("next_min", n=mins)
    if mins < 1440:
        return T("next_hour", n=mins // 60)
    return T("next_day", n=mins // 1440)

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
    if PRIMARY != "hermes" and (CFG.get("spend_mode") or "own") != "account":
        return None, None
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
    if PRIMARY != "hermes":
        return [0] * 7          # json 主源没提供 week 时不要拿 Hermes 的数据冒充
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
    if PRIMARY != "hermes": return False, 0.0
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
NOTIFY_PATH = os.path.join(BASE, "notify.json")
ALERT_STATE = os.path.join(BASE, ".alert_state")
BEEP_REQ = os.path.join(BASE, "beep.req")

def other_agents():
    """非主源的 agent：返回 [{"label", "active", "ts"}]，只保留正在跑或 10 分钟内完成的。"""
    out = []
    for s in SOURCES[0 if PRIMARY == "hermes" else 1:]:
        d = s.get("data") or {}
        lr = d.get("last_reply") or {}
        ts = float(lr.get("ts") or 0)
        active = bool(d.get("active"))
        if active or (ts and time.time() - ts < 600):
            out.append({"label": s.get("label") or "agent", "active": active, "ts": ts})
    return out

def notification():
    """外部（MCP / 任意脚本）推送的通知：{title, body, ts, ttl}，过期返回 None。"""
    try:
        d = json.load(open(NOTIFY_PATH, encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > float(d.get("ttl", 300)):
            return None
        return d
    except Exception:
        return None

def alert_text(bal):
    """余额低于阈值时返回提示文字，否则 None。"""
    try:
        thr = float(CFG.get("alert_low_balance", 10))
        b = float(bal)
    except Exception:
        return None
    return T("low_balance", v=f"{b:.2f}") if b < thr else None

def ping_beep(level):
    """告警出现时写一次 beep.req，由 watch 播放提示音（同一告警只响一次）。"""
    try:
        prev = open(ALERT_STATE).read().strip() if os.path.exists(ALERT_STATE) else ""
    except Exception:
        prev = ""
    cur = level or ""
    if cur and cur != prev:
        try:
            open(BEEP_REQ, "w").write(cur)
        except Exception:
            pass
    try:
        open(ALERT_STATE, "w").write(cur)
    except Exception:
        pass

def render(out, page=0):
    refresh_stats()
    page = page % len(PAGE_KEYS)
    img = Image.new("L", (W, HT), 255)
    d = ImageDraw.Draw(img)

    # 顶栏
    d.rectangle([0, 0, W, 34], fill=0)
    d.text((10, 7), assistant_label().upper(), font=font(18), fill=255)
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
    PT = page_titles()
    _ttl = f"{page + 1}/{len(PAGE_KEYS)}  {PT[page]}"
    _pl = multi_source_label()
    if _pl:
        _ttl += f" · {_pl}"
    d.text((10, 40), _ttl, font=font(14), fill=90)

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
        age = source_age()

        # 当前进度（最上面）：真实租约 → 处理中 + 本轮耗时
        d.text((16, 66), T("current"), font=font(11), fill=125)
        prog = T("working") if active else T("idle")
        d.text((16, 80), prog, font=font(28), fill=0)
        if active:
            secs = int(elapsed)
            sub = T("turn_min", m=secs // 60, s=secs % 60) if secs >= 60 else T("turn_sec", s=secs)
        else:
            sub = T("last_reply", ago=ago(m["ts"])) if m else T("no_reply")
        al = alert_text(bal)
        ping_beep(al)
        busy = next((o for o in other_agents() if o["active"]), None)
        if al:
            d.text((16, 118), al, font=font(12), fill=0)
        elif busy:
            d.text((16, 118), T("agent_working", label=busy["label"]), font=font(12), fill=0)
        elif age is not None and age > 900 and not active:
            d.text((16, 118), T("src_stale", n=int(age // 60)), font=font(12), fill=0)
        else:
            d.text((16, 120), sub, font=font(11, bold=False), fill=120)

        # 右侧：模型（小标题在上、名称放大，下方补今日消息数）
        mdl = model_name()
        f_lbl = font(11)
        size = 20
        f_mdl = font(size)
        while d.textlength(mdl, font=f_mdl) > 170 and size > 13:
            size -= 1
            f_mdl = font(size)
        while d.textlength(mdl, font=f_mdl) > 170 and len(mdl) > 4:
            mdl = mdl[:-2] + "…"
        mx = W - 16 - d.textlength(mdl, font=f_mdl)
        d.text((mx, 64), T("model"), font=f_lbl, fill=125)
        d.text((mx, 82), mdl, font=f_mdl, fill=0)
        sub = T("msgs_today", n=today_msg_count())
        sx = min(mx, W - 16 - d.textlength(sub, font=font(11)))
        d.text((sx, 112), sub, font=font(11), fill=125)

        d.line([16, 138, W - 16, 138], fill=210)

        # 花费 / 余额
        slab = T("spent_today")
        if since:
            midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            if since - midnight > 600:
                slab += T("since", t=datetime.datetime.fromtimestamp(since).strftime("%H:%M"))
        d.text((16, 146), slab, font=font(11, bold=False), fill=125)
        d.text((16, 162), (f"¥{cny:,.2f}" if cny is not None else "—"), font=font(29), fill=0)

        bx = 200
        blabel = T("balance")
        if bage is not None and bage >= 60:
            blabel += T("min_ago", n=int(bage // 60))
        elif bage is not None:
            blabel += T("just_now")
        d.text((bx, 146), blabel, font=font(11, bold=False), fill=125)

        # 金额位数多时自动降字号，保证「金额 + 赠金」不重叠
        gtxt = T("credit_na") if str(granted).strip() in ("", "—", "None") else T("credit", v=granted)
        f_gift = font(10)
        w_gift = d.textlength(gtxt, font=f_gift)
        num = "—" if str(bal).strip() in ("", "—", "None") else f"¥{bal}"
        size = 29
        for cand in (29, 26, 24, 22, 20):
            if bx + d.textlength(num, font=font(cand)) + 10 + w_gift <= W - 16:
                size = cand
                break
        f_num = font(size)
        d.text((bx, 162), num, font=f_num, fill=0)
        nb = d.textbbox((0, 0), num, font=f_num)
        gb = d.textbbox((0, 0), gtxt, font=f_gift)
        gy = 162 + nb[3] - gb[3]
        d.text((W - 16 - w_gift, gy), gtxt, font=f_gift, fill=125)

        d.line([16, 204, W - 16, 204], fill=210)

        # 最近消息（最多两行）；有外部通知时优先显示通知
        nt = notification()
        _rf = font(11, bold=False) if (LANG() == "en" or nt) else font(10, bold=False)
        d.text((16, 208 if (LANG() == "en" or nt) else 210),
               T("notice") if nt else T("recent"), font=_rf, fill=125)
        if nt:
            d.text((16, 224), clean_text(nt.get("title") or "", 40), font=font(14), fill=0)
            lines = wrap_lines(d, clean_text(nt.get("body") or "", 64), 14, W - 32, 1)
            d.text((16, 242), lines[0], font=font(14), fill=60)
        elif m:
            body = clean_text(m["content"], 64)
            # 前缀与正文一起折行：否则首行按全宽折行，加上「N 分钟前 · 」后
            # 末尾会超出 400px 被裁掉，而下一行从被裁掉的字之后开始，那些字永远看不到。
            prefix = f"{ago(m['ts'])} · "
            lines = wrap_lines(d, prefix + body, 14, W - 32, 2)
            d.text((16, 224), lines[0], font=font(14), fill=0)
            if len(lines) > 1:
                d.text((16, 242), lines[1], font=font(14), fill=0)
        else:
            d.text((16, 224), T("no_records"), font=font(14), fill=110)

    elif page == 1:
        # 统计：近 7 日消息
        d.text((16, 68), T("last7"), font=font(14), fill=110)
        _others = SOURCES[0 if PRIMARY == "hermes" else 1:]
        if _others:
            parts = []
            for s in _others[:2]:
                sd = s.get("data") or {}
                n = sd.get("messages_today")
                lab = str(s.get("label") or "agent")
                short = lab.split()[0] if " " in lab else lab   # "Claude Code" → "Claude"
                parts.append(short + (f" {n}" if n is not None else ""))
            txt = " · ".join(parts)
            f_ag = font(11, bold=False)
            while d.textlength(txt, font=f_ag) > 190 and len(txt) > 6:
                txt = txt[:-2] + "…"
            d.text((W - 16 - d.textlength(txt, font=f_ag), 69), txt, font=f_ag, fill=90)
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
        for i, wd in enumerate(T("week_short")):
            d.text((RX + i * (bw + gap) + bw / 2 - 5, base_y + 6), wd, font=font(11, bold=False), fill=120)

        d.line([10, 234, W - 10, 234], fill=200)
        d.text((16, 241), T("today_n", n=today_msg_count()), font=font(14), fill=0)
        d.text((150, 241), T("mem", n=count_facts()), font=font(14), fill=0)
        d.text((276, 241), T("skills", n=count_skills()), font=font(14), fill=0)

    elif page == 2:
        today = datetime.datetime.now()
        wd = T("week_full")[today.weekday()]
        line(T("today"), today.strftime("%Y-%m-%d") + T("date_wd", wd=wd), big=True)
        jobs = cron_jobs()
        if not jobs:
            line(T("cron"), T("none"))
        for j in jobs[:3]:
            line(j["name"][:16], f"{fmt_next(j['next'])} · {cron_text(j['schedule'])}")

    else:
        # 日志页：每条会话两行正文（14px），3 条共约 168px
        yy = 66
        for m in recent_msgs(3):
            role = {"user": T("role_user"), "assistant": T("role_ai"), "tool": T("role_tool")}.get(m["role"], m["role"])
            d.text((12, yy), f"{role} · {ago(m['ts'])}", font=font(11, bold=False), fill=110)
            body = clean_text(m["content"], 90)
            lines = wrap_lines(d, body, 14, W - 24, 2)
            ly = yy + 14
            for ln in lines:
                d.text((12, ly), ln, font=font(14), fill=0)
                ly += 18
            yy = ly + 6

    # 底栏
    d.line([10, HT - 30, W - 10, HT - 30], fill=160)
    for i in range(len(PAGE_KEYS)):
        cx = 16 + i * 14
        d.ellipse([cx, HT - 22, cx + 7, HT - 15], fill=0 if i == page else 200)
    hint = f"v{VERSION} · " + (T("demo") if DEMO else "") + T("paging")
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
        cut = s[:limit]
        if cut and cut[-1].isalnum():
            j = cut.rfind(" ")
            if j > limit * 0.6:          # 回退不要超过 40%
                cut = cut[:j]
        s = cut.rstrip() + "…"
    return s

def wrap_lines(d, text, size, max_w, max_lines=2):
    """按像素宽度折行，最多 max_lines 行，超出用省略号。
    中文按字断行；西文优先按词断行，避免把单词从中间劈开。"""
    f = font(size)

    def tw(s):
        return d.textlength(s, font=f)

    def ell(s):
        """收尾加省略号时保证仍不超宽（省略号本身也占宽度）"""
        while s and tw(s + "…") > max_w:
            s = s[:-1]
        return (s + "…") if s else "…"

    def _tokens(t):
        """CJK 逐字成词（可任意断行）；西文按词；空白折叠成一个。"""
        out, buf = [], ""
        for ch in t or "":
            o = ord(ch)
            cjk = (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                   or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF)
            if ch.isspace():
                if buf:
                    out.append(buf); buf = ""
                if not out or out[-1] != " ":
                    out.append(" ")
            elif cjk:
                if buf:
                    out.append(buf); buf = ""
                out.append(ch)
            else:
                buf += ch
        if buf:
            out.append(buf)
        return out

    tokens = _tokens(text)
    lines, cur, truncated = [], "", False

    for i, tok in enumerate(tokens):
        if tw(cur + tok) <= max_w:
            cur += tok
            continue
        if tok.isspace():
            if cur.strip():
                lines.append(cur.rstrip())
                cur = ""
                if len(lines) >= max_lines and i < len(tokens) - 1:
                    truncated = True
                    break
            continue
        if cur.strip():
            lines.append(cur.rstrip())
            cur = ""
            if len(lines) >= max_lines:
                truncated = True
                break
        # 单个词比整行还宽 → 退化为按字符切
        rest = tok
        while rest:
            piece = ""
            for ch in rest:
                if tw(piece + ch) <= max_w:
                    piece += ch
                else:
                    break
            if not piece:                 # 极端窄，兜底一个字符
                piece, rest = rest[:1], rest[1:]
            else:
                rest = rest[len(piece):]
            if rest:
                lines.append(piece)
                if len(lines) >= max_lines:
                    truncated = True
                    break
            else:
                cur = piece
        if truncated:
            break

    if cur.strip():
        if len(lines) < max_lines:
            lines.append(cur.rstrip())
        else:
            truncated = True

    lines = lines[:max_lines]
    if truncated and lines:
        lines[-1] = ell(lines[-1])
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
    link_status = lambda: (T("connected"), True)
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
                return int(open(path).read().strip()) % len(PAGE_KEYS)
            return int(json.load(open(path)).get("page", 0)) % len(PAGE_KEYS)
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
        # 没有 Hermes 也没有配置任何 json 源时才用示例数据
        if not _json_sources(effective_config()):
            enable_demo()

    if a.selftest:
        import tempfile
        ok = True
        for i in range(len(PAGE_KEYS)):
            out = os.path.join(tempfile.gettempdir(), f"zectrix_selftest_{i}.png")
            render(out, i)
            with Image.open(out) as im:
                good = im.size == (W, HT)
            ok = ok and good and os.path.getsize(out) > 1000
            print(f"  page {i+1} {page_titles()[i]}: {'OK' if good else 'FAIL'} ({os.path.getsize(out)} B)")
        print("selftest", T("selftest_pass") if ok else T("selftest_fail"))
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
                    open(os.path.join(BASE, "pages.txt"), "w").write(str(len(PAGE_KEYS)))
                except Exception:
                    pass
                render(a.out, read_page() if a.page is None else a.page)
            except Exception as e:
                print("render error:", e, flush=True)
            time.sleep(delay)
    else:
        p = read_page() if a.page is None else a.page
        print(render(a.out, p), os.path.getsize(a.out), "B")
