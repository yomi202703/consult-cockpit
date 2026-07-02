#!/usr/bin/env python3
"""Give plain ChatGPT (web, no API) pseudo directory-exploration over a repo.

Human-driven design: ChatGPT is the navigator (decides what to look at), a local
read-only loop is its hands. You seed one brief (repo tree + a fetch protocol +
your task), then chat with ChatGPT normally in the tab. Whenever ChatGPT emits a
`fetch` code block, this watcher runs the read-only commands against the repo and
pastes the results back into the same conversation — so you never copy files by
hand. Edits are NOT applied here; take ChatGPT's diff to pi/Gemma and test it.

Subcommands:
    nav.py consult <repo> "question"    # autonomous: brief + auto-serve fetches,
                                        #   print ChatGPT's final answer (for agents)
    nav.py brief <repo> ["task text"]   # print the initial brief to paste/send
    nav.py serve <repo> [--rounds N]    # watch the tab, auto-answer fetch blocks
    nav.py seed  <repo> ["task text"]   # send the brief into the tab, then exit

Reuses chatgpt-web's Chrome (port 9333, signed-in profile) via cdp.py/ask.py.
"""
import sys, os, re, json, time

HERE = __file__.rsplit("/", 1)[0]
sys.path.insert(0, HERE)
from cdp import WS                                        # noqa: E402
from ask import (ensure_chrome, reload_recover, EDITOR, SEND, STOP,  # noqa: E402
                 ASSISTANT)

# ---- repo reading (read-only, scoped to the repo root) ----------------------

MAX_FILE_LINES = 600        # cap a single READ (use line ranges for more)
MAX_FILE_BYTES = 64 * 1024
MAX_GREP_HITS = 120
MAX_REPLY_BYTES = 40 * 1024  # keep ChatGPT's context from overflowing
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
             "build", ".next", ".cache", "target"}
PROTOCOL = """You are helping me work on a code repository. You cannot touch the \
filesystem; a local read-only agent fetches repo contents for you on request.

When you want to inspect the repo, output EXACTLY ONE fenced code block tagged \
`fetch`, one command per line:
  READ <relpath>            full file (capped)
  READ <relpath> <a>-<b>    only lines a..b
  GREP <regex> [reldir]     search file contents
  LS [reldir]               list a directory
  TREE [reldir]             tree under a directory
Rules: paths are relative to the repo root and must stay inside it; ask only for \
what you need (<= 8 items per turn); prefer line ranges for large files. I will \
reply with the contents. When you are not fetching, just talk normally (no fetch \
block). When you have a fix, give a unified diff or the full updated file. \
Reason and answer in English, even if the task text below is in another language."""


def repo_root(p):
    r = os.path.abspath(os.path.expanduser(p))
    if not os.path.isdir(r):
        sys.exit(f"not a directory: {r}")
    return r


def safe(root, rel):
    """Resolve rel under root; return abs path or None if it escapes the repo."""
    rel = (rel or "").strip().strip("/")
    full = os.path.normpath(os.path.join(root, rel))
    if full == root or full.startswith(root + os.sep):
        return full
    return None


def is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(2048)
    except OSError:
        return True


