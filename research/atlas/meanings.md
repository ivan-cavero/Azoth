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
| `flow.world-entry.rung.self-identification.body` | The 21 bytes the lab carries, against a real record that is **12,706 bytes**, now laid out to the byte (2026-10-26): **135-byte prefix + a 56 x 56 grid of big-endian `u32` (12,544 bytes) + 27-byte tail**, which sums to the record exactly. Proven three ways that agree cell for cell: a live Frida probe read the decoded `std::vector<u32>` span as 12,544 with `struct+0x00 = 56`; the record's `0xFFFFFFFF` runs sit on a **224-byte row lattice** (56 runs, one per row, at phase `0x87`); and **56 of 56 rows** begin with an empty cell. Cells are a small enum -- only eight distinct values, `0xFFFFFFFF` (1,716, empty) plus big-endian `0`..`6` -- and the wire is **big-endian** while the struct is host little-endian, measured by matching the probe's cells `0..23` against the record bytes. The earlier "off by exactly one byte" is **withdrawn**: it was the modulo-4 remainder of a wrong model, and there is no orphan byte. The grid's *semantics* remain unnamed. | body layout measured end to end; grid semantics unnamed |
| `flow.world-entry.rung.level-info.unexplained` | **Measured live on 1.460, 2026-10-26** by reading the decoded struct out of `FUN_146447ac0`. Named and closed: the two strings are `NewWorld_VitaeEterna` (size 20) and `coatlicue/NewWorld_VitaeEterna` (size 30); the four `u32` at `0x38/0x3c/0x40/0x44` are **floats to the client** (the struct holds `0x45000000` etc. while the record holds the bytes reversed, so the byte swap happens in the deserializer, not the handler) and equal 2048.0, 16.0, 12272.0, 10250.0; the dedup key at struct `+0xa8` is `0xC17F9BE48F` = `record[0x66:0x6e]` big-endian, confirming the wire→struct link for the one field the lab already rewrites; and struct `+0xa0..+0xa3` = `[1,1,1,0]`, which occurs at exactly one offset in the record (`0x62`), so the old 10-byte "tag block" at `0x5c` is really 6 unnamed bytes plus those four flags. **Still unnamed:** what the four floats describe. The geometric reading (`2048/16 = 128`, `12272/16 = 767`) suggested world coordinates and that is now **refuted**: across 7,216 position samples the player sits at x 9023..9362, y 2743..3027, z 58..88, and 12272/10250 are outside every range. The `u64` at `0x48`, the 6 bytes at `0x5c` and the `0x50` flags remain unnamed. Only `+0xa1`, `+0xa2` and `+0xa8` are ever read by the client. | floats proven and coordinates refuted; three groups still unnamed |
| `flow.world-entry.rung.spawn.body` | Spawn record id 1. The record and its payload layout are verified against the official replay, and **all 48 fragments are now named** (2026-10-26): a fragment's second varint is a type-table index and the registration hook names it, giving 47 distinct types, every one a `*ReplicatedState`. The boundaries, previously closed as underdetermined from the bytes, were measured live. See "The 48 spawn fragments, named". | layout verified, all 48 fragments named |
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
| 0x07 | R | `0x651` | 4 | `ReceivePlayerSpawnPointMsg` (named 2026-10-26; body is the typed header alone) |
| 0x08 | R | `0xa4` | 20 | `ClientAddEntryMsg` |
| 0x09 | R | `0xca4` | 102 | `EventNotificationComponentClientFacet_SyncNotifications` |
| 0x0a | R | `0x14f` | 12 | `TimeSynchMsg` |
| 0x0b | R | `0x18a6` | 40 | `GridTrackingComponentClientFacet_UpdatePhasing` (named 2026-10-26) |
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
| 15 | `WaitingForActorGameConnection` | Carrier | **the actor game connection reaches state 2** | — | — | — | verified, and measured live on 1.460 |
| 16 | `WaitingForSpawnPoint` | Carrier | `[carrier+0xBC8]` becomes set | `0x663` | `LevelInfoChangedMsg` | 110 | handler and body verified; measured live on 1.460 |
| 17 | `WaitingForPlayerSpawn` | Carrier | `[carrier+0x252]` becomes set | `0x8` | `ReplicatedStateBundle` | 46,407 | **the wall on 1.460**: the bundle arrives and the client still times out |
| 18 | `InGame` | REP | the 1 Hz state stream | `0x8` ongoing | `ReplicatedStateBundle` | 7,167 | measured effect on 1.400; NOT reached on 1.460 |
| after | presence | REP | server adds actors | `0x79` | `AddActorMessage` | — | head 16 B verified |

**`0x8` is `ReplicatedStateBundle`, not `ReceiveStateBundle`.** Corrected 2026-10-26
by the registration hook: GUID for `typeIndex[8]` resolves to
`ReplicatedStateBundle` on trait `Amazon::Hub`, and `ReceiveStateBundle` appears
nowhere in the 1.460 trait registry (`aoi-trait-registry.json`). The old name is
still in older prose, in `client-functions.json` and in the lab's own log strings;
those are not evidence and should not be treated as a competing claim. The
authoritative name is this row. Reproduce with `python ef.py re message-names 0x8`.

**Measured on 1.460, 2026-10-26** (`builds.json`, session
`.azoth/logs/runs/run-20261026-1460-ladder`): rungs 14, 15, 16 and 17 are all
reached by the client itself, with no forced gate. Rung 15 closed the way the
row says it should, `WaitingForREPConnection` -> `WaitingForActorGameConnection`
followed by `actor game connection succeeds`. Rung 17 is where it stops: the
world sent the 46,407-byte bundle six times (seq 86, 89, 90, 91, 102, 108) and
the client never logged `player spawn succeeds`; at 10:02:13 it gave up on its
own schedule, `State(WaitingForPlayerSpawn) is timeout : frames 10,
currentTimeoutIntervalCount 2`. So the captured spawn that satisfied 1.400 does
not satisfy 1.460, and the open question is the interior of the bundle, not the
transport.

### `0x663` laid out to the byte

The two `LevelInfoChangedMsg` records in the official 1.365 replay (seq `0x10` and
seq `0x4d`) are **byte-identical**, 110 bytes including the 4-byte typed header.
The body is 106 bytes:

**These are RECORD offsets, and that base matters.** A note here briefly re-based this
table to body offsets and declared the old one "shifted +4"; that was wrong and is
withdrawn. The record base is what the rest of the system uses —
`replay_store.REPLAY_FRESH_LEVELINFO_TARGET` is `(0x4D, 0x0663, 0x66, 8)` and
`REPLAY_CAPTURED_LEVELINFO_KEY` is exactly `record[0x66:0x6e]` — and the table sums to
**110**, the full record, not 106. Both are right; they are different bases. Never
quote these numbers without saying which base.

| Record offset | Size | Bytes, identical in both records | Field |
| --- | --- | --- | --- |
| `0x00` | 4 | `00 01 a3 19` | typed header, prefix varint 1635 |
| `0x04` | 21 | `14` + `NewWorld_VitaeEterna` | `azstr` 20, the level name |
| `0x19` | 31 | `1e` + `coatlicue/NewWorld_VitaeEterna` | `azstr` 30, the level path |
| `0x38` | 4 | `45 00 00 00` | `be_f32` **2048.0** |
| `0x3c` | 4 | `41 80 00 00` | `be_f32` **16.0** |
| `0x40` | 4 | `46 3f c0 00` | `be_f32` **12272.0** |
| `0x44` | 4 | `46 20 28 00` | `be_f32` **10250.0** |
| `0x48` | 8 | zero | unnamed `u64` |
| `0x50` | 4 | `01 01 00 00` | unnamed. **Not** a `be_f32` (it would read `1.7e-38`), and **not** the struct's four `u8`: those are the four bytes at `0x62` (below). Which struct slot this field reaches is unmeasured |
| `0x54` | 8 | `9c fa 58 61 78 14 69 f2` | the session nonce |
| `0x5c` | 6 | `65 03 00 00 00 00` | unnamed |
| `0x62` | 4 | `01 01 01 00` | **the four `u8` the struct calls `+0xa0..+0xa3`** — measured, exact, unique in the record |
| `0x66` | 8 | `00 00 00 c1 7f 9b e4 8f` | the client context key |

**Measured live on 1.460, 2026-10-26** — `reverse/probes/client/frida-levelinfo-struct.py`
read the decoded struct out of `FUN_146447ac0` (`args[1]`, the second argument) while the
client entered the world. Everything below is read from that struct, not inferred.

*The four values are floats to the client, and the swap is proven.* The struct holds
`0x45000000`, `0x41800000`, `0x463FC000`, `0x46202800` — i.e. **2048.0, 16.0, 12272.0,
10250.0** — while the record holds those same bytes in the opposite order. The handler
copies verbatim (`*(u32*)(dst+0x50) = *(u32*)(src+0x50)`), so the **byte swap happens in
the deserializer**, before the handler. That closes the question the bytes alone could
not: the big-endian reading is what the client believes.

*The strings are measured, not inferred.* `+0x00` is `NewWorld_VitaeEterna` (size 20) and
`+0x28` is `coatlicue/NewWorld_VitaeEterna` (size 30) — exactly the `azstr` payloads at
record `0x04` and `0x19`.

