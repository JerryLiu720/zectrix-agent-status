#!/usr/bin/env python3
"""zectrix — 状态屏的统一命令。

  zectrix status            当前配置 / 设备 / 服务状态
  zectrix setup             交互式配置（助手、语言、余额阈值）
  zectrix connect <agent>   claude-code | hermes | codex
  zectrix discover          重新发现设备 IP
  zectrix pause / resume    暂停 / 恢复推送
  zectrix restart           重启渲染与推送
"""
import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(BASE, "config.json")
CONFIG_TXT = os.path.join(BASE, "config.txt")
STATS = os.path.expanduser("~/zectrix-stats.json")
UID = str(os.getuid())
AGENTS = {
    "com.zectrix.agentstatus.daemon": "daemon",
    "com.zectrix.agentstatus.watch": "watch",
}


def load_cfg():
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG)


def device_ip():
    try:
        for line in open(CONFIG_TXT, encoding="utf-8"):
            if line.startswith("IP="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def running(label):
    r = subprocess.run(["launchctl", "print", f"gui/{UID}/com.zectrix.agentstatus.{label}"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True
    pat = "zectrix-watch" if label == "watch" else "agent_status.py --daemon"
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0


def kick(label):
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{UID}/com.zectrix.agentstatus.{label}"],
                   capture_output=True)


def cmd_status(_a):
    cfg = load_cfg()
    srcs = cfg.get("sources")
    if srcs:
        desc = " → ".join(f"{s.get('type')}:{s.get('label') or s.get('path') or ''}".rstrip(":")
                          for s in srcs)
    elif cfg.get("source"):
        desc = cfg["source"] + (":" + cfg.get("stats_file", "") if cfg.get("stats_file") else "")
    else:
        has_h = os.path.exists(os.path.expanduser("~/.hermes/state.db"))
        desc = "自动：" + ("Hermes" if has_h else ("Claude Code（~/zectrix-stats.json）" if os.path.exists(STATS) else "示例数据"))

    print(f"配置      {CONFIG if os.path.exists(CONFIG) else '（未创建，自动检测）'}")
    print(f"数据源    {desc}")
    print(f"语言      {cfg.get('lang', 'zh')}")
    print(f"设备 IP   {device_ip() or '未发现（运行 zectrix discover）'}")
    print(f"渲染进程  {'运行中' if running('daemon') else '未运行'}")
    print(f"推送进程  {'运行中' if running('watch') else '未运行'}")
    try:
        lines = open(os.path.join(BASE, "logs", "watch.log"), encoding="utf-8").read().strip().splitlines()
        if lines:
            print(f"最近推送  {lines[-1]}")
    except Exception:
        pass


def cmd_discover(_a):
    script = os.path.join(BASE, "scripts", "resolve_ip.py")
    r = subprocess.run([sys.executable, script, "--config", CONFIG_TXT,
                        "--bin", os.path.join(BASE, "bin", "zectrix-status")],
                       capture_output=True, text=True)
    ip = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
    if ip:
        print(f"找到设备: {ip}")
        return 0
    print("没找到设备。确认：同一 Wi-Fi、设备已开「待机保持 Wi-Fi」。")
    return 1


def _wire_json_source(cfg):
    srcs = cfg.get("sources") or []
    if not any((s or {}).get("type") == "json" and s.get("path") == STATS for s in srcs):
        srcs = [{"type": "json", "path": STATS, "label": "Claude Code"}] + \
               [s for s in srcs if (s or {}).get("type") != "hermes"]
    cfg["sources"] = srcs
    return cfg


def cmd_connect(agent):
    cfg = load_cfg()
    if agent == "claude-code":
        cfg = _wire_json_source(cfg)
        save_cfg(cfg)
        r = subprocess.run([sys.executable, os.path.join(BASE, "scripts", "install_claude_hooks.py")])
        if r.returncode != 0:
            print("hook 安装失败，可手动运行 scripts/install_claude_hooks.py")
            return r.returncode
        print(f"已接入 Claude Code，数据写到 {STATS}")
    elif agent == "hermes":
        cfg["sources"] = [{"type": "hermes"}]
        save_cfg(cfg)
        print("已切回 Hermes 数据源")
    elif agent == "codex":
        cfg = _wire_json_source(cfg)
        save_cfg(cfg)
        notify = os.path.join(BASE, "scripts", "codex_notify.py")
        codex_cfg = os.path.expanduser("~/.codex/config.toml")
        os.makedirs(os.path.dirname(codex_cfg), exist_ok=True)
        line = f'notify = ["{sys.executable}", "{notify}"]'
        try:
            txt = open(codex_cfg, encoding="utf-8").read()
        except FileNotFoundError:
            txt = ""
        if "notify" in txt:
            print("~/.codex/config.toml 里已有 notify，请把这一行换成：")
            print("  " + line)
        else:
            with open(codex_cfg, "a", encoding="utf-8") as f:
                if txt and not txt.endswith("\n"):
                    f.write("\n")
                f.write(line + "\n")
            print(f"已写入 {codex_cfg}：{line}")
    else:
        print("支持的 agent：claude-code / hermes / codex")
        return 1
    kick("daemon")
    print("已重启渲染进程")
    return 0


def cmd_setup(args):
    cfg = load_cfg()
    agent = args.agent
    if not agent:
        print("用哪个助手？")
        print("  1) Hermes        （读 ~/.hermes 数据）")
        print("  2) Claude Code   （读 ~/zectrix-stats.json）")
        print("  3) Codex         （读 ~/zectrix-stats.json）")
        print("  4) 其他          （只写 stats.json）")
        agent = {"1": "hermes", "2": "claude-code", "3": "codex", "4": "other"}.get(
            input("选择 [1]: ").strip() or "1", "hermes")
    lang = args.lang
    if not lang:
        lang = {"1": "zh", "2": "en"}.get(input("界面语言 1) 中文  2) English  [1]: ").strip() or "1", "zh")
    threshold = args.threshold
    if threshold is None:
        raw = input("余额低于多少提醒（元）？[10]: ").strip()
        threshold = float(raw) if raw else 10.0

    cfg["lang"] = lang
    cfg["alert_low_balance"] = threshold
    if agent == "hermes":
        cfg["sources"] = [{"type": "hermes"}]
    elif agent in ("claude-code", "codex", "other"):
        cfg = _wire_json_source(cfg)
    save_cfg(cfg)
    print(f"已写入 {CONFIG}")

    if agent in ("claude-code", "codex"):
        rc = cmd_connect(agent)
        return rc
    kick("daemon")
    print("已重启渲染进程")
    return 0


def cmd_pause(_a):
    subprocess.run(["launchctl", "bootout", f"gui/{UID}/com.zectrix.agentstatus.watch"],
                   capture_output=True)
    print("已暂停推送（渲染仍在后台）")
    return 0


def cmd_resume(_a):
    plist = os.path.expanduser("~/Library/LaunchAgents/com.zectrix.agentstatus.watch.plist")
    subprocess.run(["launchctl", "bootstrap", f"gui/{UID}", plist], capture_output=True)
    print("已恢复推送")
    return 0


def cmd_restart(_a):
    kick("daemon")
    kick("watch")
    print("已重启渲染与推送")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="zectrix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("discover").set_defaults(fn=cmd_discover)
    sub.add_parser("pause").set_defaults(fn=cmd_pause)
    sub.add_parser("resume").set_defaults(fn=cmd_resume)
    sub.add_parser("restart").set_defaults(fn=cmd_restart)
    p = sub.add_parser("connect")
    p.add_argument("agent", choices=["claude-code", "hermes", "codex"])
    p.set_defaults(fn=lambda a: cmd_connect(a.agent))
    p2 = sub.add_parser("setup")
    p2.add_argument("--agent", choices=["hermes", "claude-code", "codex", "other"])
    p2.add_argument("--lang", choices=["zh", "en"])
    p2.add_argument("--threshold", type=float)
    p2.set_defaults(fn=cmd_setup)
    a = ap.parse_args()
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
