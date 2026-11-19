#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# 一键启动 Toy Lite (后台运行, 终端标签页可以随便关)
#
# 用法 (在任意目录都可以):
#   bash run.sh
#   bash /storage/emulated/0/Download/Toy-Relay-AI-mcp-SOSEXY-main/toy_lite/run.sh
#
# 脚本自己定位自己所在的目录, 所以放在哪都能跑。

# --- 定位目录 (脚本自己所在位置) ---
SELF="$0"
case "$SELF" in
  /*) ;;
  *) SELF="$(pwd)/$SELF" ;;
esac
DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)"
[ -z "$DIR" ] && DIR="$(pwd)"

# 如果脚本所在目录没有 toy_lite.py, 往上一级找
if [ ! -f "$DIR/toy_lite.py" ] && [ -f "$DIR/../toy_lite/toy_lite.py" ]; then
    DIR="$(cd "$DIR/../toy_lite" && pwd)"
fi

if [ ! -f "$DIR/toy_lite.py" ]; then
    echo "❌ 找不到 toy_lite.py (脚本目录: $DIR)"
    echo "   请在 toy_lite 目录里运行, 或把 run.sh 放到该目录"
    exit 1
fi

cd "$DIR" || { echo "❌ 无法进入目录: $DIR"; exit 1; }

# --- 选 python ---
PY=python
command -v python >/dev/null 2>&1 || PY=python3

# --- 已在跑就别重复启动 ---
if [ -f "$DIR/toy_lite.pid" ]; then
    PID=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "ℹ️  已经在跑了 (PID $PID)"
        echo "   控制页: http://127.0.0.1:8765/relay/"
        echo "   MCP   : http://127.0.0.1:8765/mcp/"
        exit 0
    fi
    rm -f "$DIR/toy_lite.pid"
fi

# --- 启动 (依次尝试 setsid / nohup / 裸后台) ---
if command -v setsid >/dev/null 2>&1; then
    setsid "$PY" toy_lite.py > "$DIR/toy_lite.log" 2>&1 &
elif command -v nohup >/dev/null 2>&1; then
    nohup "$PY" toy_lite.py > "$DIR/toy_lite.log" 2>&1 &
else
    "$PY" toy_lite.py > "$DIR/toy_lite.log" 2>&1 &
fi
echo $! > "$DIR/toy_lite.pid"

sleep 3
PID=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "✅ 已启动 (PID $PID)"
    echo "   控制页: http://127.0.0.1:8765/relay/"
    echo "   MCP   : http://127.0.0.1:8765/mcp/"
    echo "   日志  : $DIR/toy_lite.log"
    echo "   停止  : bash $DIR/stop.sh"
else
    echo "❌ 启动失败, 日志最后 20 行:"
    tail -n 20 "$DIR/toy_lite.log" 2>/dev/null
    exit 1
fi
