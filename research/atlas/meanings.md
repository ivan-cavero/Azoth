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

The rule is now confirmed on the installed build, not just derived from the
previous one. `FUN_14087b760` (0x14087b760-0x14087b906) is the 1.460 reader, found
by instruction signature, and its decompiled ladder is the rule above term for
expressed differently: below 0x80 the byte is the value, below 0xc0 one more byte
with shift 6 and mask 0x3f, below 0xe0 two more with shift 5 and mask 0x1f, below
0xf0 three more with shift 4, otherwise four more, with the cursor at `state+0x10`
bounds-checked against `state+0x8` before each read. It is called from 853 sites
across 765 functions, so it is a marshalling primitive rather than a
message-specific reader. The landmark is recorded in
`research/atlas/client-functions.json` as `prefix_varint_reader_1460`.

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
| `flow.world-entry.rung.self-identification.body` | The 21 bytes the lab carries, against a real record that is **12,706 bytes**. The wire type is now settled (`0x65c`, measured through the registration hook with a validated control), so what is left is only the body: its size does not match the `0x38`-byte struct under any integer element count (off by one byte), the field order is unproven, and the vector's meaning is unread. The only live test of the 21-byte body raised an access violation on 1.400. | wire type verified, body unproven |
| `flow.world-entry.rung.level-info.unexplained` | The part of `LevelInfoChangedMsg` (`0x663`) that is not the level name, the level path, or the client context key: the four 4-byte groups at `0x38`, the zero `u64` at `0x48`, the four bytes at `0x50`, the four bytes at `0x54`, and the ten bytes at `0x5c`. The whole 106-byte body is now laid out to the byte, and the two records in the official replay are byte-identical. What stays unnamed is only these, and the handler reads none of them. **`0x54` is not a per-record nonce** — see the layout below. | body laid out, five field groups unnamed |
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

That is why level info is 110 wire bytes and a struct past `0xb0`. The
correspondence is a model read off two handlers, not a proof for a third, and
self-identification is where it breaks: the model predicts a 21-byte body for a
`0x38`-byte struct with an empty vector, but the real record is 12,702 body
bytes, which no integer element count reconciles with that model (it lands on
`c = 3170.25`). The model is not wrong about strings and vectors; it is
unverified for this message, and the size says the message carries far more than
the struct's shape suggests.

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
| 0x04 | R | `0x40a` | 76 | `CalendarConnectedMsg` |
| 0x05 | R | `0x1be` | 76 | `CoatlicueTimingConfigurationConnectedMsg` |
| 0x06 | R | `0x65c` | 12,706 | `PlayerManagerSelfIdentificationMsg` (measured 2026-10-25; the earlier `LastSpawnedBotCharacterId` was an adjacency error, see "Next meaning to earn") |
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
| 15 | `WaitingForActorGameConnection` | Carrier | **the actor game connection reaches state 2** | — | — | — | verified |
| 16 | `WaitingForSpawnPoint` | Carrier | `[carrier+0xBC8]` becomes set | `0x663` | `LevelInfoChangedMsg` | 110 | handler and body verified |
| 17 | `WaitingForPlayerSpawn` | Carrier | `[carrier+0x252]` becomes set | `0x8` | `ReceiveStateBundle` | 46,407 | layout verified, fragments closed |
| 18 | `InGame` | REP | the 1 Hz state stream | `0x8` ongoing | `ReceiveStateBundle` | 7,167 | measured effect |
| after | presence | REP | server adds actors | `0x79` | `AddActorMessage` | — | head 16 B verified |

### `0x663` laid out to the byte

The two `LevelInfoChangedMsg` records in the official 1.365 replay (seq `0x10` and
seq `0x4d`) are **byte-identical**, 110 bytes including the 4-byte typed header.
The body is 106 bytes:

| Offset | Size | Bytes, identical in both records |
| --- | --- | --- |
| `0x00` | 4 | `00 01 a3 19` typed header, prefix varint 1635 |
| `0x04` | 21 | `azstr` 20 = `NewWorld_VitaeEterna` |
| `0x19` | 31 | `azstr` 30 = `coatlicue/NewWorld_VitaeEterna` |
| `0x38` | 4 | `45 00 00 00` |
| `0x3c` | 4 | `41 80 00 00` |
| `0x40` | 4 | `46 3f c0 00` |
| `0x44` | 4 | `46 20 28 00` |
| `0x48` | 8 | zero |
| `0x50` | 4 | `01 01 00 00` |
| `0x54` | 4 | `9c fa 58 61` |
| `0x58` | 4 | `78 14 69 f2` |
| `0x5c` | 10 | `65 03 00 00 00 00 01 01 01 00` |
| `0x66` | 8 | `00 00 00 c1 7f 9b e4 8f` — the client context key |

Two corrections this settles:

- **`0x54` is not a per-record nonce.** The two records are byte-identical, so
  whatever sits there is constant inside a session. Calling it a nonce invited a
  rewrite that no observation supports. The only field the lab deliberately
  rewrites is the 8 bytes at `0x66`.
- **The tail was never unexplained.** `replay_store.REPLAY_FRESH_LEVELINFO_TARGET`
  names exactly `(seq 0x4d, type 0x663, offset 0x66, length 8)`, and
  `REPLAY_CAPTURED_LEVELINFO_KEY` is the very byte string in this table, so
  `remap_fresh_levelinfo_key` is remapping the client context key. That is the
  measured meaning of the last 8 bytes and it was already in the code.

The four groups at `0x38` read as big-endian floats as `2048.0`, `16.0`,
`12272.0`, `10250.0`. That is a reading, not a meaning: one session and two
identical records give no second signal, so those four, the zero `u64`, and the
bytes at `0x50` and `0x54` stay unnamed. They are the whole remaining debt on
this rung, and Rust may encode them as the captured constants once the row says
so — the handler reads none of them.

### The last three rungs are Carrier state, not messages

This is the single most important correction in this inventory, and it was in the
client's own log the whole time. The 1.460 official session's `Game.log` shows:

```
08:27:55.006  GameConnectionWrapper: start actor game connection
08:27:55.006  Update state WaitingForREPConnection to new state WaitingForActorGameConnection
08:27:55.105  GameConnectionWrapper: actor game connection succeeds
08:27:55.105  Update state WaitingForActorGameConnection to new state WaitingForSpawnPoint
08:27:55.209  [GameMessagePort] LevelInfoChanged
08:27:55.381  GameConnectionWrapper: spawn point found
08:27:55.381  Update state WaitingForSpawnPoint to new state WaitingForPlayerSpawn
```

So the transition out of state 15 is the **actor game connection succeeding**, and
the transition out of 16 is the **spawn point flag**. Three tiny leaf functions
read those Carrier flags, and their addresses on 1.460 are verified:

| Carrier flag | Address on 1.460 | Body |
| --- | --- | --- |
| `[carrier+0xA0] == 2` | `0x145A934A0` | `cmp dword [rcx+0xA0],2 ; sete al ; ret` |
| `[carrier+0xBC8]` | `0x145A916F0` | `movzx eax, byte [rcx+0xBC8] ; ret` |
| `[carrier+0x252]` | `0x145A934F0` | `movzx eax, byte [rcx+0x252] ; ret` |

None of the three has a `.pdata` entry (no stack, no frame), which is normal for a
leaf and is why walking the function table cannot find them.

**What this means for the rung that was blocked.** Rung 15 is *not* a message. It
is not `ClientAddEntryMsg` (`0xa4`), and it is not the 21-byte body the lab carries.
A private server moves the client out of 15 by completing the Carrier actor game
connection, which is a transport job. `PlayerManagerSelfIdentificationMsg` still
exists and its handler still spawns the player, so it belongs to the rung-17 path,
not to rung 15. The `0xa4` actor-id message is what tells the client WHICH actor it
is, which is a precondition for that spawn, not the transition itself.

The three rungs that are still open are open for different reasons, and the
reason matters more than the status:

- **15** — **closed as a transport question.** The rung is left when the Carrier
  actor game connection reaches state 2 (`[carrier+0xA0] == 2`, getter at
  `0x145A934A0`), not when a message arrives. `ClientAddEntryMsg` carries the
  player's 16-byte actor id and arrives immediately before level info, but it is a
  precondition for the spawn rather than the transition.
- **17** — the record and its payload layout are verified, including the actor id
  at 29,731 and the position at 38,332/38,336. The 48 fragment boundaries are
  closed as underdetermined; see the spawn row.
