# Live status

Updated: 2026-10-09 (overnight session). Exact function evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json);
the consolidated wire reference is
[`research/docs/JAVELIN-PROTOCOL.md`](research/docs/JAVELIN-PROTOCOL.md) and the
message table is
[`research/atlas/javelin-messages.json`](research/atlas/javelin-messages.json);
what the client expects from the server, phase by phase, is
[`research/docs/SERVER-CONTRACT.md`](research/docs/SERVER-CONTRACT.md); how to
bring up and patch a private run is
[`research/docs/PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).

## Active objective

Make the local player move in the private client. **Entry to the world, the
rendered world, the possessed player, and a stable session are all solved and
reproducible.** Movement is the only open failure, and its cause is now known
(see below).

## Confirmed

- **The private run works end to end (2026-10-07).** With the runbook sequence
  the world renders and the player is possessed: `Initialize()` without
  `Cleanup()`, `player spawn succeeds, in game`, `InGame`, physics active.
- **The session is stable, and two more causes of the ~27 s drop are fixed
  (2026-10-10).** Verified live: a run held the world for **2 h 06 min** with
  `transportError` 0, `disconnected from REP` 0 and `OnLocalNetworkConnectionWarning`
  1, against 27 s and a warning count of 22 before the fixes. The world renders
  with the player, the NPCs and the full HUD
  (`research/sessions/2026-10-10/`).
  1. **The activity clock no longer waits for the replay.** The `0x15d` heartbeat
     and the `0x1096`/`0x1097` input response both gated on the replay queue being
     empty, but the replay is ~1090 Carrier chunks and needs ~22 s at
     `AZOTH_CHUNK_GAP_MS=20` — inside the client's ~27 s watchdog. The session log
     had **zero** `heartbeat` and **zero** `input-response` events. They now run
     concurrently with the replay, which is what the capture shows the real server
     doing. The state stream still waits: it re-applies the same captured bundles,
     and double-applying state is not idempotent client-side.
  2. **16-bit wire fields now wrap.** The server's envelope sequence was unmasked,
     so once `next_out_seq` passed 65535 the keepalive raised
     `OverflowError: int too big to convert` and stayed dead for **two hours**
     (7395 consecutive tick errors). Every 16-bit field now goes through `_u16()`,
     and a `tick-error` logs a traceback so a repeating error names its function.
- **The server now emits on its own clock.** Every periodic emitter used to be
  called from `on_app_data` (once per inbound datagram), so server output scaled
  with client input: measured `Pearson(inbound, outbound) = 0.995`, peak 286
  datagrams/s, amplification 3.4:1. `PeerSession.tick()` now runs from the UDP
  loop at `TICK_HZ` (50) whether or not a datagram arrived. After: Pearson
  **0.180**, amplification **0.96:1**, peak **99/s**, `v3-registered` 8 -> **1**.
  `TestAuthoritativeTick` fails if a periodic emitter is ever called from
  `on_app_data` again.
- **Three server defects that made the loop stall itself are fixed** (each was
  the `transportError 4` red cable): the event log reopened a ~90 MB file per
  event (measured 27 s of silence under a 287-record burst); every ACK was a
  separate datagram (1:1 with inbound); and the post-replay heartbeat was
  retried to its 6-try cap (1106 heartbeats produced 5437 resends, 46% of all
  outbound traffic).
- **Private-run gates 1-8b** (see the runbook). Three fail silently: Caddy CA
  trust, the DTLS pin, and the server settings below.
  - Gate 5 (black screen) = the ClientContext predicate.
  - Gate 6 (no player) = server env `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`.
  - Gate 7 (red cable/timeout) = server env `AZOTH_REPLAY_INPUT_RESPONSE=1`.
  - Gate 8 (post-spawn transport drop) = `AZOTH_CHUNK_GAP_MS=20`.
  - Gate 8b (resend storm) = `AZOTH_RESEND_INTERVAL_S=1.0`.
- **The launcher was dead on PowerShell 5.1** (`$PSScriptRoot` inside a `param()`
  default), and `az.py`/`private-run.py` both use `powershell.exe`, so the whole
  documented run path was broken. Fixed 2026-10-09.
- **The protocol is now decoded at the container level** (2026-10-09), with
  tests rather than prose:
  - The **prefix varint** every typed message and bundle field starts with.
    `services/world/src/azoth_world/javelin/varint.py`; 137/138 captured message
    types round-trip.
  - The **type-0x08 StateBundle** body, byte-exact: 78 of 79 captured bundles
    consume their body exactly. `javelin/bundle.py`.
  - The **message registry**: all 144 message types with GUID and wire type,
    `research/atlas/javelin-messages.json`. All 12 movement wire types reproduce
    from two independent derivations.
  - The **replication gate**: a bundle is accepted only when its instance id
    matches and its counter exceeds the client's high-water.
- **Warnings in a clean session are few and all benign**: 26 x Slice transform
  (0-component `remoteplayer` slices), 25 x RMIDispatch facet-not-found, 1 x
  `RequestGetPlayer: empty characterId`, 1 x benign physics note, 1 x
  `XDllSingleton already instantiated`.
- Input delivery is verified: scan-code `SendInput` reaches the client, mouse
  look rotates the camera, and the UI consumes keys. WASD still does not move the
  player: measured 2026-10-10 in the stable session, holding W for 2 s gave a
  motion ratio of 0.18x with the scene pixels identical between captures.
- **The client is confirmed to consume our post-replay traffic (2026-10-10).**
  Hooking the type-resolution function `FUN_1461acfe0` on a live session shows
  the client resolving exactly three type ids in a repeating cycle, and they are
  the three messages the server sends after the replay: index 349 (`0x15d`,
  PingMsg — the heartbeat), and 4246/4247 (`0x1096`/`0x1097` — the input
  response). That is the mechanism behind the stability fix below.
  **Negative result:** the same hook shows `FUN_1461acfe0` resolves *typed
  message* types, so `FUN_146af2340` cannot be assumed to be the state-bundle
  fragment reader, and the constant `key=1`/`type=1` across all 79 captured
  bundles is now suspect — a field that never varies is more likely a constant
  header than a type index. The fragment codec needs re-derivation with a signal
  that is not shared with the heartbeat path.
- **The `inject` lever is validated end to end.** A type-0x08 StateBundle built
  from scratch by `javelin/bundle.py` was accepted by the live client with no
  error, which is independent proof that the container layout is right. A
  `StartMovementCommunicationMsg` (`0x2d6`) with an empty body was also accepted,
  proving the type and framing. **Negative result:** a bundle carrying an unknown
  fragment `type_index` is dropped *silently*, so the client log is not a usable
  signal for "does the client know this fragment type" — future codec work needs a
  Frida hook or an observable state change instead.
- Tests: **109 world**, **24 gateway**.

### Movement: the client never emits anything (measured 2026-10-10)

Holding W for 2 s in a stable in-world session produces **no movement message in
either direction**. Decoding every client->server record in that window gives
zero `StartMovementCommunicationMsg`, `AckMovementMsg`, `CommitMovementMsg`,
`MoveActorMsg` and `ReceivePlayerPositionClientMsg`. The channel-1 local-player
stream (119/120 B, actor `1a954abc…` at offset 8, raw payload with no typed
marker) is **byte-identical across 3038 records** taken while W was held: masking
the rolling 4-byte counter at offset 0, only two bytes ever differ (offset `0x31`
and `0x4e`). No position, no orientation, no velocity. The client's own
`teleport_player` command (T) does not move the player either.

So the client is not simulating movement and failing to send it — **nothing moves
in the client at all**. That matters for the fix: the server cannot unblock
movement by *replying* to a client message, because the client never sends one.
The server has to cause the body to exist.

### Movement blocker (re-measured; the earlier diagnosis is corrected)

The client broadcasts its local-player state on channel 1 (type `0x635`) and the
server answers only on channels 0 and 3. The capture contains **no movement
message in the server->client direction at all**, so the reply must be
constructed server-side.

**The measured cause is that the client never reaches its own movable-body
gate.** `FUN_141763b70` — the function that would create the local player's
`GameTransformComponent` and set up the body — ran **exactly once, at process
startup, before the world was entered**, and its creator `FUN_141582430` was
**never called** during login, spawn, or the first minutes in world
(`local_body_gate_never_runs_20261003_2250`). So the gate is not failing; it is
not reached. Nothing points at it statically, so it is reached through a
delegate/virtual dispatch that no current server message triggers.

**Correction to the earlier "the player has no physics component" conclusion —
and it was worse than a partial correction.** The GUID list in
`local_player_has_no_physics_20261004` is **shifted by one entry**, and
`physics_component_guids_corrected_20261005` fixed only four of them, so the
record still disagreed with the binary. The shift: the old list gave
`GameRigidBodyClientFacetConfig` = `{0BCAB3AC…}` (that is `GameRigidBodyConfig`),
`GameRigidBodyServerFacetConfig` = `{0E0EDECA…}` (that is
`GameRigidBodyClientFacetConfig`), `GameRigidBodyComponentBase` = `{0C1F07A3…}`
(that is `GameRigidBodyServerFacetConfig`), and `CharacterControllerConfig` =
`{824E1E63…}` (that is `RockNRoll::CharacterSupportInfo`). And
`{B1237004-14E1-4327-8774-D2C5796230E7}`, recorded as `CharacterPhysicsComponent`,
**does not exist in this build at all**. The verified registry is
`research/atlas/az-type-registry.json` (4814 names, 4818 entries, 750 in the type
table), regenerated and checked by `reverse/tools/scan-az-types.py`.

**Consequence: the "no physics component" conclusion is UNPROVEN, not
established** — it was reached by searching for ids that do not exist. What
remains proven is only that the player **prefab** ships no physics component.

**Trap for anyone re-deriving these:** a loose scan for `<name> …<bare-guid>`
pairs a name with unrelated neighbours. It maps `Transform` to
`{5D9958E9-…}` (the AZ math struct) when the entity-component `Transform` is
`{484AE67D-…}`. Use the brace-wrapped `{GUID}` form only.

**The bundle call chain is now verified, not guessed.** `FUN_14643e7b0` (the
handler that logs `skipping ReceiveStateBundle`) → `FUN_146455e90` →
`FUN_14175ccc0` → `FUN_146af20d0` → `FUN_146af2340`, every edge a real call. The
call site shows `FUN_146af20d0` filling a **record id** and a **vector of fragment
objects** (not raw payloads — `FUN_146af2340` creates one object per fragment),
and `FUN_141717fc0` then indexes a handler table at
`state + 0x608 + record_id*0x10`. So the record id is a **handler index**, which
is why record id 1 is the local-player metadata slot.

**Where physics actually comes from.** The server replicates entities and
components through an **area-of-interest trait** system (`Amazon::Hub::Aoi`, 185
traits), as *records* carrying *fragments* — the `0x08` bundle. `PhysicsTrait`
owns state type `{F05E34C6-AF1E-476D-9472-5FC118FC4503}` and registers
`RegisterRigidBodyMsg` and friends. The by-name component creator
(`FUN_141416740`) was measured **never to run** during world entry, and the
capture's 79 fragments all carry `type_index` 1, so the replay never delivers a
rigid body either.

### The replication architecture, mapped (2026-10-10)

There are **three** message systems, and conflating them is what made the
protocol look opaque:

1. **AOI traits** (82 traits, 2276 trait/message pairs —
   `research/atlas/aoi-trait-registry.json`): server-side authority for entity and
   component state. A trait replicates state as **records carrying fragments**,
   which is what the `0x08` bundle transports. The record id selects a handler at
   `state + 0x608 + record_id*0x10`.
2. **Client messages** (1783 RMIs): component-facet method calls named
   `<Component><Client|Server>Facet_<Method>`. This is the system behind the live
   warning `RMIDispatch: The facet target ID couldn't be found` — the server calls
   a facet method on a facet the client does not have.
3. **Javelin typed messages** (144 — `research/atlas/javelin-messages.json`):
   session, hub and movement control, carrying a wire type number.

**The spawn protocol is now readable.** The client asks with
`PlayerSpawnPointRequestTrait::RequestPlayerSpawnPointMsg`; the server answers
with `ReceivePlayerSpawnPointSuccessMsg`; the manager runs
`ProcessSpawnQueueMsg`; and the body is created through
`PrefabSpawnRequestTrait::RequestSpawnPrefabMsg`. **Physics is registered
separately**, by `PhysicsTrait::RegisterCharacterMsg` /
`RegisterCharacterWithRepulsorsMsg`. `PhysicsTrait` alone registers **76**
messages, including `RequestCharacterSetPositionMsg`,
`RequestCharacterPositionDeltaMsg` and `RequestIsCharacterReadyMsg`.

So "give the player a body" is not one message: it is a spawn-point handshake, a
spawn-queue process, a prefab spawn **and** a physics registration — and the
capture contains only the first part.

### The state bundle is a RECORD SEQUENCE — corrected and verified (2026-10-10)

The `0x08` body is `[marker][01][varint SEQ][6 invariant bytes][varint length]`
then a payload that is a **sequence of records**, each
`[u8 record_id][u8 fragment_count][fragments…]`.

This replaced the earlier "one record, one fragment" model, which was wrong in a
way that passed every check it was given: it consumed all 79 captured bodies
exactly, because it treated the whole payload as one opaque fragment payload.
**"Consumes exactly" is necessary but not sufficient** — an opaque-remainder model
always consumes exactly, so that check cannot distinguish one fragment from many.

The discriminating evidence is the client's own reads. A live Frida probe on
`FUN_146af20d0` (one record) and `FUN_146af2340` (one fragment) measured, per
record, the bytes consumed and the number of nested reader calls, and:

- the `fragment_count` byte **equals the nested-call count in all 90 distinct
  records** (`01 30`→48, `01 09`→9, `02 03`→3, `03 01`→1, `0d 06`→6, `1d 13`→19);
- byte-exact on the 78-byte bundle: payload 66 bytes = **two records of 33
  bytes** (`48 03 …`, `49 03 …`), with the client measuring `consumed=33,
  fragments=3` for each;
- `record_id` is **sequential** across a session (1…`0x2e`, then `0x48`, `0x49`,
  `0x4a`) — a handler index, matching `state + 0x608 + record_id*0x10`;
- `SEQ` spans **1..53**, exactly the high-water the client logged live.

So the spawn record's fragment count is **48**, not 1. All 78 bundles round-trip
exactly through the new parser.

**The fragment grammar is also verified.** A fragment is
`[varint KEY][varint TYPE_INDEX][type-specific payload]` — **exactly two header
varints, no length field**. A live probe logging every varint read with its offset
shows the first two varints at offsets 0 and 1 in **300 of 300 fragments**, with 48
distinct keys and 47 distinct types and a **1:1** key→type binding. The keys are
sparse (0…77), which is a component slot table with freed slots, and the spawn
record has exactly 48 fragments with exactly 48 distinct keys. The payload length
is **implied by the type** (the reader consumes it through vtable `+0x90`), which
explains the variable fragment sizes.

**The container is now fully understood down to the fragment.** What remains is
the **per-type payload encoding** — one codec per component type. That is the
remaining long tail, and it is also what physics needs, since a physics component
would arrive as one of these fragments.

## Decompilation campaign

**50** targets in the committed manifest
(`research/atlas/decomp-campaign.json`: launch 3, login 2, server-select 11,
character-select 0, world-entry 12, in-world 22). Growth through `campaign add` /
`expand` now persists to that manifest instead of only to the ignored per-build
state, so it survives the machine. The bulk corpus remains complete:
423,579 `.pdata` ranges accounted for, **423,542 `ok` / 37 `fail`** (20 timeouts,
10 mid-function fragments, 6 payload-cap, 1 address-space), and it does **not**
cover the 13,943 leaf functions in `.text` that carry no unwind info.

## Next useful step

**Implement record/fragment replication, starting with `PhysicsTrait`.** That is
the single piece that unlocks both open goals: it is how the client is told to
give the local player a rigid body (movement), and it is how NPCs and any other
entity reach the client. The container is now understood and tested, so the work
is the fragment payload codecs — start by finding the reader the client installs
for a fragment type and reading its field order, exactly as was done for the
message types.

Also ready, in priority order:

1. A live run to settle whether re-applying a captured record is idempotent
   client-side (the state stream's open question).
2. Serve a real character UUID; stop sending RMIs for facets the client lacks.
3. The two unresolved wire types (`ActorQueryMsg`, `RoutingUnsubscribeMsg`).

Do not return to input/focus checks, connection stability, or gates 1-8b — all
solved and documented in `research/docs/PRIVATE-CLIENT-RUNBOOK.md`.

## Project structure

The game profile/runtime, PAK index, tools, and old logs live in ignored
project-local paths (`private-client/`, `.azoth/`, `reverse/builds/`).
