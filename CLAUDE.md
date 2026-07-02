# consult-cockpit — repo memory

3-lane browser cockpit: a worker LLM (any OpenAI-compatible endpoint; today a
local Gemma) and a reader (today the signed-in web ChatGPT over CDP) both explore
a repo; you watch "who reads which file" and hand results between them. What/why
is in README.md and SKILL.md; this file is only what a fresh session gets wrong.

## Run / check
- `bash run.sh [repo]` — launch (default repo = cwd), opens localhost:8079. The
  repo field is editable in the UI, so one instance can point anywhere.
- `bash run.sh doctor` — validate the four prerequisites; run before first use or
  on a new machine.
- No build, no venv, no pip. Stdlib only, any python3 (3.9+).

## Prerequisites (easy to miss)
- The scrape reader (chatgpt-web + dedicated Chrome :9333, signed into ChatGPT) is
  OPTIONAL: without it the cockpit runs worker-only (/consult returns 503). This
  repo does not manage sign-in; Chrome autolaunch is off (`ask.py up` starts it).
- Worker config: `WORKER_LLM_BASE_URL/_MODEL` in a `.env` (`src/env.py` resolves
  `$COCKPIT_ENV` → `./.env` → `~/.claude/lib/improver/.env`). The API key resolves
  explicit env var > keychain (`bash run.sh auth set worker`) > .env value — a key
  in a stale .env does NOT beat the keychain (env.from_live_env/_injected). doctor
  prints which source won.

## The one invariant that must not break
Raw repo file bodies never enter the worker's PERSISTENT chat history.
- consult (the reader reads): `run_commands` output goes only to the reader tab
  and the middle lane — never to the worker.
- forward: crosses only the reader's answer text, capped 8KB.
- explore (the worker reads locally): the deliberate exception — repo bytes enter
  a TRANSIENT sub-context that is discarded; only the distilled final answer joins
  the persistent history.
Touch the explore loop or `/forward` → preserve this. It is why the worker's small
context survives. Rationale: `_dev/decisions.md` (2026-07-01).

## Conventions a newcomer gets wrong
- All runtime code lives in `src/` (server / llm_client / env / secrets_store /
  repo_fetch + static); the repo root holds only entry/meta (`run.sh`, README,
  SKILL, CLAUDE). Put new modules in `src/`, not the root.
- `nav`/`ask`/`cdp` are IMPORTED as a library from the chatgpt-web skill
  (`COCKPIT_SCRIPTS`), not vendored here — EXCEPT `src/repo_fetch.py`, a deliberate
  ownership fork of nav's pure repo-reading block (so worker-only mode needs no
  chatgpt-web). CDP fixes go upstream in chatgpt-web; repo-fetch fixes go in
  repo_fetch.py.
- Adding a provider dialect = one 4-field entry in llm_client.ADAPTERS
  (path/headers/payload/parse_line), not a class hierarchy.
- Routes are /worker, /worker-explore; /gemma* are legacy aliases slated for
  removal at public release (same branch — never duplicate the handler body).
- All CDP tab access is serialized onto the single tab-controller thread in
  `src/server.py`. Never call `ws.*` from a request handler or a worker thread;
  hand work to the controller. Worker chat/explore are network-only and safely
  concurrent.
- Governance lives in `_dev/` (STATUS / decisions / TODO), the owner's convention —
  not `docs/`.