*The dedup key is measured end to end.* `+0xa8` = `831069611151` = `0xC17F9BE48F` =
`record[0x66:0x6e]` read big-endian. This is the field the handler compares against the
cached value, and it is the same constant the lab already uses
(`REPLAY_CAPTURED_LEVELINFO_KEY`), so the wire→struct link for that field is now
confirmed rather than assumed.

*The flags are measured, and they moved a row.* `+0xa0..+0xa3` = `[1, 1, 1, 0]`, and that
exact 4-byte sequence occurs at **one** offset in the whole record: `0x62`. So the bytes
the table used to call a single 10-byte "tag block" at `0x5c` are really **6 unnamed
bytes followed by the four flags**. `+0xa0` and `+0xa1` and `+0xa2` are all `1`, which is
why the `+0xa2` state-transition branch fires on this record; `+0xa3` is `0`.

*What the four floats are is still unnamed, and one reading is now refuted.* The pair is
geometric (`2048 / 16 = 128` exactly, `12272 / 16 = 767` exactly), which suggested
12272 and 10250 were world coordinates. **They are not the player's position.** Across
7,216 position samples already on disk the local player sits at x 9023..9362, y
2743..3027, z 58..88; 12272 and 10250 fall outside every one of those ranges. Whatever
they describe, it is not where the player is. Naming them would still be a guess, so
they stay unnamed — but the coordinate hypothesis is retired, not merely unproven.

*A control that failed, recorded so nobody repeats it.* The probe also tried to call the
client's own position accessor (`FUN_140fddfa0`) inside the handler. It raised
`access violation accessing 0x900000001`: the handler runs while the world is still
loading, so the holder is not valid yet. That call must be made from a settled tick, not
from inside a message handler. It does not affect the struct reading, which succeeded.

**What the handler actually consumes, decompiled 2026-10-26.** `FUN_146447ac0`
(`0x146447ac0-0x146447f4f`) reads exactly three struct offsets and nothing else:
`+0xa1` (one byte, logged), `+0xa2` (one byte, gates a state transition), and
`+0xa8` (eight bytes, compared against the cached value — the dedup key). It then hands
the whole message to `FUN_146403a70`, which copies it field by field into the component
struct and in doing so **proves the field order**: `0x20` string, `0x28` string,
`0x50..0x5c` four `u32`, `0x60` `u64`, `0x68` `std::function`, `0xa0..0xa3` four
`u8`, `0xa8` `u64`.

So the level name, the level path and the context key are the only three values the
client acts on. Everything else is carried and ignored — which is why Rust may encode
them as the captured constants once this row says so, and why leaving them unnamed
does not block anything.

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
  at 29,731 and the position at 38,332/38,336. The 48 fragment boundaries are now
  measured live and all 48 fragments are named; see the spawn row.
- **presence** — `AddActorMessage` is wire `0x79`, not `0x449`, and its head is a
  proven 16-byte fixed read that is *not* proven to be an actor id.

The one rung with no wire type at all is greetings, because it is a Carrier
command rather than a message. That is the complete map: 15 states, four rungs
with verified wire forms, one rung answered by a Carrier flag, and two open with a
named reason each.

| Rung | Client state it moves | What it is | Evidence |
| --- | --- | --- | --- |
| Registration response | `WaitingForREPConnection` (14) → `WaitingForActorGameConnection` (15) | Wire type `0x3`, 88 bytes, **parsed on the 1.365 replay** (`0x1_T0x3_R.bin`): `00 01 03`, `u32` zero at `0x03`, `0x0b` at `0x07`, 8 bytes at `0x08`, 32 redacted bytes at `0x10`, then the 36-byte ASCII string `#[RETAIL].Javelin.1.365.6031.6006993` at `0x30`, then `01 00 00 01` at `0x54`. The handler `FUN_1464768a0` on `30fe6461…` (vtable slot `0x148503e28`) logs `received registration response from REP`, passes the message to the virtual setter at **`+0x2d0`** with the label **`Server version`** (`.rdata` `0x1484ffe38`), then reads the client's own version through slot **`+0x50`** of the client object and writes it through slot **`+0x110`**. It does not compare the two; whether anything behind those slots does is unmeasured. **Measured live 2026-10-26:** the lab still declares `[RETAIL].Javelin.1.400.6031.6004151` (`v3.py:23`) to a 1.460 client and the client logs exactly that, so the recommendation below is not yet in the code. Two independent signals therefore agree: the handler names the field, and the captured body contains it. The server reports its own build, and in that capture server and client agreed at 1.365, so a 1.460 client should be told `#[RETAIL].Javelin.1.460.6033.6024067`. This rung is a version handshake, not a gameplay body. | version string verified |
| Greetings | GridMate peer handshake | A **Carrier command**, not an application message: `Cmd_Greetings` = command byte 1 inside a Carrier record. It has no type-table slot, the 1.460 image contains no `Greeting` string at all, and the 1.365 replay has no record for it among its 177. The ladder's first typed exchange is the client's `RegistrationRequestV3Msg`, not a greeting. | transport-level, no typed record |
| Self identification | `WaitingForREPConnection`/`WaitingForActorGameConnection` (15) -> `WaitingForSpawnPoint` (16) | `PlayerManagerSelfIdentificationMsg`. The client handler is `FUN_146455ec0` on SHA-256 `30fe6461...`: it logs `PlayerManagerSelfIdentification`, returns early when the game or client-SDK pointer is null, copies the message into the player-manager component, sets an identified flag at component `-0x7f0`, and either spawns from the debug cvars or delegates to `FUN_14167cc70`. Its decoded struct is `0x38` bytes: `0x00` u32, `0x08` `std::vector<u32>` (24 bytes), `0x28` u8, `0x2c` u64, `0x34` u32. Only `0x28` is named: non-zero switches placement to the debug cvars and skips the real spawn. **The body is now measured** (2026-10-26): a 135-byte prefix, a **56 x 56 grid of big-endian `u32`** (12,544 bytes) whose cells are an 8-value enum with `0xFFFFFFFF` = empty, and a 27-byte tail; `struct+0x00` is 56, the grid side, and the vector holds 3,136 elements. Two 16-byte GUIDs are redacted (prefix `0x05`, tail `0x3192`) and only the prefix one has a lever. The grid's meaning is unnamed. The message is registered in `Javelin::ClientMessagesTrait`, the same trait as `LevelInfoChangedMsg`. (Superseded text removed 2026-10-26: this paragraph used to say `0x65c` was `LastSpawnedBotCharacterId`, and later that the wire order was open by one byte -- the first was the adjacency defect corrected in `b7d106e`, the second was a wrong model now replaced by measurement.) | handler, struct and body measured; grid semantics unnamed |
| Level info | `WaitingForSpawnPoint` (16) → `WaitingForPlayerSpawn` (17) | `LevelInfoChangedMsg`, wire type `0x663`. The handler is `FUN_146447ac0` on `30fe6461…`, the next virtual slot in the same vtable as the self-identification handler, and it reads only three struct offsets: `+0xa1`, which it logs as `levelInfo.m_clientContextInstanceId`, `+0xa2`, and `+0xa8`, which it compares against the slot it cached last time and **returns early when they match**. The body is parsed end to end on the 1.365 replay record `0x10_T0x663_R.bin`, 110 bytes: `00 01 a3 19`, `14`+`NewWorld_VitaeEterna`, `1e`+`coatlicue/NewWorld_VitaeEterna`, four big-endian floats `2048.0 / 16.0 / 12272.0 / 10250.0` at `0x38`, `u64` zero at `0x48`, `01 01 00 00` at `0x50`, an 8-byte per-record nonce at `0x54`, `65 03 00 00 00 00 01 01 01 00` at `0x5c`, and the 8-byte `level_context_key` `00 00 00 c1 7f 9b e4 8f` at `0x66`. The key is named: it is the dedup key, proven by the early return above and independently by the lab's own capture note that a repeated `0x663` with the same key is ignored. | partial, measured |
| Spawn | `WaitingForPlayerSpawn` (17) → `InGame` (18) | Record type `0x8`, record id 1, 48 fragments, 46,393 payload bytes. **Measured on the 1.365 replay** (`0x6c_T0x8_R.bin`, 46,407 bytes total): `00 01 08` then a run of `01`/`00` flags to `0x0b`, then the varint `d9 a9 05` = 46,393, and exactly that many bytes follow. The payload is `[record_id = 1][fragment_count = 0x30 = 48][48 fragments]`, where a fragment is `[varint key][varint type_index][payload]` with **no length field**. Verified offsets inside the payload: `actor_id` 16 bytes at 29,731 (preceded at 29,727 by `00 00 00 02`), `position_x` BE f32 at 38,332 = 9343.6416, `position_y` BE f32 at 38,336 = 2786.7327. The actor id bytes match the constant the deleted crate pinned, byte for byte, and the 1,802 redacted bytes match its declared redaction count. The capture carries this same record **24 times** and all 24 payloads are byte-identical, so it is fully static. The 48 fragment boundaries are **not** derivable from the bytes -- a byte walk on the small variant (record id 1, 9 fragments, 7,152 bytes) is exhaustive and admits only a degenerate path, so the constraints are insufficient, not merely expensive. They were **measured live** instead (2026-10-18, 25 identical copies), and every fragment is now named by its type index; see "The 48 spawn fragments, named". The position sits in fragment 36, `ALCReplicatedState`. | layout verified, all 48 fragments named; payloads are baseline/delta, not fixed layout |
| State stream | keeps the connection indicator quiet | The **ongoing** variant: record id 1 at 7,167 bytes with a fragment count byte of 9, carried at seq 0x73, 0x98, 0x9a, 0x9c and 0x9e. Its head is `00 01 08 01 <seq> 01 01 01 01 00 00 <len varint> 01 09`. It carries no position at all, which is why the spawn record is the server's only lever on where a player starts. The spawn itself is re-sent 24 times byte-identically, so the stream is a verbatim repeat rather than an update. | measured effect, unknown body |

