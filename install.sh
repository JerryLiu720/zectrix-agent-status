#!/bin/bash
# HERMES 状态屏一键安装
# 用法: ./install.sh <设备IP> [页面刷新间隔秒数]
set -euo pipefail

IP="${1:-}"
INTERVAL="${2:-3}"
MODE="login"          # login=开机自启；manual=手动开关（回家才打开）

for a in "$@"; do
  case "$a" in
    --mode=login|login)     MODE="login" ;;
    --mode=manual|manual)   MODE="manual" ;;
    --mode=*)               echo "未知模式：$a（可选 login / manual）"; exit 1 ;;
  esac
done
[ -z "$IP" ] && { echo "用法: ./install.sh <设备IP> [间隔秒]"; echo "提示: 设备 IP 可在设备「设置 → 网络」中查看"; exit 1; }

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/zectrix-agent-status"
SDK_DIR="$INSTALL_DIR/zectrix-local-push-sdk"
LA="$HOME/Library/LaunchAgents"
UID_N="$(id -u)"

echo "==> [0/6] 预检设备连通性"
if ping -c 1 -W 1500 "$IP" >/dev/null 2>&1; then
  echo "    $IP 可达"
else
  echo "    ⚠️  无法 ping 通 $IP —— 常见原因："
  echo "       1) 设备与电脑不在同一 Wi-Fi"
  echo "       2) 设备未开启「设置 → 网络同步 → 待机保持 Wi-Fi」"
  echo "       3) IP 已变化（DHCP）"
  echo "    仍继续安装，装完可用 ./restart.sh 重试连接。"
fi

echo "==> [1/6] 检查依赖"
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "缺少 python3"; exit 1; }
"$PY" - <<'EOF'
import sys
try:
    import PIL  # noqa
except ImportError:
    sys.exit("缺少 Pillow：请先执行 python3 -m pip install pillow -i https://pypi.tuna.tsinghua.edu.cn/simple")
EOF

if ! command -v cmake >/dev/null 2>&1; then
  echo "    未找到 cmake，用 pip 安装（不走 brew，避免 auto-update 连 GitHub 卡住）"
  "$PY" -m pip install -q cmake -i https://pypi.tuna.tsinghua.edu.cn/simple || true
fi
CMAKE_BIN="$("$PY" -c 'import cmake,os;print(os.path.join(os.path.dirname(cmake.__file__),"data","bin"))' 2>/dev/null || true)"
export PATH="${CMAKE_BIN:-}:$PATH"
export CMAKE_POLICY_VERSION_MINIMUM=3.5

# 已装 Rust 但 PATH 里没有（登录 shell 未加载配置）时直接复用
if [ -x "$HOME/.cargo/bin/cargo" ]; then
  export PATH="$HOME/.cargo/bin:$PATH"
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "    未找到 Rust，使用国内镜像安装"
  curl --proto '=https' --tlsv1.2 -sSf https://rsproxy.cn/rustup-init.sh | sh -s -- -y --profile minimal
  export PATH="$HOME/.cargo/bin:$PATH"
fi
command -v cargo >/dev/null || { echo "Rust 安装失败"; exit 1; }

