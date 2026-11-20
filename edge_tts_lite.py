"""
edge_tts_lite.py — 零依赖的 edge-tts 实现 (纯标准库)

微软 Edge 浏览器自带的免费 TTS 引擎:
  - 不需要 API Key / 账号
  - 没有调用次数限制
  - 中文音质很自然 (Neural 音色)

本模块用标准库 (http.client + hashlib + base64) 直接实现 edge-tts 的
WebSocket 协议, 不依赖 edge-tts / websocket-client 等第三方包。

用法:
    from edge_tts_lite import synth, play
    mp3 = synth("你好", voice="zh-CN-YunxiNeural")
    play("/tmp/a.mp3")
"""
import base64
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time

__all__ = ["synth", "play", "list_voices", "EDGE_VOICES", "SynthError"]


class SynthError(Exception):
    pass


# ---- 推荐的中文嗓音 ----
# (voice_id, 中文名, 性别, 适合什么)
EDGE_VOICES = [
    ("zh-CN-XiaoxiaoNeural", "晓晓", "女", "自然清亮, 通用"),
    ("zh-CN-XiaoyiNeural", "晓伊", "女", "年轻活泼, 偏甜"),
    ("zh-CN-YunxiNeural", "云希", "男", "清朗温柔, 少年感"),
    ("zh-CN-YunjianNeural", "云健", "男", "新闻播音腔, 浑厚"),
    ("zh-CN-YunyangNeural", "云扬", "男", "解说明快"),
    ("zh-HK-HiuMaanNeural", "曉曼", "女", "粤语"),
    ("zh-HK-WanLungNeural", "雲龍", "男", "粤语"),
    ("zh-TW-HsiaoChenNeural", "曉臻", "女", "台湾腔"),
    ("zh-TW-YunJheNeural", "雲哲", "男", "台湾腔"),
]

DEFAULT_VOICE = "zh-CN-YunxiNeural"

# ---- edge-tts 协议常量 ----
_HOST = "speech.platform.bing.com"
_PATH = "/consumer/speech/synthesize/readaloud/edge/v1"
_TRUSTED_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
_ORIGIN = "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"


def _generate_sec_ms_gec() -> str:
    """生成 Sec-MS-GEC 头 (edge-tts 新版必须带)"""
    unix_time = int(time.time())
    str_0 = (int(unix_time * 1000) % 100000000).to_bytes(4, "big").hex()
    rand_0 = random.randint(0, 0xFFFFFFFF).to_bytes(4, "big").hex()
    str_1 = hex(unix_time)[2:]
    rand_1 = random.randint(0, 0xFFFFFFFF).to_bytes(4, "big").hex()
    to_be = _TRUSTED_TOKEN.encode("ascii")
    to_be += bytes.fromhex(str_0)
    to_be += bytes.fromhex(rand_0)
    to_be += str_1.encode("ascii")
    to_be += bytes.fromhex(rand_1)
    sha256 = hashlib.sha256(to_be).digest()
    return hashlib.sha256(sha256 + b"\x00\x00\x00\x00").hexdigest().upper()


def _ws_key() -> str:
    return base64.b64encode(os.urandom(16)).decode()


def _mkssml(text, voice, rate, pitch) -> bytes:
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="zh-CN">'
        '<voice name="%s"><prosody rate="%s" pitch="%s">%s</prosody></voice>'
        "</speak>"
    ) % (voice, rate, pitch, text)
    return ssml.encode("utf-8")


def _ws_send(sock, data: bytes, opcode: int = 0x1) -> None:
    header = bytearray()
    header.append(0x80 | opcode)
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < (1 << 16):
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    mask = os.urandom(4)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + masked)


