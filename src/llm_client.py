"""Streaming chat client for a cockpit lane (worker now; reader when API-based).

Any OpenAI-compatible endpoint (Bearer + /chat/completions + SSE data:/[DONE]):
OpenAI, vLLM, ollama, Groq, OpenRouter, a local Gemma... A lane is described by
{LANE}_LLM_BASE_URL / _MODEL / _PROVIDER (optional, default "openai") /
_API_KEY. The key resolves with precedence
    explicit env var > keychain (secrets_store, account=<provider>) > .env value
— env.from_live_env tells the first and last apart. Zero third-party deps —
stdlib urllib only — so the tool runs under a bare python3.

The provider adapter seam is the ADAPTERS table: path, headers, payload,
parse_line. A future non-OpenAI dialect (e.g. anthropic /v1/messages with
event-typed SSE) is a new 4-field entry, not a rewrite.

Context invariant: the caller owns `history`. Repo file bodies must never be
appended here for the *consult* path; the *explore* path reads into a transient
context (see server.py). This module just relays whatever messages it is given.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Iterator

import env as cockpit_env
import secrets_store

_TIMEOUT = float(os.environ.get("COCKPIT_GEMMA_TIMEOUT", "180"))

# ---- provider adapters -------------------------------------------------------
# One entry per API dialect: request path, auth headers, payload builder, and a
# stream-line parser returning (delta_text_or_None, done). Keep it a flat table;
# no classes/registries until a second dialect actually exists.


def _openai_parse_line(line: str):
    if not line.startswith("data:"):
        return None, False
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        return None, True
    try:
        obj = json.loads(data)
    except ValueError:
        return None, False
    for choice in obj.get("choices", []):
        piece = (choice.get("delta") or {}).get("content")
        if piece:
            return piece, False
    return None, False


ADAPTERS = {
    "openai": {
        "path": "/chat/completions",
        "headers": lambda key: {"Authorization": f"Bearer {key}"} if key else {},
        "payload": lambda model, messages, temperature, max_tokens: {
            "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens, "stream": True,
        },
        "parse_line": _openai_parse_line,
    },
}
# These providers all speak the OpenAI dialect.
_PROVIDER_TO_ADAPTER = {"openai": "openai", "gemma": "openai",
                        "ollama": "openai", "vllm": "openai"}


class LaneConfig:
    def __init__(self, lane, provider, base_url, model, key, key_source):
        self.lane = lane                # "worker" | "reader"
        self.provider = provider        # keychain account + adapter selector
        self.base_url = base_url
        self.model = model
        self.key = key
        self.key_source = key_source    # "env" | "keychain" | ".env" | "none"

    @property
    def adapter(self):
        name = _PROVIDER_TO_ADAPTER.get(self.provider)
        if name is None:
            raise NotImplementedError(
                f"provider '{self.provider}' has no adapter yet "
                "(openai-compatible only for now)")
        return ADAPTERS[name]


def resolve_lane(lane: str) -> LaneConfig | None:
    """Build a LaneConfig from {LANE}_LLM_*; None when the lane is unconfigured
    (no BASE_URL) — e.g. the dormant API reader."""
    cockpit_env.load_env()
    up = lane.upper()
    base = (os.environ.get(f"{up}_LLM_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    model = os.environ.get(f"{up}_LLM_MODEL") or ""
    if not model:
        raise RuntimeError(f"{up}_LLM_MODEL not set (run `bash run.sh doctor`)")
    provider = os.environ.get(f"{up}_LLM_PROVIDER") or "openai"

    key_var = f"{up}_LLM_API_KEY"
    key = cockpit_env.from_live_env(key_var)          # 1. explicit env var
    key_source = "env"
    if not key:
        key = secrets_store.get(provider)             # 2. keychain
        key_source = "keychain"
    if not key:
        key = os.environ.get(key_var) or ""           # 3. .env-injected value
        key_source = ".env" if key else "none"
    return LaneConfig(lane, provider, base, model, key, key_source)


def stream_chat(messages: list[dict], *, lane: str = "worker",
                temperature: float = 0.3, max_tokens: int = 1024,
                timeout: float | None = None) -> Iterator[str]:
    """Yield text deltas from the lane's endpoint for an OpenAI-style
    messages list: [{"role": "user"|"assistant"|"system", "content": str}, ...]
    """
    cfg = resolve_lane(lane)
    if cfg is None:
        raise RuntimeError(
            f"{lane.upper()}_LLM_BASE_URL not set "
            "(run `bash run.sh doctor`; store the key with "
            "`bash run.sh auth set " + lane + "`)")
    ad = cfg.adapter
    payload = json.dumps(ad["payload"](cfg.model, messages,
                                       temperature, max_tokens)).encode()
    req = urllib.request.Request(cfg.base_url + ad["path"], data=payload,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in ad["headers"](cfg.key).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
        for raw in resp:                       # HTTPResponse iterates by line
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            piece, done = ad["parse_line"](line)
            if done:
                break
            if piece:
                yield piece


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    lane = "worker"
    if args and args[0] == "--lane":
        lane = args[1]; args = args[2:]
    prompt = args[0] if args else "In one sentence, what are you?"
    cfg = resolve_lane(lane)
    if cfg:
        print(f"[{lane}] {cfg.provider} {cfg.model} @ {cfg.base_url} "
              f"(key: {cfg.key_source})", file=sys.stderr)
    got = False
    for tok in stream_chat([{"role": "user", "content": prompt}],
                           lane=lane, max_tokens=120):
        sys.stdout.write(tok)
        sys.stdout.flush()
        got = True
    print("\n---", "OK (streamed)" if got else "NO TOKENS RECEIVED")
