# Meanings

This is the inventory of what a New World server has to mean, taken from the
Rust workspace the day it was deleted (2026-10-25). The code remains in git
history under `server/`. A new server may send a message only after its row
here says the fields are understood.

The Python gateway and world under `services/` are the measuring lab. They may
still emit a captured blob. That blob is not a model of the game.

Client build this inventory was taken against: **1.460.6033.6024067**,
SHA-256 `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

Evidence words: **measured** (seen on a live client or capture), **partial**
(we know the role, not the fields), **unknown** (bytes we cannot name).

## The type-id prefix

A typed record on a data channel is `[vlq32 length][00 01][type][body]`. The two
bytes after `00 01` are not a little-endian integer. They are a prefix varint:
the number of leading 1-bits in the first byte is how many continuation bytes
follow, and those continuation bytes are a little-endian integer placed above
the first byte's low bits.

    n = leading 1-bits in b0        shift = 7 - n
    value = (LE(continuation) << shift) | (b0 & ((1 << shift) - 1))

| Type | Bytes | Check |
| --- | --- | --- |
| `0x5d1` | `91 17` | n=1, low=0x11, cont=0x17: 23<<6 \| 17 = 1489 |
| `0x65c` | `9c 19` | n=1, low=0x1c, cont=0x19: 25<<6 \| 28 = 1628 |
| `0x663` | `a3 19` | n=1, low=0x23, cont=0x19: 25<<6 \| 35 = 1635 |
| `0x1b88` | `88 6e` | n=1, low=0x08, cont=0x6e: 110<<6 \| 8 = 7048 |
| `0x13` | `13` | n=0: 19 |

Measured: the bytes in the second column are the ones in the headers of the
official 1.365 replay (`services/world/replay/messages-redacted.txt`, files
`T0x65c`, `T0x663`, `T0x1b88`, `T0x13`). The implementation is
`services/world/src/azoth_world/javelin/varint.py`, whose docstring derives it
from the reader `FUN_14087b5c0` on the previous build and round-trips 137 of 138
captured message types. The old note that read `91 17` as the little-endian
integer `0x1791` was reading the varint backwards; the two bytes are the type
`0x5d1`, not a number.

## Names

| Word | What it is |
| --- | --- |
| Everfall | This project: a private New World server |
| New World | The game. The stock client is the contract |
| Azoth | A resource inside the game. Also the previous name of this project. Not the server |
| `.azoth/` | Local tools, logs, and the pinned Python. The path stays so existing checkouts keep working |
| `azoth_gateway`, `azoth_world` | Import names of the Python lab. Not crate names |
| `ef.py` / `lab/` | The command that starts and stops processes |
| `services/` | The measuring lab: HTTP gateway, DTLS replay, private-client launcher |
| `server/` | Absent. A Rust crate appears only after a row below names its fields |

## Unnamed, with ids

Every byte we cannot name has an id. The set does not grow without a new id.
Naming a field removes it from this list. None of these ids is a gameplay noun.

| Id | What is still unnamed | Evidence |
| --- | --- | --- |
| `flow.channel.document` | The channel HTTP document the client needs before login. Identity does not belong in it. | partial |
| `flow.region.captured-body` | Login, entitlements, world list, and ticket JSON that still copies an official response | unknown bodies |
| `flow.world-entry.rung.registration.body` | Registration response, wire type `0x3`, 88 bytes. **Parsed**: typed header, `u32` zero, `0x0b`, 8 bytes, 32 redacted bytes, then the 36-byte server version string `#[RETAIL].Javelin.<version>`, then `01 00 00 01`. The version string is the named field; the rest has no second signal. | version string verified, rest partial |
| `flow.world-entry.rung.greetings.body` | GridMate greeting. Not a game event. | partial |
| `flow.world-entry.rung.self-identification.body` | The 21 bytes the lab carries. Not one byte is proven: the only live test of this body was a two-rung burst that raised an access violation on 1.400, and the wire type is a candidate in both directions. The client handler is decompiled and its decoded struct is named, but the handler never sees the wire. | handler named, wire type and body unproven |
| `flow.world-entry.rung.level-info.unexplained` | The part of `LevelInfoChangedMsg` (`0x663`) that is not the level name, the path, the four floats, or the context key: the `u64` at `0x48`, the four flag bytes at `0x50`, the per-record nonce at `0x54`, and the ten-byte group at `0x5c`. The handler reads none of them, so they are either consumed by the deserializer or ignored. | partial |
| `flow.world-entry.rung.spawn.body` | Spawn record id 1. The record and its payload layout are now verified against the official replay; what stays unnamed is the interior of the 48 fragments. | layout verified, fragments unknown |
| `flow.world-entry.rung.state-stream.body` | The resend of that spawn, about once a second. The quiet cable is measured. The body is the spawn. | measured effect |
| `flow.world-entry.presence.fields` | Add-actor fanout. The head is a proven 16-byte fixed read but not a proven ActorGuid, and the tail offsets are known while their meanings are not. | partial |

