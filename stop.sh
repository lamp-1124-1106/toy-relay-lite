#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# 停止 Toy Lite
# 用法: bash stop.sh  (在任意目录都可以)

SELF="$0"
case "$SELF" in
  /*) ;;
  *) SELF="$(pwd)/$SELF" ;;
esac
DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)"
[ -z "$DIR" ] && DIR="$(pwd)"

if [ -f "$DIR/toy_lite.pid" ]; then
    PID=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
    if [ -n "$PID" ]; then
        kill "$PID" 2>/dev/null && echo "⏹ 已停止 (PID $PID)" || echo "ℹ️ 进程已不在"
    fi
    rm -f "$DIR/toy_lite.pid"
else
    pkill -f "toy_lite.py" 2>/dev/null && echo "⏹ 已停止" || echo "ℹ️ 没有在跑的实例"
fi
