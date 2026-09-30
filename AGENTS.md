# AGENTS.md — Azoth

Hard rules for agents working in this repo. Single monorepo, no submodules.
Pre-monorepo history: repos archived on GitHub + branch `archive/pre-monorepo`.

**Language:** commits, comments, docs and technical artifacts are written in
English. Historical sessions (docs/sessions/) stay in Spanish as archives.

## Layout

```text
az.py            ← everything goes through here (python az.py gateway|caddy|game|mode|click|key|shape|doc|run)
services/        ← Python services: gateway/ (:8080), world/ (DTLS, pending), launcher/
research/        ← RE: atlas/, docs/, tools/, schemas/, fixtures/, sessions/ (raw gitignored)
deploy/          ← Caddy :443, certs, hosts switch (official/private)
scripts/         ← live game instrumentation (synthetic input, shape harness, OpenAPI generator)
docs/            ← index + architecture + historical sessions
```

## Screenshots: NEVER read the raw PNG

`orca computer get-app-state` returns ~700KB PNGs → `413 request body too large`.
**Before any `read` on an image:**

```bash
python scripts/shrink-image.py <capture.png>   # prints the path to read
```

If it still 413s: `python scripts/shrink-image.py <capture.png> "" 640`. The
`.small.jpg` files are disposable (gitignored).

## The atlas is the memory (research/atlas/)

1. **RE finding = atlas commit at the moment it happens.** `endpoints.json`
   (operation, method, path, query, auth, frequency), `models.json` (exact wire
   keys, types, required/optional, evidence = exe VA), `errors.json`, `levers.md`
   (debug levers). If it only exists in STATUS.md or the chat, **it does not exist**.
2. Guessed fields (not RE'd): `"evidence": "guessed"`. The gateway serves from the
   atlas; if they diverge, the atlas wins.
3. You spot a debug lever in memory (cvars, dumps, config keys) → write it to
   `levers.md` **now**, under "To investigate". Not "for later".
4. **Traffic capture is automatic.** Every gateway request/response is logged to
   `services/gateway/traffic.jsonl` (local) and summarized into
   `research/atlas/observed-endpoints.json` (tracked, one entry per endpoint
   family with a captured example). After a play session run `python az.py doc`
   to regenerate `research/atlas/openapi.json` and commit it. New endpoint family
   the client requests but we don't mock → gateway 404s it and logs it; that is
   the next work item.
   **Never truncate `traffic.jsonl` while the gateway is running** (e.g. rewriting
   it with Python to drop test lines): the gateway holds the file open in append
   mode and keeps writing at its old offset, so the capture silently stops. Stop
   the gateway, edit, restart it.

## RE method (what works, in order of value)

See `research/docs/DECOMPILATION.md` for the full workflow. Summary:

1. **xrefmap first** (`research/tools/reversing/xrefmap.py`): one pass over `.text`,
   persisted `{va: [xrefs]}` map. Per-query scans are O(n) and timeout.
2. **Strings and the AZ reflection registry**: the camelCase property names in the
   reflection block ARE the wire keys. A block with no xrefs is decorative.
3. **Ghidra headless** for the real unmarshaller: `research/tools/reversing/decomp.py`
   (Ghidra at `C:\Users\ivang\tools\ghidra_12.1.3_PUBLIC`). Output to
   `research/derived/decomp/` (gitignored, regenerable).
4. **Capstone for targeted parsers** (key order, types). Offset conventions:
   `.rdata`: `vaddr = fileoff + 0x1800`; `.text`: `vaddr = fileoff + 0xA00`.
5. **Game.log is gold**: state machine, URLs, RMI names. Ingest:
   `python research/tools/capture/nw_capture.py ingest --log <Game.log>`.
6. **NEVER ReadProcessMemory/Frida/debugger with EAC active** (ban). See
   `research/docs/EAC.md`. Memory only post-2027 or a private build without EAC.
7. Traffic capture: only against OUR gateway (hosts + local CA). Against Amazon
   there is no possible MITM (pinned TLS) and the official capture was noise.

## Test loop (without this you measure garbage)

- The gateway override (`services/gateway/mock_discovery/`, gitignored) lets you
  change bodies without restarting the gateway — but **the panel does not
  re-render**: restart the game (~2 min per shape).
- `Game.log` accumulates sessions: cut at this run's `Executable: NewWorld.exe`,
  or the test measures an old screen.
- Full A/B harness (override → restart → read the panel via orca screenshots): `python az.py shape <body.json>`.
- 400-probe A/B: HTTP 400 on getlogininfo advances the UI; 200-parse-OK does not.
- The model cannot read images: game screen = `az.py shot` (+ `shrink-image.py`).
- **Dev mode**: `python az.py gateway reload` runs the gateway with hot-reload —
  edit any file under `services/gateway/src/` and it restarts automatically.

### World attempts (the expensive loop)

- **One A/B = one fresh `NewWorld.exe`.** After a failed attempt the client destroys its
  `ClientContext` and never re-creates it in that process, so every later bundle is dropped with
  `clientContext == nullptr`. Restart the game for every measurement.
- The launcher's `-Watch` flow applies the in-memory patches automatically
  (`patch-predicate-flag.py`, `patch-timeout-watchdog.py`, spawn gate, anticheat, DTLS trust).
- **Verify the attempt happened before trusting any counter.** A world attempt is real when
  `Game.log` shows `ProcessPendingReliableMsgQueue processing 26 messages`. If it is absent, every
  Frida counter reads 0 and a working hook looks broken.
- **`AZOTH_LOG_RAW=1` on the world server** logs every inbound datagram before DTLS. Without it a
  failed handshake is invisible server-side, so "packets never arrived" and "DTLS rejected them"
  look identical.
- Restart the world server when its peer table has stale sessions; a client that reuses its source
  port is handled by the stale-session reset, but a long-lived server still accumulates dead peers.

## Python

- **stdlib only** in services/ and scripts/ (no pip, no pytest — `unittest`).
- Tests: `python az.py gateway test` (19) + `python -m unittest discover -s services/world/tests`
  (52) + `python services/gateway/tests/test_traffic.py` (3). Change → tests before commit.
- `src/` layout inside each service; entry: `python -m azoth_gateway`.
- Paths: **never hard-code** `C:\Users\...` or `F:\Azoth`. Everything relative to
  `__file__` / `%LOCALAPPDATA%`. The CLI (`az.py`) resolves from the repo root.
- Ruff configured; `contextlib.suppress` over `try/except: pass`.
- Code stays readable: one concern per route module, comments explain *why*
  (wire quirks), not *what*.

## Commits

- The user decides pushes; never commit without an explicit request.
- `mock_discovery/`, `traffic.jsonl`, `sessions/*` raw, `derived/decomp/`, certs,
  `hosts.*`, logs and `.small.jpg`: gitignored, never versioned.
- Live project state lives in STATUS.md (lean, ~35 lines) + the atlas.
