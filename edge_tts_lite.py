"""
edge_tts_lite.py — 零依赖的 edge-tts 实现 (纯标准库)

微软 Edge 浏览器自带的免费 TTS 引擎:
  - 不需要 API Key
  - 不需要账号
  - 没有调用次数限制
  - 中文音质很自然

本模块用标准库 (http.client + ssl + hashlib + base64) 直接实现
edge-tts 的 WebSocket 协议, 不依赖 edge-tts / websocket-client 等第三方包。

用法:
    from edge_tts_lite import synth
    mp3 = synth("你好", voice="zh-CN-XiaoxiaoNeural")

如果系统里有 edge-tts 命令 (pip install edge-tts), 会优先用它 —— 更稳。
"""
import base64
import hashlib
import json
import os
import random
import re
import shutil
import struct
import subprocess
import time
import urllib.request

__all__ = ["synth", "list_voices", "EDGE_VOICES", "SynthError"]


class SynthError(Exception):
    pass


# 中文 + 常见中英混合的推荐嗓音
EDGE_VOICES = [
    # (voice_id, 中文名, 性别)
    ("zh-CN-XiaoxiaoNeural", "晓晓", "女"),
    ("zh-CN-XiaoyiNeural", "晓伊", "女"),
    ("zh-CN-YunxiNeural", "云希", "男"),
    ("zh-CN-YunjianNeural", "云健", "男"),
    ("zh-CN-YunyangNeural", "云扬", "男"),
    ("zh-HK-HiuMaanNeural", "曉曼", "女"),
    ("zh-HK-WanLungNeural", "雲龍", "男"),
    ("zh-TW-HsiaoChenNeural", "曉臻", "女"),
    ("zh-TW-YunJheNeural", "雲哲", "男"),
]

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# ---- edge-tts 协议常量 ----
_WSS_URL = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud"
    "/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4"
)
_SEC_MS_GEC = "D4B1E4C0-B7B0-4C68-9E4A-6A6D9F9B8C4E"  # 旧版固定值, 新版需动态算
_ORIGIN = "Origin: chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"

# Sec-MS-GEC 动态生成 (2024 起 edge-tts 必须带)
_CLOCK_SKEW = 0
_TRUSTED_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"


def _generate_sec_ms_gec() -> str:
    """生成 Sec-MS-GEC 头 (edge-tts 6.x 之后的要求)"""
    import datetime
    ticks = int((time.time() + _CLOCK_SKEW) * 1000) % 100000000
    ticks += 0x7fffffff  # 0xFFFFFFFF - offset
    str_0 = ticks.to_bytes(4, "big").hex()
    rand_0 = random.randint(0, 0xFFFFFFFF).to_bytes(4, "big").hex()
    unix_time = int(time.time() + _CLOCK_SKEW)
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


def _mkssml(text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz") -> bytes:
    """构造 SSML (edge-tts 只接受微软自己生成的格式)"""
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="zh-CN">'
        '<voice name="%s"><prosody rate="%s" pitch="%s">%s</prosody></voice>'
        "</speak>"
    ) % (voice, rate, pitch, text)
    return ssml.encode("utf-8")


def _handshake_ws(host: str, path: str, headers: dict) -> "socket":
    """用标准库做 WebSocket 握手 + 收发帧"""
    import http.client
    import socket
    import ssl

    conn = http.client.HTTPSConnection(host, timeout=30)
    conn.putrequest("GET", path, skip_accept_encoding=True)
    conn.putheader("Host", host)
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders()
    resp = conn.getresponse()
    if resp.status != 101:
        raise SynthError("WebSocket 握手失败: HTTP %s" % resp.status)
    sock = conn.sock
    sock.settimeout(30)
    return conn, sock


def _ws_send(sock, data: bytes, opcode: int = 0x1) -> None:
    """发 WebSocket 帧 (客户端必须 mask)"""
    import os as _os
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
    mask = _os.urandom(4)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + masked)


def _ws_recv(sock, bufsize: int = 4096) -> bytes:
    """读一帧, 返回 payload"""
    def _readn(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise SynthError("WebSocket 连接被关闭")
            buf += chunk
        return buf

    b1, b2 = _readn(2)
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _readn(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _readn(8))[0]
    mask = _readn(4) if masked else None
    payload = _readn(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return payload


def _synth_stdlib(text, voice, rate, pitch) -> bytes:
    """纯标准库实现 (备用路径)"""
    import http.client

    host = "speech.platform.bing.com"
    path = "/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=%s" % _TRUSTED_TOKEN
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": _ws_key(),
        "Sec-MS-GEC": _generate_sec_ms_gec(),
        "Sec-MS-GEC-Version": "1-130.0.2849.68",
        "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    }

    conn, sock = _handshake_ws(host, path, headers)
    try:
        ssml = _mkssml(text, voice, rate, pitch)
        # binary frame: header 0x00 0x00 0x00 0x00 + 4B len + ssml
        payload = b"\x00\x00\x00\x00" + struct.pack("<I", len(ssml)) + ssml
        _ws_send(sock, payload, opcode=0x2)

        audio = bytearray()
        while True:
            msg = _ws_recv(sock)
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            # 文本帧: JSON, 里面 path=audio 或 turn.end
            if msg and msg[:1] == b"{":
                try:
                    obj = json.loads(msg.decode("utf-8"))
                except Exception:
                    continue
                path = obj.get("path", "")
                if path == "audio":
                    audio += base64.b64decode(obj.get("data", ""))
                elif path == "turn.end":
                    break
            # 二进制帧: 直接是音频
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
    """调用系统里的 edge-tts 命令 (更稳, 有就用)"""
    exe = shutil.which("edge-tts")
    if not exe:
        raise SynthError("edge-tts 命令不存在")
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "edge_tts_out.mp3")
    cmd = [exe, "--voice", voice, "--rate", rate, "--pitch", pitch,
           "--text", text, "--write-media", out]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    with open(out, "rb") as f:
        data = f.read()
    try:
        os.remove(out)
    except Exception:
        pass
    return data


def synth(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%",
          pitch: str = "+0Hz", prefer_cmd: bool = True) -> bytes:
    """合成语音, 返回 mp3 bytes

    Args:
        text: 要念的文本
        voice: 嗓音 id, 如 zh-CN-XiaoxiaoNeural
        rate: 语速, 如 +20% / -10%
        pitch: 音调, 如 +10Hz / -5Hz
        prefer_cmd: 是否优先用 edge-tts 命令 (装了的话更稳)
    """
    if not text or not str(text).strip():
        raise SynthError("文本为空")
    text = str(text)

    if prefer_cmd and shutil.which("edge-tts"):
        try:
            return _synth_subprocess(text, voice, rate, pitch)
        except Exception:
            pass  # 掉回标准库实现

    # 重试: Sec-MS-GEC 算错的话重试一次
    last_err = None
    for attempt in range(3):
        try:
            return _synth_stdlib(text, voice, rate, pitch)
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise SynthError("合成失败: %s" % last_err)


def list_voices() -> list:
    """列出推荐的嗓音"""
    return [{"id": v, "name": n, "gender": g} for v, n, g in EDGE_VOICES]


if __name__ == "__main__":
    import sys
    txt = sys.argv[1] if len(sys.argv) > 1 else "你好，我是你的 AI 伴侣。"
    v = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE
    data = synth(txt, v)
    out = "/tmp/tts_test.mp3"
    with open(out, "wb") as f:
        f.write(data)
    print("OK %d bytes -> %s" % (len(data), out))