## What the client walks

The client does three different jobs against three different programs. Mixing
them into one process is how a private server becomes a pile of routes.

| Program | Job | What we actually know | Lab today |
| --- | --- | --- | --- |
| Channel | HTTP document that gets the client to the login screen: channel list, news, images, cache validators | The client will not continue without it. Identity does not belong here. | Python gateway |
| Region | Who you are: token, credentials, entitlements, login info, world list, queue ticket | The route list is real. Many JSON bodies are still the shape the official servers returned, not values this project owns. | Python gateway |
| World | Gameplay over DTLS. One UDP socket, a 50 Hz tick, then the entry ladder below. | The tick rate and the datagram ceiling are measured. The bodies of the ladder are mostly captured. | Python world |

A captured HTTP body is allowed in the lab so the client can be opened and
observed. It is labeled unknown until someone writes the fields down here.

### How a rung handler receives its message

Every rung handler in this family is a virtual method of the player manager and
receives an already-decoded struct, never bytes. The self-identification
handlers sit in one vtable: `0x1484fdb78` holds the adjustor thunk
`0x146455eac` for `FUN_146455ec0` (self identification) and `0x1484fdb88` holds
`0x146447aa8` for `FUN_146447ac0` (level info).

The struct keeps the wire order, and the two container members expand:

| On the wire | In the struct |
| --- | --- |
| a length byte then the characters | a 32-byte `std::string` |
| a count then the elements | a 24-byte `std::vector` |

That is why level info is 110 wire bytes and a struct past `0xb0`, and why a
21-byte self-identification body corresponds to a `0x38`-byte struct. The
correspondence is a model read off two handlers, not a proof for a third: the
self-identification body order stays a candidate until its own decoder is read.

## World entry ladder

Order is part of the meaning. Sending two rungs in one burst crashed the
client. Sending them out of order leaves the client stuck with no error.
Each rung is valid only in the state the previous rung produced.

### The ladder is a numbered state machine

`GameConnectionWrapper` keeps its state in an int at `this + 0x1530`, and
`FUN_14644b330` dispatches it with `switch (state - 4)`. Every transition logs
`Update state %s to new state %s`, resolving both names through one table at
`0x1484fb420`, indexed by the state number itself:

| State | Name | What moves the client out of it |
| --- | --- | --- |
| 4 | `Disconnected` | — |
| 5 | `QueryGameUpdateCheck` | HTTP |
| 6 | `WaitingForGameUpdateCheck` | |
| 7 | `QueueGameLogin` | HTTP |
| 8 | `WaitingForQueuedLogin` | |
| 9 | `QueryForRemoteConfigClass` | HTTP |
| 10 | `WaitingForRemoteConfigClass` | |
| 11 | `ObtainREPRequirements` | HTTP |
| 12 | `WaitingForREPRequirements` | |
| 13 | `StartREPConnection` | DTLS begins here |
| 14 | `WaitingForREPConnection` | the registration response, 88 captured bytes |
| 15 | `WaitingForActorGameConnection` | self identification |
| 16 | `WaitingForSpawnPoint` | level info |
| 17 | `WaitingForPlayerSpawn` | the spawn record |
| 18 | `InGame` | — |

The transition helper `FUN_146467910(this, n)` sets the state to `n + 4`. Read
as a whole this is the whole ladder, numbered, from the client's own strings:
no rung number is guessed.

### The first typed exchange, measured

The official 1.365 replay holds 177 records. In sequence order its opening is,
with the names the fixed scanner now resolves:

