"""Tiny .env reader — stdlib only, no dotenv dependency.

Reading the .env here means the whole tool runs under a bare python3 (no venv,
no pip) on any machine that has the .env.

Search order (first readable file wins; never overwrites already-exported vars):
  1. $COCKPIT_ENV      explicit override
  2. <cockpit>/.env    local (next to the sources)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.environ.get("COCKPIT_ENV"),
    os.path.join(HERE, ".env"),
]
# API key is NOT required here: it may live in the keychain (secrets_store)
# instead of any .env. PROVIDER is optional (defaults to "openai").
REQUIRED = ("WORKER_LLM_BASE_URL", "WORKER_LLM_MODEL")

# Names injected into os.environ by load_env (as opposed to vars that were
# already set when the process started). llm_client uses this to implement the
# key precedence "explicit env var > keychain > .env value" — without it, a
# stale .env key would masquerade as an explicit override and beat the keychain.
_injected = set()


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
        with open(path) as f:
            data = _parse(f.read())
    except OSError:
        return applied
    for k, v in data.items():
        applied[k] = v
        if k not in os.environ and v:
            os.environ[k] = v
            _injected.add(k)
    return applied


def from_live_env(name):
    """Return os.environ[name] only if it was set by the caller's environment,
    not injected from a .env file by load_env(). None otherwise."""
    if name in _injected:
        return None
    return os.environ.get(name) or None


def missing_required():
    load_env()
    return [k for k in REQUIRED if not os.environ.get(k)]
