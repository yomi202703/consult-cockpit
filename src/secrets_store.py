"""API-key store on the macOS keychain — stdlib only, no keytar.

Shells out to /usr/bin/security exactly like Claude Code's extension does
(teardown 2026-07-02): find/add(-U)/delete-generic-password, 2s timeout,
exit codes 44/36 treated as a clean "not found". One keychain item per
provider: service="consult-cockpit", account=<provider> (per
_dev/design_auth.md — lanes sharing a provider share the key).

Key resolution precedence lives in llm_client.resolve_lane, not here:
explicit env var > keychain > .env value. This module only talks to the
keychain; any failure degrades to None so the .env fallback continues.

CLI:
  python3 src/secrets_store.py get|set|delete <account>
  python3 src/secrets_store.py auth-lane get|set|delete <lane>   (worker|reader)
"""
import os
import subprocess
import sys

SERVICE = "consult-cockpit"
_SECURITY = "/usr/bin/security"
_TIMEOUT = 2  # seconds; a locked/headless keychain must not hang the app
_NOT_FOUND = (44, 36)  # errSecItemNotFound / not-found variants


def _run(args, input_text=None):
    try:
        return subprocess.run([_SECURITY] + args, capture_output=True,
                              text=True, timeout=_TIMEOUT, input=input_text)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[secrets] keychain unavailable: {e!r}", file=sys.stderr)
        return None


def get(account):
    """Return the secret for account, or None (not found / keychain trouble)."""
    r = _run(["find-generic-password", "-s", SERVICE, "-a", account, "-w"])
    if r is None:
        return None
    if r.returncode == 0:
        return r.stdout.rstrip("\n") or None
    if r.returncode not in _NOT_FOUND:
        print(f"[secrets] keychain read failed (rc={r.returncode}); "
              "falling back to .env", file=sys.stderr)
    return None


def set(account, secret):  # noqa: A001  (module-level, mirrors get/delete)
    """Store (or overwrite, -U) the secret for account. Returns True on success."""
    r = _run(["add-generic-password", "-U", "-s", SERVICE, "-a", account,
              "-w", secret])
    ok = r is not None and r.returncode == 0
    if not ok and r is not None:
        print(f"[secrets] keychain write failed (rc={r.returncode}): "
              f"{(r.stderr or '').strip()[:120]}", file=sys.stderr)
    return ok


def delete(account):
    """Remove the secret; not-found counts as success."""
    r = _run(["delete-generic-password", "-s", SERVICE, "-a", account])
    return r is not None and (r.returncode == 0 or r.returncode in _NOT_FOUND)


def _lane_provider(lane):
    """Map a lane name to its provider (= keychain account) via env config."""
    import env as cockpit_env
    cockpit_env.load_env()
    return os.environ.get(f"{lane.upper()}_LLM_PROVIDER") or "openai"


def _cli(argv):
    usage = ("usage: secrets_store.py get|set|delete <account>\n"
             "       secrets_store.py auth-lane get|set|delete <lane>")
    if argv and argv[0] == "auth-lane":
        argv = argv[1:]
        if len(argv) != 2 or argv[1] not in ("worker", "reader"):
            sys.exit(usage)
        op, account = argv[0], _lane_provider(argv[1])
        print(f"[secrets] lane {argv[1]} -> provider '{account}'", file=sys.stderr)
    elif len(argv) == 2:
        op, account = argv
    else:
        sys.exit(usage)

    if op == "get":
        got = get(account)
        if got is None:
            sys.exit(f"no key stored for '{account}'")
        print(got)
    elif op == "set":
        import getpass
        secret = getpass.getpass(f"API key for '{account}': ").strip()
        if not secret:
            sys.exit("empty key, nothing stored")
        sys.exit(0 if set(account, secret) else 1)
    elif op == "delete":
        sys.exit(0 if delete(account) else 1)
    else:
        sys.exit(usage)


if __name__ == "__main__":
    _cli(sys.argv[1:])
