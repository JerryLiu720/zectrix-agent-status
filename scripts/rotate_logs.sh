#!/bin/bash
# 日志轮转：单个日志超过 1MB 就只保留最后 2000 行（避免长期运行撑爆磁盘）
set -eu
DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)/logs}"
MAX=$((1024 * 1024))
mkdir -p "$DIR"
for f in "$DIR"/*.log; do
  [ -e "$f" ] || continue
  size=$(stat -f%z "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt "$MAX" ]; then
    tail -n 2000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "$(date '+%F %T') rotated $(basename "$f") $size -> $(stat -f%z "$f")" >> "$DIR/rotate.log"
  fi
done