def _ws_recv(sock) -> bytes:
    def _readn(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise SynthError("WebSocket 连接被关闭")
            buf += chunk
        return buf

    b1, b2 = _readn(2)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _readn(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _readn(8))[0]
    masked = b2 & 0x80
    mask = _readn(4) if masked else None
    payload = _readn(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return payload


def _synth_stdlib(text, voice, rate, pitch) -> bytes:
    import http.client

    path = "%s?TrustedClientToken=%s" % (_PATH, _TRUSTED_TOKEN)
    headers = {
        "User-Agent": _UA,
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Origin": _ORIGIN,
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": _ws_key(),
        "Sec-MS-GEC": _generate_sec_ms_gec(),
        "Sec-MS-GEC-Version": "1-130.0.2849.68",
    }

    conn = http.client.HTTPSConnection(_HOST, timeout=30)
    conn.putrequest("GET", path, skip_accept_encoding=True)
    conn.putheader("Host", _HOST)
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders()
    resp = conn.getresponse()
    if resp.status != 101:
        raise SynthError("WebSocket 握手失败: HTTP %s" % resp.status)
    sock = conn.sock
    sock.settimeout(30)

    try:
        ssml = _mkssml(text, voice, rate, pitch)
        payload = b"\x00\x00\x00\x00" + struct.pack("<I", len(ssml)) + ssml
        _ws_send(sock, payload, opcode=0x2)

        audio = bytearray()
        while True:
            msg = _ws_recv(sock)
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            if msg and msg[:1] == b"{":
                try:
                    obj = json.loads(msg.decode("utf-8"))
                except Exception:
                    continue
                p = obj.get("path", "")
                if p == "audio":
                    audio += base64.b64decode(obj.get("data", ""))
                elif p == "turn.end":
                    break
            elif msg:
                audio += msg
    finally:
        try:
            sock.close()
        except Exception:
            pass

    if not audio:
        raise SynthError("没有收到音频数据")
    return bytes(audio)


def _synth_subprocess(text, voice, rate, pitch) -> bytes:
    exe = shutil.which("edge-tts")
    if not exe:
        raise SynthError("edge-tts 命令不存在")
    out = os.path.join(tempfile.gettempdir(), "edge_tts_out_%d.mp3" % os.getpid())
    cmd = [exe, "--voice", voice, "--rate", rate, "--pitch", pitch,
           "--text", text, "--write-media", out]
    subprocess.run(cmd, check=True, capture_output=True, timeout=90)
    with open(out, "rb") as f:
        data = f.read()
    try:
        os.remove(out)
    except Exception:
        pass
    return data


def synth(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%",
          pitch: str = "+0Hz") -> bytes:
    """合成语音, 返回 mp3 bytes"""
    if not text or not str(text).strip():
        raise SynthError("文本为空")
    text = str(text)

    if shutil.which("edge-tts"):
        try:
            return _synth_subprocess(text, voice, rate, pitch)
        except Exception:
            pass

    last_err = None
    for attempt in range(3):
        try:
            return _synth_stdlib(text, voice, rate, pitch)
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise SynthError("合成失败: %s" % last_err)


def play(path: str) -> bool:
    """在本机播放一个音频文件 (尽力而为, 失败返回 False)"""
    # Windows
    if os.name == "nt":
        for exe in ("wmplayer",):
            if shutil.which(exe):
                try:
                    subprocess.Popen([exe, path])
                    return True
                except Exception:
                    pass
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False
    # macOS
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["afplay", path])
            return True
        except Exception:
            try:
                subprocess.Popen(["open", path])
                return True
            except Exception:
                return False
    # Linux
    for exe in ("mpg123", "mpv", "ffplay", "paplay", "cvlc"):
        if shutil.which(exe):
            try:
                subprocess.Popen([exe, path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                continue
    try:
        subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def list_voices():
    return [{"id": v, "name": n, "gender": g, "note": d} for v, n, g, d in EDGE_VOICES]


if __name__ == "__main__":
    txt = " ".join(sys.argv[1:]) or "你好，我是路尧。你的声音，从今天开始由我自己的嗓子说出来了。"
    out = os.path.join(tempfile.gettempdir(), "tts_demo.mp3")
    try:
        data = synth(txt, DEFAULT_VOICE)
        with open(out, "wb") as f:
            f.write(data)
        print("合成成功: %d bytes -> %s" % (len(data), out))
        if play(out):
            print("已开始播放")
        else:
            print("没找到播放器, 手动打开上面的文件")
    except Exception as e:
        print("失败: %s" % e)
        sys.exit(1)
