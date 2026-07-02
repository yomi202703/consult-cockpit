---
name: consult-cockpit
description: Launch a 3-lane browser cockpit where a local Gemma and signed-in web ChatGPT both explore a repo — Gemma reads locally (fast, small repos), ChatGPT reads via the chatgpt-web consult loop (context offload, big/cross-file), and you hand results between them. Use when you want to point Gemma/ChatGPT at a repo and watch "who is reading which file" live. Triggers — "cockpit", "consult cockpit", pointing it at a repo.
---

## What it is

One browser page, three lanes:
- left = ChatGPT mirror (the real signed-in tab, read over CDP)
- middle = fetch traffic — what files are being read, by whom (the star)
- right = Gemma free-form chat, and Gemma local repo exploration

Two ways to put repo knowledge into an answer:
- consult ▶ (left) — ChatGPT reads the repo via the chatgpt-web fetch protocol.
  Slow (~40s, browser-driven) but offloads reading to ChatGPT's big context. For
  large / cross-file work where Gemma's context would overflow.
- explore repo ▶ (right) — Gemma reads the repo itself via the same protocol,
  direct API, no browser. Fast (~4s). For small / targeted work. Repo bytes enter
  only a transient sub-context; the persistent Gemma chat stays lean.
- forward ⇥ (right) — hand ChatGPT's last answer into the Gemma chat (answer text
  only, capped 8KB). This is the human-driven handoff.

## Run it

```
bash run.sh [REPO]     # launch pointed at REPO (default: current dir), opens browser
bash run.sh doctor     # validate prerequisites and exit
```

`[REPO]` only sets the pre-filled repo path — the field is editable in the UI, so
one running instance can point at any repo. Any repo path works (it's a runtime
value, expanduser'd); the tool is not tied to any particular repo.

## Prerequisites (run `doctor` to check all four)

1. `python3` — no venv, no pip. Stdlib only (urllib for Gemma, chatgpt-web's own
   dependency-free CDP client).
2. The `chatgpt-web` skill — provides the dedicated Chrome (debug port 9333) and
   the one-time ChatGPT sign-in. The cockpit reuses its `nav/ask/cdp` as a library.
3. A `.env` with `WORKER_LLM_BASE_URL/API_KEY/MODEL/PROVIDER` (the Gemma
   OpenAI-compatible endpoint). Shippable to internal machines.
4. The dedicated Chrome running and signed into ChatGPT (one-time; a Cloudflare
   check is cleared by hand once — see chatgpt-web SKILL).

## Portability

Zero third-party deps and no improver/venv dependency — the cockpit reads the
.env itself (`env.py`) and talks to Gemma over stdlib urllib. To use on another
internal machine: copy this dir + the `chatgpt-web` skill, drop the `.env` (or set
`COCKPIT_ENV`), sign into the dedicated Chrome once, then `bash run.sh doctor`.

Overrides: `COCKPIT_PYTHON`, `COCKPIT_SCRIPTS` (chatgpt-web scripts dir),
`COCKPIT_ENV` (.env path), `COCKPIT_PORT` (default 8079), `COCKPIT_REPO`.

## Design invariant

Raw repo file bodies never enter the *persistent* Gemma history. The consult path
sends them only to ChatGPT; `forward` crosses only the answer text (capped). The
explore path reads into a transient context that is discarded — only its distilled
answer joins the chat. See `_dev/decisions.md`.

## Files

- `src/server.py` — SSE hub, single CDP tab-controller thread, consult loop, Gemma
  explore loop, routes, `doctor`.
- `src/gemma_chat.py` — free-form streaming client (stdlib urllib).
- `src/env.py` — .env reader (decouples from improver).
- `src/static/index.html` — the 3-lane UI (no build step, no deps).
- `run.sh` — launcher + doctor.
