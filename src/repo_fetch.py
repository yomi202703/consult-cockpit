"""Read-only repo fetch layer — the cockpit's own copy.

Deliberate ownership fork (2026-07-03) of the pure, browser-free block of
chatgpt-web/scripts/nav.py (its repo-reading half: fetch protocol, READ/GREP/
LS/TREE executors, brief builder). Forked so the worker lane (and the whole
process) no longer needs chatgpt-web installed; upstream nav.py stays
untouched and keeps its own copy for the CLI. Recorded in _dev/decisions.md.

Everything here is read-only and scoped under the given repo root.
"""
import os
import re
import sys

# ---- limits / protocol -------------------------------------------------------

MAX_FILE_LINES = 600        # cap a single READ (use line ranges for more)
MAX_FILE_BYTES = 64 * 1024
MAX_GREP_HITS = 120
MAX_REPLY_BYTES = 40 * 1024  # keep the model's context from overflowing
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
    """Filtered walk. Returns relpaths."""
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


def build_brief(root, task):
    name = os.path.basename(root)
    tree = tree_str(root)
    task = task or "<describe your problem/goal here>"
    return (f"{PROTOCOL}\n\nRepo root: {name}\n\nFile tree:\n{tree}\n\nTask:\n{task}")
