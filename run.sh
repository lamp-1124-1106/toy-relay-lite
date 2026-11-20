#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# 一键启动 Toy Lite (后台运行, 终端标签页可以随便关)
#
# 用法 (在任意目录都可以):
#   bash run.sh
#   bash /sdcard/Download/TOYLITE/run.sh
#
# 脚本自己定位自己所在的目录, 所以放在哪都能跑。
#
# 注意: Pydroid 里 setsid 会 "exec python: Permission denied",
#       所以这里只用 nohup (已验证可用)。

# --- 定位目录 (脚本自己所在位置) ---
SELF="$0"
case "$SELF" in
  /*) ;;
  *) SELF="$(pwd)/$SELF" ;;
esac
DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)"
[ -z "$DIR" ] && DIR="$(pwd)"

if [ ! -f "$DIR/toy_lite.py" ] && [ -f "$DIR/../toy_lite/toy_lite.py" ]; then
    DIR="$(cd "$DIR/../toy_lite" && pwd)"
fi

if [ ! -f "$DIR/toy_lite.py" ]; then
    echo "❌ 找不到 toy_lite.py (脚本目录: $DIR)"
    exit 1
fi

cd "$DIR" || { echo "❌ 无法进入目录: $DIR"; exit 1; }

# --- 选 python ---
PY=python
command -v python >/dev/null 2>&1 || PY=python3

# --- 真实探活: 连一下 8765, 而不是靠 kill -0 (安卓上僵尸 PID 会骗人) ---
alive() {
    "$PY" - <<'PYEOF' >/dev/null 2>&1
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read()
except Exception:
    raise SystemExit(1)
PYEOF
}

if alive; then
    echo "ℹ️  已经在跑了 (端口 8765 有响应)"
    echo "   控制页: http://127.0.0.1:8765/relay/"
    echo "   MCP   : http://127.0.0.1:8765/mcp/"
    exit 0
fi

# 端口被占但探活失败 = 有个僵尸/半死进程占着, 先清掉
if [ -f "$DIR/toy_lite.pid" ]; then
    OLD=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
    [ -n "$OLD" ] && kill -9 "$OLD" 2>/dev/null
    rm -f "$DIR/toy_lite.pid"
fi
pkill -f "toy_lite.py" 2>/dev/null
sleep 1

# --- 启动: 只用 nohup (setsid 在 Pydroid 里会 Permission denied) ---
nohup "$PY" -u toy_lite.py > "$DIR/toy_lite.log" 2>&1 &
echo $! > "$DIR/toy_lite.pid"

# --- 等它起来 (最多 15 秒), 用真实探活判断 ---
OK=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    sleep 1
    if alive; then OK=1; break; fi
done

PID=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
if [ "$OK" = "1" ]; then
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