- **presence** — `AddActorMessage` is wire `0x79`, not `0x449`, and its head is a
  proven 16-byte fixed read that is *not* proven to be an actor id.

The one rung with no wire type at all is greetings, because it is a Carrier
command rather than a message. That is the complete map: 15 states, four rungs
with verified wire forms, one rung answered by a Carrier flag, and two open with a
named reason each.

| Rung | Client state it moves | What it is | Evidence |
| --- | --- | --- | --- |
| Registration response | `WaitingForREPConnection` (14) → `WaitingForActorGameConnection` (15) | Wire type `0x3`, 88 bytes, **parsed on the 1.365 replay** (`0x1_T0x3_R.bin`): `00 01 03`, `u32` zero at `0x03`, `0x0b` at `0x07`, 8 bytes at `0x08`, 32 redacted bytes at `0x10`, then the 36-byte ASCII string `#[RETAIL].Javelin.1.365.6031.6006993` at `0x30`, then `01 00 00 01` at `0x54`. The handler `FUN_1464768a0` on `30fe6461…` (vtable slot `0x148503e28`) logs `received registration response from REP`, passes the message to a virtual setter labelled **`Server version`**, and then copies the client's own version string into the same slot. Two independent signals therefore agree: the handler names the field, and the captured body contains it. The server reports its own build, and in that capture server and client agreed at 1.365, so a 1.460 client should be told `#[RETAIL].Javelin.1.460.6033.6024067`. This rung is a version handshake, not a gameplay body. | version string verified |
| Greetings | GridMate peer handshake | A **Carrier command**, not an application message: `Cmd_Greetings` = command byte 1 inside a Carrier record. It has no type-table slot, the 1.460 image contains no `Greeting` string at all, and the 1.365 replay has no record for it among its 177. The ladder's first typed exchange is the client's `RegistrationRequestV3Msg`, not a greeting. | transport-level, no typed record |
| Self identification | `WaitingForREPConnection`/`WaitingForActorGameConnection` (15) → `WaitingForSpawnPoint` (16) | `PlayerManagerSelfIdentificationMsg`. The client handler is `FUN_146455ec0` on SHA-256 `30fe6461…`: it logs `PlayerManagerSelfIdentification`, returns early when the game or client-SDK pointer is null, copies the message into the player-manager component, sets an identified flag at component `-0x7f0`, and either spawns from the debug cvars or delegates to `FUN_14167cc70`. Its decoded struct is `0x38` bytes: `0x00` u32, `0x08` `std::vector<u32>` (24 bytes), `0x28` u8, `0x2c` u64, `0x34` u32. Only `0x28` is named: non-zero switches placement to the debug cvars and skips the real spawn. `0x00`, the vector, the u64 and the u32 are copied into component slots that nothing ever reads. The message is registered in `Javelin::ClientMessagesTrait`, the same trait as `LevelInfoChangedMsg`, which is a proven typed message, so trait membership does not settle its wire type. **Nothing about the wire is proven.** The 21-byte body the lab carries is a reconstruction, and its only live test was a two-rung SelfIdent+LevelInfo burst that raised an access violation at `0x146b6f1be` on 1.400 (2026-09-18), which is why `POST_V3_ENABLED = False` in `rep.py`; it has never been shown to advance the rung on its own. The competing `0x65c` candidate is now **eliminated**: wire `0x65c` is `LastSpawnedBotCharacterId` (slot 1628, GUID `169443e0-…`, with the name NUL-padded immediately before the GUID at `.rdata` 0x1480041e0/0x148004200), so the 12,706-byte grid the replay carries is bot spawn data and the lever that filled its GUID was retargeting a bot id. What remains is `0x5d1`, whose type-table GUID `60a51dfc-…` is unnamed and which the 1.365 replay does not contain at all. | handler decompiled and struct named; wire type and body both unproven |
| Level info | `WaitingForSpawnPoint` (16) → `WaitingForPlayerSpawn` (17) | `LevelInfoChangedMsg`, wire type `0x663`. The handler is `FUN_146447ac0` on `30fe6461…`, the next virtual slot in the same vtable as the self-identification handler, and it reads only three struct offsets: `+0xa1`, which it logs as `levelInfo.m_clientContextInstanceId`, `+0xa2`, and `+0xa8`, which it compares against the slot it cached last time and **returns early when they match**. The body is parsed end to end on the 1.365 replay record `0x10_T0x663_R.bin`, 110 bytes: `00 01 a3 19`, `14`+`NewWorld_VitaeEterna`, `1e`+`coatlicue/NewWorld_VitaeEterna`, four big-endian floats `2048.0 / 16.0 / 12272.0 / 10250.0` at `0x38`, `u64` zero at `0x48`, `01 01 00 00` at `0x50`, an 8-byte per-record nonce at `0x54`, `65 03 00 00 00 00 01 01 01 00` at `0x5c`, and the 8-byte `level_context_key` `00 00 00 c1 7f 9b e4 8f` at `0x66`. The key is named: it is the dedup key, proven by the early return above and independently by the lab's own capture note that a repeated `0x663` with the same key is ignored. | partial, measured |
| Spawn | `WaitingForPlayerSpawn` (17) → `InGame` (18) | Record type `0x8`, record id 1, 48 fragments, 46,393 payload bytes. **Measured on the 1.365 replay** (`0x6c_T0x8_R.bin`, 46,407 bytes total): `00 01 08` then a run of `01`/`00` flags to `0x0b`, then the varint `d9 a9 05` = 46,393, and exactly that many bytes follow. The payload is `[record_id = 1][fragment_count = 0x30 = 48][48 fragments]`, where a fragment is `[varint key][varint type_index][payload]` with **no length field**. Verified offsets inside the payload: `actor_id` 16 bytes at 29,731 (preceded at 29,727 by `00 00 00 02`), `position_x` BE f32 at 38,332 = 9343.6416, `position_y` BE f32 at 38,336 = 2786.7327. The actor id bytes match the constant the deleted crate pinned, byte for byte, and the 1,802 redacted bytes match its declared redaction count. The capture carries this same record **24 times** and all 24 payloads are byte-identical, so it is fully static. What is **not** recovered is the 48 fragment boundaries, and that question is now **closed by demonstration**: on the small variant (record id 1, 9 fragments, 7,152 bytes) the same walk is exhaustive, and it admits exactly one path — a degenerate one with two zero-length fragments and a 6,983-byte tail. The constraints are insufficient, not merely expensive. | layout verified, fragments closed as underdetermined |
| State stream | keeps the connection indicator quiet | The **ongoing** variant: record id 1 at 7,167 bytes with a fragment count byte of 9, carried at seq 0x73, 0x98, 0x9a, 0x9c and 0x9e. Its head is `00 01 08 01 <seq> 01 01 01 01 00 00 <len varint> 01 09`. It carries no position at all, which is why the spawn record is the server's only lever on where a player starts. The spawn itself is re-sent 24 times byte-identically, so the stream is a verbatim repeat rather than an update. | measured effect, unknown body |

