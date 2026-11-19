#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# 一键启动 Toy Lite (后台运行, 终端标签页可以随便关)
# 用法: bash /storage/emulated/0/Download/Toy-Relay-AI-mcp-SOSEXY-main/run.sh

DIR=/storage/emulated/0/Download/Toy-Relay-AI-mcp-SOSEXY-main/toy_lite
PY=python

cd "$DIR" || { echo "❌ 目录不存在: $DIR"; exit 1; }

# 已在跑就别重复启动
if [ -f "$DIR/toy_lite.pid" ] && kill -0 "$(cat "$DIR/toy_lite.pid")" 2>/dev/null; then
    echo "ℹ️  已经在跑了 (PID $(cat "$DIR/toy_lite.pid"))"
    echo "   控制页: http://127.0.0.1:8765/relay/"
    echo "   MCP   : http://127.0.0.1:8765/mcp/"
    exit 0
fi

nohup "$PY" toy_lite.py > "$DIR/toy_lite.log" 2>&1 &
echo $! > "$DIR/toy_lite.pid"

sleep 3
if kill -0 "$(cat "$DIR/toy_lite.pid")" 2>/dev/null; then
    echo "✅ 已启动 (PID $(cat "$DIR/toy_lite.pid"))"
    echo "   控制页: http://127.0.0.1:8765/relay/"
    echo "   MCP   : http://127.0.0.1:8765/mcp/"
    echo "   停止  : bash $(dirname "$0")/stop.sh"
else
    echo "❌ 启动失败, 日志:"
    tail -n 20 "$DIR/toy_lite.log"
    exit 1
fi
