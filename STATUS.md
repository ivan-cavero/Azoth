# Live status

Everfall. Private New World server. The Rust tree in `server/` was removed
on 2026-10-25. Inventory: `research/atlas/meanings.md`. How we rebuild:
`docs/PLAN.md`. Command: `python ef.py`.

## Now

The Python gateway, Python world, and Caddy are the measuring lab
(`python ef.py dev`). They can still put a client into a world by sending
captured traffic. That is a rig, not the game.

**The lab runs 1.460 now.** On 2026-10-26 the private copy was refreshed from
Steam (`patch-dtls-disk.py restore`, then `apply` at `0x145DCF9F5`) and reproduces
`97f17df3…` exactly. Install and lab copy are the same build for the first time.

## Measured run, 2026-10-26 10:00

Launched without the patch set, which is what the run below records. Evidence in
`.azoth/logs/runs/run-20261026-1460-ladder/`.

Rungs 14→17 in order: `StartREPConnection` → `WaitingForREPConnection` → (15)
`WaitingForActorGameConnection` → (16) `WaitingForSpawnPoint` → (17)
`WaitingForPlayerSpawn`, then `OnCampfireLoginComplete, ownership=permanent`, then
`State(WaitingForPlayerSpawn) is timeout: frames 10` → `Disconnected`.

**Rung 15 is confirmed on 1.460** and closed itself with no forced gate. **Auth is no
longer the wall**: the persona login completes and the client renders character select.

**Rung 17 is passed and the world renders** (2026-10-26). The 120 s timeout was never
the bundle: `ClientContext::Initialize` self-cleans when a predicate returns 0, so
every bundle was dropped with `clientContext == nullptr`. The world-phase patch set
fixes that — and the 1.460 ladder runs **never applied it**, because the launcher only
runs it under `-Watch`. With `python scripts/session/private-run.py --settle 55` plus
`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` (read at import: restart the world), one run
gives `player spawn succeeds`, `InGame`, **26 `Slice:` lines**, 0 `Cleanup()`, 0 errors,
and Windsward on screen with the player possessed.

## Named, 2026-10-26

Two ladder wire types had no name and now do, through the client's own
registration hook, walked backwards from GUID to name and validated on the two
proven controls (`0x663`, `0x65c`):

| Wire | Name | Trait |
| --- | --- | --- |
| `0x651` | `ReceivePlayerSpawnPointMsg` | `ClientViewListenerTrait` |
| `0x18a6` | `GridTrackingComponentClientFacet_UpdatePhasing` | `ClientMessages` |

`0x651` has no body; `0x18a6` is a 40-byte periodic record with unnamed fields. **The
type table is one name per wire**: all 3,390 named types carry a single answer, because
the "ambiguity" was the reader taking eight qwords from the table base instead of the
lambda's own 48-byte row. No settled name changed.

The spawn's **48 fragments are named too**: a fragment's second varint is a type-table
index, so the hook names it — 47 distinct types, all `*ReplicatedState`. The boundaries
are not derivable from the bytes, because a fragment has no length field at all; they
were measured live. The position is in fragment 36, `ALCReplicatedState`.

## Next

**Name the fields of `0x5de`, the first interaction message.** The flag hunt this file asked
for is done, and it came back negative in a useful way: opening the inventory or the skills
panel, sheathing, `q`/`r`/`f`, `lshift`, numpad loadouts, `e`, `1` send **no typed message at
all**, and the ALC body's change is structural, not per-key — **283 bytes with the position
marker at 91 idle, 298 with it at 94 when a panel is open**, so the 15-byte growth shifts
everything after it by 3. That is why a byte map reported 133 "fields" that were one region.

The twelve menus a player names are all server-backed: **564 client→server messages** across
179 facet families. `AttributeComponentServerFacet_RequestSpendAttributePoints` `0x5de` goes
first because the character panel already renders 239 points with `+` buttons in a session
that runs today, and because `Attribute` has **zero** reply messages — the server confirms by
changing replicated state.

Plan, order and per-system method: `research/docs/INTERACTION-DECOMP-PLAN.md`.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename the
in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
