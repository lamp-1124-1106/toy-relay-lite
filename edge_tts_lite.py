"""
edge_tts_lite.py — 零依赖的 edge-tts 实现 (纯标准库)

微软 Edge 浏览器自带的免费 TTS 引擎:
  - 不需要 API Key / 账号
  - 没有调用次数限制
  - 中文音质很自然 (Neural 音色)

本模块用标准库 (http.client + hashlib + base64) 直接实现 edge-tts 的
WebSocket 协议, 不依赖 edge-tts / websocket-client / aiohttp 等第三方包。

协议要点 (对照 rany2/edge-tts 官方源码):
  1. URL 查询参数带 ConnectionId / Sec-MS-GEC / Sec-MS-GEC-Version
  2. Header 带 Cookie: muid=<32位大写hex>
  3. 连上后先发文本帧 Path:speech.config (JSON, 指定音频格式)
  4. 再发文本帧 Path:ssml (带 X-RequestId / Content-Type / X-Timestamp 头)
     —— voice 名字在 SSML 里, 这一步发不对, 嗓音就不生效!
  5. 收: 文本帧 -> 解析 Path (audio.metadata / turn.end)
         二进制帧 -> 前2字节是header长度, 之后是 headers + mp3 数据

⭐ 三条降级路径 (自动):
  1. 系统里有 edge-tts 命令  -> 用它 (最稳)
  2. 本文件自实现 WebSocket  -> 音质最好
  3. Windows 内置 SAPI (PowerShell) -> 零安装保底, 音质一般但一定能出声
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
import uuid

__all__ = ["synth", "play", "list_voices", "EDGE_VOICES", "SynthError"]


class SynthError(Exception):
    pass


# ---- 推荐的中文嗓音 ----
# (voice_id, 中文名, 性别, 适合什么)
EDGE_VOICES = [
    ("zh-CN-YunxiNeural", "云希", "男", "清朗温柔, 少年感"),
    ("zh-CN-XiaoxiaoNeural", "晓晓", "女", "自然清亮, 通用"),
    ("zh-CN-XiaoyiNeural", "晓伊", "女", "年轻活泼, 偏甜"),
    ("zh-CN-YunjianNeural", "云健", "男", "新闻播音腔, 浑厚"),
    ("zh-CN-YunyangNeural", "云扬", "男", "解说明快"),
    ("zh-HK-HiuMaanNeural", "曉曼", "女", "粤语"),
    ("zh-HK-WanLungNeural", "雲龍", "男", "粤语"),
    ("zh-TW-HsiaoChenNeural", "曉臻", "女", "台湾腔"),
    ("zh-TW-YunJheNeural", "雲哲", "男", "台湾腔"),
]

DEFAULT_VOICE = "zh-CN-YunxiNeural"

# ---- 协议常量 ----
_HOST = "speech.platform.bing.com"
_BASE = "/consumer/speech/synthesize/readaloud"
_PATH = _BASE + "/edge/v1"
_TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
_CHROMIUM_FULL_VERSION = "143.0.3650.75"
_CHROMIUM_MAJOR_VERSION = _CHROMIUM_FULL_VERSION.split(".", 1)[0]
_SEC_MS_GEC_VERSION = "2-%s" % _CHROMIUM_FULL_VERSION
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
       " (KHTML, like Gecko) Chrome/%s.0.0.0 Safari/537.36 Edg/%s.0.0.0"
       % (_CHROMIUM_MAJOR_VERSION, _CHROMIUM_MAJOR_VERSION))


# ===================== DRM: Sec-MS-GEC v2 =====================
# 移植自 rany2/edge-tts 的 drm.py (Windows file time + CS64 摘要)
WIN_EPOCH = 11644473600
S_TO_NS = 1e9
_U32_MASK = 0xFFFFFFFF

_SHA256_INITIAL = (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
                   0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
_SHA256_STATE = (0xFD9FBEA2, 0x91243CE7, 0xBE499094, 0xCD2E1E0A,
                 0x6C006F49, 0x04BD35AB, 0xFEBE0D0E, 0x03EFFBD2)
_SHA256_SCHEDULE = (
    0xEB24CBE3, 0x15581A26, 0xA3A6F2E9, 0x3C3CF5C8, 0x9C3F3F14, 0x708A7A9C,
    0xA0323CF6, 0xD5E1E63E, 0xDB5C0FAE, 0x9E53A2D1, 0x8FAC3F81, 0x1C0B0E1B,
    0xE1A8C0B6, 0x9E4E4A48, 0x8B2C1F0C, 0x0E3C1D6E, 0x90E1D9FB, 0xEDBE4AE3,
    0x1C7C4A0F, 0xD2E30C1B, 0xA0E3B0D1, 0xC2F3D9A0, 0x1B1F0F2E, 0x0D2B5F04,
    0x4B1B0B0E, 0x0E2C0D1F, 0x1A6F0F1E, 0x2E1C0D2E, 0x0E1D0F2E, 0x1E2F0C1D,
    0x0F1E2D0C, 0x1C0D2E0F, 0x2E0F1D0C, 0x0D1E2F0C, 0x1E0F2D0C, 0x0F1D2E0C,
    0x2E0D1F0C, 0x0C2E1F0D, 0x1F0D2E0C, 0x0D1F2E0C, 0x1E0C2F1D, 0x2E0C1D1F,
    0x0D1E2C0F, 0x1F2E0D0C, 0x2D0C1E0F, 0x0C1F2E0D, 0x1E0D2F0C, 0x0D2C1E0F,
    0x2F0D1E0C, 0x0C2F1E0D, 0x1D0E2F0C, 0x0F1D2E0C, 0x2C0F1D0E, 0x0D2C0F1E,
    0x1F0E2D0C, 0x0E1F2D0C, 0x2D0C1F0E, 0x0C2D1E0F, 0x1E0C2D1F, 0x0F1E0C2D,
    0x1D0F2E0C, 0x0C1D2F0E, 0x2E0C1D0F, 0x0D0E1F2C, 0x1F0C2D0E, 0x0E1F0C2D,
    0x2D0E1F0C, 0x0C2D0E1F, 0x1E0F1C2D, 0x0F1E2D0C, 0x1D2E0F0C, 0x0C2D1E0F,
    0x2E0F1C0D, 0x0F2C1D0E, 0x1C0D2E0F, 0x0D1C2E0F, 0x2F0E1C0D, 0x0E2F1C0D,
    0x1D0E2F0C, 0x0C1D0E2F, 0x2C1D0E0F, 0x0F2C1D0E, 0x1E0F2C1D, 0x0D1E0F2C,
    0x2D0E1F0C, 0x0C2D0E1F, 0x1F0C2D0E, 0x0E1F0C2D, 0x2D1F0C0E, 0x0C2D1F0C,
    0x1E0C2D1F, 0x0F1E0C2D, 0x2C1E0F0C, 0x0C2C1E0F, 0x1F0D2C1E, 0x0D1F0D2C,
    0x2E1F0D0C, 0x0C2E1F0D, 0x1D0C2E1F, 0x0F1D0C2E, 0x2F1D0C0E, 0x0E2F1D0C,
    0x1C0E2F1D, 0x0D1C0E2F, 0x2F1D0C0E, 0x0E2F1D0C, 0x1D0E2F1C, 0x0F1D0E2F,
    0x2C1D0E0F, 0x0C2C1D0E, 0x1F0E2C1D, 0x0D1F0E2C, 0x2E1F0D0C, 0x0C2E1F0D,
    0x1D0C2E1F, 0x0F1D0C2E, 0x2F1D0C0E, 0x0E2F1D0C, 0x1C0E2F1D, 0x0D1C0E2F,
    0x2F1C0E0D, 0x0E2F1C0D, 0x1D0E2F1C, 0x0F1D0E2F, 0x2C1D0E0F, 0x0C2C1D0E,
    0x1F0E2C1D, 0x0D1F0E2C, 0x2E1F0D0C, 0x0C2E1F0D, 0x1D0C2E1F, 0x0F1D0C2E,
)
_SHA256_ROUND_CONSTANTS = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1,
    0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1, 0xEFBE4786,
    0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147,
    0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B,
    0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A,
    0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)
_SHA256_ADJUSTMENT = 0xC9DC06A7
_SHA256_BLOCK_CONSTANTS = (_SHA256_ROUND_CONSTANTS[:14] + (_SHA256_ADJUSTMENT,)
                         + _SHA256_ROUND_CONSTANTS[15:])
_SHA256_SIGMA0_ADJUSTMENT = 0x059C0B80
_SHA256_SIGMA1_ADJUSTMENT = 0x000B92C0

_CS64_COEFFICIENTS = (
    (0xE82E91B1, 0xB32700D0), (0x44DE24C6, 0x88DFF51D),
    (0x3BEB65BC, 0x29514038), (0xC89C5933, 0xB328CBDF),
    (0x8D1EC211, 0xD405B4D5), (0x314EF5D5, 0x26E55F3C),
    (0xE92491B1, 0x607801C6), (0xF0A5B9D5, 0x82B2C1FB),
    (0x06064CF3, 0xFA51A3DA), (0xDA79FA60, 0x207CC464),
    (0xBED20560, 0x3C3C74F3), (0x89F9C9F8, 0xD2D14B61),
    (0x35FA38C6, 0xBB04A2C1), (0xCB49E3C6, 0xC5626167),
)
_CS64_FACTOR = 0x82893933
_CS64_ADJUSTMENT0 = 0xF2F90B1A
_CS64_ADJUSTMENT1 = 0x0B1A0000


def _rol16(value):
    value &= _U32_MASK
    return ((value << 16) | (value >> 16)) & _U32_MASK


def _words_le4_even(data):
    padded = data + b"\x00" * ((-len(data)) % 4)
    if not padded:
        return []
    words = list(struct.unpack("<%dI" % (len(padded) // 4), padded))
    if len(words) % 2:
        words.append(0)
    return words


def _sigma0(value):
    return ((value >> 7) ^ (value << 25) ^ (value >> 18) ^ (value << 14)
            ^ (value >> 3)) & _U32_MASK


def _sigma1(value):
    return ((value >> 17) ^ (value << 15) ^ (value >> 19) ^ (value << 13)
            ^ (value >> 10)) & _U32_MASK


def _expand_sha256_schedule(words, first_word=16):
    mask = _U32_MASK
    for index in range(first_word, 64):
        x, y = words[index - 2], words[index - 15]
        s1 = _sigma1(x)
        if index == 16:
            s1 = (s1 ^ _SHA256_SIGMA1_ADJUSTMENT) & mask
        s0 = _sigma0(y)
        if index == 29:
            s0 = (s0 ^ _SHA256_SIGMA0_ADJUSTMENT) & mask
        words.append((s1 + words[index - 7] + s0 + words[index - 16]) & mask)


def _sha256_rounds(state, words, first_round=0):
    a, b, c, d, e, f, g, h = state
    mask = _U32_MASK
    constants = (_SHA256_BLOCK_CONSTANTS if first_round == 14
                 else _SHA256_ROUND_CONSTANTS)
    aligned = min(64, ((first_round + 7) // 8) * 8)
    for index in range(first_round, aligned):
        rot_e = e * 0x100000001
        rot_a = a * 0x100000001
        t1 = ((h + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (g ^ (e & (f ^ g))) + constants[index] + words[index]))
        t2 = ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
              + ((a & b) | (c & (a | b))))
        a, b, c, d, e, f, g, h = ((t1 + t2) & mask, a, b, c, (d + t1) & mask,
                                 e, f, g, h)
    for index in range(aligned, 64, 8):
        rot_e = e * 0x100000001
        rot_a = a * 0x100000001
        t1 = ((h + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (g ^ (e & (f ^ g))) + constants[index] + words[index]))
        d = (d + t1) & mask
        h = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((a & b) | (c & (a | b))))) & mask)
        rot_e = d * 0x100000001
        rot_a = h * 0x100000001
        t1 = ((g + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (h & (a & (b ^ h))) + constants[index + 1] + words[index + 1]))
        c = (c + t1) & mask
        g = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((h & a) | (b & (h | a))))) & mask)
        rot_e = c * 0x100000001
        rot_a = g * 0x100000001
        t1 = ((f + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (e ^ (c & (d ^ e))) + constants[index + 2] + words[index + 2]))
        b = (b + t1) & mask
        f = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((g & h) | (a & (g | h))))) & mask)
        rot_e = b * 0x100000001
        rot_a = f * 0x100000001
        t1 = ((e + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (d ^ (e & (f ^ e))) + constants[index + 3] + words[index + 3]))
        a = (a + t1) & mask
        e = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((f & g) | (h & (f | g))))) & mask)
        rot_e = a * 0x100000001
        rot_a = e * 0x100000001
        t1 = ((d + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (c ^ (a & (b ^ c))) + constants[index + 4] + words[index + 4]))
        h = (h + t1) & mask
        d = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((e & f) | (g & (e | f))))) & mask)
        rot_e = h * 0x100000001
        rot_a = d * 0x100000001
        t1 = ((c + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (b ^ (h & (c ^ h))) + constants[index + 5] + words[index + 5]))
        g = (g + t1) & mask
        c = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((h & b) | (a & (h | b))))) & mask)
        rot_e = c * 0x100000001
        rot_a = g * 0x100000001
        t1 = ((b + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (a ^ (c & (d ^ a))) + constants[index + 6] + words[index + 6]))
        f = (f + t1) & mask
        b = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((c & d) | (e & (c | d))))) & mask)
        rot_e = b * 0x100000001
        rot_a = f * 0x100000001
        t1 = ((a + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
               + (h ^ (c & (d ^ h))) + constants[index + 7] + words[index + 7]))
        e = (e + t1) & mask
        a = ((t1 + ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)
               + ((f & g) | (h & (f | g))))) & mask)
    return a, b, c, d, e, f, g, h


def _sha256_init(data):
    mask = _U32_MASK
    words = [0] * 14 + [int.from_bytes(data[:3], "big")]
    words.append(int.from_bytes(data[3:7], "big"))
    for index in range(16, 30):
        value = _SHA256_SCHEDULE[index - 16]
        if index - 2 >= 14:
            value += ((_sigma1(words[index - 2]) ^ _SHA256_SIGMA1_ADJUSTMENT)
                      if index == 16 else _sigma1(words[index - 2]))
        if index - 7 >= 14:
            value += words[index - 7]
        if index - 15 >= 14:
            value += ((_sigma0(words[index - 15]) ^ _SHA256_SIGMA0_ADJUSTMENT)
                      if index == 29 else _sigma0(words[index - 15]))
        words.append(value & mask)
    words.append((_sigma1(words[28]) + words[23] + _sigma0(words[15])
                  + words[14] + _SHA256_ADJUSTMENT
                  - _SHA256_ROUND_CONSTANTS[14]) & mask)
    _expand_sha256_schedule(words, 31)
    working = _sha256_rounds(_SHA256_STATE, words, 14)
    return tuple((x + y) & mask for x, y in zip(_SHA256_INITIAL, working))


def _sha256_digest(data):
    if len(data) < 7:
        raise ValueError("Token salt must contain at least seven bytes")
    mask = _U32_MASK
    length = 57 + len(data)
    padded = data[7:] + b"\x80" + b"\x00" * ((55 - length) % 64)
    padded += struct.pack(">Q", length * 8)
    state = _sha256_init(data[:7])
    for offset in range(0, len(padded), 64):
        words = list(struct.unpack(">16I", padded[offset:offset + 64]))
        _expand_sha256_schedule(words)
        working = _sha256_rounds(state, words)
        state = tuple((x + y) & mask for x, y in zip(state, working))
    return struct.pack(">8I", *state)


def _cs64_digest(data, digest):
    mask = _U32_MASK
    key_a, key_b = struct.unpack_from("<II", digest)
    key_a |= 1
    key_b |= 1
    factors = ((key_a * _CS64_FACTOR) & mask, (key_b * _CS64_FACTOR) & mask)
    terms = [(coefficient * factors[index % 2]) & mask
             for index, (coefficient, _) in enumerate(_CS64_COEFFICIENTS)]
    offsets = [offset for _, offset in _CS64_COEFFICIENTS]
    for index, word in enumerate(_words_le4_even(b"\x00" + data)):
        term = word * (key_a if index % 2 == 0 else key_b)
        offset = _rol16(word) * (0xEF0569FB if index % 2 == 0 else 0xC31713DB)
        if index == 0:
            term += _CS64_ADJUSTMENT0 * factors[0]
            offset += _CS64_ADJUSTMENT1
        terms.append(term & mask)
        offsets.append(offset & mask)
    swap_acc = swap_last = state = acc = 0
    for index in range(0, len(terms), 2):
        x, y = terms[index], terms[index + 1]
        t = _rol16((offsets[index] + x) & mask)
        q = (t * 0x76F50F34) & mask
        swap_acc += (_rol16(q) * 0xC3EFEA97 + q) & mask
        t = _rol16((offsets[index + 1] + y) & mask)
        q = (t * 0x1881CE3C) & mask
        swap_last = (_rol16(q) * 0x35BD1EC9 + q) & mask
        swap_acc = (swap_acc + swap_last) & mask
        state = (state * key_a + x) & mask
        state = (_rol16(state) * 0xCF98B111) & mask
        state = (_rol16(state) * 0x87085B9F) & mask
        state = (_rol16(state) * 0x12CEB96D) & mask
        state = (_rol16(state) * 0x257E1D83) & mask
        acc += state
        t = (state * key_b + y) & mask
        t = (_rol16(t) * 0xA27416F5) & mask
        t = (_rol16(t) * 0xD38396FF) & mask
        state = (_rol16((_rol16(t) * 0x7C932B89) & mask) * 0xBFA49F69) & mask
        acc += (acc + state) & mask
    return swap_last ^ state, swap_acc ^ acc


def _token_hash(data):
    digest = _sha256_digest(data)
    cs64 = struct.pack("<II", *_cs64_digest(data, digest)).hex().upper()
    return cs64, digest.hex().upper()


def generate_sec_ms_gec(unix_timestamp=None):
    """生成 Sec-MS-GEC v2 token (格式: <16hex>-<64hex>)"""
    if unix_timestamp is None:
        ticks = time.time()
    else:
        ticks = float(unix_timestamp)
    ticks += WIN_EPOCH
    ticks -= ticks % 300
    ticks *= S_TO_NS / 100
    str_to_hash = ("%.0f%s" % (ticks, _TRUSTED_CLIENT_TOKEN)).encode("ascii")
    cs64, sha256 = _token_hash(str_to_hash)
    return "%s-%s" % (cs64, sha256)


def _generate_muid():
    return os.urandom(16).hex().upper()


def _date_to_string():
    return time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
                          time.gmtime())


# ===================== WebSocket =====================
def _ws_key():
    return base64.b64encode(os.urandom(16)).decode()


def _ws_send(sock, data, opcode=0x1):
    """发 WebSocket 帧 (客户端必须 mask)"""
    if isinstance(data, str):
        data = data.encode("utf-8")
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


def _ws_recv(sock):
    """读一帧, 返回 (opcode, payload)"""
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
    return opcode, payload


def _get_headers_and_data(data, header_length):
    headers = {}
    for line in data[:header_length].split(b"\r\n"):
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key] = value
    return headers, data[header_length + 2:]


def _mkssml(text, voice, rate, pitch, volume="+0%"):
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xml:lang='en-US'>"
        "<voice name='%s'>"
        "<prosody pitch='%s' rate='%s' volume='%s'>%s</prosody>"
        "</voice></speak>"
    ) % (voice, pitch, rate, volume, text)


def _synth_stdlib(text, voice, rate, pitch):
    """纯标准库实现 (对照官方 communicate.py)"""
    import http.client

    conn_id = uuid.uuid4().hex
    gec = generate_sec_ms_gec()
    path = ("%s?TrustedClientToken=%s&ConnectionId=%s&Sec-MS-GEC=%s"
            "&Sec-MS-GEC-Version=%s"
            % (_PATH, _TRUSTED_CLIENT_TOKEN, conn_id, gec, _SEC_MS_GEC_VERSION))

    headers = {
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": _ws_key(),
        "User-Agent": _UA,
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "muid=%s;" % _generate_muid(),
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
    sock.settimeout(40)

    try:
        # --- 1) speech.config ---
        config = (
            "X-Timestamp:%s\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n"
            "\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"'
            '},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}'
            "\r\n"
        ) % _date_to_string()
        _ws_send(sock, config, opcode=0x1)

        # --- 2) ssml (voice 在这里! 发不对嗓音就不生效) ---
        ssml = _mkssml(text, voice, rate, pitch)
        ssml_msg = (
            "X-RequestId:%s\r\n"
            "Content-Type:application/ssml+xml\r\n"
            "X-Timestamp:%sZ\r\n"
            "Path:ssml\r\n"
            "\r\n"
            "%s"
        ) % (conn_id, _date_to_string(), ssml)
        _ws_send(sock, ssml_msg, opcode=0x1)

        # --- 3) 收 ---
        audio = bytearray()
        got_audio = False
        while True:
            opcode, msg = _ws_recv(sock)
            if opcode == 0x1:      # 文本帧
                raw = msg if isinstance(msg, bytes) else msg.encode("utf-8")
                idx = raw.find(b"\r\n\r\n")
                if idx < 0:
                    continue
                h, _data = _get_headers_and_data(raw, idx)
                path = h.get(b"Path", b"")
                if path == b"turn.end":
                    break
                # response / turn.start / audio.metadata -> 忽略
            elif opcode == 0x2:    # 二进制帧
                if len(msg) < 2:
                    continue
                header_length = int.from_bytes(msg[:2], "big")
                if header_length > len(msg):
                    continue
                h, data = _get_headers_and_data(msg, header_length)
                if h.get(b"Path") != b"audio":
                    continue
                if not data:
                    continue
                audio += data
                got_audio = True
            else:
                break
    finally:
        try:
            sock.close()
        except Exception:
            pass

    if not got_audio or not audio:
        raise SynthError("没有收到音频数据")
    return bytes(audio)


def _synth_subprocess(text, voice, rate, pitch):
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


# ---------- Windows SAPI 保底 (零安装, 一定有中文声) ----------
def _synth_sapi(text, out_path):
    """用 Windows 内置 SAPI 合成 WAV (System.Speech, 零安装)"""
    if os.name != "nt":
        raise SynthError("SAPI 只在 Windows 上可用")
    ps = os.path.join(tempfile.gettempdir(), "_tts_sapi_%d.ps1" % os.getpid())
    wav = out_path + ".wav"
    b64 = base64.b64encode(str(text).encode("utf-8")).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop'\n"
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$t = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('%s'))\n"
        "$s.SetOutputToWaveFile('%s')\n"
        "$s.Speak($t)\n"
        "$s.Dispose()\n"
    ) % (b64, wav.replace("'", "''"))
    with open(ps, "w", encoding="utf-8") as f:
        f.write(script)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps],
            capture_output=True, timeout=120)
        if r.returncode != 0:
            raise SynthError("SAPI 失败: " + r.stderr.decode("utf-8", "ignore")[:400])
        if not os.path.exists(wav):
            raise SynthError("SAPI 没生成音频")
        with open(wav, "rb") as f:
            return f.read()
    finally:
        for p in (ps, wav):
            try:
                os.remove(p)
            except Exception:
                pass


def synth(text, voice=DEFAULT_VOICE, rate="+0%", pitch="+0Hz", allow_sapi=True):
    """合成语音, 返回音频 bytes (mp3 或 wav)

    尝试顺序: edge-tts 命令 -> 自实现 WebSocket -> Windows SAPI
    """
    if not text or not str(text).strip():
        raise SynthError("文本为空")
    text = str(text)

    # 1) 装了官方库就用它
    if shutil.which("edge-tts"):
        try:
            return _synth_subprocess(text, voice, rate, pitch)
        except Exception:
            pass

    # 2) 自实现 WebSocket
    last_err = None
    for attempt in range(3):
        try:
            return _synth_stdlib(text, voice, rate, pitch)
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)

    # 3) Windows SAPI 保底
    if allow_sapi and os.name == "nt":
        try:
            return _synth_sapi(text, os.path.join(tempfile.gettempdir(), "tts_sapi_out"))
        except Exception as e:
            raise SynthError("edge-tts 失败 (%s); SAPI 也失败: %s" % (last_err, e))

    raise SynthError("合成失败: %s" % last_err)


def play(path):
    """在本机播放一个音频文件 (尽力而为, 失败返回 False)"""
    if os.name == "nt":
        if shutil.which("wmplayer"):
            try:
                subprocess.Popen(["wmplayer", path])
                return True
            except Exception:
                pass
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False
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
    txt = " ".join(sys.argv[1:]) or "Hello, this is Luyao."
    out = os.path.join(tempfile.gettempdir(), "tts_demo.mp3")
    try:
        data = synth(txt, DEFAULT_VOICE)
        with open(out, "wb") as f:
            f.write(data)
        print("OK %d bytes -> %s" % (len(data), out))
        if play(out):
            print("playing")
        else:
            print("no player found")
    except Exception as e:
        print("FAILED: %s" % e)
        sys.exit(1)
