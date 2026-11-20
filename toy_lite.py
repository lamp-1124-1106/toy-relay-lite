"""
toy_lite.py — 零依赖玩具中继 + MCP + 免费 TTS (v5)
只用 Python 标准库, 不需要 fastapi / uvicorn / mcp / pydantic / edge-tts。
手机 (Pydroid 3) 或电脑 (Windows / macOS / Linux) 都能跑。

  # 手机 (Pydroid 3): 只监听本机
  python toy_lite.py

  # 电脑: 监听局域网, 让手机上的 RikkaHub 能连进来
  HOST=0.0.0.0 python toy_lite.py

  # 加访问口令
  HOST=0.0.0.0 TOKEN=你的口令 python toy_lite.py

  # Windows 双击 run_pc.bat

环境变量:
  HOST   监听地址, 默认 127.0.0.1 / 可设 0.0.0.0 (局域网)
  PORT   端口, 默认 8765
  TOKEN  可选。设了之后 /mcp /state /toy/* 需要 X-API-Key

v5 相比 v4:
  - 新增 toy_speak 工具: AI 用 edge-tts (微软免费引擎) 合成语音并播放
  - 新增 toy_speak_and_play: 说话同时让玩具震动配合
  - TTS 零依赖实现放在 edge_tts_lite.py
"""
import json
import os
import queue
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
TOKEN = os.environ.get("TOKEN", "").strip()
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "state.json")

MOTORS = ("suction", "vibration", "electric")
MOTOR_CN = {"suction": "吮吸", "vibration": "震动", "electric": "电流"}

SUPPORTED_PROTOOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

# ---- TTS (可选, 缺了也不影响其他功能) ----
try:
    import edge_tts_lite as _tts
    TTS_OK = True
except Exception:
    _tts = None
    TTS_OK = False

DEFAULT_VOICE = "zh-CN-YunxiNeural"   # 云希: 清朗温柔男声
LAST_AUDIO = os.path.join(ROOT, "state", "last_tts.mp3")

_lock = threading.Lock()
_subs = []
_sessions = {}
SSE_IDLE = 20.0


# ---------------- 状态 ----------------
def default_state():
    return {
        "cmd": "stop",
        "motor": "all",
        "intensity": 0,
        "patterns": {},
        "updated_at": 0,
        "history": [],
    }


def read_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_state()


def write_state(st):
    st["updated_at"] = int(time.time() * 1000)
    st.setdefault("history", [])
    hist = st["history"]
    hist.append({
        "cmd": st.get("cmd"),
        "motor": st.get("motor"),
        "intensity": st.get("intensity"),
        "ts": st["updated_at"],
    })
    st["history"] = hist[-20:]
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        print("[warn] 写 state 失败:", e, flush=True)
    broadcast(st)
    return st


def broadcast(st):
    with _lock:
        subs = list(_subs)
    for q in subs:
        try:
            q.put_nowait(st)
        except Exception:
            pass


def set_motor(motor, intensity):
    if motor not in MOTORS:
        raise ValueError("未知马达: " + str(motor))
    intensity = max(0, min(100, int(intensity)))
    st = read_state()
    st["cmd"] = "set"
    st["motor"] = motor
    st["intensity"] = intensity
    if intensity == 0:
        st.setdefault("patterns", {}).pop(motor, None)
    return write_state(st)


def set_pattern(motor, ptype, high, low, duration):
    if motor not in MOTORS:
        raise ValueError("未知马达: " + str(motor))
    st = read_state()
    st["cmd"] = "set"
    st["motor"] = motor
    st["intensity"] = int(high)
    st.setdefault("patterns", {})[motor] = {
        "type": ptype,
        "high": max(0, min(100, int(high))),
        "low": max(0, min(100, int(low))),
        "duration": max(1, int(duration)),
    }
    return write_state(st)


def stop_all():
    st = read_state()
    st["cmd"] = "stop"
    st["motor"] = "all"
    st["intensity"] = 0
    st["patterns"] = {}
    return write_state(st)


# ---------------- TTS ----------------
def do_speak(text, voice=DEFAULT_VOICE, rate="+0%", pitch="+0Hz"):
    """合成 + 播放语音, 返回 (mp3路径, 字节数, 是否已播放)"""
    if not TTS_OK:
        raise ValueError("TTS 模块不可用 (edge_tts_lite.py 缺失)")
    data = _tts.synth(text, voice=voice, rate=rate, pitch=pitch)
    os.makedirs(os.path.dirname(LAST_AUDIO), exist_ok=True)
    with open(LAST_AUDIO, "wb") as f:
        f.write(data)
    played = False
    try:
        played = _tts.play(LAST_AUDIO)
    except Exception:
        played = False
    return LAST_AUDIO, len(data), played


