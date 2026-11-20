#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# run.sh — 一键启动 Toy Lite (v6: 不用 nohup/setsid, 纯 Python 分离进程)
#
# 【为什么改写】
# OPPO/ColorOS 上 Pydroid 的 nohup 会被套一层 setsid, 直接报:
#   setsid: exec python: Permission denied
# 绕法: 用 Python 的 subprocess(start_new_session=True) 自己调 setsid(2) 系统调用,
#       完全不经过 setsid 可执行文件 → 不 Permission denied。
#
# 用法:
#   bash run.sh
#   bash /sdcard/Download/TOYLITE/run.sh

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

# 清掉旧进程 / 旧 pid 文件
if [ -f "$DIR/toy_lite.pid" ]; then
    OLD=$(cat "$DIR/toy_lite.pid" 2>/dev/null)
    [ -n "$OLD" ] && kill -9 "$OLD" 2>/dev/null
    rm -f "$DIR/toy_lite.pid"
fi
pkill -f "toy_lite.py" 2>/dev/null
sleep 1

# --- 分离启动: 纯 Python, 不用 nohup / setsid 可执行文件 ---
"$PY" - <<'PYEOF'
import os, subprocess, sys
cwd = os.getcwd()
log = open(os.path.join(cwd, "toy_lite.log"), "a")
p = subprocess.Popen(
    [sys.executable, "-u", "toy_lite.py"],
    stdout=log, stderr=subprocess.STDOUT,
    cwd=cwd,
    start_new_session=True,   # 自己调 setsid(2), 不经过 setsid 可执行文件
)
try:
    open(os.path.join(cwd, "toy_lite.pid"), "w").write(str(p.pid))
except Exception:
    pass
print(p.pid)
PYEOF

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
    echo "   ⚠️ 请到 系统设置 → 电池 → 后台运行管理, 允许 Pydroid 3 后台活动"
else
    echo "❌ 分离启动失败, 日志最后 20 行:"
    tail -n 20 "$DIR/toy_lite.log" 2>/dev/null
    echo ""
    echo "👉 改用前台模式 (保持这个终端标签页开着, 别关):"
    echo "   cd $DIR && $PY -u toy_lite.py"
    exit 1
fi
