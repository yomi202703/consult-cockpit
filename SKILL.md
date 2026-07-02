---
name: consult-cockpit
description: Launch a 3-lane browser cockpit where a worker LLM (any OpenAI-compatible endpoint; today a local Gemma) and a reader (today the signed-in web ChatGPT) both explore a repo — the worker reads locally (fast, small repos), the reader reads via the chatgpt-web consult loop (context offload, big/cross-file), and you hand results between them. Use when you want to point two models at a repo and watch "who is reading which file" live. Triggers — "cockpit", "consult cockpit", pointing it at a repo.
---

## What it is

One browser page, three lanes:
- left = reader mirror (the real signed-in ChatGPT tab, read over CDP; shows
  "disabled" when chatgpt-web is absent — the cockpit still runs worker-only)
- middle = fetch traffic — what files are being read, by whom (the star)
- right = worker free-form chat, and worker local repo exploration

Two ways to put repo knowledge into an answer:
- consult ▶ (left) — the reader reads the repo via the chatgpt-web fetch protocol.
  Slow (~40s, browser-driven) but offloads reading to the reader's big context. For
  large / cross-file work where the worker's context would overflow.
- explore repo ▶ (right) — the worker reads the repo itself via the same protocol,
  direct API, no browser. Fast (~4s). For small / targeted work. Repo bytes enter
  only a transient sub-context; the persistent worker chat stays lean.
- forward ⇥ (right) — hand the reader's last answer into the worker chat (answer
  text only, capped 8KB). This is the human-driven handoff.

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
   - API reader: `READER_LLM_*` in `.env` — consult runs browser-free, takes
     precedence over the scrape lane.
   - scrape reader: the `chatgpt-web` skill (dedicated Chrome on port 9333,
     one-time ChatGPT sign-in, Cloudflare cleared by hand once).

## Portability

Zero third-party deps, no venv. To use on another machine: copy this dir, drop a
`.env` (or set `COCKPIT_ENV`), store the key with `run.sh auth set worker`, then
`bash run.sh doctor`. Add the `chatgpt-web` skill + Chrome sign-in only if you
want the scrape reader.

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
- `src/static/index.html` — the 3-lane UI (no build step, no deps).
- `run.sh` — launcher + doctor + auth.