Chunking is a transport fact, not a game fact. A record bigger than about 256
bytes was acknowledged and never delivered when sent as one datagram
(measured 2026-09-24). The working cut is 1100 byte chunks, one chunk per
50 Hz tick. The datagram ceiling is 1200 bytes. Above the path MTU a lost
fragment loses the whole datagram.

## The three types the replay used to have no name for

`scan-wire-names.py` names a wire type by pairing it with a printable run in
`.rdata`, and that heuristic is now **disproven**. It is not merely imprecise: it
gives the proven `LevelInfoChangedMsg` GUID (`typeIndex[1635]`) **no name at
all**, because that GUID has no adjacent string. So every name in
`research/derived/wire-type-names.json` is a candidate, not an owner.

The reliable method is the client's own registration hook, and it is mechanical.
Each handled message has a lambda RTTI descriptor whose mangled name spells both
the message and its trait:

```
.?AV<lambda_1>@?1???$InstallRegistrationHook@V<Message>@<Trait>@@@Hub@Amazon@@YA_NXZ@
```

From that descriptor the chain is fixed: `lea rax,[td]; ret` thunk →
`.rdata` record where `rec[5]` is the thunk and `rec[4]` is the lambda body →
the body calls a small per-message function → that function does
`lea r11,[<guid string>]` → the dashed GUID → `typeIndex` → wire type. One parser
copy per registration, each with its own hard-coded `lea`, which is why the GUID
is never a 16-byte constant and why searching for the GUID as bytes finds nothing.

