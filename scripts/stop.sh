#!/bin/bash
# 关闭状态屏进程（同时断开设备）。自启开关请在「系统设置 → 通用 → 登录项」里管理。
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"

echo "关闭状态屏进程…"
for L in $LABELS; do
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null && echo "  ✅ 已停止 $L" || echo "  - $L 未在运行"
done
pkill -f "agent_status.py --daemon" 2>/dev/null && echo "  ✅ 已结束渲染进程"
pkill -f "examples/watch" 2>/dev/null || true
pkill -f "zectrix-watch" 2>/dev/null || true
sleep 1
echo
if pgrep -f "agent_status.py --daemon|zectrix-watch|examples/watch" >/dev/null; then
  echo "⚠️ 仍有残留进程"
else
  echo "完成：进程已全部退出，设备已回到主页。"
fi
