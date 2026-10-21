#!/bin/bash
# 启动状态屏，并恢复开机自启（launchd 不可用时退化为手动启动）
UID_N="$(id -u)"
LA="$HOME/Library/LaunchAgents"
DIS="$LA/disabled"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
IP="$(grep -E '^IP=' "$DIR/config.txt" 2>/dev/null | cut -d= -f2)"
WATCH=""
for c in "$DIR/bin/zectrix-watch" "$HOME/zectrix-sdk/bin/zectrix-watch" "$DIR/zectrix-local-push-sdk/target/release/examples/watch"; do
  [ -x "$c" ] && WATCH="$c" && break
done
mkdir -p "$DIR/logs"

echo "启动状态屏…"
ok=0
if [ -d "$DIS" ] && ls "$DIS"/*.plist >/dev/null 2>&1; then
  mkdir -p "$LA"; mv -f "$DIS"/*.plist "$LA"/ 2>/dev/null
  for L in com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate; do
    [ -f "$LA/$L.plist" ] || continue
    launchctl bootout "gui/$UID_N/$L" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$LA/$L.plist" 2>/dev/null && ok=1
  done
  [ "$ok" = 1 ] && echo "  ✅ 已启动，并恢复开机自启"
fi

if [ "$ok" = 0 ]; then
  [ -z "$IP" ] && { echo "  ⚠️ 缺少 config.txt（设备 IP），请先运行 ./install.sh <设备IP>"; exit 1; }
  [ -z "$WATCH" ] && { echo "  ⚠️ 找不到推送程序，请先运行 ./install.sh <设备IP>"; exit 1; }
  pgrep -f "agent_status.py --daemon" >/dev/null || \
    nohup "$PY" "$DIR/agent_status.py" --daemon --interval 3 >> "$DIR/logs/status-daemon.log" 2>&1 &
  sleep 1
  pgrep -f "zectrix-watch|examples/watch" >/dev/null || \
    nohup "$WATCH" "$IP" "$DIR/status.png" gray16 >> "$DIR/logs/watch.log" 2>&1 &
  echo "  ✅ 已启动（手动模式，设备 $IP）"
fi
sleep 3
echo "屏幕应在几秒内显示第 1 页。"
