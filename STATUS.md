# Live status

Everfall. Private New World server. The Rust tree in `server/` was removed
on 2026-10-25. Inventory: `research/atlas/meanings.md`. How we rebuild:
`docs/PLAN.md`. Command: `python ef.py`.

## Now

The Python gateway, Python world, and Caddy are the measuring lab
(`python ef.py dev`). They can still put a client into a world by sending
captured traffic. That is a rig, not the game.

Client build under study: **1.460.6033.6024067** —
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.
That is the executable installed here, measured 2026-10-25, so no address is
newly retired. `8654f01d…` is `1.400.6031.6004151`, and its addresses stay retired.

The ladder is a numbered state machine, 4..18, read from the client's own
state table at `0x1484fb420`. `research/atlas/meanings.md` carries the complete
map: every state, its transport, its wire type, its name and its size.
`research/derived/wire-type-names.json` is **candidate only**: its adjacency
heuristic is disproven, because it gives the proven `LevelInfoChangedMsg` GUID no
name at all. The reliable method is the client's own registration hook, and
`meanings.md` documents it.

## Next

**Rung 15 is closed, and it closed itself.** On 2026-10-22 at 19:22 local,
against the lab's own world at `127.0.0.1:9000` and on the same build string,
the client walked the whole ladder without a helper:

```
17:24:52.867  WaitingForREPConnection
17:24:54.085  start actor game connection    -> WaitingForActorGameConnection
17:24:54.251  actor game connection succeeds -> WaitingForSpawnPoint
17:24:54.285  spawn point found              -> WaitingForPlayerSpawn
17:24:55.794  player spawn succeeds, in game -> InGame
```

It then ran **229 s in-world with no crash and no disconnect**. Evidence:
`.azoth/logs/game-before-instance2-20261022-192626.log`.

The launcher console for that run was not captured, so "the forced ladder was
off" rests on two things: commit `608b52b` made it opt-in at 17:17 that evening,
and the forced path kills the client at ~34 s while this one lived 229 s. The
world's `world.log` for that window is gone, so the server half is inferred.

So the Carrier acceptance flight in `rep.py` (`carrier_state_datagram`:
CLOCK_SYNC, CONNECT_ACK, CT_ACKS) is **proven against the real client on 1.460**.
A private server does not need a self-identification body to pass rung 15;
`ClientAddEntryMsg` (`0xa4`) and `PlayerManagerSelfIdentificationMsg` are
preconditions for the spawn, not the transition.

## Live run, 2026-10-25

Attempted live; did not reach REP. **Auth is the wall, not the game.** Patched, the
client dies ~20-25 s after `IapClient: 14` (benign). Unpatched it survives to auth and
fails: `Omni CreateSession 201, id:` empty, then `@mm_authresult_Error_Persona`, with
config GETs but **no auth POST**. Detail: `builds.json` `live_run_2026_10_25_private_client`.

## Blocked by

Auth, as above. Nothing on the world-entry ladder. What remains there is
decompilation debt, not a blocker:

1. `0x663` is laid out to the byte, the two captured records are identical,
   and five field groups stay unnamed with the handler reading none of them.
2. `flow.world-entry.rung.self-identification.body`: the wire type is settled
   (`0x65c`, measured), but the 21-byte lab body is not the real one. The replay
   record is 12,706 bytes and the struct model lands off by one byte.
3. No type in the official replay is nameless any more: `0x40a` and `0x1be` are
   `CalendarConnectedMsg` and `CoatlicueTimingConfigurationConnectedMsg`, and
   `0x5b2` is `ObjectivesComponentServerFacet_UpdateTrackedObjectives`.
4. The spawn's 48 boundaries are closed as **underdetermined**: the small variant
   makes the walk exhaustive and admits one degenerate path.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename
the in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
