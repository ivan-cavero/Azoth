# Live status

Everfall. Private New World server. The Rust tree in `server/` was removed
on 2026-10-25. Inventory: `research/atlas/meanings.md`. How we rebuild:
`docs/PLAN.md`. Command: `python ef.py`.

## Now

The Python gateway, Python world, and Caddy are the measuring lab
(`python ef.py dev`). They can still put a client into a world by sending
captured traffic. That is a rig, not the game.

**The lab runs 1.460 now.** On 2026-10-26 the private copy was refreshed from
Steam (`patch-dtls-disk.py restore`, then `apply` at site `0x145DCF9F5`) and it
reproduces the recorded patched hash `97f17df3…` exactly. Install and lab copy
are the same build for the first time: `1.460.6033.6024067`, `30fe6461…`.

## Measured run, 2026-10-26 10:00

The first live ladder on 1.460, launched **without** the Frida patch set: the
`-Watch` set kills the client inside `frida-agent.dll_unloaded` at offset
`0x9c7e0`, `0xc0000005`, which is the execute-after-unload race already on
record. Natural ladder, no forced gate. Evidence in
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

**Rung 15 is confirmed on 1.460**, and it closed itself with no forced gate.
**Auth is no longer the wall**: the persona login completes and the gateway
answers tokens and entitlements. The client reaches the character screen and
renders it (`Azoth_Dev`, Windsward).

**The wall is rung 17.** The world sent the spawn six times — `0x8` bundles of
exactly **46,407 bytes** (seq 86, 89, 90, 91, 102, 108), the size the atlas
records — and the client never logged `player spawn succeeds`; its own state
machine timed out after ~120 s. So the captured spawn satisfies 1.400 but not
1.460. The older note that this ladder reached `InGame` on 1.460 does not
reproduce today; what reproduces is the sequence above.

## Named, 2026-10-26

Two ladder wire types had no name and now do, through the client's own
registration hook, walked backwards from GUID to name and validated on the two
proven controls (`0x663`, `0x65c`) before either was trusted:

| Wire | Name | Trait |
| --- | --- | --- |
| `0x651` | `ReceivePlayerSpawnPointMsg` | `ClientViewListenerTrait` |
| `0x18a6` | `GridTrackingComponentClientFacet_UpdatePhasing` | `ClientMessages` |

`0x651` is 4 bytes: the typed header and no body, so the record is the whole
message. `0x18a6` is the 40-byte periodic record the atlas called "the periodic
counter"; its fields stay unnamed. Both carry their full evidence chain in
`meanings.md` and the ontology. The same pass fixed seven of eleven `ef.py re`
workflows, dead since the kind-layout reorg.

## Next

**Find what rung 17 reads that the captured spawn does not supply on 1.460.**
The bundle arrives, at the right size, so this is an interior question and not a
transport one. The atlas already names the debt: the spawn's 48 fragment
boundaries are "closed as underdetermined". Start by re-deriving the 1.460
`[carrier+0x252]` setter and diffing it against the 1.400 one. Nothing external
blocks this: auth works and the ladder walks to 17.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename the
in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