Validated on the control: `LevelInfoChangedMsg` → `0x663`. Reproduced
independently on `ObjectivesComponentServerFacet_UpdateTrackedObjectives` →
`0x5b2` (TD `0x14a1d8d50`, thunk `0x1439ee500`, body `0x1439ee450` → `0x143a3da80`,
`lea` at `0x143a3db31` → `0x148255808` = `298436a9-…`).

### `CoatlicueClientMessages`, fully resolved

| Member | Wire | Index |
| --- | --- | --- |
| `CalendarConnectedMsg` | **`0x40a`** | 1034 |
| `CoatlicueTimingConfigurationConnectedMsg` | **`0x1be`** | 446 |
| `DistributionManagerConnectedMsg` | `0x2b9` | 697 |
| `MessageReceiptMsg` | `0x40b` | 1035 |
| `State` | `0x2bd` | 701 |
| `TerrainGlobalManagerConnectedMsg` | `0x2ae` | 686 |
| `TractGlobalManagerConnectedMsg` | `0x288` | 648 |
| `WorldQueryConnectedMsg` | `0x44` | 68 |

Two independent routes agree. The registration walk above gives this table, and
the seven non-`State` GUIDs sit contiguously in `.rdata` at `0x84fc998..0x84fca88`
in exactly this member order, immediately after the `CoatlicueClientMessages::State`
descriptor. Spot-checked by hand: the `CalendarConnectedMsg` wrapper `0x1469a5fa0`
calls `0x146437730`, whose `lea r11,[0x1484fd998]` at `0x1464377e1` is the
`979e13fb-…` string; the `CoatlicueTimingConfigurationConnectedMsg` wrapper
`0x1469a6050` calls `0x146437b30`, whose `lea r11,[0x1484fd9c0]` at `0x146437be1`
is the next string, `1e718638-…`.

So the two unnamed types the replay carries at seq `0x04` and `0x05` are
`CalendarConnectedMsg` and `CoatlicueTimingConfigurationConnectedMsg`. Both are
76 bytes and both are server→client, which fits two "connected" notices arriving
right after the registration response.

### `0x5b2` keeps its original name

`0x5b2` is `ObjectivesComponentServerFacet_UpdateTrackedObjectives` (GUID
`298436a9-06d0-4bda-8dd9-0708b36e7374`). The 2026-10-14 note that stripped this
name was itself the adjacency defect: the string
`ObjectivesComponentServerFacet_UpdateTrackedObjectives` at `.rdata` `0x82547a8`
is followed by two GUIDs, `55a7d1e9-…` (wire `0xa4d`) at `0x82547e0` and
`298436a9-…` at `0x8254808`, and adjacency cannot say which one owns the string.
The registration hook can, and it says `0x5b2`.

## Blocks that several messages share

Some byte runs repeat across different message types. A shared run means two
messages are talking about the same object, so it is stronger evidence than a
single record's layout: the same value cannot be coincidence when it appears in
types with different headers.

Three blocks are measured, and each is an unnamed field until someone names it.

### The 8-byte session nonce

`9c fa 58 61 78 14 69 f2` appears in two different messages, at the same relative
position after a 4-byte flag group:

| Message | Flags | Nonce | What follows |
| --- | --- | --- | --- |
| `0x663` level info, at `0x50` | `01 01 00 00` | the nonce | `65 03 00 00 00 00 01 01 01 00` then the 8-byte context key |
| `0x18a6`, at `0x14` | `01 01 00 00` | the same nonce | `65 03 00 00 00 00 02 <counter>` |

So the tail of both messages is `[4 flag bytes][8-byte nonce][65 03 00 00 00 00]
[discriminator]`, and the discriminator decides what follows. `65 03 00 00` is
`869` as a little-endian `u32`, which reads like a version or protocol tag; that
is a candidate, not a name.

### `0x18a6` is a periodic counter

Four instances, 40 bytes each, at seq `0x0b`, `0x38`, `0x53` and `0x68`. The body
is identical except the **last byte**, which increments: `01`, `02`, `03`, `04`.
That is a sequence number, so this is a keepalive rather than an event. Its
16-byte id is `f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a`, which is **not**
the player's actor id; as a GUID with the first three fields little-endian it is
`57EDCBF8-8BC6-F418-BF85-314BBC4A951A`.

