#!/bin/bash
# 完全卸载：停止服务并移除 LaunchAgent（不删安装目录）
set -u
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"
LA="$HOME/Library/LaunchAgents"

echo "卸载状态屏服务…"
for L in $LABELS; do
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null && echo "  ✅ 已停止 $L" || true
  [ -f "$LA/$L.plist" ] && rm -f "$LA/$L.plist" && echo "  ✅ 已删除 $L.plist"
done
pkill -f "agent_status.py --daemon" 2>/dev/null || true
pkill -f "examples/watch" 2>/dev/null || true
pkill -f "zectrix-watch" 2>/dev/null || true
echo
echo "完成。安装目录仍保留（默认 ~/zectrix-agent-status），可手动删除。"
