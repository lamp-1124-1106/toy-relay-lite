#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# 停止 Toy Lite
DIR=/storage/emulated/0/Download/Toy-Relay-AI-mcp-SOSEXY-main/toy_lite
if [ -f "$DIR/toy_lite.pid" ]; then
    PID=$(cat "$DIR/toy_lite.pid")
    kill "$PID" 2>/dev/null && echo "⏹ 已停止 (PID $PID)" || echo "ℹ️ 进程已不在"
    rm -f "$DIR/toy_lite.pid"
else
    pkill -f "toy_lite.py" 2>/dev/null && echo "⏹ 已停止" || echo "ℹ️ 没有在跑的实例"
fi
