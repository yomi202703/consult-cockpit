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
CHAT_REPLY = "MOCK-CHAT: hello from the mock."


def pick_reply(messages):
    text = "\n".join(m.get("content", "") for m in messages)
    if "Here are the requested contents" in text:
        return FINAL_REPLY
    if "fenced code block tagged" in text:      # the fetch-protocol brief
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
