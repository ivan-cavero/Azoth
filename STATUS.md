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

```
09:59:55  Disconnected              -> QueryGameUpdateCheck
10:00:12  ObtainREPRequirements     -> StartREPConnection
10:00:12  StartREPConnection        -> WaitingForREPConnection        (14)
10:00:13  WaitingForREPConnection   -> WaitingForActorGameConnection  (15)  PASSES
10:00:13  actor game connection succeeds
10:00:13  WaitingForActorGameConnection -> WaitingForSpawnPoint       (16)  PASSES
10:00:13  spawn point found         -> WaitingForPlayerSpawn          (17)
10:01:51  OnCampfireLoginComplete, login successful, ownership=permanent
10:02:13  State(WaitingForPlayerSpawn) is timeout: frames 10, count 2
10:02:14  WaitingForPlayerSpawn     -> Disconnected
```

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

**Write the Rust wire crate.** The naming phase is done for everything a first crate
needs: 3,390 types named, the delta format measured (a payload opens with a presence
mask, so an unset field is *absent*, not stale), and the position quad closed — x/y are
`f32` big-endian on the wire, z is client-derived, and the delta is
`scale * (2*byte - 255) / 255`. Start `everfall-wire` with `LevelInfoChangedMsg` and
the `worldPosAbs` fragment, testing the meaning against the captured bytes.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename the
in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
