"""Tiny .env reader — decouples the cockpit from the improver package.

The cockpit only ever needed improver for `.env` parsing (WORKER_LLM_*), not the
heavy langgraph venv. Reading it here means the whole tool runs under a bare
python3 (no venv, no pip) on any internal machine that has the .env.

Search order (first readable file wins; never overwrites already-exported vars):
  1. $COCKPIT_ENV                    explicit override
  2. <cockpit>/.env                  local, e.g. shipped to an internal machine
  3. ~/.claude/lib/improver/.env     this machine's existing config (fallback)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.environ.get("COCKPIT_ENV"),
    os.path.join(HERE, ".env"),
    os.path.expanduser("~/.claude/lib/improver/.env"),
]
REQUIRED = ("WORKER_LLM_BASE_URL", "WORKER_LLM_API_KEY",
            "WORKER_LLM_MODEL", "WORKER_LLM_PROVIDER")


def _parse(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def env_source():
    """Return the path of the .env that would be used, or None."""
    for path in CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def load_env():
    """Populate os.environ from the first readable .env; return applied dict.
    Does not overwrite vars already set in the live environment."""
    applied = {}
    path = env_source()
    if not path:
        return applied
    try:
        data = _parse(open(path).read())
    except OSError:
        return applied
    for k, v in data.items():
        applied[k] = v
        if k not in os.environ and v:
            os.environ[k] = v
    return applied


def missing_required():
    load_env()
    return [k for k in REQUIRED if not os.environ.get(k)]
