#!/bin/bash
# 统一处理三个 LaunchAgent：daemon（渲染）、watch（推送）、logrotate（日志）
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"
LA="$HOME/Library/LaunchAgents"

echo "== 服务状态 =="
for L in $LABELS; do
  if launchctl print "gui/$UID_N/$L" >/dev/null 2>&1; then
    echo "  ✅ $L （已加载）"
  else
    echo "  ⭕ $L （未加载）"
  fi
done
echo
echo "== 进程 =="
pgrep -fl "agent_status.py --daemon|zectrix-watch|examples/watch" || echo "  （无）"
echo
echo "== 设备心跳 =="
HB="$(dirname "$0")/../conn.txt"
if [ -f "$HB" ]; then
  TS=$(cat "$HB"); NOW=$(date +%s); echo "  最近心跳 $((NOW-TS)) 秒前"
else
  echo "  无心跳文件（尚未连接过）"
fi
