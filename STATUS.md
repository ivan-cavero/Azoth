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

The first live ladder on 1.460, launched **without** the Frida patch set: the
`-Watch` set kills the client inside `frida-agent.dll_unloaded` at `0x9c7e0`,
`0xc0000005`, the execute-after-unload race already on record. Natural ladder, no
forced gate. Evidence in `.azoth/logs/runs/run-20261026-1460-ladder/`.

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

**Rung 15 is confirmed on 1.460**, and it closed itself with no forced gate.
**Auth is no longer the wall**: the persona login completes, the gateway answers
tokens and entitlements, and the client renders the character screen
(`Azoth_Dev`, Windsward).

**The wall is rung 17.** The world sent the spawn six times — `0x8` bundles of
exactly **46,407 bytes** (seq 86, 89, 90, 91, 102, 108) — and the client never
logged `player spawn succeeds`; its state machine timed out after ~120 s. So the
captured spawn satisfies 1.400 but not 1.460. The older note that this ladder
reached `InGame` on 1.460 does not reproduce; what reproduces is the sequence above.

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

**Name the last field that blocks the port.** Types are settled (3,390 named) and the
delta format is measured: a payload opens with a presence mask, so an unset field is
*absent*, not stale. One thing blocks a Rust position encoder — the wire encoding of
the absolute quad. The client reads floats at `member+0x10`, the payload holds f32-BE
at +20, and how one becomes the other is unrecovered. Start there.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename the
in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