### The 36-byte identity block and the `58 61 78 14` tag

`0x40a` and `0x1be` are both 76 bytes and differ only in their first 40; bytes
40..76 are **byte-identical**, and the same 36 bytes appear inside `0x65c` at
offset 57. The layout is the same in all three:

```
[4-byte tag 58 61 78 14][32 bytes][36-byte shared block]
```

`0x40a`: tag at 4, block at 40. `0x1be`: tag at 4, block at 40. `0x65c`: tag at
21, block at 57. The 36-byte block is
`cb d4 a1 8a 40 42 c7 ee a4 62 98 c7 49 9b a8 26 ef 53 39 aa 29 70 e2 83 fc f3
4b 6f 8f 07 86 d6 8b f3 ae 45`, and the tag is the same 4 bytes in all three. A
private server that echoes a captured record keeps these consistent for free; one
that composes messages has to know what they are, and nobody does yet.

### `0x651` is a message with no body

One instance, 4 bytes: `00 01 91 19`. That is the typed header and nothing else,
so its body is zero length. A message that carries no data is a signal, and at seq
`0x07` it sits between the registration rungs and the rest of the handshake.

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

**The wire type is settled: `0x65c`.** Measured 2026-10-25 on build `30fe6461…`
by walking the client's own registration hook, and validated against a control.
The chain, every link re-checked by hand:

| Step | Evidence |
| --- | --- |
| lambda TypeDescriptor | name at `0x14a15a2c0` = `.?AV<lambda_1>@?1???$InstallRegistrationHook@VPlayerManagerSelfIdentificationMsg@ClientMessagesTrait@Javelin@@@Hub@Amazon@@YA_NXZ@`, TD `0x14a15a2b0` |
| thunk | `0x1414f2b00` = `48 8d 05 a9 77 c6 08 c3` (`lea rax,[0x14a15a2b0]; ret`) |
| record | `0x148012b10`, `rec[5]` = the thunk, `rec[4]` = `0x1414f2940` (the lambda body) |
| lambda body | `0x1414f2940`: `call 0x146163290` (registry), `call 0x1416ec940` (type record), `call 0x1461aaa00` (install) |
| GUID string | inside `0x1416ec940`, `lea r11,[rip+0x6917808]` at `0x1416ec9f1` → `0x148004200` = `169443e0-a508-4653-b437-49b7a195f69c` |
| wire type | `typeIndex[1628]` = that GUID, and `9c 19` is prefix varint 1628 = **`0x65c`** |

The whole trait resolves by the same walk, and four of these six wire types had
no name before:

| Member | Wire | Index | GUID string | `lea` site |
| --- | --- | --- | --- | --- |
| `DebugCommandResponseMsg` | `0x66` | 102 | `0e86f8d7-3340-4396-b944-ba79385b394a` | `0x1416c91f1` |
| `State` | `0x2f` | 47 | `c1b677cf-2812-4c22-8ce3-756e863c8d82` | `0x141701bf1` |
| `PlayerManagerSelfIdentificationMsg` | **`0x65c`** | 1628 | `169443e0-a508-4653-b437-49b7a195f69c` | `0x1416ec9f1` |
| `PlayerManagerRejectedMsg` | `0x65e` | 1630 | `dcb01cb8-d04a-40ea-a3af-96604fe322fb` | `0x1416ec7f1` |
| `LevelInfoChangedMsg` | `0x663` | 1635 | `45918D03-02E7-42A4-8A30-1B205F8C37FE` | `0x1416dfff1` |
| `RemoteConfigChangedMsg` | `0x667` | 1639 | `51a74e6c-7053-4214-a735-f6448cd66517` | `0x1416f71f1` |

`PlayerManagerRejectedMsg` at `0x65e` is the natural pair for
self-identification: the accept and the reject of the same exchange. Four of the
six are consecutive in the index (1628, 1630, 1635, 1639), which is a second,
independent signal that they belong to one trait.

Note for anyone re-running this: `pe.va_to_foff()` is **not** `va - image_base`.
Sections are aligned, and subtracting the base reads the wrong bytes.

