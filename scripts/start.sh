#!/bin/bash
# 统一处理三个 LaunchAgent：daemon（渲染）、watch（推送）、logrotate（日志）
UID_N="$(id -u)"
LABELS="com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate"
LA="$HOME/Library/LaunchAgents"

echo "启动状态屏服务…"
for L in $LABELS; do
  PL="$LA/$L.plist"
  if [ ! -f "$PL" ]; then echo "  ⚠️ 缺少 $PL（先运行 ./install.sh）"; continue; fi
  launchctl bootout "gui/$UID_N/$L" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$PL" && echo "  ✅ 已启动 $L" || echo "  ❌ 启动失败 $L"
done
echo "完成。屏幕应在几秒内显示第 1 页。"
