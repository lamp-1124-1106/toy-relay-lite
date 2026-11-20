#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_tts.py — TTS 诊断脚本 (Windows 友好)
把每一步都打印出来, 定位问题用。

用法:
    python test_tts.py

会:
  1. 打印 Python 版本和当前目录
  2. 检查 edge_tts_lite.py 在不在
  3. 尝试合成 (英文文本, 避开命令行编码坑)
  4. 尝试合成中文文本
  5. 把 mp3 存到桌面, 并尝试播放
"""
import os
import sys
import platform
import traceback

def p(*a):
    print(*a)
    sys.stdout.flush()

p("=" * 60)
p("[1] Python info")
p("    version :", sys.version.split()[0])
p("    exe     :", sys.executable)
p("    cwd     :", os.getcwd())
p("    platform:", platform.platform())
p("=" * 60)

p("[2] Checking files...")
here = os.path.dirname(os.path.abspath(__file__))
p("    script dir :", here)
for f in ("edge_tts_lite.py", "toy_lite.py"):
    path = os.path.join(here, f)
    p("    %-16s %s  (%s bytes)" % (
        f, "FOUND" if os.path.exists(path) else "MISSING",
        os.path.getsize(path) if os.path.exists(path) else 0))
p("=" * 60)

p("[3] Import edge_tts_lite...")
try:
    sys.path.insert(0, here)
    import edge_tts_lite as tts
    p("    OK. voices:", len(tts.EDGE_VOICES))
except Exception as e:
    p("    IMPORT FAILED:", e)
    traceback.print_exc()
    p("    -> try: pip install edge-tts")
    sys.exit(1)
p("=" * 60)

# 存到桌面
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
if not os.path.isdir(desktop):
    desktop = os.path.join(os.path.expanduser("~"), "桌面")
if not os.path.isdir(desktop):
    desktop = os.getcwd()
p("[4] Output dir:", desktop)
p("=" * 60)

# --- 英文测试 (排除中文命令行编码问题) ---
p("[5] Synthesizing ENGLISH test...")
out_en = os.path.join(desktop, "tts_test_en.mp3")
try:
    data = tts.synth("Hello, this is a test of the text to speech engine.",
                      voice="en-US-JennyNeural")
    with open(out_en, "wb") as fp:
        fp.write(data)
    p("    OK ->", out_en, "(%d bytes)" % len(data))
except Exception as e:
    p("    FAILED:", e)
    traceback.print_exc()
    p("    -> try: pip install edge-tts")
    out_en = None
p("=" * 60)

# --- 中文测试 ---
p("[6] Synthesizing CHINESE test (zh-CN-YunxiNeural)...")
out_cn = os.path.join(desktop, "tts_test_cn.mp3")
try:
    data = tts.synth("你好，我是路尧。这是我的声音。", voice="zh-CN-YunxiNeural")
    with open(out_cn, "wb") as fp:
        fp.write(data)
    p("    OK ->", out_cn, "(%d bytes)" % len(data))
except Exception as e:
    p("    FAILED:", e)
    traceback.print_exc()
    out_cn = None
p("=" * 60)

# --- 播放 ---
p("[7] Playing...")
for f in (out_cn, out_en):
    if not f:
        continue
    try:
        ok = tts.play(f)
        p("    play(%s) -> %s" % (os.path.basename(f), "OK" if ok else "NO PLAYER FOUND"))
    except Exception as e:
        p("    play failed:", e)
p("=" * 60)

p("[8] Result")
p("    EN mp3:", out_en if out_en and os.path.exists(out_en) else "NONE")
p("    CN mp3:", out_cn if out_cn and os.path.exists(out_cn) else "NONE")
p("    (double-click the mp3 files on Desktop to hear them)")
p("=" * 60)
