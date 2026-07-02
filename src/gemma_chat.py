"""Free-form streaming chat with the local Gemma (OpenAI-compatible endpoint).

Deliberately NOT improver's gemma_subagent (which forces one of five fixed JSON
`kind`s and blocks). The cockpit's right lane is a conversation: free-form text +
token streaming. Zero third-party deps — stdlib urllib only — so the tool runs
under a bare python3 on any internal machine that has the .env.

Context invariant: the caller owns `history`. Repo file bodies must never be
appended here for the *consult* path; the *explore* path reads into a transient
context (see server.py). This module just relays whatever messages it is given.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Iterator

from env import load_env

_TIMEOUT = float(os.environ.get("COCKPIT_GEMMA_TIMEOUT", "180"))


def _endpoint() -> tuple[str, str, str]:
    load_env()
    base = (os.environ.get("WORKER_LLM_BASE_URL") or "").rstrip("/")
    key = os.environ.get("WORKER_LLM_API_KEY") or ""
    model = os.environ.get("WORKER_LLM_MODEL") or ""
    if not base or not model:
        raise RuntimeError("WORKER_LLM_BASE_URL / WORKER_LLM_MODEL not set "
                           "(run `bash run.sh doctor`)")
    return base, key, model


def stream_chat(messages: list[dict], *, temperature: float = 0.3,
                max_tokens: int = 1024, timeout: float | None = None) -> Iterator[str]:
    """Yield text deltas from Gemma for an OpenAI-style messages list.

    messages: [{"role": "user"|"assistant"|"system", "content": str}, ...]
    """
    base, key, model = _endpoint()
    payload = json.dumps({
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens, "stream": True,
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=payload,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
        for raw in resp:                       # HTTPResponse iterates by line
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            for choice in obj.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    yield piece


if __name__ == "__main__":
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "In one sentence, what are you?"
    got = False
    for tok in stream_chat([{"role": "user", "content": prompt}], max_tokens=120):
        sys.stdout.write(tok)
        sys.stdout.flush()
        got = True
    print("\n---", "OK (streamed)" if got else "NO TOKENS RECEIVED")