| seq | dir | type | bytes | name |
| --- | --- | --- | --- | --- |
| 0x00 | W | `0x13` | 2,750 | `RegistrationRequestV3Msg` |
| 0x01 | R | `0x3` | 88 | `RegistrationResponseMsg` |
| 0x02 | R | `0x15d` | 12 | `PingMsg` |
| 0x03 | W | `0x15d` | 36 | `PingMsg` |
| 0x04 | R | `0x40a` | 76 | unnamed |
| 0x05 | R | `0x1be` | 76 | unnamed |
| 0x06 | R | `0x65c` | 12,706 | `LastSpawnedBotCharacterId` |
| 0x07 | R | `0x651` | 4 | unnamed |
| 0x08 | R | `0xa4` | 20 | `ClientAddEntryMsg` |
| 0x09 | R | `0xca4` | 102 | `EventNotificationComponentClientFacet_SyncNotifications` |
| 0x0a | R | `0x14f` | 12 | `TimeSynchMsg` |
| 0x0b | R | `0x18a6` | 40 | unnamed |
| 0x0c | R | `0x1b88` | 42 | `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` |

Two things follow. The client speaks first, with a 2,750-byte V3 registration
request, so a private server's first job is to **answer** that, not to open the
conversation. And no greeting record exists in the capture: `Cmd_Greetings` is a
Carrier command inside the transport framing, which is why it has no type-table
slot and no client string.

### The complete map

Every rung, its transport, its wire type and how far it is proven. "Verified"
means the wire form was read from a capture and a second signal agrees; "named"
means the client's own string names the step but no body was read; "candidate"
means the evidence points at it without closing it.

| State | Name | Transport | What moves the client | Wire | Message | Bytes | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | `Disconnected` | — | — | — | — | — | named |
| 5 | `QueryGameUpdateCheck` | HTTP | client asks | — | — | — | named |
| 6 | `WaitingForGameUpdateCheck` | HTTP | response | — | — | — | named |
| 7 | `QueueGameLogin` | HTTP | client asks | — | — | — | named |
| 8 | `WaitingForQueuedLogin` | HTTP | response | — | — | — | named |
| 9 | `QueryForRemoteConfigClass` | HTTP | client asks | — | — | — | named |
| 10 | `WaitingForRemoteConfigClass` | HTTP | response | — | — | — | named |
| 11 | `ObtainREPRequirements` | HTTP | client asks | — | — | — | named |
| 12 | `WaitingForREPRequirements` | HTTP | response | — | — | — | named |
| 13 | `StartREPConnection` | DTLS | client opens the socket | — | — | — | named |
| 14 | `WaitingForREPConnection` | REP | **client sends first** | `0x13` | `RegistrationRequestV3Msg` | 2,750 | verified |
| 14→15 | | REP | server answers | `0x3` | `RegistrationResponseMsg` | 88 | verified |
| 15 | `WaitingForActorGameConnection` | REP | server hands over the actor id | `0xa4` | `ClientAddEntryMsg` | 20 | candidate |
| 16 | `WaitingForSpawnPoint` | REP | server sends the level | `0x663` | `LevelInfoChangedMsg` | 110 | handler and body verified |
| 17 | `WaitingForPlayerSpawn` | REP | server sends the spawn | `0x8` | unnamed | 46,407 | layout verified, fragments unknown |
| 18 | `InGame` | REP | the 1 Hz state stream | `0x8` ongoing | unnamed | 7,154 | measured effect |
| after | presence | REP | server adds actors | `0x79` | `AddActorMessage` | — | head 16 B verified |

The three rungs that are still open are open for different reasons, and the
reason matters more than the status:

- **15** — `ClientAddEntryMsg` carries the player's own 16-byte actor id and
  arrives twice, the second time immediately before level info. That is the right
  shape and the right position, but no capture shows the transition itself, and
  `PlayerManagerSelfIdentificationMsg` — the trait member that names this step —
  never appears in the replay at all.
- **17** — the record and its payload layout are verified, including the actor id
  at 29,731 and the position at 38,332/38,336. What is not recoverable from the
  bytes is the 48 fragment boundaries, and that is a measurement, not a shrug.
- **presence** — `AddActorMessage` is wire `0x79`, not `0x449`, and its head is a
  proven 16-byte fixed read that is *not* proven to be an actor id.

