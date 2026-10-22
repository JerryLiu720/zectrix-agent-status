#!/bin/bash
# 打开状态屏：优先用 LaunchAgent（保留系统登录项里的自启设置），失败则手动拉起
UID_N="$(id -u)"
LA="$HOME/Library/LaunchAgents"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
IP="$(grep -E '^IP=' "$DIR/config.txt" 2>/dev/null | cut -d= -f2)"
WATCH=""
for c in "$DIR/bin/zectrix-watch" "$HOME/zectrix-sdk/bin/zectrix-watch"; do
  [ -x "$c" ] && WATCH="$c" && break
done
mkdir -p "$DIR/logs"
rm -f "$DIR/PAUSED"

echo "打开状态屏…"
ok=0
for L in com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate; do
  [ -f "$LA/$L.plist" ] || continue
  launchctl bootstrap "gui/$UID_N" "$LA/$L.plist" 2>/dev/null && ok=1
done
if [ "$ok" = 1 ]; then
  echo "  ✅ 已通过 LaunchAgent 启动"
else
  [ -z "$IP" ] && { echo "  ⚠️ 缺少 config.txt（设备 IP），请先运行 ./install.sh <设备IP>"; exit 1; }
  [ -z "$WATCH" ] && { echo "  ⚠️ 找不到推送程序，请先运行 ./install.sh <设备IP>"; exit 1; }
  pgrep -f "agent_status.py --daemon" >/dev/null || \
    nohup "$PY" "$DIR/agent_status.py" --daemon --interval 3 >> "$DIR/logs/status-daemon.log" 2>&1 &
  sleep 1
  pgrep -f "zectrix-watch|examples/watch" >/dev/null || \
    nohup "$WATCH" "$IP" "$DIR/status.png" gray16 >> "$DIR/logs/watch.log" 2>&1 &
  echo "  ✅ 已手动启动（设备 $IP）"
fi
sleep 3
echo "屏幕应在几秒内显示第 1 页。"
