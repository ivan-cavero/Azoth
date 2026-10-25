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

Settle which wire type is `PlayerManagerSelfIdentificationMsg`, and prove the
body. The handler is done and its decoded struct is named, but the rung's wire
side is unproven. The competing `0x65c` candidate is now **eliminated**: measured
2026-10-25, wire `0x65c` is `LastSpawnedBotCharacterId` (slot 1628, GUID
`169443e0-…`, name NUL-padded immediately before the GUID in `.rdata`), so the
12,706-byte grid the replay carries is bot spawn data and the
`AZOTH_REPLAY_SELFIDENT_GUID` lever was retargeting a bot id. What remains is
`0x5d1`, whose type-table GUID `60a51dfc-…` is unnamed and which the replay does
not contain at all. A new hypothesis to test: self-identification may arrive on
the **actor game connection**, a separate GridMate connection from the REP
channel the replay dump covers.

## Blocked by

No live capture of a `PlayerManagerSelfIdentificationMsg` exists on any build,
so there is nothing to read the body from. The cheapest unblock is a passive
capture of one official login on 1.460 that includes this rung.

Second blocker, measured: the spawn's 48 fragment boundaries are not recoverable
from its bytes. A constrained search over the 29,721 offsets that parse as a
fragment header found no 48-fragment path ending exactly at 46,393 within a
2,000,000-node budget. Serving the captured spawn verbatim stays the only option
until the per-type fragment readers are decoded.

## Do not

Recreate `server/`. Send a datagram because a capture contained it. Rename
the in-game resource Azoth. Read `docs/archive/` or `docs/journal/raw/` whole.
