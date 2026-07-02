#!/usr/bin/env python3
"""Send a prompt to chatgpt.com and capture the reply, via Chrome CDP.

Usage:
    python3 ask.py "your prompt"          # ask in the current conversation
    python3 ask.py --new "your prompt"     # start a fresh chat first
    python3 ask.py --timeout 300 "..."     # max seconds to wait for the reply

Shares ONE dedicated Chrome instance with gemini-web (port 9333, profile
~/.gemini-chrome): two AI tabs in a single signed-in browser, no API cost, no
AppleScript. Side effects are real: runs ChatGPT on the user's signed-in account.

Exit codes: 0 ok | 1 not reachable | 3 not signed in / blocked (see SKILL.md).
"""
import sys, os, time, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import PORT, chatgpt_target, port_alive, new_tab, WS  # noqa: E402


def _find_chrome():
    """Resolve the Google Chrome executable for the current OS (Mac/Windows/Linux).
    The Mac path is the original default; Windows/Linux locations are added so the
    skill is portable. Returns the first that exists, else the first candidate."""
    import shutil
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform == "win32":
        cands = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        cands = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for c in cands:
        if (os.sep in c) or (os.altsep and os.altsep in c):
            if os.path.exists(c):
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return cands[0]


CHROME = _find_chrome()
PROFILE = os.path.expanduser("~/.gemini-chrome")  # shared with gemini-web
APP_URL = "https://chatgpt.com/"

# ChatGPT selectors.
EDITOR = "#prompt-textarea"
SEND = '[data-testid="send-button"]'
STOP = '[data-testid="stop-button"]'
ASSISTANT = '[data-message-author-role="assistant"]'
LAST_JS = ("(()=>{const n=document.querySelectorAll('%s');"
           "const l=n[n.length-1];return l?l.innerText:'';})()" % ASSISTANT)


def reconnect(target):
    """Fresh WS to the target with Runtime enabled (context changes after reload)."""
    ws = WS(target["webSocketDebuggerUrl"])
    ws.cmd("Runtime.enable")
    return ws


def reload_recover(ws, target):
    """A streaming reply can stall client-side while the server already finished.
    Reload re-reads the persisted reply; return a fresh ws once the editor is back."""
    try:
        ws.cmd("Page.enable"); ws.cmd("Page.reload", {"ignoreCache": False})
    except Exception:
        pass
    for _ in range(30):
        time.sleep(2)
        try:
            w = reconnect(target)
            if w.evaluate(f"!!document.querySelector('{EDITOR}')"):
                return w
        except Exception:
            pass
    return reconnect(target)


def poll_reply(ws, target, base, timeout):
    """Poll for the NEW reply, recovering from client-side stream stalls. Settle
    only once generation has finished (stop-button gone) and text is stable;
    while generation is still active, never settle on stable text (it may be a
    preamble/thinking pause) — reload to re-read the server-side reply instead.
    Also reload if generation stalls empty; on timeout, read the last message
    directly."""
    cap = """(()=>{
      const n=document.querySelectorAll('%s');
      const ready = n.length >= %d + 1;
      const last = ready ? n[n.length-1] : null;
      const gen = !!document.querySelector('%s');
      return JSON.stringify({ready, gen, text: last ? last.innerText : ''});
    })()""" % (ASSISTANT, base, STOP)

    last = ""; stable = 0; stalled = 0; reloaded = False
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ws.evaluate(cap)
        try:
            st = json.loads(raw) if isinstance(raw, str) else {}
        except ValueError:
            st = {}
        text = st.get("text", ""); gen = st.get("gen"); ready = st.get("ready")
        if text and text == last:
            stable += 1
            if not gen and stable >= 3:
                return text.strip()
            # gen still active + long-stable text = a reasoning/preamble pause
            # mid-generation (ChatGPT always emits a preamble, then thinks) OR a
            # stuck stop-button. Settling here returns the preamble and loses the
            # real answer, so do NOT settle: reload once to clear a stuck button /
            # re-read the server-side reply, then resume polling.
            if gen and stable >= 20:
                ws = reload_recover(ws, target)
                stable = 0; last = ""
                continue
        else:
            stable = 0
        if not text and (gen or not ready):
            stalled += 1
        else:
            stalled = 0
        if stalled >= 12 and not reloaded:
            ws = reload_recover(ws, target)
            reloaded = True; stalled = 0; stable = 0; last = ""
            continue
        last = text
        time.sleep(2)

    if not reloaded:
        ws = reload_recover(ws, target)
    txt = ws.evaluate(LAST_JS)
    txt = txt if isinstance(txt, str) else ""
    return (txt or last).strip()


# Autolaunch is OFF by default: the skill never spawns Chrome as a side effect
# of asking. Launch happens ONLY on an explicit trigger — `ask.py up`, or the
# env override CHATGPT_WEB_AUTOLAUNCH=1. This is why a killed Chrome stays dead.
AUTOLAUNCH = os.environ.get("CHATGPT_WEB_AUTOLAUNCH") == "1"


def launch_chrome():
    """Spawn the shared debug Chrome and wait for the port. Explicit trigger only."""
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
         "--no-first-run", "--no-default-browser-check", APP_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        time.sleep(1)
        if port_alive():
            return True
    return False


