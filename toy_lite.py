"""
toy_lite.py — 零依赖玩具中继 + MCP 服务 (v2)
只用 Python 标准库, 不需要 fastapi / uvicorn / mcp / pydantic。
手机 (Pydroid 3) 上可直接跑。

  python toy_lite.py            # 监听 127.0.0.1:8765
  PORT=9000 python toy_lite.py # 换端口

提供:
  GET  /                 健康信息
  GET  /health           存活探针
  GET  /relay/           中继控制页 (Web Bluetooth)
  GET  /stream           SSE 状态推送 (chunked)
  GET  /state            当前状态
  POST /mcp/             MCP Streamable HTTP 端点
  GET  /mcp/             MCP SSE 流 (server -> client)
  DELETE /mcp/           结束 MCP 会话
  POST /toy/<motor>      HTTP 控制端点 (suction/vibration/electric/stop)
"""
import json
import os
import queue
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "state.json")

MOTORS = ("suction", "vibration", "electric")
MOTOR_CN = {"suction": "吮吸", "vibration": "震动", "electric": "电流"}

# MCP 协议版本: 客户端要哪个我们回哪个 (Kotlin SDK 常要 2025-06-18 / 2025-03-26)
SUPPORTED_PROTOOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

SESSION_ID = "toy-lite-" + secrets.token_hex(8)

_lock = threading.Lock()
_subs = []  # SSE 订阅者队列列表


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
        print("[warn] 写 state 失败:", e)
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


# ---------------- MCP 工具 ----------------
TOOLS = [
    {
        "name": "toy_suction",
        "description": "控制玩具的吮吸马达 (吸力)。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intensity": {"type": "integer", "minimum": 0, "maximum": 100}
            },
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_vibration",
        "description": "控制玩具的震动马达。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intensity": {"type": "integer", "minimum": 0, "maximum": 100}
            },
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_electric",
        "description": "控制玩具的电流刺激马达。intensity 0-100, 0=停止该马达, 100=最大。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intensity": {"type": "integer", "minimum": 0, "maximum": 100}
            },
            "required": ["intensity"],
        },
    },
    {
        "name": "toy_pattern",
        "description": "播放一段节奏 (波形)。type: wave(波浪) / pulse(脉冲) / climb(攀升) / constant(恒定)。high/low 为强度上下限 0-100, duration 为持续秒数。",
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
                lines.append("   节奏: %s = %s (%d-%d, %ds)" % (m, p.get("type"), p.get("low"), p.get("high"), p.get("duration")))
        return "\n".join(lines)
    if name == "toy_history":
        limit = int(args.get("limit", 5))
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
    raise ValueError("未知工具: " + str(name))


def handle_mcp(req):
    """req: 已解析的 JSON-RPC 字典 -> 响应 dict 或 None (通知)"""
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        want = params.get("protocolVersion")
        ver = want if want in SUPPORTED_PROTOOLS else SUPPORTED_PROTOOLS[0]
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": ver,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "toy-lite", "version": "2.0.0"},
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None  # 通知, 不回复

    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = call_tool(name, args)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:
            result = {"content": [{"type": "text", "text": "❌ %s" % e}], "isError": True}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found: " + str(method)}}


def handle_mcp_batch(reqs):
    out = []
    for r in reqs:
        try:
            resp = handle_mcp(r)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": r.get("id"),
                    "error": {"code": -32603, "message": "Internal error: %s" % e}}
        if resp is not None:
            out.append(resp)
    return out or None


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ToyLite/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id, Mcp-Protocol-Version")

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.send_header("Mcp-Session-Id", SESSION_ID)
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
        """写一个 HTTP/1.1 chunk"""
        data = text.encode("utf-8")
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def _sse_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        self.send_header("Mcp-Session-Id", SESSION_ID)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if path.startswith("/mcp"):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        self._json({"error": "not found", "path": path}, 404)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/health"):
            self._json({"ok": True, "service": "toy-lite", "version": "2.0.0",
                        "ts": int(time.time() * 1000)})
            return

        if path == "/state":
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

        # MCP 的 GET 流 (部分客户端会连上来等 server->client 通知)
        if path.startswith("/mcp"):
            self._sse_headers()
            try:
                self._chunk(": connected\n\n")
                q = queue.Queue(maxsize=200)
                with _lock:
                    _subs.append(q)
                while True:
                    try:
                        st = q.get(timeout=15)
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
                try:
                    self.wfile.write(b"0\r\n\r\n")
                except Exception:
                    pass
            return

        # 玩具状态 SSE
        if path == "/stream":
            self._sse_headers()
            q = queue.Queue(maxsize=200)
            with _lock:
                _subs.append(q)
            try:
                self._chunk("data: %s\n\n" % json.dumps(read_state(), ensure_ascii=False))
                while True:
                    try:
                        st = q.get(timeout=15)
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
                try:
                    self.wfile.write(b"0\r\n\r\n")
                except Exception:
                    pass
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
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._json({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": "Parse error: %s" % e}}, 400)
                return

            if isinstance(req, list):
                resp = handle_mcp_batch(req)
            else:
                try:
                    resp = handle_mcp(req)
                except Exception as e:
                    resp = {"jsonrpc": "2.0", "id": req.get("id"),
                            "error": {"code": -32603, "message": "Internal error: %s" % e}}

            if resp is None:
                # 通知: 202 Accepted, 空 body
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self._cors()
                self.send_header("Mcp-Session-Id", SESSION_ID)
                self.end_headers()
                return

            # 内容协商: 客户端只接受 SSE 时用 SSE 包装
            accept = (self.headers.get("Accept") or "").lower()
            want_sse = ("text/event-stream" in accept and "application/json" not in accept)
            if want_sse:
                self._sse_headers()
                self._chunk("event: message\ndata: %s\n\n" % json.dumps(resp, ensure_ascii=False))
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                self._json(resp)
            return

        if path.startswith("/toy/"):
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
                else:
                    self._json({"error": "unknown action"}, 404)
                    return
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
                return
            self._json({"ok": True, "state": st})
            return

        self._json({"error": "not found", "path": path}, 404)


def main():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    if not os.path.exists(STATE_PATH):
        write_state(default_state())
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    print("=" * 46)
    print("  Toy Lite v2 · 零依赖玩具中继 + MCP")
    print("  控制页: http://%s:%d/relay/" % (HOST, PORT))
    print("  MCP   : http://%s:%d/mcp/" % (HOST, PORT))
    print("  Session: %s" % SESSION_ID)
    print("  按 Ctrl+C 停止")
    print("=" * 46)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