Chunking is a transport fact, not a game fact. A record bigger than about 256
bytes was acknowledged and never delivered when sent as one datagram
(measured 2026-09-24). The working cut is 1100 byte chunks, one chunk per
50 Hz tick. The datagram ceiling is 1200 bytes. Above the path MTU a lost
fragment loses the whole datagram.

## Rung 17 is passed, and the wall was never the bundle

Measured 2026-10-26, build `30fe6461`, and it corrects the previous section.

**The client reaches `InGame`.** The exact sequence from `Game.log`, with the
world-phase patches applied:

```
16:38:29.674  StartREPConnection            -> WaitingForREPConnection
16:38:29.736  WaitingForREPConnection       -> WaitingForActorGameConnection
16:38:29.869  WaitingForActorGameConnection -> WaitingForSpawnPoint
16:38:29.903  WaitingForSpawnPoint          -> WaitingForPlayerSpawn
16:38:30.304  [ClientContext] Initialize()
16:38:30.337  Loading level NewWorld_VitaeEterna
16:38:30.787  player spawn succeeds, in game
16:38:30.787  WaitingForPlayerSpawn         -> InGame
```

Counted over the whole run: `Initialize()` **3**, `Cleanup()` **0**, `player spawn
succeeds` **1**, `new state InGame` **1**, and **0** `Failed to unmarshal`, **0**
`ValidationError`, **0** `transportError`, **0** `OnConnectionFail`. The
`connection_player_timeout` that the previous section called the wall is absent.

**Why the earlier run failed, and why the diagnosis was already written down.**
`levers.md` recorded this on 2026-09-27: `LoadContextAndLevel` reads a virtual
predicate and hands its result to `ClientContext::Initialize` as the 7th argument,
and `Initialize` **self-cleans when that value is 0** -- the `Initialize()` log and
the `Cleanup()` log are separated only by that one flag. The predicate returns 0, so
the context died in the same millisecond and every state bundle was dropped with
`clientContext == nullptr`. The fix is
`services/launcher/runtime-tools/patch-predicate-flag.py`, which forces the flag to
1 and NOPs the failure branch.

So the mechanism was known, documented and shipped. What was missing is that the
1.460 ladder runs **never applied it**. Proven rather than assumed: every launcher
log under `.azoth/logs/` from those runs contains **zero** `predicate flag` lines,
because `Start-NwPrivate.ps1` only runs the patch set under `-Watch`, and the runs
were launched without it.

**Rung 17 was therefore never a protocol problem.** The captured spawn record is
fine, all 48 fragments are fine, and the delta format question is unrelated to
whether the client ever applies them. The client was discarding the bundle for a
reason that had nothing to do with its contents.

**A defect found and fixed on the way.** `scripts/session/private-run.py` -- the
script that performs exactly this sequence -- died on
`ModuleNotFoundError: No module named 'winwindow'`. Its `winwindow` import resolves
against `scripts/gui/`, but the script lives in `scripts/session/`, and the file
moved without the path following it. Nothing had run it since, so nobody noticed.
Fixed by adding `scripts/gui` to `sys.path`. Without that one-line fix the whole
sequence below cannot be reproduced.

**The distinction that has to survive, and it did.** `InGame` is a state machine, not
a picture. The first patched run reported `InGame` while the world **never rendered**:
the tool's own verdict was "0 `[WARNING] Slice:` lines after 90s; the client is most
likely hung on a loading screen. Do NOT treat this as a rendered world", and a
screenshot showed a black screen with only the debug HUD. The acceptance criterion is
therefore the `Slice:` count, not the state name.

**Both gates are now open, measured in one run.** After restarting the world with
`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`:

| Check | Result |
| --- | --- |
| `player spawn succeeds` | 1 |
| `new state InGame` | 1 |
| `[WARNING] Slice:` lines | **26** |
| `Cleanup()` | **0** |
| `Failed to unmarshal` / `ValidationError` / `transportError` / `OnConnectionFail` | **0** |

The tool's verdict for that run was "InGame reached, world streaming (26 slice lines),
player possessed", and a screenshot shows the town of Windsward with the local player
in third person and the debug HUD reporting `RTT 0.000 ms`, `Input Latency 0.000 ms`,
`228 UPD` in and `56 UPD` out. So this is a rendered, possessed world, not a state
machine reporting success over a black screen.

**The second lever, which is what opened the render gate.** `levers.md` records
`AZOTH_REPLAY_LOCAL_PLAYER_UUID=character` as the possession fix and as gate 6: the
client's local-player gate compares the UUID in a `PlayerComponentClientFacet` against
the character UUID in its local option store, and only a match lets the manager context
be set. That lever defaults to **`off`** in `rep.py` and is read **at import**, so
turning it on requires restarting the world, not just setting it in a shell. Setting it
in the shell before `python ef.py dev`, and confirming it in the world's own `config`
event (`replay_local_player_uuid: character`), is what turned the first patched run's
black screen into the rendered world above.

**The third thing, and it is a timing fact rather than a lever.**
`scripts/session/private-run.py` waits a fixed **20 s** after the window appears before
sending the splash Space, then a `--settle` window before patching. On 1.460 those 20 s
land on the **title screen**, which ignores the scan code, so the Space is wasted and
every later click lands on a client that never left the title; the symptom is
`Unable to call JavelinGame::RequestHandleLoginSteps - Auth manager does not exist`,
which reads like an auth failure and is not one. With `--settle 55` the client reached
character select and the click path worked. The failure is silent -- the script cannot
tell a title screen from character select -- so a screenshot is the only honest check.

**What this means for the project.** The ladder is not the wall any more, and the
remaining work is naming field layouts and then writing Rust, not unblocking the
transport. Two things must stay true for that to hold: the world-phase patch set must
be applied (it is, via `private-run.py`), and the world must be started with the
identity lever (it is not a default). A run without either reproduces the old failure
and will look like a protocol bug.

## The 48 spawn fragments, named

The spawn record's fragment boundaries were closed as underdetermined from the
bytes, and that stands: a fragment has no length field, so a byte walk needs the
type schema it is trying to recover. The boundaries were measured live instead
(`frag-spawn.jsonl`, 25 copies of the record, all byte-identical), and once the
boundaries exist the fragment's second varint turns out to be a **type-table
index**, which the registration hook can name.

All 48 fragments are named, over 47 distinct type indices, because keys 61 and 76
both carry type 1755. Every one is a `*ReplicatedState`, which is what a state
bundle fragment has to be, and that is the cross-check: 47 unrelated indices all
landing on replicated-state descriptors cannot be coincidence.