The one rung with no wire type at all is greetings, because it is a Carrier
command rather than a message. That is the complete map: 15 states, four rungs
with verified wire forms, three open with a named reason each.

| Rung | Client state it moves | What it is | Evidence |
| --- | --- | --- | --- |
| Registration response | `WaitingForREPConnection` (14) → `WaitingForActorGameConnection` (15) | Wire type `0x3`, 88 bytes, **parsed on the 1.365 replay** (`0x1_T0x3_R.bin`): `00 01 03`, `u32` zero at `0x03`, `0x0b` at `0x07`, 8 bytes at `0x08`, 32 redacted bytes at `0x10`, then the 36-byte ASCII string `#[RETAIL].Javelin.1.365.6031.6006993` at `0x30`, then `01 00 00 01` at `0x54`. The handler `FUN_1464768a0` on `30fe6461…` (vtable slot `0x148503e28`) logs `received registration response from REP`, passes the message to a virtual setter labelled **`Server version`**, and then copies the client's own version string into the same slot. Two independent signals therefore agree: the handler names the field, and the captured body contains it. The server reports its own build, and in that capture server and client agreed at 1.365, so a 1.460 client should be told `#[RETAIL].Javelin.1.460.6033.6024067`. This rung is a version handshake, not a gameplay body. | version string verified |
| Greetings | GridMate peer handshake | A **Carrier command**, not an application message: `Cmd_Greetings` = command byte 1 inside a Carrier record. It has no type-table slot, the 1.460 image contains no `Greeting` string at all, and the 1.365 replay has no record for it among its 177. The ladder's first typed exchange is the client's `RegistrationRequestV3Msg`, not a greeting. | transport-level, no typed record |
| Self identification | `WaitingForREPConnection`/`WaitingForActorGameConnection` (15) → `WaitingForSpawnPoint` (16) | `PlayerManagerSelfIdentificationMsg`. The client handler is `FUN_146455ec0` on SHA-256 `30fe6461…`: it logs `PlayerManagerSelfIdentification`, returns early when the game or client-SDK pointer is null, copies the message into the player-manager component, sets an identified flag at component `-0x7f0`, and either spawns from the debug cvars or delegates to `FUN_14167cc70`. Its decoded struct is `0x38` bytes: `0x00` u32, `0x08` `std::vector<u32>` (24 bytes), `0x28` u8, `0x2c` u64, `0x34` u32. Only `0x28` is named: non-zero switches placement to the debug cvars and skips the real spawn. `0x00`, the vector, the u64 and the u32 are copied into component slots that nothing ever reads. The message is registered in `Javelin::ClientMessagesTrait`, the same trait as `LevelInfoChangedMsg`, which is a proven typed message, so trait membership does not settle its wire type. **Nothing about the wire is proven.** The 21-byte body the lab carries is a reconstruction, and its only live test was a two-rung SelfIdent+LevelInfo burst that raised an access violation at `0x146b6f1be` on 1.400 (2026-09-18), which is why `POST_V3_ENABLED = False` in `rep.py`; it has never been shown to advance the rung on its own. The competing `0x65c` candidate is now **eliminated**: wire `0x65c` is `LastSpawnedBotCharacterId` (slot 1628, GUID `169443e0-…`, with the name NUL-padded immediately before the GUID at `.rdata` 0x1480041e0/0x148004200), so the 12,706-byte grid the replay carries is bot spawn data and the lever that filled its GUID was retargeting a bot id. What remains is `0x5d1`, whose type-table GUID `60a51dfc-…` is unnamed and which the 1.365 replay does not contain at all. | handler decompiled and struct named; wire type and body both unproven |
| Level info | `WaitingForSpawnPoint` (16) → `WaitingForPlayerSpawn` (17) | `LevelInfoChangedMsg`, wire type `0x663`. The handler is `FUN_146447ac0` on `30fe6461…`, the next virtual slot in the same vtable as the self-identification handler, and it reads only three struct offsets: `+0xa1`, which it logs as `levelInfo.m_clientContextInstanceId`, `+0xa2`, and `+0xa8`, which it compares against the slot it cached last time and **returns early when they match**. The body is parsed end to end on the 1.365 replay record `0x10_T0x663_R.bin`, 110 bytes: `00 01 a3 19`, `14`+`NewWorld_VitaeEterna`, `1e`+`coatlicue/NewWorld_VitaeEterna`, four big-endian floats `2048.0 / 16.0 / 12272.0 / 10250.0` at `0x38`, `u64` zero at `0x48`, `01 01 00 00` at `0x50`, an 8-byte per-record nonce at `0x54`, `65 03 00 00 00 00 01 01 01 00` at `0x5c`, and the 8-byte `level_context_key` `00 00 00 c1 7f 9b e4 8f` at `0x66`. The key is named: it is the dedup key, proven by the early return above and independently by the lab's own capture note that a repeated `0x663` with the same key is ignored. | partial, measured |
| Spawn | `WaitingForPlayerSpawn` (17) → `InGame` (18) | Record type `0x8`, record id 1, 48 fragments, 46,393 payload bytes. **Measured on the 1.365 replay** (`0x6c_T0x8_R.bin`, 46,407 bytes total): `00 01 08` then a run of `01`/`00` flags to `0x0b`, then the varint `d9 a9 05` = 46,393, and exactly that many bytes follow. The payload is `[record_id = 1][fragment_count = 0x30 = 48][48 fragments]`, where a fragment is `[varint key][varint type_index][payload]` with **no length field**. Verified offsets inside the payload: `actor_id` 16 bytes at 29,731 (preceded at 29,727 by `00 00 00 02`), `position_x` BE f32 at 38,332 = 9343.6416, `position_y` BE f32 at 38,336 = 2786.7327. The actor id bytes match the constant the deleted crate pinned, byte for byte, and the 1,802 redacted bytes match its declared redaction count. What is **not** recovered is the 48 fragment boundaries, and that is now a measurement: a constrained search over the 29,721 offsets that parse as a fragment header found no 48-fragment path ending exactly at 46,393 within a 2,000,000-node budget, under both ascending-key and distinct-key-only walks. This reproduces the deleted crate's own claim that a fragment cannot be walked from its bytes alone. | layout verified, fragments unknown |
| State stream | keeps the connection indicator quiet | The same record re-sent about once a second, but the **ongoing** variant: 9 fragments, 7,154 bytes, and it carries no position at all. Because of that asymmetry the spawn record is the server's only lever on where a player starts. | measured effect, unknown body |