# ---------------- MCP 工具 ----------------
TOOLS = [
    {
        "name": "toy_suction",
        "description": "控制玩具的吮吸马达 (吸力)。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {"intensity": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_vibration",
        "description": "控制玩具的震动马达。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {"intensity": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_electric",
        "description": "控制玩具的电流刺激马达。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {"intensity": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_pattern",
        "description": "播放一段节奏 (波形)。type: wave(正弦) / pulse(方波) / climb(渐强渐弱) / constant(恒定)。high/low 为强度上下限 0-100, duration 为持续秒数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "motor": {"type": "string", "enum": list(MOTORS)},
                "type": {"type": "string", "enum": ["wave", "pulse", "climb", "constant"]},
                "high": {"type": "integer", "minimum": 0, "maximum": 100},
                "low": {"type": "integer", "minimum": 0, "maximum": 100},
                "duration": {"type": "integer", "minimum": 1, "maximum": 3600},
            },
            "required": ["motor", "type", "high", "duration"],
        },
    },
    {
        "name": "toy_stop",
        "description": "立即停止玩具所有马达 (吮吸/震动/电流) 并取消所有节奏。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_status",
        "description": "查询玩具当前状态 (哪个马达、强度、正在播放的节奏)。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "toy_history",
        "description": "查看最近的命令历史 (调试用)。limit 默认 5, 最多 20。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        },
    },
    {
        "name": "toy_speak",
        "description": "用声音说话 (免费 edge-tts 中文语音合成, 会在这台设备上播放出来)。voice 可选: zh-CN-YunxiNeural(清朗男声) / zh-CN-XiaoxiaoNeural(自然女声) / zh-CN-XiaoyiNeural(活泼女声) / zh-CN-YunjianNeural(播音腔) / zh-CN-YunyangNeural(解说)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要念出来的内容"},
                "voice": {"type": "string", "description": "嗓音, 默认 zh-CN-YunxiNeural"},
                "rate": {"type": "string", "description": "语速, 如 +10% / -10%"},
                "pitch": {"type": "string", "description": "音调, 如 +5Hz"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "toy_voices",
        "description": "列出可用的免费中文嗓音。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_tool(name, args):
    args = args or {}
    if name == "toy_suction":
        v = int(args.get("intensity", 0))
        set_motor("suction", v)
        return "✅ 吮吸马达已设到 %d%%" % v if v else "✅ 吮吸马达已停止"
    if name == "toy_vibration":
        v = int(args.get("intensity", 0))
        set_motor("vibration", v)
        return "✅ 震动马达已设到 %d%%" % v if v else "✅ 震动马达已停止"
    if name == "toy_electric":
        v = int(args.get("intensity", 0))
        set_motor("electric", v)
        return "✅ 电流马达已设到 %d%%" % v if v else "✅ 电流马达已停止"
    if name == "toy_pattern":
        motor = args.get("motor", "vibration")
        ptype = args.get("type", "wave")
        high = int(args.get("high", 60))
        low = int(args.get("low", 10))
        dur = int(args.get("duration", 30))
        set_pattern(motor, ptype, high, low, dur)
        return "✅ %s马达开始播放 %s 节奏 (强度 %d-%d, 持续 %d 秒)" % (
            MOTOR_CN.get(motor, motor), ptype, low, high, dur)
    if name == "toy_stop":
        stop_all()
        return "✅ 所有马达已停止"
    if name == "toy_status":
        st = read_state()
        if st.get("cmd") == "stop":
            return "⏹️ 玩具当前所有马达已停止"
        pats = st.get("patterns") or {}
        lines = ["▶️ 玩具当前状态:"]
        lines.append("   马达: %s (%s)" % (MOTOR_CN.get(st.get("motor"), st.get("motor")), st.get("motor")))
        lines.append("   强度: %s%%" % st.get("intensity"))
        if pats:
            for m, p in pats.items():
                lines.append("   节奏: %s = %s (%d-%d, %ds)" % (
                    m, p.get("type"), p.get("low"), p.get("high"), p.get("duration")))
        return "\n".join(lines)
    if name == "toy_history":
        limit = max(1, min(20, int(args.get("limit", 5))))
        hist = (read_state().get("history") or [])[-limit:]
        if not hist:
            return "暂无历史"
        out = ["📜 最近命令:"]
        for h in hist:
            out.append("   - %s %s %s%%" % (
                time.strftime("%H:%M:%S", time.localtime(h["ts"] / 1000)),
                MOTOR_CN.get(h.get("motor"), h.get("motor")),
                h.get("intensity"),
            ))
        return "\n".join(out)
    if name == "toy_speak":
        text = args.get("text", "")
        voice = args.get("voice") or DEFAULT_VOICE
        rate = args.get("rate") or "+0%"
        pitch = args.get("pitch") or "+0Hz"
        path, size, played = do_speak(text, voice, rate, pitch)
        return "🔊 已用 %s 合成并播放 (%d KB, %s)。音频: %s" % (
            voice, size // 1024, "已播放" if played else "已生成但本机无播放器", path)
    if name == "toy_voices":
        if not TTS_OK:
            return "❌ TTS 模块不可用"
        lines = ["🎙️ 可用嗓音 (edge-tts 免费):"]
        for v in _tts.list_voices():
            lines.append("   %s  %s (%s) - %s" % (v["id"], v["name"], v["gender"], v["note"]))
        return "\n".join(lines)
    raise ValueError("未知工具: " + str(name))


def new_session():
    sid = "toy-lite-" + secrets.token_hex(8)
    with _lock:
        _sessions[sid] = {"created": time.time()}
    return sid


def handle_mcp(req, sid):
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in SUPPORTED_PROTOOLS else SUPPORTED_PROTOOLS[0]
        new_sid = new_session()
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": ver,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "toy-lite", "version": "5.0.0"},
            },
        }, new_sid

    if method in ("notifications/initialized", "initialized"):
        return None, None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}, None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}, None
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = call_tool(name, args)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:
            result = {"content": [{"type": "text", "text": "❌ %s" % e}], "isError": True}
        return {"jsonrpc": "2.0", "id": rid, "result": result}, None

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resources": []}}, None
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resourceTemplates": []}}, None
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}}, None
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}, None
    if method == "completion/complete":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"completion": {"values": [], "hasMore": False}}}, None
    if method in ("notifications/cancelled", "notifications/progress", "notifications/roots/list_changed"):
        return None, None

    if rid is None:
        return None, None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": "Method not found: " + str(method)}}, None