| n | key | type | name | offset |
| --- | --- | --- | --- | --- |
| 1 | 71 | 4878 | `MusicalPerformancePlayerComponentReplicatedState` | 2 |
| 2 | 10 | 3829 | `ObjectiveInteractorComponentReplicatedState` | 25 |
| 3 | 27 | 129 | `AttributeComponentReplicatedState` | 171 |
| 4 | 31 | 1927 | `ReactionTrackingReplicatedState` | 280 |
| 5 | 45 | 2932 | `CooldownTimersComponentReplicatedState` | 320 |
| 6 | 56 | 3147 | `GuildsComponentReplicatedState` | 6,233 |
| 7 | 12 | 1195 | `PlayerAppearanceComponentReplicatedState` | 6,247 |
| 8 | 76 | 1755 | `ContainerComponentReplicatedState` | 6,275 |
| 9 | 67 | 3681 | `ProgressionPointReplicatedState` * | 6,285 |
| 10 | 51 | 1994 | `GroupsComponentReplicatedState` | 11,039 |
| 11 | 55 | 4176 | `SocialReplicatedState` | 11,086 |
| 12 | 43 | 1525 | `StatMultiplierTableComponentReplicatedState` | 11,101 |
| 13 | 50 | 4321 | `WaypointsComponentReplicatedState` | 11,633 |
| 14 | 60 | 3786 | `CurrencyComponentReplicatedState` | 11,650 |
| 15 | 19 | 3133 | `EntitlementComponentReplicatedState` | 11,663 |
| 16 | 41 | 15 | `VitalsComponentReplicatedState` | 11,678 |
| 17 | 9 | 3935 | `PlayerComponentReplicatedState` | 11,747 |
| 18 | 35 | 3765 | `ItemSkinningComponentReplicatedState` | 11,838 |
| 19 | 13 | 603 | `AudioProxyComponentReplicatedState` | 11,859 |
| 20 | 77 | 2938 | `GlobalStorageComponentReplicatedState` | 11,865 |
| 21 | 29 | 6234 | `InstancedSlayerScriptReplicatedState` | 12,518 |
| 22 | 61 | 1755 | `ContainerComponentReplicatedState` | 12,531 |
| 23 | 0 | 10 | `GdeMetadataReplicatedState` | 29,707 |
| 24 | 74 | 5691 | `TransmogComponentReplicatedState` | 29,747 |
| 25 | 42 | 4297 | `StaminaComponentReplicatedState` | 31,129 |
| 26 | 47 | 1652 | `ManaComponentReplicatedState` | 31,158 |
| 27 | 39 | 5620 | `MountComponentReplicatedState` | 31,179 |
| 28 | 33 | 982 | `LootTrackerComponentReplicatedState` | 31,238 |
| 29 | 49 | 3152 | `FactionComponentReplicatedState` | 31,294 |
| 30 | 62 | 3183 | `PaperdollComponentReplicatedState` | 31,307 |
| 31 | 5 | 3290 | `PlayerTimeComponentReplicatedState` | 33,357 |
| 32 | 57 | 1566 | `ChatReplicatedState` | 33,386 |
| 33 | 68 | 497 | `GameEventComponentReplicatedState` | 33,395 |
| 34 | 4 | 2406 | `PlayerArenaReplicatedState` | 33,404 |
| 35 | 20 | 3652 | `PlayerHomeComponentReplicatedState` * | 33,467 |
| 36 | 16 | 11 | `ALCReplicatedState` | 38,310 |
| 37 | 48 | 5257 | `ChargeComponentReplicatedState` | 38,397 |
| 38 | 32 | 2895 | `MagicComponentReplicatedState` | 38,403 |
| 39 | 46 | 185 | `AbilityComponentReplicatedState` | 38,416 |
| 40 | 14 | 1528 | `DamageReceiverComponentReplicatedState` | 39,405 |
| 41 | 22 | 3857 | `ObjectivesComponentReplicatedState` | 39,415 |
| 42 | 1 | 6951 | `PointsAccumulatorComponentReplicatedState` | 41,210 |
| 43 | 65 | 911 | `CategoricalProgressionReplicatedState` | 41,231 |
| 44 | 66 | 3210 | `AchievementComponentReplicatedState` | 42,228 |
| 45 | 2 | 5437 | `ItemManagementComponentReplicatedState` | 44,255 |
| 46 | 34 | 4913 | `RewardTrackComponentReplicatedState` | 45,760 |
| 47 | 70 | 899 | `ProgressionComponentReplicatedState` | 46,286 |
| 48 | 44 | 4236 | `StatusEffectsComponentReplicatedState` | 46,304 |

`*` The naming tool attributes every slot of a hook record to the GUID that record
references, so a record holding more than one hook yields more than one name for
the same GUID. Types 3652 and 3681 are the only two such rows here
(`PlayerHomeComponentReplicatedState`/`RespawnInfo` and
`ProgressionPointReplicatedState`/`ProgressionComponentServerFacet_Debug_ModifyExp`).
A fragment carries a replicated state by construction, so the `*ReplicatedState`
candidate is the one listed. The ambiguity is a limitation of the tool, not a GUID
shared by two types.

Two things this settles and one it opens.

Settled: the position is in fragment 36, which is `ALCReplicatedState`, not
`PositionInTheWorldReplicatedState`. That type exists in the same table at index
13, and **no fragment in this record carries type 13**. Verified against the
replay's own bytes: fragment 36 starts at 38,310 with the header `10 0b` (key 16,
type 11), and 38,332 holds `46 11 fe 91 45 2e 2b b9` = 9343.6416 / 2786.7327. So
the local player's authoritative position arrives inside the Actor Local Control
state, which is consistent with the 2026-10-18 negative: a record-1 bundle
carrying only that one fragment did not reposition the player, because the client
takes the record as a unit.

Settled: the fragment type index and the wire type index are the same namespace.
That is what makes the naming mechanical, and it is why `ef.py re message-names`
works on a fragment list without a new tool.

Open: the atlas used to record that only 1 of 48 fragments had a name
(`telemetry`). That was the adjacency heuristic failing on these descriptors, not
the descriptors being unnameable. Every name above comes from the registration
hook.

The same table is committed machine-readable as
`research/derived/spawn-fragments.json`, because the capture it comes from is
gitignored and would otherwise be the only record.

### The fragment payload is not a fixed layout

Named fragments are not the same as a readable schema, and the difference is
architectural rather than a missing afternoon of work. The same fragment type does
not carry the same bytes in the same places, measured three ways:

1. **The update omits a field the baseline carries.** Type `11`
   (`ALCReplicatedState`) has an 87-byte body in the spawn record, payload
   `38310..38397`, and the authoritative x/y pair is at payload `+20` as big-endian
   f32 (9343.6416, 2786.7327). The *same* key and type in the 9-fragment record
   (payload offset `5335`) does **not** contain that pair anywhere: searched as f32
   big-endian and little-endian, and each component alone -- zero hits in its 7,153
   bytes, while the spawn's 46,393 bytes match at `38332`. A field that is simply
   absent cannot be a fixed offset that happens to hold a stale value.
2. **The client's own reads move.** The same fragment type yields its nested
   prefix-varint reads at offsets `29, 32, 34, 37, 38, 41` in one instance and
   `33, 36, 38, 41, 43, 46` in another, with the same *values* (`31`, `1081`) at
   the shifted offsets. This is supporting evidence rather than independent proof:
   a variable-length field ahead of them would also shift them, so it rules out a
   flat fixed struct but does not on its own establish delta encoding.
3. **The mechanism exists in the build.** The client registers
   `statereplication-enable-hub-delta-compression` and `asc-enable-fragment-sharing`
   (see the 452 `javelin-server.*` cvars), so delta compression is a feature this
   build has, not an inference from the bytes.

Signal 1 carries the argument on its own -- a field that is absent cannot be a
stale fixed offset. Signals 2 and 3 say the mechanism is the plausible one; they
do not select it uniquely.

What that means: the spawn record is a **baseline** -- the first and only time the
client hears this entity's full state, which is why the position is there and
nowhere else -- and later records carry **deltas**.

**CORRECTION 2026-10-26: the delta format is no longer unmeasured.** This paragraph
used to say that "field mask, present-field list and the reference state are all
still unmeasured and none is guessable from three instances". That was true when it
was written and is now wrong: the format was recovered by decompiling the reader and
the writer, and it was never going to come from the bytes. See "The delta format,
measured" below. The rest of this section stands -- the payload is still not a fixed
layout, and there is still no offset to patch.

The consequence for the ladder is the useful part. Rung 17 fails although the
spawn bundle arrives at the right size, and a delta interpretation says why the
obvious line of attack cannot work: there is no fixed offset to patch, so "find
what the captured spawn does not supply" is the wrong question for a record whose
fields are conditional. The right question is whether the client rejects the
record or accepts it and then waits for something else, which is a handler
question and needs a hook, not more byte reading.

For the Rust port the same fact is a constraint worth having early: a server that
**echoes captured bytes** satisfies this format for free, because it never has to
encode a delta. A server that **authors** state -- spawning a second entity,
moving one, setting a component -- has to produce deltas against a reference
state the client is holding, and that encoder is the real work item. It is not
blocked by naming; it is blocked by the format, which is a different thing.

## Rung 17: the client accepts the record and waits

> **SUPERSEDED 2026-10-26 -- rung 17 is passed.** Everything in this section is
> still true about the run it was measured on, but that run launched the client and
> clicked Play **without the world-phase patch set**. With the patches applied at
> character select, the same build reaches `player spawn succeeds` and `new state
> InGame`. The wall was never the bundle's contents: it was
> `ClientContext::Initialize` self-cleaning because the predicate returned 0, which
> dropped every bundle with `clientContext == nullptr`. Read the section below for
> the diagnosis of the unpatched run, and "Rung 17 is passed, and the wall was never
> the bundle" for the correction.

The open question after the spawn fragments were named was whether the client
**rejects** the captured spawn or **accepts it and waits** for something. The
client's own log answers it, with no probe and no new address: it accepts.

Measured on the 1.460 run in `.azoth/logs/runs/run-20261026-1460-ladder/`:

| Signature | Count | Meaning |
| --- | --- | --- |
| `Failed to unmarshal` | **0** | nothing was rejected as malformed |
| `ValidationError` | **0** | nothing was rejected as invalid |
| `player spawn succeeds` | 0 | the spawn never completed |
| `Errors::connection_player_timeout` | 1 | the failure is a wait that expired |

So the 46,407-byte spawn record was decoded without a single complaint and the
state machine still expired. That is the "accept and wait" branch, and it retires
the line of investigation that looks for a wire field the capture omits: a record
the client parses cleanly is not missing a field it knows how to reject.

Two details from the same log that constrain what comes next.

