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

rem ---- 找 python: 优先当前目录的免安装版, 再找系统的 ----
set PY=
if exist ".\python.exe" (
    set "PY=.\python.exe"
) else (
    where python >nul 2>nul && set "PY=python"
)
if "%PY%"=="" (
    where py >nul 2>nul && set "PY=py -3"
)
if "%PY%"=="" (
    echo [x] 没找到 Python!
    echo.
    echo 方案一: 装标准版 Python
    echo   https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    echo.
    echo 方案二: 装免安装版 (解压到本目录即可)
    echo   https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
    echo   解压后把里面的文件全部移到这个目录
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
echo   手机要用的话, 把下面这行跑在另一个窗口:
echo     set HOST=0.0.0.0 ^& python toy_lite.py
echo.
echo   关闭本窗口即停止服务
echo ============================================================
echo.

set HOST=0.0.0.0
%PY% toy_lite.py

pause