def list_files(root):
    """git ls-files when available, else a filtered walk. Returns relpaths."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            out.append(rel)
    out.sort()
    return out


def tree_str(root, sub=""):
    base = safe(root, sub) or root
    lines = []
    n = 0
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        depth = dirpath[len(base):].count(os.sep)
        rel = os.path.relpath(dirpath, base)
        lines.append(("  " * depth) + (os.path.basename(dirpath) if rel != "." else ".") + "/")
        for f in sorted(files):
            if f.startswith("."):
                continue
            lines.append(("  " * (depth + 1)) + f)
            n += 1
            if n > 800:
                lines.append("  ... (truncated)")
                return "\n".join(lines)
    return "\n".join(lines)


def do_read(root, rel, rng=None):
    full = safe(root, rel)
    if not full or not os.path.isfile(full):
        return f"(not found: {rel})"
    if is_binary(full):
        return f"(binary file, skipped: {rel})"
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    if rng:
        a, b = rng
        a = max(1, a); b = min(total, b)
        chunk = lines[a - 1:b]
        hdr = f"{rel} (lines {a}-{b} of {total})"
    else:
        chunk = lines[:MAX_FILE_LINES]
        hdr = (f"{rel} (1-{len(chunk)} of {total})"
               if total > MAX_FILE_LINES else f"{rel} ({total} lines)")
    body = "".join(chunk)[:MAX_FILE_BYTES]
    return f"### READ {hdr}\n```\n{body}\n```"


def do_grep(root, pat, sub=""):
    try:
        rx = re.compile(pat)
    except re.error as e:
        return f"### GREP {pat}\n(bad regex: {e})"
    base = safe(root, sub) or root
    hits, n = [], 0
    targets = [base] if os.path.isfile(base) else None
    walkroot = base if os.path.isdir(base) else root
    for dirpath, dirs, files in os.walk(walkroot):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            full = os.path.join(dirpath, f)
            if is_binary(full):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{os.path.relpath(full, root)}:{i}: {line.rstrip()[:200]}")
                            n += 1
                            if n >= MAX_GREP_HITS:
                                hits.append("... (more hits truncated)")
                                return f"### GREP {pat}\n" + "\n".join(hits)
            except OSError:
                pass
        if targets:
            break
    return f"### GREP {pat}\n" + ("\n".join(hits) if hits else "(no matches)")


def do_ls(root, sub=""):
    full = safe(root, sub) or root
    if not os.path.isdir(full):
        return f"### LS {sub or '.'}\n(not a directory)"
    items = []
    for e in sorted(os.listdir(full)):
        if e.startswith(".") or e in SKIP_DIRS:
            continue
        items.append(e + ("/" if os.path.isdir(os.path.join(full, e)) else ""))
    return f"### LS {sub or '.'}\n" + "\n".join(items)


CMD_RE = re.compile(r"^\s*(READ|GREP|LS|TREE)\b", re.I)
RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def run_commands(root, lines):
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or not CMD_RE.match(line):
            continue
        parts = line.split()
        op = parts[0].upper()
        try:
            if op == "READ":
                rel = parts[1]
                rng = None
                if len(parts) >= 3:
                    m = RANGE_RE.match(parts[2])
                    if m:
                        rng = (int(m.group(1)), int(m.group(2)))
                out.append(do_read(root, rel, rng))
            elif op == "GREP":
                pat = parts[1]
                sub = parts[2] if len(parts) >= 3 else ""
                out.append(do_grep(root, pat, sub))
            elif op == "LS":
                out.append(do_ls(root, parts[1] if len(parts) >= 2 else ""))
            elif op == "TREE":
                sub = parts[1] if len(parts) >= 2 else ""
                out.append(f"### TREE {sub or '.'}\n```\n{tree_str(root, sub)}\n```")
        except Exception as e:
            out.append(f"(error running `{line}`: {e})")
    reply = "Here are the requested contents:\n\n" + "\n\n".join(out)
    if len(reply.encode()) > MAX_REPLY_BYTES:
        reply = reply.encode()[:MAX_REPLY_BYTES].decode("utf-8", "replace")
        reply += "\n\n(reply truncated — ask for narrower ranges)"
    return reply


# ---- ChatGPT tab I/O (reuses chatgpt-web Chrome) ----------------------------

def connect():
    target = ensure_chrome()
    if not target:
        sys.exit("ERROR: dedicated Chrome is down; autolaunch is off. Start it first: "
                 "python3 scripts/ask.py up  (or export CHATGPT_WEB_AUTOLAUNCH=1)")
    ws = WS(target["webSocketDebuggerUrl"])
    ws.cmd("Runtime.enable")
    return ws, target


def send_message(ws, text):
    """Insert text into the ChatGPT editor and click send (multi-line safe)."""
    ws.evaluate(f"""(()=>{{const e=document.querySelector('{EDITOR}');if(!e)return;
      e.focus();const s=window.getSelection(),r=document.createRange();
      r.selectNodeContents(e);s.removeAllRanges();s.addRange(r);}})()""")
    ws.type_text(text)
    time.sleep(0.5)
    clicked = ws.evaluate(
        f"(()=>{{const b=document.querySelector('{SEND}');if(!b||b.disabled)return false;b.click();return true;}})()")
    if not clicked:
        ws.evaluate(f"(()=>{{const e=document.querySelector('{EDITOR}');e&&e.focus();}})()")
        ws.key("Enter", "Enter", 13)


# read the latest assistant turn: count, generating flag, plain text, code blocks
STATE_JS = """(()=>{
  const a=[...document.querySelectorAll('%s')];
  const last=a[a.length-1]||null;
  const gen=!!document.querySelector('%s');
  const blocks=last?[...last.querySelectorAll('pre code')].map(c=>({
    lang:((c.className||'').match(/language-([\\w-]+)/)||[])[1]||'',
    text:c.innerText||''})):[];
  return JSON.stringify({count:a.length, gen, text:last?last.innerText:'', blocks});
})()""" % (ASSISTANT, STOP)


def get_state(ws):
    raw = ws.evaluate(STATE_JS)
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}


def find_fetch(blocks):
    """Return command lines from a fetch block, or None. Tolerant: matches a
    block tagged `fetch`, else any block whose lines look like our commands."""
    for b in blocks:
        if b.get("lang", "").lower() == "fetch":
            return b.get("text", "").splitlines()
    for b in blocks:
        lines = [l for l in b.get("text", "").splitlines() if l.strip()]
        if lines and all(CMD_RE.match(l) for l in lines):
            return lines
    return None


def wait_complete(ws, target, after_count, max_wait=300):
    """Wait for a completed assistant turn beyond after_count: generation idle and
    text stable. Recover from reasoning-model stalls (empty/stuck) by reloading to
    re-read the server-side reply, like ask.py. Returns (ws, state)."""
    prev = ""; stable = 0; empty = 0; reloaded = False
    deadline = time.time() + max_wait
    while time.time() < deadline:
        st = get_state(ws)
        count, gen, text = st.get("count", 0), st.get("gen"), st.get("text", "")
        if count > after_count and not gen and text:
            if text == prev:
                stable += 1
                if stable >= 2:
                    return ws, st
            else:
                stable = 0; prev = text
        else:
            stable = 0
        empty = empty + 1 if (not text and (gen or count <= after_count)) else 0
        if empty >= 12 and not reloaded:
            ws = reload_recover(ws, target); reloaded = True
            empty = 0; prev = ""; stable = 0
            continue
        time.sleep(2)
    if not reloaded:
        ws = reload_recover(ws, target)
    return ws, get_state(ws)


def serve(root, rounds=0):
    ws, target = connect()
    print(f"[nav] serving {root} — watching ChatGPT for `fetch` blocks "
          f"({'unlimited' if not rounds else rounds} rounds). Ctrl-C to stop.",
          flush=True)
    served = 0
    st = get_state(ws)
    while True:
        cmds = find_fetch(st.get("blocks", []))
        cur = st.get("count", 0)
        if cmds:
            names = " | ".join(l.strip() for l in cmds if l.strip())[:200]
            print(f"[nav] fetch from ChatGPT: {names}", flush=True)
            reply = run_commands(root, cmds)
            send_message(ws, reply)
            served += 1
            print(f"[nav] served round {served} ({len(reply)} bytes)", flush=True)
            if rounds and served >= rounds:
                print(f"[nav] reached {rounds} rounds, exiting.", flush=True)
                return
            time.sleep(3)
        # wait for the next completed assistant turn (model's reply, or human's next)
        ws, st = wait_complete(ws, target, after_count=cur)


NEWCHAT_JS = """(()=>{const b=[...document.querySelectorAll('a,button')]
  .find(x=>/new chat|新しいチャット/i.test((x.getAttribute('aria-label')||'')+' '+x.textContent));
  if(b)b.click();})()"""


def consult(root, question, max_rounds=6):
    """Autonomous one-shot: open a fresh chat, brief ChatGPT with the tree +
    question, auto-serve every `fetch` it asks for, and return its final (non-
    fetch) answer on stdout. This is the entry point an agent (e.g. pi/Gemma)
    calls to get a ChatGPT analysis that has 'explored' the repo. Read-only:
    apply and test any proposed diff yourself."""
    ws, target = connect()
    ws.evaluate(NEWCHAT_JS); time.sleep(1.5)
    base = get_state(ws).get("count", 0)
    send_message(ws, build_brief(root, question))
    print(f"[nav] consulting ChatGPT about {os.path.basename(root)} "
          f"(<= {max_rounds} fetch rounds)...", file=sys.stderr, flush=True)
    cur = base
    for _ in range(max_rounds):
        ws, st = wait_complete(ws, target, after_count=cur)
        cur = st.get("count", cur)
        cmds = find_fetch(st.get("blocks", []))
        if not cmds:
            print(st.get("text", "").strip())
            return
        names = " | ".join(l.strip() for l in cmds if l.strip())[:200]
        print(f"[nav] fetch: {names}", file=sys.stderr, flush=True)
        send_message(ws, run_commands(root, cmds))
    print("[nav] max fetch rounds reached; last message follows:", file=sys.stderr)
    print(get_state(ws).get("text", "").strip())


def build_brief(root, task):
    name = os.path.basename(root)
    tree = tree_str(root)
    task = task or "<describe your problem/goal here>"
    return (f"{PROTOCOL}\n\nRepo root: {name}\n\nFile tree:\n{tree}\n\nTask:\n{task}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, root = sys.argv[1], repo_root(sys.argv[2])
    rest = sys.argv[3:]
    if cmd == "brief":
        print(build_brief(root, rest[0] if rest else ""))
    elif cmd == "seed":
        ws, _ = connect()
        send_message(ws, build_brief(root, rest[0] if rest else ""))
        print("[nav] brief sent to the ChatGPT tab.")
    elif cmd == "serve":
        rounds = 0
        if "--rounds" in rest:
            rounds = int(rest[rest.index("--rounds") + 1])
        serve(root, rounds)
    elif cmd == "consult":
        if not rest:
            sys.exit('usage: nav.py consult <repo> "question"')
        consult(root, rest[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