Chunking is a transport fact, not a game fact. A record bigger than about 256
bytes was acknowledged and never delivered when sent as one datagram
(measured 2026-09-24). The working cut is 1100 byte chunks, one chunk per
50 Hz tick. The datagram ceiling is 1200 bytes. Above the path MTU a lost
fragment loses the whole datagram.

## Presence

**The wire type was wrong, and that is now fixed at the source.** `AddActorMessage`
is wire type **121**, not 449. In `.rdata` at `0x1485800e0` the string
`AddActorMessage` is followed by the uppercase GUID `96C829CE-…` (slot 121) and
only then, after four NULs, by the lowercase `bc291efa-…` (slot 449).

Four defects in `scan-wire-names.py` combined to misname wire types:

1. `ROOT` resolved to `reverse/` instead of the repo root, so the tool had been
   **unrunnable** since `private-client/` moved and the committed table was stale.
2. `_pick_name` skipped any GUID-shaped run and kept looking. A *brace* belongs to
   the same descriptor and must be skipped, but a *plain dashed GUID* is another
   descriptor's id, so the name further back is not this type's. Conflating them
   is how 449 stole `AddActorMessage` from 121.
3. A printable run clipped by the 0x100 window, or split by the 110-character cap,
   was accepted as a name. That is where the fragment `cc8a` came from for slot
   `0x5d1`.
4. The GUID pattern accepted only lowercase, so a type registered with an
   UPPERCASE dashed GUID was never indexed and its name belonged to nobody: a GUID
   up to `0xd0` bytes further along then picked it up. This is the root cause
   behind most of the corrections.

Case turned out to be the discriminator, and it is measured, not assumed. A
**lowercase** braced GUID *is* a registration (`<name>\0<cvar>\0{695842bb-…}` is
slot 5037, `PlayerArenaComponentServerFacet_RequestRemoteEnterDungeon`). An
**uppercase** braced GUID is AZ's rendering of a GUID inside another descriptor
(`PingMsg\0{85C7E01E-…}\0<plain guid>`), and indexing it makes it claim `PingMsg`
and leaves wire 349 unnamed — the tool refused to write when that happened, which
is how the rule was found. The all-zero GUID is padding and is always skipped.