def handle_mcp_batch(reqs, sid):
    out = []
    new_sid = None
    for r in reqs:
        try:
            resp, s = handle_mcp(r, sid)
            if s:
                new_sid = s
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": r.get("id"),
                    "error": {"code": -32603, "message": "Internal error: %s" % e}}
        if resp is not None:
            out.append(resp)
    return (out or None), new_sid


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ToyLite/5.0"
    protocol_version = "HTTP/1.1"
    timeout = 60
    disable_nagle_algorithm = True

    def log_message(self, fmt, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id, Mcp-Protocol-Version")

    def _auth_ok(self):
        if not TOKEN:
            return True
        key = self.headers.get("X-API-Key") or ""
        if not key:
            key = (self.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        return key == TOKEN

    def _proto_version(self):
        v = self.headers.get("MCP-Protocol-Version")
        return v if v in SUPPORTED_PROTOOLS else None

    def _json(self, obj, code=200, extra=None, sid=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        if sid:
            self.send_header("Mcp-Session-Id", sid)
        pv = self._proto_version()
        if pv:
            self.send_header("MCP-Protocol-Version", pv)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, text):
        data = text.encode("utf-8")
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def _sse_headers(self, sid=None):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        if sid:
            self.send_header("Mcp-Session-Id", sid)
        self.end_headers()

    def _end_chunk(self):
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if path.startswith("/mcp"):
            sid = self.headers.get("Mcp-Session-Id")
            if sid:
                with _lock:
                    _sessions.pop(sid, None)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        self._json({"error": "not found", "path": path}, 404)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/health"):
            self._json({"ok": True, "service": "toy-lite", "version": "5.0.0",
                        "tts": TTS_OK, "ts": int(time.time() * 1000)})
            return

        if path == "/state":
            if not self._auth_ok():
                self._json({"error": "需要 X-API-Key"}, 401)
                return
            self._json(read_state())
            return

        if path == "/relay":
            fp = os.path.join(ROOT, "relay.html")
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    self._html(f.read())
            except Exception as e:
                self._html("<h1>relay.html 找不到</h1><p>%s</p>" % e, 500)
            return

        if path == "/tts.mp3":
            try:
                with open(LAST_AUDIO, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(data)))
                self._cors()
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self._json({"error": "no audio"}, 404)
            return

        if path.startswith("/mcp"):
            sid = self.headers.get("Mcp-Session-Id")
            self._sse_headers(sid)
            try:
                self._chunk(": connected\n\n")
                while True:
                    self._chunk(": ping\n\n")
                    time.sleep(SSE_IDLE)
            except Exception:
                pass
            finally:
                self._end_chunk()
            return

        if path == "/stream":
            self._sse_headers()
            q = queue.Queue(maxsize=200)
            with _lock:
                _subs.append(q)
            try:
                self._chunk("data: %s\n\n" % json.dumps(read_state(), ensure_ascii=False))
                while True:
                    try:
                        st = q.get(timeout=SSE_IDLE)
                        data = "data: %s\n\n" % json.dumps(st, ensure_ascii=False)
                    except queue.Empty:
                        data = ": ping\n\n"
                    self._chunk(data)
            except Exception:
                pass
            finally:
                with _lock:
                    if q in _subs:
                        _subs.remove(q)
                self._end_chunk()
            return

        self._json({"error": "not found", "path": path}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        raw = self.rfile.read(n) if n else b""

        if path.startswith("/mcp"):
            if not self._auth_ok():
                self._json({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32001, "message": "需要 X-API-Key 请求头"}}, 401)
                return
            sid = self.headers.get("Mcp-Session-Id")
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._json({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": "Parse error: %s" % e}}, 400, sid=sid)
                return

            if isinstance(req, list):
                resp, new_sid = handle_mcp_batch(req, sid)
            else:
                try:
                    resp, new_sid = handle_mcp(req, sid)
                except Exception as e:
                    resp = {"jsonrpc": "2.0", "id": req.get("id"),
                            "error": {"code": -32603, "message": "Internal error: %s" % e}}
                    new_sid = None

            out_sid = new_sid or sid

            if resp is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self._cors()
                if out_sid:
                    self.send_header("Mcp-Session-Id", out_sid)
                self.end_headers()
                return

            accept = (self.headers.get("Accept") or "").lower()
            want_sse = ("text/event-stream" in accept and "application/json" not in accept)
            if want_sse:
                self._sse_headers(out_sid)
                self._chunk("event: message\ndata: %s\n\n" % json.dumps(resp, ensure_ascii=False))
                self._end_chunk()
            else:
                self._json(resp, sid=out_sid)
            return

        if path.startswith("/toy/"):
            if not self._auth_ok():
                self._json({"ok": False, "error": "需要 X-API-Key"}, 401)
                return
            action = path.split("/")[-1]
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                body = {}
            try:
                if action == "stop":
                    st = stop_all()
                elif action in MOTORS:
                    st = set_motor(action, body.get("intensity", body.get("level", 0)))
                elif action == "status":
                    st = read_state()
                elif action == "speak":
                    path_, size, played = do_speak(
                        body.get("text", ""),
                        body.get("voice") or DEFAULT_VOICE,
                        body.get("rate") or "+0%",
                        body.get("pitch") or "+0Hz")
                    self._json({"ok": True, "bytes": size, "played": played, "file": path_})
                    return
                elif action == "voices":
                    self._json({"ok": True, "voices": _tts.list_voices() if TTS_OK else []})
                    return
                else:
                    self._json({"error": "unknown action"}, 404)
                    return
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
                return
            self._json({"ok": True, "state": st})
            return

        self._json({"error": "not found", "path": path}, 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 256

    def get_request(self):
        sock, addr = self.socket.accept()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
        return sock, addr


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


def main():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    if not os.path.exists(STATE_PATH):
        write_state(default_state())
    srv = Server((HOST, PORT), Handler)
    ip = local_ip()
    print("=" * 52, flush=True)
    print("  Toy Lite v5 · 玩具中继 + MCP + 免费 TTS", flush=True)
    print("=" * 52, flush=True)
    print("  本机控制页: http://127.0.0.1:%d/relay/" % PORT, flush=True)
    if HOST in ("0.0.0.0", "::"):
        print("  手机连这个: http://%s:%d/mcp/" % (ip or "<你的电脑IP>", PORT), flush=True)
        print("  (手机和电脑要在同一个 Wi-Fi)", flush=True)
    else:
        print("  MCP       : http://127.0.0.1:%d/mcp/" % PORT, flush=True)
    print("  TTS       : %s" % ("可用 ✓" if TTS_OK else "不可用 (缺 edge_tts_lite.py)"), flush=True)
    if TOKEN:
        print("  访问口令  : X-API-Key: %s" % TOKEN, flush=True)
    elif HOST in ("0.0.0.0", "::"):
        print("  ⚠️  未设口令, 同 Wi-Fi 下其他设备也能控制玩具", flush=True)
    print("  队列      : %d   keepalive: %ds" % (srv.request_queue_size, Handler.timeout), flush=True)
    print("  按 Ctrl+C 停止", flush=True)
    print("=" * 52, flush=True)
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n已停止", flush=True)


if __name__ == "__main__":
    main()
