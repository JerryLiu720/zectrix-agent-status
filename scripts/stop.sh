#!/bin/bash
# 停止状态屏，并禁止下次登录自动启动
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"
LA="$HOME/Library/LaunchAgents"
DIS="$LA/disabled"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$DIS"

echo "停止状态屏…"
for L in $LABELS; do
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null && echo "  ✅ 已停止 $L" || echo "  - $L 未在运行"
  [ -f "$LA/$L.plist" ] && mv -f "$LA/$L.plist" "$DIS/" && echo "  ✅ 已禁用开机自启 $L"
done
pkill -f "agent_status.py --daemon" 2>/dev/null && echo "  ✅ 已结束渲染进程"
pkill -f "examples/watch" 2>/dev/null || true
pkill -f "zectrix-watch" 2>/dev/null || true
echo
echo "完成：设备几秒后回到主页，下次登录也不会自动启动。"
echo "想恢复：$DIR/scripts/start.sh"