**The baseline is skipped once and then retried.** At `10:00:13.831`, 20 ms after
`Calling clientContext->Initialize`, the client logs
`HandleUnexpectedMessage skipping ReceiveStateBundle for bundle message due to
clientContext == nullptr`, and at `10:00:14.306` it logs
`ProcessPendingReliableMsgQueue processing 2 messages from m_pendingUnexpectedMsgs`.
The bundle is not dropped; it is deferred past a window where the client has no
context to apply it to. The spawn sends that follow (`seq` 42, 43, 46, 48, 51, 52,
53 of type `0x8`, each 46,407 bytes in 43 chunks) all arrive after that window, so
the timing race alone does not explain the timeout. It is also why "the spawn
arrives 15-18 ms too early" was recorded as the cause earlier and is not
sufficient on its own.

**The stream that follows carries no position.** The world loops record 1 at
`player_period_s: 0.25` while the client waits. That is the 9-fragment, 7,153-byte
record, which was measured to contain no position pair at all (see "The fragment
payload is not a fixed layout"), so everything the client receives while it waits
is a delta against a baseline it is holding, not new position information.

**Decision 2026-10-26: the version mismatch stays a candidate on purpose.** It is
recorded and not fixed, because fixing it would be making the replay work, and the
replay working is not the goal. The goal is a complete, named inventory so the Rust
server can be written against named fields. A one-line change to `v3.py:23` would
move the experiment and say nothing about the protocol, so it waits until someone is
actually working on the ladder. What the inventory owes the Rust port is the fact
that the field exists, that it is called `Server version`, that the client records
both versions, and that nothing in this build was found comparing them -- all four
are now written down.

**A concrete defect found in the same run, unrelated to the decode.** At
`10:00:13.190` the client logs
`Server version: [RETAIL].Javelin.1.400.6031.6004151` -- the lab declares a 1.400
server to a 1.460 client. The value comes from
`services/world/src/azoth_world/javelin/v3.py:23` (`DEFAULT_SERVER_VERSION`), no
test pins it, and the registration-response row above had already recorded that a
1.460 client should be told `#[RETAIL].Javelin.1.460.6033.6024067`. Decompiling the
handler `FUN_1464768a0` on `30fe6461` shows why the mismatch is unproven rather
than proven-harmless: it writes the server's string through virtual slot `+0x2d0`
of the game-connection object (the label passed with it is `Server version`,
recovered from `.rdata` `0x1484ffe38`), then fetches the client's own version
through slot `+0x50` of the client object and writes it through slot `+0x110`. It
never compares them itself. Whether a comparison exists behind `+0x2d0` or
`+0x110` is **unmeasured**, so "the version mismatch causes the timeout" is a
candidate, not a finding.

### The delta format, measured

Recovered 2026-10-26 by decompiling the fragment reader and, independently, the
fragment **writer** on build `30fe6461`. Every claim below was re-checked by the
parent against the binary: the vtable slots, the 54-bit mask constant, the group
geometry, the decompressor, and the five field names all reproduce.

**A fragment has no length field because it never needs one.** The fragment reader
`0x146af38c0` reads the key varint, reads the type-index varint, resolves the type
object, and then hands the live stream to that object's **virtual slot `+0x90`**,
letting the type consume whatever it consumes. The consumed count is computed
*afterwards*, as `position_after - position_before`, and passed only to
`FUN_146a64be0` / `FUN_146a64170`, which are log helpers. So the boundaries are not
derivable from the bytes because the format does not put them there; the schema
implies the length. This is why the 2026-10-18 live measurement of the 48 offsets is
not a workaround for weak analysis but the only possible source.

**The payload opens with a presence mask.** For `ALCReplicatedState` (type id
`01B0664B-3AB6-44A6-87E3-8C69D40E0365`, type index 11, vtable `0x148100b10`), the
payload reader is vtable `+0x90` = `0x142a44650` and the shape is:

```
u8            top_mask              raw byte, not a varint; 8 usable bits, ALC uses 2
for each set bit g in top_mask:
    varint64  field_mask            54 usable bits (0x3fffffffffffff)
    for each set bit f of field_mask, ascending:
        field f's own codec          that field's vtable+0x30
```

Three independent numbers agree on 54: each group is `0x3b0` bytes = `54 x 0x10`
descriptor slots plus a `0x50` header, the mask is ANDed with `0x3fffffffffffff`
(`2^54 - 1`), and the loop bound computes `0x360 >> 4 = 54`.

**The writer confirms it in reverse, which is the check that matters.** Vtable
`+0x88` = `0x142a3f120` collects the presence bits, writes the body, then seeks back
to the payload start (`+0x48`), writes the single mask byte (`+0x40`), and seeks to
the end (`+0x38`). The mask is a back-patch because the bits are not known until
every field's presence predicate has run. A group whose mask is empty has its top
bit cleared. Reader and writer agreeing on the same constant from opposite
directions is what makes this measured rather than inferred.

**So field presence IS the delta.** `bit set <=> field on the wire`. A field that is
not set is not stale, it is absent, and the decoder never touches it. This is the
mechanism behind the missing position pair, now with a cause instead of an inference.

**The reference state is the absolute portion, inside the same field.** ALC carries
the quantity twice -- `worldPosRel` (bit 10) and `worldPosAbs` (bit 26), `idRel` (0)
and `idAbs` (24), `timeOffsetRel` (1) and `timeOffsetAbs` (25) -- as distinct members
with distinct presence bits. The value transform is vtable `+0x78` = `0x142a3dd60`,
which is a two-line trampoline into `0x142a28350`:

```c
value = *(float*)(member + 0x10) + dequantize(byte at member + 0x60, scale at +0x88)
// and +0x14/+0x61, +0x18/+0x62 for the other two axes
```

and the same function's failure branch carries the client's own statement of the
contract, from `.rdata` `0x1480ffab0`:

```
"Absolute portion in delta compression wasn't set! We can't calculate the value."
```

with the reflection key `DeltaCompression` at `0x1480ffb00`. That is why a delta with
no absolute base is fatal rather than stale: the client refuses to compute and says
so in a string.

**The field table, in bit order** (group 0, 53 of 54 slots used; group 1, 9 of 54).
The names below are read from the class's own `.rdata`, which clusters them at
`0x148100c94..0x148100fxx`:

| bit | field | bit | field |
| --- | --- | --- | --- |
| 0 | `idRel` | 26 | **`worldPosAbs`** |
| 1 | `timeOffsetRel` | 27 | `scopeTimeBlob0Data0` |
| 2 | `slayerSeqTimeRel` | 28 | `scopeTimeBlobEx` |
| 3 | `slayerSeqTimeAbs` | 29 | `scopeTimeBlob1Data0` |
| 4/6/8 | `slayerSeqTimeRel` | 30 | `teleportAndMigrationId` |
| 5/7/9 | `slayerSeqTimeAbs` | 31 | `scopeData` |
| **10** | **`worldPosRel`** | 32 | `scopeInfoBlob` |
| 11 | `rotation` | 33 | `globalFragTags` |
| 12/15/18/21 | `slayerStateId` | 34 | `aiAngleToDesiredFacing` |
| 13/16/19/22 | `slayerStateIdStarted` | 35 | `wpnaccrystance` |
| 14/17/20/23 | `slayerSequenceId` | 36 | `wpnaccrymvmnt` |
| 24 | `idAbs` | 37 | `scopeTimeBlob0Data1` |
| 25 | `timeOffsetAbs` | 38..42 | `scopeTimeBlob1Data1`, `timeAnchor`, `dataBits`, `moreDataBits`, `combinedExtraNetworkData` |
| 43..48 | `segmentedStamina`, `gritBrokenCounter`, `shapeCastFilter`, `slayerScriptLayers`, `slayerScriptFlags`, `scopeTimeBlob0Data2` | 49..52 | `scopeTimeBlob0Data3`, `scopeTimeBlob1Data2/3`, `quantization` |

Group 1: `distGround`, `waterDepth`, `scopelessInfoBlob`, `scopelessTimeBlob`,
`hitCharacterCounter`, `hitStructureCounter`, `hitWorldCounter`, `forbiddenBounds`,
`currentGridAccessibility`.

**The type index is a real registry, not a code offset.** `0x1461ae2a0` turns the
varint index into a 16-byte type id through a flat table at `registry + 0x40` with
stride `0x10`, bounds-checked against `registry + 0x48`; **index 0 is the escape
that carries the 16 id bytes inline**. `0x1461ae3f0` then calls `0x146166220`, a hash
map keyed by that id, whose node holds the key halves at `+0x10`/`+0x18` and the type
object at `+0x20`. A missing key returns 0 and the fragment fails.

**Independent corroboration across types, from the 300-fragment live capture.** Every
fragment in `fragment-grammar.jsonl` records the varints the client's own reader read
inside it. Measuring the first payload varint from the end of the type-index varint:
offsets are 2, 3, 4, 10, 19, 23, 27, 31 -- **0 and 1 never occur**, and 2 is the
floor, which is exactly one mask byte plus one field-mask varint. That holds across
many different types, not just ALC, so mask-first framing is the general shape and
not an ALC peculiarity. It is still not decompiled for the other 47 types, and is
recorded as strongly indicated rather than measured for them.

**The absolute quad is now measured, and it was the last field blocking the port.**
The decompressor was read live on a client already in the world (probe
`reverse/probes/client/frida-worldpos-decompress.py`, hooks `FUN_142a28350`, which ALC
vtable `+0x78` calls with `param_1 = ALC + 0x8c0`). The `worldPosAbs` member as the
client actually holds it:

| Member offset | Holds | Value at the measured instant |
| --- | --- | --- |
| `+0x10` | x, host `f32` | `9343.6416015625` |
| `+0x14` | y, host `f32` | `2786.732666015625` |
| `+0x18` | z, host `f32` (client-derived, not on the wire) | `87.5379638671875` |
| `+0x60/+0x61/+0x62` | three quantized delta bytes, one per axis | `0x7F`, `0x7F`, `0x7F` |
| `+0x88` | quantization scale | `0x40000000` = `2.0f` |

**The wire is `f32` big-endian and the client byte-swaps on read.** Proved by
reversing the bytes rather than by inspecting code: the wire at spawn payload `+20` is
`46 11 fe 91`, the memory u32 at `member+0x10` is `0x4611FE91`, and
`struct.pack("<I", 0x4611FE91)` = `91 fe 11 46`, which is that wire run **backwards**.
Same for y (`45 2e 2b b9` → `0xB92B2E45` → `b9 2b 2e 45`). Both interpretations give
the exact floats the atlas already had. So a Rust encoder writes x and y as `f32`
big-endian -- which is precisely what the `AZOTH_STATE_POSITION` lever has been doing
at the byte level all along.

**z is not on the wire and the client fills it.** The struct holds `87.538`, and the
2026-10-14 measurement independently recorded the accessor reporting
`87.5379638671875` while x/y sat exactly on the server's values. The wire carries a 2D
position; the height comes from the client.

**The delta formula, closed to the last bit.** `FUN_142a28350` adds a dequantized byte
to the absolute value, and the dequantizer at `0x1417171d0` is a leaf with no `.pdata`
entry, so it was read as instructions:

```
movzx eax, cl            ; the quantized byte
movaps xmm0, xmm1        ; xmm1 = the scale
mulss xmm0, [C]          ; C = f32 at .rdata 0x14804e270 = 0x3C008081
movd  xmm2, eax
cvtdq2ps xmm2, xmm2
mulss xmm0, xmm2
subss xmm0, xmm1
ret
```

which is `delta = scale * (C * byte - 1)` with `C = 0.007843137718737125`. That constant
is **exactly `f32(2/255)`**, bit for bit, so:

```
delta     = scale * (2 * byte - 255) / 255      byte in [0,255], zero at byte = 127.5
value     = absolute + delta                     computed in f32
```

`byte = 127.5` would be zero and is not representable, so the smallest step is
`+-scale/255`; `0x7F` sits just below zero and `0x80` just above. Verified numerically
rather than by eye: at the measured scale 2.0, byte `0x7F` predicts `-0.007843137`,
and an `f32` near 9343.64 has ULP `2^-10 = 0.0009765625`, so the prediction rounds to
`-8 ULP = -0.0078125` -- which is exactly the measured difference between the absolute
`9343.6416015625` and the produced `9343.6337890625`. Predicting the rounding, not just
the magnitude, is what makes this a closed measurement.

**Hypothesis, not measured:** the scale at `+0x88` most likely comes from the wire's
`quantization` field (group 0, bit 52), which is the only field in the schema whose name
matches that role. The value 2.0 was read from the member, not traced back to a wire
byte, so the link is plausible and unproven.

**What remains unknown, and it is much smaller now.** Which bit the update record
actually sets is still a **hypothesis** -- the schema offers `worldPosRel` and the names
fit, but no raw update payload exists locally to confirm it. The per-field codecs
(`+0x18` present?, `+0x28` write, `+0x30` read) are per-field-type and not enumerated.
Neither blocks a position encoder: the byte layout and the delta arithmetic are both
measured, and an encoder that writes `worldPosAbs` with three `0x7F` delta bytes needs
none of the codec detail.

### What a Rust encoder needs, now that the format is known

A server that **echoes captured bytes** needs none of this and is not blocked by it.
A server that **authors** state needs the following, in order:

- `record := varint record_id | u8 fragment_count | fragment*`
- `fragment := varint key | varint type_index | payload`, with no length anywhere
- resolve `type_index` (0 means the next 16 bytes are the id) and let the type's
  schema define the payload
- emit the top mask **last or back-patched**, because presence is not known until
  every predicate has run -- this is what the client's own writer does
- `worldPosAbs` must be present at least once per entity before any relative form,
  or the client refuses to compute a position and logs that it cannot
- never infer a payload length: emit the fields, count the bytes, trust the count

And the position, now that the quad is measured:

```
worldPosAbs (group 0, bit 26):
    x        f32 BIG-ENDIAN          # measured: memory u32 is these bytes reversed
    y        f32 BIG-ENDIAN
    z        NOT SENT                # the client derives the height from the ground
    deltas   3 bytes, one per axis   # 0x7F/0x7F/0x7F at the captured spawn
    scale    f32                     # 2.0 in the captured spawn

delta = scale * (2*byte - 255) / 255     # zero is byte 127.5, not representable,
value = absolute + delta                 # so the finest step is +-scale/255, in f32
```

The three `0x7F` bytes are what the capture carried, and they mean "just below zero"
rather than "no delta". An encoder that wants an exact position should expect a
residual of up to `scale/255` per axis -- at scale 2.0 that is 0.0078 units, which is
under a centimetre of world space and far below anything a client can see.

### Two negatives about the rung-17 log path, and one reasoning trap

Measured 2026-10-26, while trying to find the handler for the bundle on 1.460. Both
negatives below are real and each was re-checked by the parent against the binary.

**The rung-17 log strings have no reference anywhere in the image.** These three
strings, with their VAs:

| String | VA | rip-relative `lea` xrefs |
| --- | --- | --- |
| `skipping ReceiveStateBundle` | `0x148500708` | **0** |
| `clientContext == nullptr` | `0x14850073e` | **0** |
| `player spawn succeeds` | `0x1484ffeff` | **0** |

Zero is surprising for a string that demonstrably appears in the client's own log, and
it means the logging call site cannot be found by scanning for the string's address.
No imm64 reference and no pointer-table entry exists either. Whatever reads them, it
does not load their address the way a normal `lea` does.

**The two verified handlers did not fire on the processor's dispatch path.** A probe
hooked twelve slots of the processor vtable `0x148590ab8` and the two handlers
verified on this build, `0x146455ec0` (`0x65c`) and `0x146447ac0` (`0x663`). Result:
**1015 calls** landed on other slots of the same vtable -- `0x14029e840` took 1001 and
`0x1402a0100` took 14 -- while both verified handlers took **0**.

**The trap, recorded because it was a real error and not a subtlety.** That second
negative was first read as "the atlas's dispatch claim is wrong, the slot-`+0x20`
address is not the dispatch". It is not wrong: `vtable 0x148590ab8 + 0x20` **is**
`0x14029f9f0`, re-checked against the binary in this session, and that same pointer
fills 24 slots of the table. What the zero actually means is that **the run never
reached the code that dispatches a bundled message at all**: in that run's `Game.log`,
`WaitingForSpawnPoint` and `WaitingForPlayerSpawn` occur **zero** times and the log
ends during CMS file loading, i.e. the client never entered the world. A probe attached
to a client that stayed at the loading screen measures a live client doing nothing on
the path of interest, and 1015 calls to other slots proves the hooks were live without
proving anything about dispatch.

The rule this yields, which is worth more than either negative: **before reading any
live negative about a protocol path, confirm from the client's own log that the run
reached that path.** Hooks firing is evidence the probe works, never evidence that the
client entered the state under test. The parent caught this only by checking the log's
size (50 KB against 206 KB for the reference run) and grepping for the ladder states.

## Field names are in the binary, but names are not encodings

Measured 2026-10-26, chasing the question "we have the replay, can we get the layouts for all
185 types instead of 6?" The answer is partly yes, and the part that is no is the part that
matters.

**Yes: a replicated-state class's field names are in `.rdata`, and they are recoverable.**
`ALCReplicatedState`'s 62 fields appear as a contiguous block of NUL-terminated identifiers at
`0x148100c94..0x148101040` -- `idRel`, `timeOffsetRel`, `worldPosRel`, `rotation`, `idAbs`,
`timeOffsetAbs`, `worldPosAbs`, `quantization`, and 40 more. This is not a guess from naming
style: those strings are independently corroborated by the measurements that named the position
field and the flags, and the block is terminated by the next class's data.

The mechanism, verified end to end on that one class:

```
type vtable 0x148100b10  +0xb8  ->  allocator 0x142a3bff0
allocator                        lea's the class-name string 0x1480fffa0 ("ALCReplicatedState")
allocator                        calls 0x142a36d50 at site 0x142a3c0fb
0x142a36d50                      lea's each field-name string, one per member
```

Extracted from that constructor: 49 distinct identifiers, including every field name that was
measured independently. So the field table of a class is readable from its constructor, and the
constructor is reachable from the allocator, which is reachable from the vtable slot `+0xb8`.

**No: it does not generalise by running the same walk for every class.** The image holds **136**
distinct `*ReplicatedState` class-name strings. Applying that exact chain to all of them links
**one** -- `ALCReplicatedState`. Field-table construction is therefore not uniform across these
classes: most either build their members somewhere else, share a generic path, or do not carry a
named field block at all.

Two extraction attempts are recorded because both failed for instructive reasons, and the second
is a trap worth remembering:

1. A first pass searched for `<ClassName>Allocator` strings. Only `ALCReplicatedStateAllocator`
   exists, so this finds exactly one class and looks like success.
2. A second pass used a regex requiring four or more characters before `ReplicatedState`, which
   **silently excluded `ALCReplicatedState` itself** -- `ALC` is three characters. The scan then
   reported zero matches while the hand-verified chain worked, which reads like a broken method
   rather than a broken regex. `{4,60}` should have been `{0,60}`.

`research/derived/field-tables.json` carries the raw material: **1,154** functions that reference
at least 8 distinct identifier strings, with their identifier sets, **26,300** distinct strings
in total. That is a genuine asset -- a field name can now be grepped to the function that builds
its table -- but it is a candidate pool, not an answer.

**And the distinction that actually reframes the question.** A field NAME is not a field
ENCODING. Even for `ALCReplicatedState`, where all 62 names are known, the presence mask is
measured and the `worldPosAbs` delta formula is closed, the wire encoding of the other **61**
fields is unknown: each is read and written through its own per-field-type codec
(`+0x18` present?, `+0x28` write, `+0x30` read). So "6 of 185" is not primarily a naming gap. It
is a **per-field codec** gap, and its size is roughly 185 types times dozens of fields each.

That is why extracting every name would not move the number much. It would make each codec
*findable* -- a named field tells you which codec to hook -- but the codecs still have to be
measured one at a time, and a name alone composes no bytes.

**What this implies for the plan, stated plainly.** Naming the types was the cheap half. What a
composing server needs is per-field encode/decode, and the only routes to that are (a) decompile
each field codec, or (b) measure it empirically -- and (b) is now possible in a way it was not
before, because the presence mask tells you which fields a given body carries, so two bodies of
the same type that differ in one field differ in exactly one field's bytes. That differential
method is the next thing worth building; it is a tool, not a session.

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

### One GUID, one row: the ambiguity was the tool

The first full sweep named 3,390 of the 7,052 type-table entries but reported **796
of them with two or more names for one GUID** -- 23% of everything named. That
looked like the client reusing a GUID, or the table genuinely being many-to-one. It
was a defect in the reader.

The registration table is a run of **48-byte rows**. Each row begins with the
address of the registration lambda that owns it, and carries that row's
type-descriptor thunk at `+0x08`. The tool used to read eight consecutive qwords
from the **table base** and treat each as a descriptor of the type being named, so
a row's answer included its neighbours'. Almost every ambiguous type resolved to
exactly the pair *slot 1* and *slot 7* -- `+0x08` and `+0x08+48` -- which is one
row and the next one. That uniformity is what gave the defect away: a real
many-to-one mapping would not land on two fixed offsets.

The rule that fixes it: the row owning a lambda is the row whose first qword **is**
that lambda, and its own descriptor is that row's second qword. Measured on build
`30fe6461`:

| Check | Result |
| --- | --- |
| The 796 ambiguous types, re-resolved | **796/796** return exactly one name |
| The 2,594 previously-unambiguous types | **2,576 agree, 18 return nothing, 0 contradict** |
| The 7 replay types with independently known names | **7/7 correct** |

The full sweep was then regenerated (`research/derived/message-names.json`, 31m55s)
and the result is stable rather than merely larger. Across the whole 7,052-entry
table: 3,390 named, 97 with no hook record, 3,565 with no GUID string -- the same
counts as before, so nothing was invented and nothing was lost. Every named row now
holds exactly **one** name where 796 held more. `resolution` splits them 3,372
`entry-match` and 18 `slot-scan`, and against the previous artifact **no
previously-unambiguous row changed its name at all** (2,594 compared: 0 changed, 0
lost, 0 gained). A tie-breaker that quietly rewrote settled answers would have been
worse than the ambiguity it fixed; this one did not touch them.

The third row is the one that makes this a measurement instead of a tidy-up, and
`0x663` is inside it: the tie-breaker returns `LevelInfoChangedMsg` alone, where the
old slot scan also offered `State` -- and `LevelInfoChangedMsg` is proven
independently by decompiling that message's handler, not by this tool.

The 18 misses matter and are why the rule is a **tie-breaker, not a replacement**.
When the row layout does not apply it returns nothing (for instance `0x96`
`UnregisterProxyMsg`, whose owning row's descriptor thunk is not the
`lea rax,[rip]; ret` shape the resolver expects), and the caller falls back to the
slot scan. So the rule can only ever *narrow* a set of candidates, never remove a
name that the slot scan had alone. Uniqueness on its own would have been easy to
fake by picking a wrong-but-consistent row; that is exactly what the fallback and
the ground-truth set exist to prevent.

One caveat that falls out of the fix and should not be read past. The type table
holds **trait** registrations as well as message ones, and the mangled name spells
which: `InstallRegistrationHook<VPersistenceRestoreListenerTrait@…>` takes a trait as
its template argument, while `InstallRegistrationHook<VLevelInfoChangedMsg@…>` takes a
message. The tie-breaker can therefore return a name ending in `Trait` for a wire
number -- `0x19` comes out `PersistenceRestoreListenerTrait`, where the slot scan had
offered `AckMovementMsg`. Both are real entries in the table; which one owns that GUID
is **not established**, and the ground-truth set of seven contains no such case, so the
7/7 result says nothing about it. Until a case like that is settled independently, a
row whose answer ends in `Trait` should be read as "this GUID belongs to a trait
registration, or to the message the slot scan offered" and not as a decision. The
regenerated table has **85** such rows, 21 of them among the 796 that were previously
ambiguous -- the other 64 were already single answers, so they are not a new risk.

What this changes for the Rust port: the type table can be read as a map from wire
number to one name, with the candidate list retained beside it as provenance
(`resolution: entry-match` versus `slot-scan`). What it does **not** change: these
are names for types, not field layouts. A named type still has an unmeasured body.

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

### `0x18a6` is `GridTrackingComponentClientFacet_UpdatePhasing`

Four instances, 40 bytes each, at seq `0x0b`, `0x38`, `0x53` and `0x68`. The body
is identical except the **last byte**, which increments: `01`, `02`, `03`, `04`.
That is a sequence number, so this is a keepalive rather than an event. Its
16-byte id is `f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a`, which is **not**
the player's actor id; as a GUID with the first three fields little-endian it is
`57EDCBF8-8BC6-F418-BF85-314BBC4A951A`.

**The wire type is now named.** GUID `D33230C8-9B7C-4B25-AFAA-254F8875A606`
(`typeIndex[6310]`), and the registration hook resolves it to
`GridTrackingComponentClientFacet_UpdatePhasing@ClientMessages@Javelin`:

| Step | Evidence |
| --- | --- |
| GUID string | `.rdata` `0x14802c838` = `{D33230C8-9B7C-4B25-AFAA-254F8875A606}`, uppercase and braced |
| `lea` site | `0x1416d53f1` inside `0x1416d5340-0x1416d5538`, the per-message type-record function |
| lambda body | one caller of that function, `0x14153aa00` |
| record | `0x148029878`, `rec[1]` = `0x14153aab0` |
| thunk | `0x14153aab0` = `lea rax,[0x14a157630]; ret` |
| TypeDescriptor | `0x14a157630` = `.?AV<lambda_1>@?1???$InstallRegistrationHook@VGridTrackingComponentClientFacet_UpdatePhasing@ClientMessages@Javelin@@@Hub@Amazon@@YA_NXZ@` |

Three independent signals agree. The name string is also in the image at
`.rdata` `0x14802c7e0`, `0x59` bytes before its own GUID, so this is one of the
rare cases where the adjacency heuristic happens to be right too. And the name
is one of the five live facet names the official 1.460 session logged
(`builds.json`, `rmi_names`), measured on a different run of the same build.
The trait is `Javelin::ClientMessages` per `aoi-trait-registry.json`, which is
the client-facing set.

What the fields mean is **not** settled by the name. The body still carries the
shared nonce block above, and the counter is a sequence number whose start value
is unknown. The name says what the client does with the record (phasing update
for the grid-tracking component); it does not name the 16-byte id at `0x04`.

### `0x651` is `ReceivePlayerSpawnPointMsg`, a message with no body

One instance, 4 bytes: `00 01 91 19`. That is the typed header and nothing else,
so its body is zero length. A message that carries no data is a signal, and at seq
`0x07` it sits between the registration rungs and the rest of the handshake.

**The wire type is now named.** GUID `21207525-B448-4193-AACA-83D4F847929F`
(`typeIndex[1617]`), and the registration hook resolves it to
`ReceivePlayerSpawnPointMsg@ClientViewListenerTrait@Javelin`:

| Step | Evidence |
| --- | --- |
| GUID string | `.rdata` `0x14802b000` = `21207525-b448-4193-aaca-83d4f847929f`, plain and lowercase |
| `lea` site | `0x1416f3ff1` inside `0x1416f3f40-0x1416f4138`, the per-message type-record function |
| lambda body | one caller of that function, `0x1414e9550` |
| record | `0x14800fe90`, `rec[1]` = `0x1414e9600` |
| thunk | `0x1414e9600` = `lea rax,[0x14a15aa90]; ret` |
| TypeDescriptor | `0x14a15aa90` = `.?AV<lambda_1>@?1???$InstallRegistrationHook@VReceivePlayerSpawnPointMsg@ClientViewListenerTrait@Javelin@@@Hub@Amazon@@YA_NXZ@` |

This one has **two** signals only, and that is the honest count: the TypeDescriptor
(the compiler wrote the name) and the trait registry, which independently reads the
same mangled hook name out of `.rdata`. The adjacency heuristic gives it **no** name
at all — the GUID is a lone lowercase run with no printable neighbour — so the one
method known to be broken is silent here rather than agreeing, and this name rests
on the hook alone.

It also fits the ladder without being used as evidence for itself: the rung it sits
under is `WaitingForSpawnPoint` (16), and its trait is `ClientViewListenerTrait`, the
listener side rather than the player-manager side. A zero-length "spawn point is
ready" signal arriving after registration and before level info is exactly the shape
rung 16 needs.

**What this does not prove.** `0x651` is *not* the message that moves the client out
of rung 15. `STATUS.md` records that the actor game connection reaching state 2 does
that, and this record arrives after registration, at the same rung, as a
notification. Sending it does not substitute for the transport work. And the body is
empty, so there is no field to name: the whole record is the name.

### Method note: the reversed walk

Both names above were produced by walking the chain in `commit b7d106e` **backwards**,
from the GUID string to the name. That direction is worth recording because it is the
one that generalises: given any wire type, read its `typeIndex` GUID, find the GUID
string in `.rdata`, take its `lea` sites, resolve the containing function, take that
function's callers, and read the thunk in the caller's record. It is the same chain,
so a name found this way is exactly as strong as one found forwards.

The two controls were re-run first and both reproduce: `0x663` →
`LevelInfoChangedMsg` and `0x65c` → `PlayerManagerSelfIdentificationMsg`. A GUID whose
`lea` site is in a function with **no** hook record returns nothing rather than a
guess, which is what happens for `0x18a6`'s second `lea` site at `0x14175a75b`.

**It is now a tool, not a procedure.** `python ef.py re message-names <wire…>` runs the
walk for any type id, and `--check` refuses to work if the two controls stop
resolving. Two details cost real time and are worth not rediscovering:

* The GUID text must be searched in **both cases and both forms**. `0x663`'s is plain
  uppercase, `0x65c`'s is plain lowercase, `0x18a6`'s and `0x1a59`'s are braced
  uppercase. Missing the plain-lowercase form silently dropped the `0x65c` control.
* `PE.xrefs_to_va` walks `.text` in Python and measured **5.07 s per wire type**,
  which is 595 minutes for the whole table. One `lea` map built once with
  `bytes.find` brings it to 210 ms per type. Same answers, 24× faster.

### `0x1a59` is the ACK of the phasing update

The client sends `0x1a59` during world entry and the replay cannot answer it
(`inbound-request-coverage` → `no_replay_response: ["0x1a59"]`). It is
`GridTrackingComponentServerFacet_ClientAckPhasingUpdate` on trait
`Javelin::ClientMessages` (GUID `B42B3E49-B674-405C-A6AD-0CC5A8E368BA`,
`typeIndex[6745]`; record fn `0x1416d5540`, lambda `0x14152d160`, thunk
`0x14152d1f0`, TD `0x14a158610`).

So it pairs with `0x18a6` `GridTrackingComponentClientFacet_UpdatePhasing`: the
server pushes a phasing update, the client acknowledges it. That is a third
independent check on the `0x18a6` name — two messages of the same component, one
`ClientFacet` and one `ServerFacet`, named `UpdatePhasing` and `ClientAckPhasingUpdate`.

**But the missing reply is not what blocks rung 17**, and the lab's own comment says
so: `inbound-request-coverage` is "a report, not a verdict", and many
`*ServerFacet_*` messages are setters answered by replicated state rather than by a
typed reply. Treating `no_replay_response` as a defect is the same class of error as
reading a capture as permission to send.

### `0x65c` body: measured — a 135-byte prefix, a 56x56 grid, a 27-byte tail

Measured 2026-10-26 on build `30fe6461…` by two independent methods that agree
**cell for cell**: static byte analysis of the official replay, and a live Frida probe
that read the decoded struct straight out of `FUN_146455ec0` on the running 1.460
client (`reverse/probes/client/frida-selfident-struct.py`, output
`.azoth/captures/probes/selfident-struct.json`).

The accounting is exact, and it is the whole record:

```text
135 (prefix) + 12,544 (grid) + 27 (tail) = 12,706
```

| Record offset | Size | Field |
| --- | --- | --- |
| `0x00` | 4 | typed header, prefix varint `9c 19` = 1628 = `0x65c` |
| `0x04` | 1 | `05` |
| `0x05` | 16 | **redacted** — GUID #1 (this is what `AZOTH_REPLAY_SELFIDENT_GUID` fills) |
| `0x15` | 4 | `58 61 78 14` = big-endian `0x14786158`, a VA into the image's `.rdata` |
| `0x19` | 107 | measured data, unnamed; ends in a run of zeros from `0x5d` |
| `0x84` | 1 | `38` = **56**, the grid side |
| `0x85` | 2 | `80 31`, unexplained |
| `0x87` | 12,544 | **the grid: 56 x 56 big-endian `u32` cells** |
| `0x3187` | 10 | zero |
| `0x3191` | 1 | `05` |
| `0x3192` | 16 | **redacted** — GUID #2 |

**The grid is proven three ways, and the three agree.**

1. *Live, from the client.* The decoded struct's `std::vector<u32>` at struct `+0x08`
   has a byte span of **12,544**, and `struct+0x00` is **56**. Only element width 4
   makes the span an exact square of that `u32` (`56 x 56 x 4 = 12,544`).
2. *Static, from the record.* The row stride is **224 bytes = 56 x 4**, and every
   `0xFFFFFFFF` run in the record sits on that lattice: **56 runs at phase 135**
   (`= 0x87`), i.e. exactly one per row.
3. *Row shape.* **56 of 56 rows begin with an empty cell.** A 56-wide lattice whose
   every row starts empty is not a coincidence of a large buffer.

**Cell values.** There are only **eight distinct values** in all 3,136 cells:

| Big-endian value | Count | Meaning |
| --- | --- | --- |
| `0xFFFFFFFF` | 1,716 | empty / unset |
| `0` | 208 | unnamed state |
| `1` | 192 | unnamed state |
| `2` | 200 | unnamed state |
| `3` | 200 | unnamed state |
| `4` | 196 | unnamed state |
| `5` | 192 | unnamed state |
| `6` | 232 | unnamed state |

So a cell is a **small enum with 7 states plus an empty sentinel**, not an id, a
pointer, or a float. The distribution is close to uniform across the seven states,
which is a property of *this* record and must not be generalised — real terrain would
not be that even.

**The wire is big-endian and the struct is host little-endian.** This is measured, not
assumed: the probe read cells `0..19` as `0xFFFFFFFF` and cells `20..23` as `2`, while
the record holds `0xFFFFFFFF x 20` followed by `00 00 00 02`. Reading those record
bytes as big-endian reproduces the probe's numbers exactly; reading them as
little-endian would give `33,554,432`. Any future encoder must write these cells
big-endian.

**Two corrections this measurement forces.**

*The "off by exactly one byte" is withdrawn, and so is the model behind it.* The body
is not `[u32][count][vector][u8][u64][u32]` filling 12,702 bytes; it is a 131-byte
prefix, the grid, and a 27-byte tail. The old arithmetic, `(12702 - 17 - 5) / 4 =
3170.0`, looked exact only because 12,681 happens to be 1 more than a multiple of 4.
**That remainder was arithmetic noise from a wrong model, not a real orphan byte** —
which is why no amount of further arithmetic on this record could place it. It is now
placed by measurement: there is no orphan byte, and the vector has **3,136** elements,
not 3,170.

*There are two redacted 16-byte GUIDs, not one.* `levers.md` and the comment on
`REPLAY_SELFIDENT_GUID_TARGET` both speak of "a separate binary GUID field" in the
singular. The record redacts **32** bytes in two blocks: `0x05..0x14` (prefix) and
`0x3192..0x31a1` (tail, the last 16 bytes of the record). The lever targets
`(0x06, 0x065C, 0x05, 16)`, which is the prefix block and is correct, but **the tail
GUID is filled by nothing**. Both blocks are preceded by the same byte `05`, so the
message plausibly carries two identity slots of the same shape; which one the client
actually consumes is not measured.

**What is still unnamed.** The grid's *semantics*. Three independent signals pin its
shape, offset, endianness and value set, and none of them says what a cell of state 3
means. Naming it would be a guess, so it stays unnamed; the row below records the
constraint instead. What the message *does* consume is unchanged and still narrow: the
handler reads only struct `+0xa1`, `+0xa2` and `+0xa8`, and only the `u8` at `+0x28`
gates the debug-cvar spawn path.

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
