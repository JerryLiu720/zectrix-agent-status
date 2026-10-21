#!/bin/bash
# 手动启动状态屏（不恢复开机自启，符合"回家才打开"的用法）
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
IP="$(grep -E '^IP=' "$DIR/config.txt" 2>/dev/null | cut -d= -f2)"
WATCH=""
for c in "$DIR/bin/zectrix-watch" "$HOME/zectrix-sdk/bin/zectrix-watch" "$DIR/zectrix-local-push-sdk/target/release/examples/watch"; do
  [ -x "$c" ] && WATCH="$c" && break
done
mkdir -p "$DIR/logs"

if [ -z "$IP" ] || [ -z "$WATCH" ]; then
  echo "⚠️ 缺少 config.txt 或推送程序，请先运行 ./install.sh <设备IP>"
  exit 1
fi

echo "启动状态屏（手动模式，设备 $IP）…"
if ! pgrep -f "agent_status.py --daemon" >/dev/null; then
  nohup "$PY" "$DIR/agent_status.py" --daemon --interval 3 >> "$DIR/logs/status-daemon.log" 2>&1 &
  echo "  ✅ 渲染进程已启动"
else
  echo "  - 渲染进程已在运行"
fi
sleep 1
if ! pgrep -f "zectrix-watch|examples/watch" >/dev/null; then
  nohup "$WATCH" "$IP" "$DIR/status.png" gray16 >> "$DIR/logs/watch.log" 2>&1 &
  echo "  ✅ 推送进程已启动"
else
  echo "  - 推送进程已在运行"
fi
sleep 3
echo
echo "屏幕应在几秒内显示第 1 页。停止：$DIR/scripts/stop.sh"
