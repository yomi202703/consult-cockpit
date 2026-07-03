---
name: consult-cockpit
description: Launch a single-lane agent-chat cockpit over a repo — you talk to a worker LLM (any OpenAI-compatible endpoint; today a local Gemma) that reads the repo itself when needed (fetch, autonomous) or asks a stronger reader (today the signed-in web ChatGPT) on your explicit request (consult). Who-read-which-file stays visible as collapsible cards in the conversation. Use when you want a small model to work a repo without bloating its context, with the offload observable. Triggers — "cockpit", "consult cockpit", pointing it at a repo.
---

## What it is

One browser page, one conversation with the worker. The worker has two tools;
each tool round is transient (the offload invariant) and leaves a collapsible
card in the conversation:
- 🔧 fetch card — the worker read the repo ITSELF (autonomous, cheap, ~4s;
  expand to see what it READ/GREPed and how many bytes were served).
- 🔍 consult card — the reader (ChatGPT) studied the repo on the user's explicit
  request ("ChatGPTに聞いて"), slow (~40s, browser-driven); expand DURING the
  run to watch live which files the reader is fetching (the old mirror lane,
  folded into the card).
- ask reader ▶ — direct consult from the input box; the raw answer lands as an
  inline card with a [⇥ worker に渡す] (forward) action.
- status pill above the input: 考え中… / repo を読み中… / ChatGPT に質問中… Ns.

Reader absent → worker-only mode (consult unavailable, `/consult` 503).

## Run it

```
bash run.sh [REPO]                    # launch pointed at REPO (default: current dir)
bash run.sh doctor                    # validate prerequisites and exit
bash run.sh auth set|get|delete LANE  # API key in the macOS keychain (LANE: worker|reader)
```

`[REPO]` only sets the pre-filled repo path — the field is editable in the UI, so
one running instance can point at any repo. Any repo path works (it's a runtime
value, expanduser'd); the tool is not tied to any particular repo.

## Prerequisites (run `doctor` to check)

1. `python3` — no venv, no pip, stdlib only (3.9+).
2. A worker endpoint (any OpenAI-compatible API): `WORKER_LLM_BASE_URL/_MODEL` in
   `.env`; the API key preferably in the keychain (`bash run.sh auth set worker`) —
   precedence: explicit env var > keychain > .env value.
3. OPTIONAL — a reader, one of two (neither → worker-only, `/consult` returns 503):
   - scrape reader (bundled `scrape/`, no API cost): `python3 scrape/ask.py up`
     then sign into ChatGPT once in the dedicated Chrome (port 9333; Cloudflare
     cleared by hand once). Works with a free ChatGPT account.
   - API reader: `READER_LLM_*` in `.env` — consult runs browser-free, takes
     precedence over the scrape lane.

## Portability

Zero third-party deps, no venv (requirements.txt exists only to declare that).
To use on another machine: copy this dir, drop a `.env` (or set `COCKPIT_ENV`),
store the key with `run.sh auth set worker` (macOS; on Windows/Linux put it in
`.env` — the keychain backend degrades cleanly), then `bash run.sh doctor` /
`run.bat doctor`. Windows launches with `run.bat`; the scrape reader's Chrome
detection covers Mac/Windows/Linux; the native 📁 folder picker is macOS-only
(a path input appears instead).

Overrides: `COCKPIT_PYTHON`, `COCKPIT_SCRIPTS` (chatgpt-web scripts dir),
`COCKPIT_ENV` (.env path), `COCKPIT_PORT` (default 8079), `COCKPIT_REPO`.

## Design invariant

Raw repo file bodies never enter the *persistent* worker history. The consult path
sends them only to the reader; `forward` crosses only the answer text (capped). The
explore path reads into a transient context that is discarded — only its distilled
answer joins the chat. See `_dev/decisions.md`.

## Files

- `src/server.py` — SSE hub, single CDP tab-controller thread, consult loops
  (API reader + scrape reader), worker explore loop, routes, `doctor`.
- `src/llm_client.py` — lane config (resolve_lane) + provider adapter table +
  streaming client (stdlib urllib, OpenAI-compatible).
- `src/secrets_store.py` — macOS keychain store for API keys (`run.sh auth`).
- `src/repo_fetch.py` — read-only repo fetch layer (ownership fork of nav's pure block).
- `src/env.py` — .env reader (+ from_live_env implementing the key precedence).
- `src/static/index.html` — the single-lane agent-chat UI (no build step, no deps).
- `run.sh` — launcher + doctor + auth.
