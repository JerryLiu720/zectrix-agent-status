#!/bin/bash
# 统一处理三个 LaunchAgent：daemon（渲染）、watch（推送）、logrotate（日志）
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"
LA="$HOME/Library/LaunchAgents"

echo "停止状态屏服务…"
for L in $LABELS; do
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null && echo "  ✅ 已停止 $L" || echo "  - $L 未在运行"
done
# 兜底：LaunchAgent 未加载时也杀掉残留进程
pkill -f "agent_status.py --daemon" 2>/dev/null && echo "  ✅ 已结束渲染进程" || true
pkill -f "examples/watch" 2>/dev/null || true
pkill -f "zectrix-watch" 2>/dev/null || true
echo "完成。设备会在几秒后回到主页。"
