"""Deterministic OpenAI-compatible mock endpoint for cockpit testing.

    python3 tests/mock_llm.py [port]        # default 8199

Speaks just enough of /chat/completions (stream=True) to drive both lanes:
- If the conversation contains a fetch brief and no served contents yet,
  reply with ONE fetch block (READ README.md) — exercises a consult/explore round.
- If served contents have arrived, reply with a fixed final answer.
- Plain chat otherwise → fixed echo-style reply.

Instant, no network, no key, same output every run. Point both lanes at it:
    WORKER_LLM_BASE_URL=http://127.0.0.1:8199/v1 (MODEL=mock)
    READER_LLM_BASE_URL=http://127.0.0.1:8199/v1 (MODEL=mock)
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8199

FETCH_REPLY = "I'll look at the repo first.\n```fetch\nREAD README.md\n```"
FINAL_REPLY = "MOCK-ANSWER: read the file; everything checks out."
CONSULT_REPLY = "```consult\nWhat is in the readme?\n```"
SYNTH_REPLY = "MOCK-SYNTH: per the reader, the readme checks out."
CHAT_REPLY = "MOCK-CHAT: hello from the mock."


def pick_reply(messages):
    """Deterministic routing off the LAST non-system message only. A tool result
    (reader answer / fetched contents / explore brief) always arrives as the most
    recent message, and a fresh user turn is likewise the last message — so the
    last message alone decides the reply. Scanning the whole conversation would
    misroute, because the persistent history accumulates across turns/tests and
    an old 'please ask the reader' would hijack a later plain chat. System
    messages are skipped: the worker's system prompt itself lists the markers."""
    last = ""
    for m in messages:
        if m.get("role") != "system":
            last = m.get("content", "")
    if "[Reader's answer]" in last:
        return SYNTH_REPLY
    if "Here are the requested contents" in last:   # a fetch/explore round served
        return FINAL_REPLY
    if "File tree:" in last:                         # explore brief, pre-serve
        return FETCH_REPLY
    if "please ask the reader" in last:              # -> worker consult block
        return CONSULT_REPLY
    if "inspect the repo" in last:                   # -> worker chat fetch block
        return FETCH_REPLY
    return CHAT_REPLY


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        reply = pick_reply(body.get("messages", []))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(0, len(reply), 12):       # stream in small deltas
            chunk = {"choices": [{"delta": {"content": reply[i:i + 12]}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    print(f"mock LLM on http://127.0.0.1:{PORT}/v1 (deterministic, instant)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