def ensure_chrome():
    """Attach to the shared debug Chrome (with a ChatGPT tab); return target.

    Does NOT launch Chrome unless autolaunch is explicitly enabled. If Chrome is
    down and autolaunch is off, returns None and the caller reports how to start it.
    """
    if not port_alive():
        if not AUTOLAUNCH:
            return None
        if not launch_chrome():
            return None
    opened = False
    for _ in range(30):
        t = chatgpt_target()
        if t:
            return t
        # instance is up (maybe only a gemini tab): open a chatgpt tab once
        if not opened:
            try:
                new_tab(APP_URL)
                opened = True
            except Exception:
                pass
        time.sleep(1)
    return None


def main():
    args = sys.argv[1:]
    new = False; timeout = 300
    while args and args[0].startswith("--"):
        if args[0] == "--new": new = True; args.pop(0)
        elif args[0] == "--timeout": args.pop(0); timeout = int(args.pop(0))
        else: break
    if args and args[0] == "up":
        if port_alive():
            print(f"already up on CDP port {PORT}"); sys.exit(0)
        print("launching dedicated Chrome ...", file=sys.stderr)
        sys.exit(0 if launch_chrome() else 1)
    if not args:
        print('usage: ask.py up | [--new] [--timeout N] "prompt"', file=sys.stderr); sys.exit(2)
    prompt = args[0]

    target = ensure_chrome()
    if not target:
        if not port_alive():
            print(f"ERROR: dedicated Chrome is down (CDP port {PORT}). Autolaunch is off, "
                  "so it will NOT start on its own.\n"
                  "  start it explicitly:  python3 scripts/ask.py up\n"
                  "  or opt into autostart: export CHATGPT_WEB_AUTOLAUNCH=1",
                  file=sys.stderr)
        else:
            print(f"ERROR: Chrome up on port {PORT} but no usable ChatGPT tab.", file=sys.stderr)
        sys.exit(1)

    ws = WS(target["webSocketDebuggerUrl"])
    ws.cmd("Runtime.enable")

    # settle + detect sign-in / Cloudflare challenge. ChatGPT's logged-out and
    # challenge pages have no #prompt-textarea, so editor presence is the signal.
    for _ in range(40):
        state = ws.evaluate("""(()=>{
          const cf=/just a moment|verifying you are human|challenge/i.test(document.body.innerText||'');
          const login=[...document.querySelectorAll('a,button')].some(e=>e.offsetParent!==null
            && /^(log ?in|sign ?up|ログイン|登録)$/i.test((e.textContent||'').trim()));
          return {editor: !!document.querySelector('#prompt-textarea'), cf, login};
        })()""") or {}
        if state.get("cf"):
            print("BLOCKED: Cloudflare/human-check on chatgpt.com. Solve it once in "
                  "the dedicated Chrome window, then retry. See SKILL.md.", file=sys.stderr)
            sys.exit(3)
        if state.get("editor"):
            break
        if state.get("login"):
            print("NOT_SIGNED_IN: log in to ChatGPT once in the dedicated Chrome "
                  f"window (CDP port {PORT}), then retry. See SKILL.md.", file=sys.stderr)
            sys.exit(3)
        time.sleep(1)
    else:
        print("ERROR: ChatGPT editor not found (not signed in, blocked, or UI changed).",
              file=sys.stderr)
        sys.exit(1)

    if new:
        ws.evaluate("""(()=>{const b=[...document.querySelectorAll('a,button')]
          .find(x=>/new chat|新しいチャット/i.test((x.getAttribute('aria-label')||'')+' '+x.textContent));
          if(b)b.click();})()""")
        time.sleep(1.2)

    base = ws.evaluate(f"document.querySelectorAll('{ASSISTANT}').length") or 0
    # user-turn baseline: appears immediately on a real send (reliable, unlike the
    # assistant turn which lags streaming) — used to confirm the send fired.
    base_user = ws.evaluate(
        "document.querySelectorAll('[data-message-author-role=\\\"user\\\"]').length") or 0

    def insert_and_send():
        # insert into the ProseMirror editor via execCommand (Trusted-Types safe)
        ws.evaluate(f"""(()=>{{const e=document.querySelector('{EDITOR}');if(!e)return;
          e.focus();const s=window.getSelection(),r=document.createRange();
          r.selectNodeContents(e);s.removeAllRanges();s.addRange(r);}})()""")
        ws.type_text(prompt)
        time.sleep(0.5)
        clicked = ws.evaluate(
            f"(()=>{{const b=document.querySelector('{SEND}');if(!b||b.disabled)return false;b.click();return true;}})()")
        if not clicked:
            ws.evaluate(f"(()=>{{const e=document.querySelector('{EDITOR}');e&&e.focus();}})()")
            ws.key("Enter", "Enter", 13)

    def send_registered():
        # a new user turn, a grown reply, or active generation proves the send
        # fired. Editor-empty alone is ambiguous (a failed insert also empties it),
        # so it is not used — avoiding a double-send.
        st = ws.evaluate(f"""(()=>{{
          const userGrew=document.querySelectorAll('[data-message-author-role="user"]').length >= {base_user}+1;
          const grew=document.querySelectorAll('{ASSISTANT}').length >= {base}+1;
          const gen=!!document.querySelector('{STOP}');
          return JSON.stringify({{userGrew, grew, gen}});
        }})()""")
        try:
            d = json.loads(st) if isinstance(st, str) else {}
        except ValueError:
            d = {}
        return bool(d.get("userGrew") or d.get("grew") or d.get("gen"))

    insert_and_send()
    time.sleep(2)
    if not send_registered():
        insert_and_send()

    print(poll_reply(ws, target, base, timeout))


if __name__ == "__main__":
    main()
