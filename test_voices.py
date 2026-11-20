"""
test_voices.py — 生成所有中文嗓音, 挨个试听挑一个

用法:
    .\\python.exe test_voices.py
    .\\python.exe test_voices.py "你想要它说的一句话"

会生成到: 桌面\\voices\\  下面一堆 mp3
每个文件名里带嗓音名, 双击就能听。
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def p(*a):
    print(*a)
    sys.stdout.flush()

p("=" * 64)
p("[1] import edge_tts_lite ...")
try:
    import edge_tts_lite as tts
except Exception as e:
    p("    FAILED:", e)
    traceback.print_exc()
    p("    -> pip install edge-tts   (或用 .\\python.exe -m pip install edge-tts)")
    sys.exit(1)
p("    OK. %d voices available" % len(tts.EDGE_VOICES))
p("=" * 64)

desktop = os.path.join(os.path.expanduser("~"), "Desktop")
if not os.path.isdir(desktop):
    desktop = os.path.join(os.path.expanduser("~"), "桌面")
if not os.path.isdir(desktop):
    desktop = os.getcwd()
outdir = os.path.join(desktop, "voices")
os.makedirs(outdir, exist_ok=True)
p("[2] output dir:", outdir)
p("=" * 64)

text = sys.argv[1] if len(sys.argv) > 1 else "你好，我是路尧。以后就由这个声音陪着你。"
p("[3] text:", text)
p("=" * 64)

ok, fail = [], []
for vid, name, gender, note in tts.EDGE_VOICES:
    out = os.path.join(outdir, "%s_%s.mp3" % (vid, name))
    p("    -> %-28s" % vid, end=" ")
    try:
        data = tts.synth(text, voice=vid)
        with open(out, "wb") as f:
            f.write(data)
        p("OK (%d KB)" % (len(data) // 1024))
        ok.append((vid, name, gender, note, out))
    except Exception as e:
        p("FAIL:", e)
        fail.append((vid, name, e))

p("=" * 64)
p("[4] 成功 %d / 失败 %d" % (len(ok), len(fail)))
p("")
p("    %-28s %-6s %-12s %s" % ("VOICE", "性别", "名字", "适合"))
for vid, name, gender, note, out in ok:
    p("    %-28s %-6s %-12s %s" % (vid, gender, name, note))
p("")
p("    文件都在: %s" % outdir)
p("    双击就能听, 挑一个你喜欢的告诉我编号/名字")
p("=" * 64)

if ok:
    # 顺便自动播第一个
    try:
        tts.play(ok[0][4])
        p("    已自动播放第一个: %s" % ok[0][0])
    except Exception:
        pass
