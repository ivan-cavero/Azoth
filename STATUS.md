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
That is the executable installed on this machine, measured 2026-10-25, so no
address is newly retired. `8654f01d…` is the previous build, `1.400.6031.6004151`,
and its addresses stay retired here.

The ladder is now a numbered state machine, 4..18, read from the client's own
state table at `0x1484fb420`, and `research/atlas/meanings.md` carries the
complete map: every state, its transport, its wire type, its message name and
its size. Four rungs have verified wire forms — registration (`0x13` request then
`0x3` response), level info (`0x663`), and the spawn (`0x8`). Three are open, each
with a named reason: the actor rung (`0xa4` is the leading candidate), the
spawn's 48 fragment boundaries, and the presence head id.

The wire-type table is honest again. `scan-wire-names.py` had been unrunnable
since `private-client/` moved, and three naming defects on top of that gave 69
wire types a confident wrong name; wire 449 was one, and it is `AddActorMessage`
that belongs to slot 121. The table now names 2170 types, every lost name was a
fragment or a neighbour's, and the hand-verified anchors still reproduce exactly.

## Next

The last three rungs are **Carrier state, not messages**, and that closes the one
that was blocked. The official 1.460 `Game.log` shows the client leaving
`WaitingForActorGameConnection` on `actor game connection succeeds`, i.e. when
`[carrier+0xA0]` reaches 2, and leaving `WaitingForSpawnPoint` on `spawn point
found`, i.e. `[carrier+0xBC8]`. The getters are verified leaf functions at
`0x145A934A0`, `0x145A916F0` and `0x145A934F0`.

So a private server does not need a 21-byte self-identification body to pass rung
15: it needs the Carrier actor game connection to complete. `ClientAddEntryMsg`
(`0xa4`) carries the actor id and is a precondition for the spawn, and
`PlayerManagerSelfIdentificationMsg` is the player manager's spawn instruction;
neither is the transition.

The next real step is therefore to make the lab's Carrier reach actor-connection
state 2, and the atlas now says which flag that is.

## Live run, 2026-10-25

Attempted live; did not reach REP. **Auth is the wall, not the game.** Patched, the
client dies ~20-25 s after `IapClient: 14` (benign). Unpatched, it survives to auth
and fails: `Omni CreateSession 201, id:` empty, then `@mm_authresult_Error_Persona`.
The gateway got config GETs and **no auth POST**. Detail: `builds.json`
`live_run_2026_10_25_private_client`.

## Blocked by

One blocker left, and it is a transport one:

1. **The Carrier actor game connection must reach state 2.** That is what moves
the client out of rung 15. The lab has a Frida helper for the private client
(`services/launcher/runtime-tools/frida-rep-force-ladder.py`) that forces the flag,
but forcing it is not the same as the connection completing, so the real
handshake is still unproven.

The spawn's 48 boundaries are closed as **underdetermined**: the small variant makes
the walk exhaustive and admits one degenerate path, so searching cannot recover
them. The map itself is not blocked; see `research/atlas/meanings.md`.

The map itself is not blocked. Every state, transport, wire type, message name
and size is recorded in `research/atlas/meanings.md`, and the blocks several
messages share are documented there too.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename
the in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
