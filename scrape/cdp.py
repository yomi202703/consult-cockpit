#!/usr/bin/env python3
"""Minimal dependency-free Chrome DevTools Protocol client for chatgpt.com.

Shares ONE dedicated Chrome instance with the gemini-web skill (same debug port
and --user-data-dir), so the two AI surfaces live as two tabs in a single
signed-in browser. Plain Chrome exposes a real debug port — attach over the WS and
drive the renderer directly.
"""
import json, os, socket, base64, struct, urllib.request

PORT = int(os.environ.get("AI_CDP_PORT", os.environ.get("GEMINI_CDP_PORT", "9333")))
CHATGPT_URL = "https://chatgpt.com"


def http_json(path, port=PORT):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5))


def chatgpt_target(port=PORT):
    """Return the CDP page target for the ChatGPT tab, or None if absent."""
    for t in http_json("/json/list", port):
        if t.get("type") == "page" and "chatgpt.com" in (t.get("url") or ""):
            return t
    return None


def any_page(port=PORT):
    for t in http_json("/json/list", port):
        if t.get("type") == "page":
            return t
    return None


def port_alive(port=PORT):
    try:
        http_json("/json/version", port)
        return True
    except Exception:
        return False


def new_tab(url, port=PORT):
    """Open a new tab via the browser-level CDP endpoint.

    Modern Chrome disables the GET /json/new shortcut, so we drive
    Target.createTarget over the browser WebSocket instead.
    """
    bws = http_json("/json/version", port)["webSocketDebuggerUrl"]
    ws = WS(bws)
    ws.cmd("Target.createTarget", {"url": url})


class WS:
    def __init__(self, url):
        assert url.startswith("ws://")
        hostport, path = url[5:].split("/", 1)
        self.path = "/" + path
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {self.path} HTTP/1.1\r\nHost: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(1)
        self._buf = b""
        self._id = 0

    def _send_frame(self, data):
        data = data.encode()
        header = bytearray([0x81])
        ln = len(data); mask = os.urandom(4)
        if ln < 126: header.append(0x80 | ln)
        elif ln < 65536: header.append(0x80 | 126); header += struct.pack(">H", ln)
        else: header.append(0x80 | 127); header += struct.pack(">Q", ln)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_frame(self):
        def rd(n):
            while len(self._buf) < n:
                self._buf += self.sock.recv(4096)
            out, self._buf = self._buf[:n], self._buf[n:]
            return out
        rd(1); b1 = rd(1)[0]
        ln = b1 & 0x7f
        if ln == 126: ln = struct.unpack(">H", rd(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", rd(8))[0]
        return rd(ln).decode("utf-8", "replace")

    def cmd(self, method, params=None):
        self._id += 1
        self._send_frame(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self._recv_frame())
            if m.get("id") == self._id:
                return m

    def evaluate(self, expr, await_promise=True):
        r = self.cmd("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise, "userGesture": True})
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return {"error": str(res["exceptionDetails"])[:300]}
        return res.get("result", {}).get("value")

    def type_text(self, text):
        self.cmd("Input.insertText", {"text": text})

    def key(self, key, code, vk):
        for t in ("keyDown", "keyUp"):
            self.cmd("Input.dispatchKeyEvent",
                     {"type": t, "key": key, "code": code, "windowsVirtualKeyCode": vk})


if __name__ == "__main__":
    print("port alive:", port_alive(), "| chatgpt target:", bool(chatgpt_target()))
