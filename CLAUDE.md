# consult-cockpit — repo memory

Single-lane agent-chat cockpit: a worker LLM (any OpenAI-compatible endpoint; today a
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
  `$COCKPIT_ENV` → `src/.env`). The API key resolves
  explicit env var > keychain (`bash run.sh auth set worker`) > .env value — a key
  in a stale .env does NOT beat the keychain (env.from_live_env/_injected). doctor
  prints which source won.

## The one invariant that must not break
Raw repo file bodies never enter the worker's PERSISTENT chat history.
- Every tool round (the worker's own fetch, the reader consult, the served
  contents) lives in a TRANSIENT working list inside `_run_worker`; only the
  user turn and the final answer join `_worker_history`.
- consult (the reader reads): `run_commands` output goes only to the reader tab
  (and byte-counts/names to SSE for the tool cards) — never to the worker's
  persistent history.
- forward: crosses only the reader's answer text, capped 8KB.
Touch `_run_worker`, the explore loop, or `/forward` → preserve this. It is why
the worker's small context survives. Rationale: `_dev/decisions.md` (2026-07-01,
2026-07-03).

## Conventions a newcomer gets wrong
- The human talks ONLY to the worker (one input, plus the `ask reader ▶` button
  for a direct consult). The worker has two tools (worker_system() in server.py,
  injected per-call, never stored):
  - fetch — reads the repo ITSELF whenever answering needs files (autonomous,
    cheap). STRICT trigger: only a real ```fetch fence counts (parse_fetch_block),
    so prose that mentions READ never fires a read. There is no explore button;
    the worker just reads. `/worker-explore` remains as a programmatic entry.
  - consult — asks the stronger reader, only on the user's EXPLICIT request
    (parse_consult_text → consult_once), answer fed back capped like /forward.
  Both tool rounds are transient (see the invariant). Touching that loop →
  preserve the invariant above.
- All runtime code lives in `src/` (server / llm_client / env / secrets_store /
  repo_fetch + static); the repo root holds only entry/meta (`run.sh`, README,
  SKILL, CLAUDE). Put new modules in `src/`, not the root.
- `scrape/` (nav/ask/cdp) is VENDORED for distribution (public users have no
  chatgpt-web skill). On dev machines the upstream skill still exists: fix CDP
  bugs upstream in chatgpt-web first, then re-copy into scrape/ — do not let the
  two copies drift silently. Resolution order: $COCKPIT_SCRIPTS → <repo>/scrape →
  ~/.claude/skills/chatgpt-web/scripts. `src/repo_fetch.py` remains the separate
  ownership fork of nav's pure repo-reading block.
- Adding a provider dialect = one 4-field entry in llm_client.ADAPTERS
  (path/headers/payload/parse_line), not a class hierarchy.
- Routes are /worker, /worker-explore (the /gemma* aliases were removed for the
  public release).
- All CDP tab access is serialized onto the single tab-controller thread in
  `src/server.py`. Never call `ws.*` from a request handler or a worker thread;
  hand work to the controller. Worker chat/explore are network-only and safely
  concurrent.
- Governance lives in `_dev/` (STATUS / decisions / TODO), the owner's convention —
  not `docs/`.
