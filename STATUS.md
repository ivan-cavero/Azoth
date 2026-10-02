# Azoth — live status

Last updated: 2026-10-02. This is the short project dashboard; detailed world findings live in [WORLD-INVESTIGATION.md](research/docs/WORLD-INVESTIGATION.md).

## Current state: **the world renders and the player is in it**

On 2026-10-02 the client entered `NewWorld_VitaeEterna` and rendered the world with
the local player possessed (fresh PID 25952, REP session 232). The blocker that had
held the project for weeks — the local player was never possessed, so the frame stayed
black — is **solved**. The cause was a single redacted identity in the replayed
capture, and the fix is one targeted substitution.

| Signal | Before | After |
| --- | --- | --- |
| gate status 1 (`writerStatus1`) | 0 | 2 |
| manager context setter (`managerSetContext`) | 0 | 2 |
| manager `+0x08` / `+0x10` | null | `0x20e4df0a800` / `0x20cd63a8eb9` |
| record-1 slot `state+0x618` | null | non-null |
| portrayal-table inserts | 148 | 226 |

Evidence: `research/sessions/world_20261002T065937Z_pid25952_session232/`.

## The fix

**`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`** (default `off`).

The local-player gate compares the UUID carried by a `PlayerComponentClientFacet`
record against the character UUID in the client's local option store. In the captured
replay **every player's facet carries that UUID in clear text except the capture
author's own, which is redacted to zeros** — and that record is the one that has to be
ours. The slot is unambiguous: it is a redacted 16-byte span immediately followed by
the length-prefixed display name of the same record (`<16 zero bytes> <len> <name>`).

Implementation: `javelin/replay_store.py::fill_local_player_uuid`, wired in `rep.py`,
tests in `services/world/tests/test_local_player_uuid.py` (8 unit + capture fixtures).
It fills exactly one span in each of the 25 large state bundles, nothing in the
interest=91 bundles and nothing in the other players' bundles.

## What is NOT done yet (the new frontier)

1. **No movement.** `WASD` changes nothing: the client emits a constant ~21 msg/s
   regardless of input, and the game window does have keyboard focus (measured
   2026-10-02). The player is a replica the client renders, with no input-driven local
   controller bound.
2. **No inventory.** 23 `RMIDispatch` errors: `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`
   targets facet ids that do not exist locally.
3. **26 `slices/remoteplayer.dynamicslice` warnings** — "Couldn't get Transform
   component on the slice!" — for the other players' actors.
4. **`State(InGame) is timeout` every 30 s** persists (`patch-timeout-watchdog.py`
   covers a different site than the one reporting).
5. The **37** `status=fail` rows in the code corpus are still untried with a longer timeout (verified against the `.idx` files; an earlier revision of this file said 25).

Each world A/B needs a fresh `NewWorld.exe`. Do not use Frida or ReadProcessMemory
while EAC is active.

## Start here

1. Read [the decompilation plan](research/docs/DECOMP-PLAN.md) for the long-term program (code corpus, PAK index, loaders, protocol captures).
2. Read [the decompilation backlog](research/docs/DECOMP-BACKLOG.md) for **everything still open** — code-corpus debt, the PAK method-15 codec, the index tool, the named loaders, the protocol-capture deadline, the world items that need RE — with blockers and a suggested order. Decompilation work is paused as of 2026-10-02; this is where it resumes.
3. Read [the world investigation](research/docs/WORLD-INVESTIGATION.md) for the measured frontier and closed hypotheses.
4. Use [the decompilation workflow](research/docs/DECOMPILATION.md) and `decomp.py` (one-shot is fine; the corpus no longer holds the project). Keep confirmed addresses in `research/derived/symbols.json`.
5. Keep confirmed wire facts in `research/atlas/`; regenerate `research/atlas/openapi.json` with `python az.py doc` after a play session and commit it.
6. For each live A/B follow [World debugging](research/docs/WORLD-DEBUGGING.md) — it now includes the attach-verification recipe and the instrument-control rule.

## Project map

- `services/`: gateway, REP/DTLS world server, launcher.
- `research/atlas/`: source of truth for endpoints, models, errors, levers, and observed traffic.
- `research/tools/reversing/`: static analysis and Ghidra automation; outputs go under ignored `research/derived/`.
- `scripts/`: game launch/input helpers and focused instrumentation; see [script index](scripts/README.md).
- `docs/`: project orientation and archived sessions; `research/docs/INDEX.md` is the RE entry point.

Historical sessions stay in `docs/sessions/`. Do not commit or overwrite existing user changes without an explicit request.