The whole trait resolves by the same walk, and four of these six wire types had
no name before. Every row below was read from a `lea` inside the per-message
type-record function, so each has its own address:

| Member | Wire | Index | GUID string | `lea` site |
| --- | --- | --- | --- | --- |
| `DebugCommandResponseMsg` | `0x66` | 102 | `0e86f8d7-3340-4396-b944-ba79385b394a` | `0x1416c91f1` |
| `State` | `0x2f` | 47 | `c1b677cf-2812-4c22-8ce3-756e863c8d82` | `0x141701bf1` |
| `PlayerManagerSelfIdentificationMsg` | **`0x65c`** | 1628 | `169443e0-a508-4653-b437-49b7a195f69c` | `0x1416ec9f1` |
| `PlayerManagerRejectedMsg` | `0x65e` | 1630 | `dcb01cb8-d04a-40ea-a3af-96604fe322fb` | `0x1416ec7f1` |
| `LevelInfoChangedMsg` | `0x663` | 1635 | `45918D03-02E7-42A4-8A30-1B205F8C37FE` | `0x1416dfff1` |
| `RemoteConfigChangedMsg` | `0x667` | 1639 | `51a74e6c-7053-4214-a735-f6448cd66517` | `0x1416f71f1` |

Five of the six are consecutive in the index (1628, 1630, 1635, 1639 with 0x66
and 0x2f as the two outliers), which is itself a second signal that they belong
to one trait. `PlayerManagerRejectedMsg` at `0x65e` is the natural pair for
self-identification: the accept and the reject of the same exchange.

**Control, and the reason the old answer was wrong.** The identical method on
`LevelInfoChangedMsg` yields `45918D03-02E7-42A4-8A30-1B205F8C37FE` →
`typeIndex[1635]` → `0x663`, which is independently proven. That same control
exposes the defect in `research/derived/wire-type-names.json`: it gives
`typeIndex[1635]` **no name at all**, because it pairs a name with a GUID by
`.rdata` adjacency, and the proven LevelInfoChanged GUID has no adjacent name.
So `wire-type-names.json` naming `0x65c` `LastSpawnedBotCharacterId` was
adjacency, not ownership: three names (`LastSpawnedSlice`,
`LastSpawnedSlicePosition`, `LastSpawnedBotCharacterId`) run consecutively before
the `169443e0` GUID. The earlier "`0x65c` is eliminated" conclusion was built on
that heuristic and is withdrawn. `0x5d1` (GUID `60a51dfc-…`) is **not** this
message.

The lab already agreed with this and the prose did not: `levers.md` has
`AZOTH_REPLAY_SELFIDENT_GUID`, which fills the redacted 16-byte GUID at `0x65c`
body offset `0x05`. The code treated `0x65c` as the self-identification record
all along.

Three things are still open, and they are body questions now, not type questions:

1. **The lab body is the wrong size.** The real record in the official 1.365
   replay is 12,706 bytes (seq `0x06`, direction R). The lab carries 21 bytes
   with an empty vector. The body is 12,702 bytes, and the model
   `4 + 4 + 4c + 1 + 8 + 4 = 21 + 4c` gives `c = 3170.25` — off by exactly one
   byte, so the vector layout is **not** confirmed. Something in the model is
   missing a byte or an element is not 4 bytes wide.
2. **What order do the fields take on the wire?** Unchanged: shape agreement is
   not proof of order, and the only live test of the 21-byte body was the
   two-rung burst that raised an access violation at `0x146b6f1be` on 1.400
   (2026-09-18). It has failed once.
3. **What does the vector carry?** Still the only variable-length member and
   still unread by the handler. At 12.7 KB it is not a small list.

Until those are settled, `flow.world-entry.rung.self-identification.body` stays
unproven and Rust does not encode this body. Encoding the wrong 21-byte body
under the right type id is how the 1.400 crash happened.

## What actually blocks the ladder

None of the above is the next step. Rung 15 is left by completing the Carrier
actor game connection (`[carrier+0xA0] == 2`, getter `0x145A934A0`), which is a
transport job, not a message. Self-identification belongs to the rung-17 path.
`STATUS.md` carries the live blocker; this section records what the rung-17
message still owes once the transport is done.
