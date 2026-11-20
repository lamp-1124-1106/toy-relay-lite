@echo off
chcp 65001 > nul
setlocal

rem ==== Toy Lite 一键启动 (Windows) ====
rem 双击这个文件即可。

cd /d "%~dp0"

echo ============================================================
echo   Toy Lite - 玩具中继 + MCP + 免费 TTS
echo ============================================================
echo.

rem ---- 找 python ----
set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (
    where py >nul 2>nul && set PY=py -3
)
if "%PY%"=="" (
    echo [x] 没找到 Python!
    echo.
    echo 请先安装 Python 3.8+ : https://www.python.org/downloads/
    echo 安装时记得勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
echo [1/2] Python: %PY%

rem ---- 检查文件 ----
if not exist "toy_lite.py" (
    echo [x] 找不到 toy_lite.py, 请确认解压完整
    pause
    exit /b 1
)
if not exist "edge_tts_lite.py" (
    echo [!] 找不到 edge_tts_lite.py, TTS 将不可用
)

rem ---- 启动 ----
echo [2/2] 启动中...
echo.
echo   控制页: http://127.0.0.1:8765/relay/
echo   MCP   : http://127.0.0.1:8765/mcp/
echo.
echo   手机要用的话, 把这行跑在另一个窗口:
echo     set HOST=0.0.0.0 ^& python toy_lite.py
echo.
echo   关闭本窗口即停止服务
echo ============================================================
echo.

set HOST=0.0.0.0
%PY% toy_lite.py

pause
