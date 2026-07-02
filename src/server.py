"""consult-cockpit — worker × reader 3-lane observation cockpit.

One process, bare python3, stdlib ThreadingHTTPServer + Server-Sent Events; no
web framework. The chatgpt-web scripts (nav/ask/cdp, stdlib only) are put on
sys.path when present — they power the scrape reader and are OPTIONAL.

Lanes:
  left   = reader: ChatGPT mirror (the real signed-in tab, read over CDP);
           disabled cleanly when chatgpt-web is absent
  middle = fetch traffic (what files the models are reading)  <- the star
  right  = worker free-form chat (any OpenAI-compatible endpoint, streamed)

CDP tab is a single shared resource: ALL ws access is serialized onto one
"tab controller" thread (command queue). The worker lane never touches CDP,
so it runs on request threads concurrently.

Context invariant (the whole point): repo file bodies (run_commands output) go
ONLY to the reader tab and to the middle lane as command names + byte counts —
never into the worker's history. /forward ships only the reader's final answer,
capped.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- path bridge: only the chatgpt-web scripts (stdlib-only, optional). No
#     venv — the cockpit reads the .env itself (env.py) and talks to the LLM
#     over stdlib urllib, so it runs under a bare python3 anywhere. ------------
HERE = os.path.dirname(os.path.abspath(__file__))
# scrape reader scripts: $COCKPIT_SCRIPTS -> vendored <repo>/scrape -> the
# original chatgpt-web skill location (dev machines).
_VENDORED_SCRAPE = os.path.join(os.path.dirname(HERE), "scrape")
SCRIPTS = (os.environ.get("COCKPIT_SCRIPTS")
           or (_VENDORED_SCRAPE if os.path.isdir(_VENDORED_SCRAPE) else None)
           or os.path.expanduser("~/.claude/skills/chatgpt-web/scripts"))
for p in (HERE, SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

# nav (chatgpt-web's CDP layer) is OPTIONAL: without it the reader/scrape lane
# is disabled but the worker lane and the UI run fine. Catch ImportError only —
# a real bug inside nav should still crash loudly.
try:
    import nav  # noqa: E402  (connect/get_state/find_fetch/send_message/wait_complete)
    _NAV_ERR = ""
except ImportError as e:
    nav = None
    _NAV_ERR = repr(e)
    print(f"[cockpit] reader lane disabled: {_NAV_ERR}", file=sys.stderr, flush=True)

import env as cockpit_env  # noqa: E402
import repo_fetch  # noqa: E402  (cockpit-owned fork of nav's pure repo layer)
from llm_client import stream_chat, resolve_lane  # noqa: E402

PORT = int(os.environ.get("COCKPIT_PORT", "8079"))
DEFAULT_REPO = os.environ.get("COCKPIT_REPO") or os.getcwd()
FORWARD_CAP = 8 * 1024        # max reader answer bytes handed to the worker
MAX_CONSULT_ROUNDS = 8
WORKER_EXPLORE_ROUNDS = 4     # keep it snappy: the worker explores locally in few rounds

_FENCE_RE = re.compile(r"```([\w-]*)\s*\n(.*?)```", re.DOTALL)


def parse_fetch_text(text: str):
    """Extract fetch commands from a raw LLM reply (the worker has no DOM to read).
    Prefer a fenced ```fetch block; else any fenced block that is all commands;
    else scan for bare READ/GREP/LS/TREE lines. run_commands ignores non-command
    lines anyway, so a loose match is safe."""
    text = text or ""
    for lang, body in _FENCE_RE.findall(text):
        lines = [l for l in body.splitlines() if l.strip()]
        if not lines:
            continue
        if lang.lower() == "fetch":
            return lines
        if all(repo_fetch.CMD_RE.match(l) for l in lines):
            return lines
    bare = [l for l in text.splitlines() if repo_fetch.CMD_RE.match(l)]
    return bare or None

# all turns (user + assistant) of the current ChatGPT conversation, for the mirror
MIRROR_JS = (
    "(()=>{const a=[...document.querySelectorAll('[data-message-author-role]')];"
    "return JSON.stringify(a.map(n=>({role:n.getAttribute('data-message-author-role'),"
    "text:n.innerText||''})));})()"
)

# =============================================================================
# SSE hub
# =============================================================================
_subs: list[queue.Queue] = []
_subs_lock = threading.Lock()
_last_status: dict = ({"event": "status", "reader": "disabled", "detail": _NAV_ERR}
                      if nav is None else
                      {"event": "status", "reader": "connecting"})


def broadcast(event: str, data: dict) -> None:
    msg = {"event": event, **data}
    if event == "status":
        global _last_status
        _last_status = msg
    with _subs_lock:
        dead = []
        for q in _subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subs.remove(q)


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _subs_lock:
        _subs.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _subs_lock:
        if q in _subs:
            _subs.remove(q)


# =============================================================================
# Shared state (worker history + last reader answer)
# =============================================================================
_state_lock = threading.Lock()
_worker_history: list[dict] = []
_last_reader_answer: str = ""
_worker_busy = False


def worker_snapshot() -> list[dict]:
    with _state_lock:
        return list(_worker_history)


# =============================================================================
# Tab controller — the ONLY thread that touches the CDP ws
# =============================================================================
_cmd_q: queue.Queue = queue.Queue()   # commands: {"type": "consult", "repo":..., "question":...}


class TabController(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="tab-controller")
        self.ws = None
        self.target = None
        self._last_connect_try = 0.0

    def _ensure_connected(self) -> bool:
        if nav is None:  # scrape lane disabled; thread shouldn't even be running
            return False
        if self.ws is not None:
            return True
        if time.time() - self._last_connect_try < 5:
            return False
        self._last_connect_try = time.time()
        try:
            self.ws, self.target = nav.connect()
            broadcast("status", {"reader": "connected"})
            return True
        except SystemExit as e:
            broadcast("status", {"reader": "disconnected", "detail": str(e)})
            self.ws = None
            return False
        except Exception as e:  # noqa: BLE001
            broadcast("status", {"reader": "disconnected", "detail": repr(e)})
            self.ws = None
            return False

    def _emit_mirror(self) -> None:
        if self.ws is None:
            return
        try:
            raw = self.ws.evaluate(MIRROR_JS)
            turns = json.loads(raw) if isinstance(raw, str) else []
            broadcast("mirror", {"turns": turns})
        except Exception:  # noqa: BLE001
            # a dead ws surfaces here; drop it so we reconnect next tick
            self.ws = None

    def _run_consult(self, root: str, question: str) -> None:
        global _last_reader_answer
        if not self._ensure_connected():
            broadcast("consult", {"status": "error",
                                  "detail": "reader tab not reachable"})
            return
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            broadcast("consult", {"status": "error", "detail": f"not a dir: {root}"})
            return
        broadcast("consult", {"status": "start", "repo": os.path.basename(root)})
        try:
            self.ws.evaluate(nav.NEWCHAT_JS)
            time.sleep(1.5)
            base = nav.get_state(self.ws).get("count", 0)
            nav.send_message(self.ws, repo_fetch.build_brief(root, question))
            broadcast("consult", {"status": "briefed"})
            cur = base
            for i in range(MAX_CONSULT_ROUNDS):
                self.ws, st = nav.wait_complete(self.ws, self.target, after_count=cur)
                cur = st.get("count", cur)
                self._emit_mirror()
                cmds = nav.find_fetch(st.get("blocks", []))
                if not cmds:
                    answer = st.get("text", "").strip()
                    with _state_lock:
                        _last_reader_answer = answer
                    broadcast("answer", {"text": answer})
                    broadcast("consult", {"status": "done", "rounds": i})
                    return
                names = " | ".join(l.strip() for l in cmds if l.strip())[:300]
                broadcast("fetch", {"names": names, "round": i + 1, "who": "reader"})
                reply = repo_fetch.run_commands(root, cmds)   # repo bodies -> reader only
                nav.send_message(self.ws, reply)
                broadcast("served", {"bytes": len(reply), "round": i + 1, "who": "reader"})
                time.sleep(2)
            # ran out of rounds
            answer = nav.get_state(self.ws).get("text", "").strip()
            with _state_lock:
                _last_reader_answer = answer
            broadcast("answer", {"text": answer, "note": "max_rounds"})
            broadcast("consult", {"status": "done", "rounds": MAX_CONSULT_ROUNDS})
        except Exception as e:  # noqa: BLE001
            broadcast("consult", {"status": "error", "detail": repr(e)})
            self.ws = None

    def run(self) -> None:
        self._ensure_connected()
        while True:
            try:
                cmd = _cmd_q.get(timeout=1.5)
            except queue.Empty:
                # idle: keep the left pane live and heal a dropped connection
                if self._ensure_connected():
                    self._emit_mirror()
                continue
            try:
                if cmd.get("type") == "consult":
                    self._run_consult(cmd["repo"], cmd["question"])
            except Exception:  # noqa: BLE001
                traceback.print_exc()


CONTROLLER = TabController()


# =============================================================================
# API reader consult (no CDP) — when READER_LLM_* is configured, the reader is
# a plain API endpoint: same fetch protocol as the scrape consult, but over
# stream_chat(lane="reader"). Takes precedence over the scrape reader.
# =============================================================================
_reader_busy = False


def _api_reader_cfg():
    """LaneConfig for the API reader, or None (unconfigured/misconfigured)."""
    try:
        return resolve_lane("reader")
    except Exception:  # noqa: BLE001
        return None


def _mirror_from(transient) -> None:
    """Render the API reader's transient conversation into the left pane,
    reusing the scrape-mirror event shape."""
    turns = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
              "text": m["content"]} for m in transient]
    broadcast("mirror", {"turns": turns})


def _run_api_consult(repo: str, question: str) -> None:
    """Consult over the API reader. Same context invariant as the scrape path:
    repo bodies go only into the reader's transient context and the middle lane
    (names + byte counts) — never into the worker history."""
    global _last_reader_answer, _reader_busy
    root = os.path.abspath(os.path.expanduser(repo))
    with _state_lock:
        if _reader_busy:
            broadcast("consult", {"status": "busy"})
            return
        _reader_busy = True
    try:
        if not os.path.isdir(root):
            broadcast("consult", {"status": "error", "detail": f"not a dir: {root}"})
            return
        broadcast("consult", {"status": "start", "repo": os.path.basename(root)})
        transient = [{"role": "user", "content": repo_fetch.build_brief(root, question)}]
        broadcast("consult", {"status": "briefed"})
        answer = ""
        for i in range(MAX_CONSULT_ROUNDS):
            full = "".join(stream_chat(transient, lane="reader", max_tokens=2048))
            transient.append({"role": "assistant", "content": full})
            _mirror_from(transient)
            cmds = parse_fetch_text(full)
            if not cmds:
                answer = full.strip()
                break
            names = " | ".join(c.strip() for c in cmds if c.strip())[:300]
            broadcast("fetch", {"names": names, "round": i + 1, "who": "reader"})
            served = repo_fetch.run_commands(root, cmds)  # repo bodies -> reader only
            broadcast("served", {"bytes": len(served), "round": i + 1, "who": "reader"})
            transient.append({"role": "user", "content": served})
        else:
            transient.append({"role": "user", "content":
                              "Stop fetching. Give your best final answer now "
                              "from what you've read."})
            answer = "".join(stream_chat(transient, lane="reader",
                                         max_tokens=2048)).strip()
            transient.append({"role": "assistant", "content": answer})
            _mirror_from(transient)
        with _state_lock:
            _last_reader_answer = answer
        broadcast("answer", {"text": answer})
        broadcast("consult", {"status": "done"})
    except Exception as e:  # noqa: BLE001
        broadcast("consult", {"status": "error", "detail": repr(e)})
    finally:
        with _state_lock:
            _reader_busy = False


# =============================================================================
# Worker chat (no CDP) — runs on its own thread, streams over SSE
# =============================================================================
# Startup snapshot: an API reader (READER_LLM_*) takes precedence over the
# scrape reader — one reader at a time keeps status/mirror ownership simple.
_API_READER0 = _api_reader_cfg()
if _API_READER0:
    _last_status = {"event": "status", "reader": "api",
                    "detail": f"{_API_READER0.provider}/{_API_READER0.model}"}


def _run_worker(user_msg: str) -> None:
    global _worker_busy
    with _state_lock:
        if _worker_busy:
            broadcast("worker", {"status": "busy"})
            return
        _worker_busy = True
        _worker_history.append({"role": "user", "content": user_msg})
        history = list(_worker_history)
    broadcast("worker", {"status": "start", "role": "user", "content": user_msg})
    acc = []
    try:
        for tok in stream_chat(history):
            acc.append(tok)
            broadcast("worker", {"status": "delta", "content": tok})
        reply = "".join(acc)
        with _state_lock:
            _worker_history.append({"role": "assistant", "content": reply})
        broadcast("worker", {"status": "done", "content": reply})
    except Exception as e:  # noqa: BLE001
        broadcast("worker", {"status": "error", "detail": repr(e)})
    finally:
        with _state_lock:
            _worker_busy = False


def _run_worker_explore(repo: str, task: str) -> None:
    """The worker navigates the repo LOCALLY via the fetch protocol (no browser,
    no reader). Repo bodies enter only a TRANSIENT sub-context; only the final
    answer joins the persistent worker history, so follow-up chat stays lean.
    This is the deliberate exception to the 'repo never enters the worker'
    invariant: the user explicitly asked the worker to read locally. Kept snappy
    via a low round cap + multi-file fetches (the brief allows <=8 items/turn)."""
    global _worker_busy
    root = os.path.abspath(os.path.expanduser(repo))
    with _state_lock:
        if _worker_busy:
            broadcast("worker", {"status": "busy"})
            return
        _worker_busy = True
        _worker_history.append({"role": "user", "content": task})
    broadcast("worker", {"status": "start", "role": "user", "content": task})
    if not os.path.isdir(root):
        broadcast("worker", {"status": "error", "detail": f"not a dir: {root}"})
        with _state_lock:
            _worker_busy = False
        return
    broadcast("explore", {"status": "start", "repo": os.path.basename(root)})
    transient = [{"role": "user", "content": repo_fetch.build_brief(root, task)}]
    answer = ""
    try:
        for i in range(WORKER_EXPLORE_ROUNDS):
            broadcast("worker", {"status": "exploring", "round": i + 1})
            full = "".join(stream_chat(transient, max_tokens=1024))
            cmds = parse_fetch_text(full)
            if not cmds:
                answer = full.strip()
                break
            names = " | ".join(c.strip() for c in cmds if c.strip())[:300]
            broadcast("fetch", {"names": names, "round": i + 1, "who": "worker"})
            served = repo_fetch.run_commands(root, cmds)  # repo bodies -> transient only
            broadcast("served", {"bytes": len(served), "round": i + 1, "who": "worker"})
            transient.append({"role": "assistant", "content": full})
            transient.append({"role": "user", "content": served})
        else:
            transient.append({"role": "user", "content":
                              "Stop fetching. Give your best final answer now "
                              "from what you've read."})
            answer = "".join(stream_chat(transient, max_tokens=1024)).strip()
        with _state_lock:
            _worker_history.append({"role": "assistant", "content": answer})
        broadcast("worker", {"status": "msg", "role": "assistant", "content": answer})
        broadcast("explore", {"status": "done"})
    except Exception as e:  # noqa: BLE001
        broadcast("worker", {"status": "error", "detail": repr(e)})
    finally:
        with _state_lock:
            _worker_busy = False


def _forward_to_worker() -> dict:
    """Human handoff: inject ONLY the reader's last answer (capped) into the
    worker history as context. Repo file bodies never travel this path."""
    with _state_lock:
        ans = _last_reader_answer
    if not ans:
        return {"ok": False, "detail": "no reader answer yet"}
    capped = ans[:FORWARD_CAP]
    truncated = len(ans) > FORWARD_CAP
    content = ("[Forwarded: the reader's repo analysis]\n\n" + capped +
               ("\n\n[...truncated]" if truncated else ""))
    with _state_lock:
        _worker_history.append({"role": "user", "content": content})
    broadcast("worker", {"status": "forwarded", "role": "user", "content": content})
    return {"ok": True, "bytes": len(capped), "truncated": truncated}


# =============================================================================
# HTTP
# =============================================================================
INDEX = os.path.join(HERE, "static", "index.html")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    # ---- GET ----
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            try:
                with open(INDEX, "rb") as f:
                    body = f.read()
            except OSError:
                body = b"<h1>index.html missing</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/state":
            wcfg = None
            try:
                wcfg = resolve_lane("worker")
            except Exception:  # noqa: BLE001  (bad config must not kill /state)
                pass
            if _API_READER0 is not None:
                rmode, rmodel = "api", _API_READER0.model
            elif nav is not None:
                rmode, rmodel = "chatgpt-web", ""
            else:
                rmode, rmodel = "disabled", ""
            with _state_lock:
                self._json(200, {"worker": list(_worker_history),
                                 "has_answer": bool(_last_reader_answer),
                                 "last_answer": _last_reader_answer,
                                 "default_repo": DEFAULT_REPO,
                                 "worker_model": wcfg.model if wcfg else "",
                                 "reader_mode": rmode,
                                 "reader_model": rmodel})
        elif self.path == "/events":
            self._sse()
        else:
            self._json(404, {"error": "not found"})

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = subscribe()
        # replay current worker history so a fresh page isn't blank
        try:
            self.wfile.write(b": connected\n\n")
            self._sse_write(_last_status)  # current reader connection state
            for m in worker_snapshot():
                self._sse_write({"event": "worker", "status": "history", **m})
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # heartbeat
                    self.wfile.flush()
                    continue
                self._sse_write(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            unsubscribe(q)

    def _sse_write(self, msg: dict):
        self.wfile.write(("data: " + json.dumps(msg) + "\n\n").encode())
        self.wfile.flush()

    # ---- POST ----
    def do_POST(self):
        body = self._read_json()
        if self.path == "/consult":
            repo = body.get("repo") or DEFAULT_REPO
            question = (body.get("question") or "").strip()
            if not question:
                return self._json(400, {"error": "question required"})
            if _API_READER0 is not None:            # API reader (no browser)
                threading.Thread(target=_run_api_consult, args=(repo, question),
                                 daemon=True).start()
                return self._json(202, {"queued": True, "repo": repo,
                                        "reader": "api"})
            if nav is None:
                return self._json(503, {"error": "reader lane disabled",
                                        "detail": _NAV_ERR})
            _cmd_q.put({"type": "consult", "repo": repo, "question": question})
            self._json(202, {"queued": True, "repo": repo})
        elif self.path == "/worker":
            msg = (body.get("message") or "").strip()
            if not msg:
                return self._json(400, {"error": "message required"})
            threading.Thread(target=_run_worker, args=(msg,), daemon=True).start()
            self._json(202, {"queued": True})
        elif self.path == "/worker-explore":
            task = (body.get("task") or "").strip()
            repo = body.get("repo") or DEFAULT_REPO
            if not task:
                return self._json(400, {"error": "task required"})
            threading.Thread(target=_run_worker_explore, args=(repo, task),
                             daemon=True).start()
            self._json(202, {"queued": True, "repo": repo})
        elif self.path == "/forward":
            self._json(200, _forward_to_worker())
        else:
            self._json(404, {"error": "not found"})


def doctor() -> int:
    """Validate the four prerequisites; print pass/fail; exit non-zero on any
    critical failure. Run before first use on a new machine."""
    import urllib.request as _u
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        ok = ok and good
        print(f"  [{'ok ' if good else 'FAIL'}] {label}"
              + (f" — {detail}" if detail else ""))

    print("consult-cockpit doctor")
    print(f"  python {sys.version.split()[0]}")

    if nav is None:
        # scrape lane disabled: informational, not a failure — worker-only mode
        print(f"  [off ] chatgpt-web scripts — not importable ({SCRIPTS})")
        print("  [off ] reader lane — disabled (worker-only mode)")
    else:
        line(os.path.isdir(SCRIPTS), "chatgpt-web scripts", SCRIPTS)
        line("connect" in dir(nav) and "send_message" in dir(nav),
             "nav/ask/cdp import", "importable")

    src = cockpit_env.env_source()
    line(bool(src), ".env found", src or "none of: $COCKPIT_ENV, src/.env")
    miss = cockpit_env.missing_required()
    wcfg = None
    if not miss:
        try:
            wcfg = resolve_lane("worker")
        except Exception as e:  # noqa: BLE001
            miss = [repr(e)[:60]]
    line(not miss, "worker lane config", "missing: " + ",".join(miss) if miss else
         f"{wcfg.provider}/{wcfg.model} (key: {wcfg.key_source})")
    try:
        rcfg = resolve_lane("reader")
    except Exception as e:  # noqa: BLE001
        rcfg = None
        print(f"  [!!  ] reader API lane — misconfigured: {repr(e)[:60]}")
    if rcfg:
        print(f"  [ok ] reader API lane — {rcfg.provider}/{rcfg.model} "
              f"(key: {rcfg.key_source}) — consult uses this, not the scrape lane")
    else:
        print("  [off ] reader API lane — not configured (scrape lane is the "
              "reader when chatgpt-web is present)")

    try:
        with _u.urlopen("http://127.0.0.1:9333/json/version", timeout=3):
            chrome = True
    except Exception:  # noqa: BLE001
        chrome = False
    if nav is None:
        print(f"  [off ] dedicated Chrome :9333 — "
              f"{'reachable but unused' if chrome else 'down'} (lane disabled)")
    elif _API_READER0 is not None:
        # the API reader owns consult; Chrome is unused, so never a failure
        print(f"  [off ] dedicated Chrome :9333 — "
              f"{'reachable but unused' if chrome else 'down'} (API reader active)")
    else:
        line(chrome, "dedicated Chrome :9333", "reachable" if chrome else
             "down — start via chatgpt-web (ask.py up) and sign in")

    wlabel = f"worker endpoint ({wcfg.model})" if wcfg else "worker endpoint"
    if not miss:
        try:
            toks = list(stream_chat([{"role": "user", "content": "ping"}],
                                    max_tokens=4, timeout=30))
            line(bool(toks), wlabel, "streamed a token")
        except Exception as e:  # noqa: BLE001
            line(False, wlabel, repr(e)[:80])
    else:
        line(False, wlabel, "skipped (config missing)")

    print("  =>", "ALL GOOD" if ok else "problems above — fix before launch")
    return 0 if ok else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("doctor", "--doctor"):
        sys.exit(doctor())
    print(f"[cockpit] repo → {DEFAULT_REPO}", flush=True)
    if _API_READER0 is not None:
        print(f"[cockpit] reader = API ({_API_READER0.provider}/"
              f"{_API_READER0.model}) — scrape controller not started", flush=True)
    elif nav is not None:
        CONTROLLER.start()
    else:
        print("[cockpit] reader lane disabled — worker-only mode", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[cockpit] http://127.0.0.1:{PORT}  (Ctrl-C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[cockpit] bye", flush=True)


if __name__ == "__main__":
    main()