echo "==> [2/6] 准备工作目录 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/bin" "$LA"
cp -f "$APP_DIR/agent_status.py" "$INSTALL_DIR/agent_status.py"
install -m 755 "$APP_DIR/scripts/rotate_logs.sh" "$INSTALL_DIR/bin/rotate-logs.sh"
mkdir -p "$INSTALL_DIR/scripts"
cp -f "$APP_DIR"/scripts/*.sh "$INSTALL_DIR/scripts/" 2>/dev/null || true
chmod +x "$INSTALL_DIR"/scripts/*.sh 2>/dev/null || true
echo 0 > "$INSTALL_DIR/ui_state.txt"
echo "IP=$IP" > "$INSTALL_DIR/config.txt"

echo "==> [3/6] 获取 Zectrix SDK（github.com 不通时走 codeload）"
if [ ! -d "$SDK_DIR" ]; then
  TMPZ="$INSTALL_DIR/sdk.zip"
  OK=0
  for URL in \
    "https://codeload.github.com/itopinion/zectrix-local-push-sdk/zip/refs/heads/main" \
    "https://ghproxy.net/https://github.com/itopinion/zectrix-local-push-sdk/archive/refs/heads/main.zip"; do
    if curl -sSL --max-time 120 -o "$TMPZ" "$URL" && [ "$(stat -f%z "$TMPZ" 2>/dev/null || echo 0)" -gt 10000 ]; then OK=1; break; fi
  done
  [ "$OK" = 1 ] || { echo "SDK 下载失败，请手动下载后解压到 $SDK_DIR"; exit 1; }
  unzip -q "$TMPZ" -d "$INSTALL_DIR"
  mv "$INSTALL_DIR/zectrix-local-push-sdk-main" "$SDK_DIR"
  rm -f "$TMPZ"
fi

echo "==> [4/6] 编译 watch（首次需编译 Opus，约 1-2 分钟）"
cp -f "$APP_DIR/examples/watch.rs" "$SDK_DIR/examples/watch.rs"
# 国内网络直接从 crates.io 拉依赖会极慢甚至卡住，临时切到 rsproxy 镜像（不改用户全局配置）
CARGO_MIRROR_ARGS=()
if [ "${ZECTRIX_NO_MIRROR:-0}" != "1" ] && curl -s --max-time 5 -o /dev/null -w '%{http_code}' https://rsproxy.cn/index/config.json | grep -q 200; then
  echo "    使用 rsproxy.cn 镜像拉取 crates"
  CARGO_MIRROR_ARGS=(--config 'source.crates-io.replace-with="rsproxy-sparse"' \
                     --config 'source.rsproxy-sparse.registry="sparse+https://rsproxy.cn/index/"' \
                     --config 'net.git-fetch-with-cli=true')
fi
( cd "$SDK_DIR" && cargo build --release --locked --example watch "${CARGO_MIRROR_ARGS[@]}" )
mkdir -p "$INSTALL_DIR/bin"
install -m 755 "$SDK_DIR/target/release/examples/watch" "$INSTALL_DIR/bin/zectrix-watch"
WATCH_BIN="$INSTALL_DIR/bin/zectrix-watch"

echo "==> 自检（渲染四页并校验尺寸）"
"$PY" "$INSTALL_DIR/agent_status.py" --selftest || { echo "自检失败，已中止"; exit 1; }

echo "==> [5/6] 生成 LaunchAgents（开机自启）"
cat > "$LA/com.zectrix.agentstatus.daemon.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.zectrix.agentstatus.daemon</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$INSTALL_DIR/agent_status.py</string>
    <string>--daemon</string><string>--interval</string><string>$INTERVAL</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$INSTALL_DIR/logs/daemon.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/logs/daemon.err.log</string>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
</dict></plist>
PLIST

cat > "$LA/com.zectrix.agentstatus.watch.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.zectrix.agentstatus.watch</string>
  <key>ProgramArguments</key><array>
    <string>$WATCH_BIN</string><string>$IP</string><string>$INSTALL_DIR/status.png</string><string>gray16</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$INSTALL_DIR/logs/watch.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/logs/watch.err.log</string>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
</dict></plist>
PLIST

cat > "$LA/com.zectrix.agentstatus.logrotate.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.zectrix.agentstatus.logrotate</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$INSTALL_DIR/bin/rotate-logs.sh</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$INSTALL_DIR/logs/rotate.out.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/logs/rotate.err.log</string>
</dict></plist>
PLIST

echo "==> [6/6] 启动服务（模式：$MODE）"
if [ "$MODE" = "manual" ]; then
  # 手动模式：把 plist 移到 disabled/，不注册开机自启；用 nohup 起当前进程
  mkdir -p "$LA/disabled"
  for L in com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate; do
    [ -f "$LA/$L.plist" ] && mv -f "$LA/$L.plist" "$LA/disabled/"
  done
  nohup "$PY" "$INSTALL_DIR/agent_status.py" --daemon --interval "$INTERVAL" \
      >> "$INSTALL_DIR/logs/status-daemon.log" 2>&1 &
  sleep 1
  nohup "$WATCH_BIN" "$IP" "$INSTALL_DIR/status.png" gray16 \
      >> "$INSTALL_DIR/logs/watch.log" 2>&1 &
  echo "    手动模式：已启动，本次登录不再自动启动"
  echo "    开启：$INSTALL_DIR/scripts/start.sh    关闭：$INSTALL_DIR/scripts/stop.sh"
else
  for L in com.zectrix.agentstatus.daemon com.zectrix.agentstatus.watch com.zectrix.agentstatus.logrotate; do
    launchctl bootout "gui/$UID_N/$L" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$LA/$L.plist"
  done
  echo "    开机自启模式：已注册 LaunchAgent"
fi

sleep 4
echo
echo "✅ 完成。屏幕应显示第 1 页（概览）。"
echo "   日志: $INSTALL_DIR/logs/watch.log"
echo "   卸载: launchctl bootout gui/$UID_N/com.zectrix.agentstatus.watch && launchctl bootout gui/$UID_N/com.zectrix.agentstatus.daemon"
echo
echo "如提示 NoDevice：确认设备与电脑同一 Wi-Fi，且开启「待机保持 Wi-Fi」。"
