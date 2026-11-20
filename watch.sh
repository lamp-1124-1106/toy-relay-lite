#!/data/data/ru.iiec.pydroid3/files/usr/bin/bash
# watch.sh — 看门狗: 服务崩了自动重启
#
# 用法:
#   bash watch.sh          # 前台跑, 终端不关 (推荐, 能看到实时日志)
#   bash watch.sh &        # 后台跑
#
# 为什么需要:
#   Pydroid 里跑的进程, 在 OPPO 的激进省电策略下可能被系统杀。
#   这个循环保证进程一挂就立刻拉起来。

SELF="$0"
case "$SELF" in
  /*) ;;
  *) SELF="$(pwd)/$SELF" ;;
esac
DIR="$(cd "$(dirname "$SELF")" 2>/dev/null && pwd)"
[ -z "$DIR" ] && DIR="$(pwd)"

cd "$DIR" || exit 1

PY=python
command -v python >/dev/null 2>&1 || PY=python3

echo "🛡️ 看门狗启动 (目录: $DIR)"
echo "   终端不要关, 切标签页没关系"
echo "   Ctrl+C 退出看门狗"
echo ""

while true; do
    "$PY" -u toy_lite.py
    echo ""
    echo "--- 服务退出 (退出码 $?), 3 秒后自动重启 ---"
    sleep 3
done