The decisive signal for the true binding is not adjacency: `FUN_146ac20a0` builds
the name from immediates (`0x726f746341646441` = `AddActor`, then `Mess`, `ag`,
`e`) **and** parses `&UNK_1485800f0`, the uppercase GUID of slot 121. One function
wrote both halves.

After the fix the table names **2559** types instead of 2239, and the accounting
is clean: **zero** names that were already correct changed slot, 391 real names
gained, and of the 71 removed, **39 moved** to the right GUID (the name survived,
the GUID was wrong) while 32 were fragments that belong to nobody. `AddActorMessage`
moved 449 → 121. The registration family gained names in the same pass: slots 2
and 19 are `RegistrationRequestV2Msg` and `RegistrationRequestV3Msg`, and slot 3
is `RegistrationResponseMsg`, independently confirming the registration rung.
Slots 449, `0x5d1`, `0x663` and 8 remain honestly unnamed.

What the unmarshal facet `FUN_146a6b3e0` does prove is the head of the layout: it
starts with `FUN_1408787b0(param_2, param_3, 0x10, &ok)`, and that helper is a
bounds-checked n-byte read, so the first 16 bytes are a fixed 16-byte field. It is
**not** proven to be an ActorGuid: the facet never interprets those bytes, and no
16-byte comparison exists in an actor context anywhere in the corpus.

The deleted server fanned out an add-actor message after the ladder, with a
candidate actor id and zeros in the fields nobody had decoded. That is not
"players see each other." Do not rebuild it until the head id is proven against a
live client and the other fields have names.

## What "official" means here

An official-feeling server decides, then tells the client what happened.

- The client asks to move. The server accepts a new transform or rejects it.
- The client asks to join a world. The server chooses the character, the
  territory, and the spawn because it knows those things.
- Another player enters your interest set. The server says so because the
  simulation moved them there.

A transformer is allowed when a field is still unknown. It lives apart from
the simulation, it names the capture and the client build, and the number of
unnamed fields in it is not allowed to grow. Replacing that transformer with
real values is the work. Changing the client later, so we can speak a clearer
protocol, is a second project and does not replace this one. The stock client
stays the test that preservation works.

## Next meaning to earn

The handler is settled. `FUN_146455ec0` on build `30fe6461…` is the client's
`PlayerManagerSelfIdentificationMsg` handler, and its decoded struct is named
(`0x38` bytes: u32, `std::vector<u32>`, u8, u64, u32; the u8 at `0x28` is the
debug-cvar spawn switch). The old `0x146454c00` note sits `0x10c0` below it,
which is consistent with the same function on the previous build, but that is
inferred: the `8654f01d…` image is not on this machine, so the old address was
not re-checked.

What is still missing is the wire. Three separate things have to be settled
before Rust may encode this rung:

1. **Is `0x5d1` this message at all?** The 1.460 type table slot 1489 holds
   GUID `60a51dfc-8745-4276-976d-8808ef52cd77`, and the 1.460 registry has no
   name for that GUID. The official 1.365 replay contains no `0x5d1` record.
   The project also carries a competing claim: `replay_store.py` calls type
   `0x65c` "SelfIdent" and targets a 16-byte GUID at body offset 5, and the
   replay does contain a 12,706-byte `0x65c` record that is mostly a grid of
   small integers and `0xffffffff` runs. That grid is a much better fit for a
   struct holding a `std::vector<u32>` than 21 zero bytes is.
2. **What order do the fields take on the wire?** The lab body
   `[u32][u32 count][count x u32][u8][u64][u32]` is 21 bytes with an empty
   vector and agrees member-for-member with the decompiled struct, but its
   provenance is a lost `self_ident.py`. Agreement of shape is not proof of
   order.
3. **What does the vector carry?** It is the only variable-length member, so it
   is what makes this message worth sending at all. Nothing in the client reads
   the copy the handler stores, so the semantic use has not been found yet.

Until those three are settled, `flow.world-entry.rung.self-identification.body`
stays unproven and Rust does not encode this body.
