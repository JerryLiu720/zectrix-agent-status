#!/bin/bash
# 重启渲染 daemon 与推送进程（改完 agent_status.py 后执行）
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
UID_N="$(id -u)"
pkill -f "agent_status.py --daemon" 2>/dev/null || true
pkill -f "examples/watch" 2>/dev/null || true
sleep 2
if launchctl print "gui/$UID_N/com.zectrix.agentstatus.daemon" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$UID_N/com.zectrix.agentstatus.daemon"
  launchctl kickstart -k "gui/$UID_N/com.zectrix.agentstatus.watch"
  echo "已通过 LaunchAgent 重启"
else
  echo "未安装 LaunchAgent，请手动启动："
  echo "  python3 $DIR/agent_status.py --daemon --interval 1 &"
  echo "  ~/zectrix-sdk/zectrix-local-push-sdk-main/target/debug/examples/watch <IP> $DIR/status.png gray16"
fi
