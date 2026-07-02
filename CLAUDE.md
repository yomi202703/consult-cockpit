# consult-cockpit — repo memory

3-lane browser cockpit: a local Gemma and the signed-in web ChatGPT both explore a
repo; you watch "who reads which file" and hand results between them. What/why is
in README.md and SKILL.md; this file is only what a fresh session gets wrong.

## Run / check
- `bash run.sh [repo]` — launch (default repo = cwd), opens localhost:8079. The
  repo field is editable in the UI, so one instance can point anywhere.
- `bash run.sh doctor` — validate the four prerequisites; run before first use or
  on a new machine.
- No build, no venv, no pip. Stdlib only, any python3 (3.9+).

## Prerequisites (easy to miss)
- The dedicated Chrome on port 9333 must be running and signed into ChatGPT — that
  is the chatgpt-web skill's browser (Cloudflare cleared by hand once). This repo
  does not manage sign-in.
- A `.env` with `WORKER_LLM_*` (the Gemma endpoint). `src/env.py` resolves it in order
  `$COCKPIT_ENV` → `./.env` → `~/.claude/lib/improver/.env`. Missing → the right
  lane errors; `doctor` says so.

## The one invariant that must not break
Raw repo file bodies never enter Gemma's PERSISTENT chat history.
- consult (ChatGPT reads): `run_commands` output goes only to the ChatGPT tab and
  the middle lane — never to Gemma.
- forward: crosses only ChatGPT's answer text, capped 8KB.
- explore (Gemma reads locally): the deliberate exception — repo bytes enter a
  TRANSIENT sub-context that is discarded; only the distilled final answer joins
  the persistent history.
Touch the explore loop or `/forward` → preserve this. It is why Gemma's small
context survives. Rationale: `_dev/decisions.md` (2026-07-01).

## Conventions a newcomer gets wrong
- All runtime code lives in `src/` (server / gemma_chat / env + static); the repo
  root holds only entry/meta (`run.sh`, README, SKILL, CLAUDE). Put new modules in
  `src/`, not the root.
- `nav`/`ask`/`cdp` are IMPORTED as a library from the chatgpt-web skill
  (`COCKPIT_SCRIPTS`), not vendored here. Do not copy or edit them in this repo —
  fix upstream in chatgpt-web.
- All CDP tab access is serialized onto the single tab-controller thread in
  `src/server.py`. Never call `ws.*` from a request handler or a Gemma thread; hand
  work to the controller. Gemma chat/explore are network-only and safely concurrent.
- Governance lives in `_dev/` (STATUS / decisions / TODO), the owner's convention —
  not `docs/`.
