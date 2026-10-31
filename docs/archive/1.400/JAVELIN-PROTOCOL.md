# Javelin / REP protocol — full reference (build 1.400.6031.6004151)

> Consolidated 2026-10-06 from static RE of `NewWorld.exe` + live captures
> (`services/world/rep_traffic.jsonl`) + the replayed capture
> (`services/world/replay/messages-redacted.txt`). Every VA is image-base
> relative (`0x140000000`). This supersedes the scattered notes in
> `REP-PROTOCOL.md` / `JAVELIN-DISPATCH.md` and adds the message-type registry.
> Re-derive VAs on any client update (`bytepat.py`, `peutil.py str`).

## 0. Layers

```
HTTP  gateway  (:8080 -> Caddy :443)      login, queue ticket, character list
  |
  v
LoginQueueResponse.RepAddress  (e.g. 127.0.0.1:9000)
  |
  v
REP / "Javelin" = O3DE GridMate over DTLS 1.2 (UDP)
  transport  -> Carrier (datagrams, records, reliability, ACKs)
  session    -> Registration V3, SelfIdent, LevelInfo
  messages   -> typed envelope [00 01 <type>] on data channels
  replication-> state bundles (type 0x08) + per-entity records
```

## 1. Transport

### 1a. DTLS trust gate

The client pins an embedded self-signed `CN=New World` cert. Only the
permissive verify path accepts our server. Verified site on this build:
`CMP 0x145dce8ad` / `JZ 0x145dce8b5 -> 0x145dce9d4`; runtime patch
`E9 1A 01 00 00 90` (`scripts/frida-trust-patch.py`). Levers: `levers.md`.

### 1b. Carrier envelope (every post-DTLS datagram)

```
byte 0  type   0x80 = plaintext records, 0x81 = LZ4-compressed block
byte 1  proto  always 0x01
bytes 2-3       datagram sequence, u16 BE
```

### 1c. MessageRecord (1..N per datagram)

```
flags   u8            (MessageFlags, below)
size    u16 BE        absent when MF_NO_LENGTH
channel u8            present only when MF_DATA_CHANNEL (else = previous)
numChunks u16 BE      present only when MF_CHUNKS (else implicit 1)
sequence  u16 BE      absent when MF_SEQUENTIAL_ID (then auto-increment/channel)
relSeq    u16 BE      absent when MF_SEQUENTIAL_REL_ID (auto-increment)
payload size bytes    (to end of datagram when MF_NO_LENGTH)
```

| flag | name | meaning |
| --- | --- | --- |
| 0x01 | MF_RELIABLE | reliable delivery |
| 0x04 | MF_CHUNKS | chunked payload, `numChunks` follows |
| 0x08 | MF_SEQUENTIAL_ID | omit `sequence` |
| 0x10 | MF_SEQUENTIAL_REL_ID | omit `relSeq` |
| 0x20 | MF_DATA_CHANNEL | `channel` byte follows |
| 0x40 | MF_NO_LENGTH | payload runs to end of datagram |
| 0x80 | MF_CONNECTING | connecting |

Flags we use for data: `0x21` (RELIABLE|DATA_CHANNEL). Post-V3 heartbeat is
RELIABLE `0x21` (unreliable `0x20` is Carrier-ACKed but never processed).

### 1d. Channels

| channel | role | evidence |
| --- | --- | --- |
| 0 | generic data / typed stream (V3 registration, replay, typed envelopes) | capture + live |
| 1 | **local-player state stream** direction C->S (`0x635` actor state) | live: ch1 size 119 x31799 |
| 2 | (not exercised in capture; C->S only if any) | none observed |
| 3 | Carrier system messages (connect, ACK, clock, bandwidth) | capture + live |

**Measured asymmetry (2026-10-05):** C->S carries ch1 (`0x635`, 119 B) plus
ch0/ch3; **S->C carries ONLY ch0 and ch3 — never ch1 or ch2.** The server
replays the captured world once on ch0 and then only sends `0x1b88` + `0x15d`.
The real server must produce ch1/ch2 replication.

### 1e. System messages (channel 3)

The 1-byte msgId is the **last** payload byte.

| id | name |
| --- | --- |
| 1 | SM_CONNECT_REQUEST |
| 2 | SM_CONNECT_ACK |
| 3 | SM_DISCONNECT |
| 4 | SM_CLOCK_SYNC |
| 5 | CT_FIRST |
| 6 | CT_ACKS (`[flags][last u16 BE][bitmap..]`; 0x40 continuous, 0x8n bitmap) |
| 7 | CT_CONN_CONTROL |
| 8 | CT_BANDWIDTH |

### 1f. The client's own record container (measured 2026-10-11)

Every non-chunked DATA record the CLIENT sends on channels 0 and 1 is:

```
u32 BE  crc32(payload)
u32 BE  len(payload)
payload = [16-byte target id][00 01][prefix-varint wire type][body]
```

Verified over one live session: 285/294 channel-0 records and **40 279/40 279**
channel-1 records satisfy BOTH the CRC and the length field. The nine channel-0
exceptions are the 1115 B / 239 B entries, which are MF_CHUNKS transfers with a
different header. Hand-checked examples: a 36 B channel-0 record whose 28-byte
payload has `crc32 = 0x2b0bc565` (bytes `2b 0b c5 65`) and `len = 0x0000001c`; a
119 B channel-1 record with `crc32 = 0x3f331f2d` and `len = 0x0000006f`.

The SERVER does not use this container. Its records are
`[vlq32 len][00 01][type][body]` — the form the official capture's server used —
and the client accepts that form on channel 0. Which container a *channel-1* reply
needs is settled by experiment: sending `ReceivePlayerPositionClientMsg` (4216) in
the client container on channel 1 still produces **0** calls into the client's own
reader (`frida-position-consumer`), exactly like the server container on channel 0.
See `position_reply_containers_refuted_20261011` in `client-functions.json`.

What the client itself streams, by channel and wire type (one session, 2026-10-11):

| channel | types seen | volume |
| --- | --- | --- |
| 1 | **only** `0x635` (GUID `01346CCD-785E-448D-A429-4B281972B1D7`) | 17 912 records, 92-153 B, 17 698 of them 119 B |
| 0 | `0x15d` (client ping, target id zero) plus typed requests | 294 records |

## 2. Message-type registry

### 2a. The 10 inline types (`FUN_146b6f190`, GUID compare)

`FUN_146b6f190` compares an inbound message's type GUID against **10** static
getters. A hit is handled inline; a miss falls to the queue (`FUN_146b6bf50`)
drained per-frame by `FUN_146b6d180` (see `JAVELIN-DISPATCH.md`). The 10 types:

| # | type | GUID | getter |
| --- | --- | --- | --- |
| 1 | RegistrationResponseMsg | `104145a7-ff95-44f1-9468-21fb41c8ac2b` | FUN_1407f2e80 |
| 2 | TimeSynchMsg | `038cd847-0653-4243-9a26-936e3bd7f312` | FUN_1407f6a30 |
| 3 | ReceiveHubInfoForActorsMsg | `64de5c88-0010-4f0b-b554-db02a2a968e8` | FUN_1407f2370 |
| 4 | ReceiveAllHubNamesMsg | `4cf9d4ae-3be1-4e9e-a8f1-a313ab114d00` | FUN_1407f1cc0 |
| 5 | PingMsg | `6a379fb8-0bdd-43a1-ab3e-9843d7be8cd3` | FUN_1407f0940 |
| 6 | ClientAddEntryMsg | `e3578b38-69ad-4c13-a7dd-3fff752d98aa` | FUN_1407ebec0 |
| 7 | ClientRemoveEntryMsg | `3c70b3a4-f1c9-4206-9c3b-2e8d132c95c4` | FUN_1407ec780 |
| 8 | UpdateMsg | `45cce5c7-83f6-4640-ad7f-2b169a461c3d` | FUN_1407f72e0 |
| 9 | IsUsingBadWordsResponseMsg | `0e289a49-92a6-42d9-8d89-093ac00837f7` | FUN_1407ef9d0 |
| 10 | FilterTextResponseMsg | `e4b8c624-9165-4a9a-9dfd-61b670b32ee3` | FUN_1407ee830 |

None of these is a replication message: they are session/chat/ping/hub types.
The replication path is the **other** branch (queue -> `object->vtable[+0x30]`
type GUID -> `proc+0x20` map -> handler).

### 2b. Typed envelope on the data channel

A typed message body is `[00 01 <prefix varint type>][payload]`. The type is
**not** a fixed `u16 BE`: it is the shared prefix varint (see 2d), which is why
a type below 0x40 is one byte (`08`) and `0x15d` is two (`9d 05`). The earlier
description in this document (`u16 BE`, or `[(type & 0x3F) | 0x80]`) was wrong
and made the replay validator emit 80 spurious marker warnings out of 138
messages.

Examples from the capture:

| type | meaning (proven / partial) | codec |
| --- | --- | --- |
| `0x0008` | StateBundle — see 2e for the byte-exact layout | FUN_146af20d0 -> FUN_146af2340 |
| `0x635` | local-player state (C->S), actor `1a954abc…` | live |
| `0x663` | LevelInfoChanged (level name + context key) | proven |
| `0x65c` | WORLD DATA blob (12706 B) | first-light codec |
| `0x16a0` | item/collection state | parsed |
| `0x1096` / `0x1097` | **server answers the 0x635 burst** (carry the player key `bf85314bbc4a951a` + state floats) | replay seq 0x75/0x76 |
| `0x1b88` | activity stream (42 B, 23 identical copies, no redaction) | replay |
| `0x15d` | heartbeat ping (server) / pong (client, 36 B) | proven |

### 2c. Type index vs GUID

State-bundle fragments reference component types by **VLQ type index**, not raw
GUID. `install/typeindex.json` (7052 entries) maps some indices to GUIDs, but
NOT all: e.g. the physics components (`GameRigidBodyComponent`,
`CharacterControllerComponent`, `CharacterPhysicsComponent`) and even the
`Transform` GUID `484AE67D-…` are absent from it. So "is type X on the wire"
cannot be answered from typeindex alone.

### 2d. The prefix varint (every typed message starts with it)

Reader: `FUN_14087b5c0`. The number of **leading 1-bits** in the first byte is
the number of continuation bytes `n` (0..4). The first byte's low `7 - n` bits
are the **lowest** bits of the value; the continuation bytes are a
**little-endian** integer placed above them:

```
value = (LE(continuation_bytes) << (7 - n)) | (b0 & ((1 << (7 - n)) - 1))
```

| first byte | n | total bytes | capacity |
| --- | --- | --- | --- |
| `00`..`7f` | 0 | 1 | 2^7 |
| `80`..`bf` | 1 | 2 | 2^14 |
| `c0`..`df` | 2 | 3 | 2^21 |
| `e0`..`ef` | 3 | 4 | 2^28 |
| `f0`..`ff` | 4 | 5 | 2^35 |

Verified against capture bytes: `9d 05` = `0x15d`, `88 6e` = `0x1b88`,
`a3 19` = `0x663`, `a0 5a` = `0x16a0`, `b4 0a` = 692, `d9 a9 05` = 46393.
Decoding every server->client message type round-trips 137 of 138 (the
exception is seq `0x25`, the datagram-first case). **Trap:** Ghidra renders the
3-byte branch as big-endian, which would make `d9 a9 05` equal 1384633 — larger
than the 46407-byte message containing it. The big-endian reading is falsified
by the data.

Implementation with tests: `services/world/src/azoth_world/javelin/varint.py`.

### 2e. The type-0x08 StateBundle, byte-exact

```
[00 01 <varint 0x08>]        typed marker
[01]                         prologue head
[varint SEQ]                 the replication counter the gate compares
[01 01 01 01 00 00]          invariant across all 78 captured bundles
[varint payload_length]
[payload]                    a SEQUENCE OF RECORDS, each:
                                 [u8 record_id][u8 fragment_count][fragments…]
```

Parsed against all 79 server->client `0x08` bodies in the capture: **78 round-trip
exactly**. `SEQ` spans **1..53** across the capture, which matches the live
high-water the client logged (`m_lastUnreliableReplicationSeq 53`).

### The one exception, measured (2026-10-23)

Seq `0x25` is the first message of its datagram and does **not** decode as a bundle
at any offset — the typed marker `00 01 08` is not intact anywhere in the block.
Its first 17 bytes are

```
03 87 94 2a 66 1f 85 43 1d 45 8b 40 d2 1f 3b 26 0d
```

and byte 16 is `0x0d` where the marker's leading `0x00` belongs. So the block is
**not** "a bundle after a preamble": the preamble appears to overwrite the marker's
first byte, and a marker search cannot find this bundle at all.

**Proven against its sibling.** Block `0x2a` is the same bundle with an intact
marker at offset 0, and `0x25[17:] == 0x2a[1:]` **byte for byte**. `0x2a` is
46,407 bytes = 14 bytes of header + the 46,393-byte payload, and the payload is
byte-identical in both blocks.

Two consequences for anyone implementing the send path:

* **use the `0x2a` shape** — `bundle::encode(seq, payload)` — not the `0x25` bytes.
  The `0x25` framing is unmodeled and cannot be reproduced from a parser.
* the corpus cannot distinguish "17-byte datagram preamble" from "16-byte preamble
  plus a first-marker byte that arrived as `0x0d`". Both readings are recorded; the
  measured fact is the 17 and the byte-for-byte equality with `0x2a`.

**And the payload is redacted.** 1,802 bytes across 161 spans are zeros where
identifiers were (first span at payload offset 11,062). The actor id at 29,731 and
the position at 38,332/38,336 are outside every span, so the two fields a server
writes are sound — but "verbatim capture" is the wrong description for the rest.

**The payload is not opaque — this was a correction (2026-10-10).** The earlier
model read the prologue's bytes as `[kind][record_id][fragment_count]` and then
treated the whole payload as ONE fragment's payload. That consumed every body
exactly, which is why it looked right, but *"consumes exactly" cannot
discriminate* when the remainder is opaque. A live Frida probe on `FUN_146af20d0`
(one record) and `FUN_146af2340` (one fragment) settled it:

* the record's `fragment_count` byte **equals the number of nested reader calls**
  in every one of 90 distinct records (`01 30`→48, `01 09`→9, `02 03`→3,
  `03 01`→1, `0d 06`→6, `1d 13`→19);
* byte-exact on the 78-byte bundle (seq `0xab`): its payload length is 66 and the
  payload is **two records of exactly 33 bytes** (`48 03 …`, `49 03 …`), and the
  client measured `consumed=33, fragments=3` for each;
* `record_id` values are **sequential** across a session (1, 2, 3, …, `0x2e`,
  then `0x48`, `0x49`, `0x4a`) — a handler index, and `FUN_141717fc0` indexes
  exactly that at `state + 0x608 + record_id*0x10`.

So the spawn record's real fragment count is **48**, not 1.

**The fragment grammar (verified 2026-10-10).** A fragment is

```
[varint KEY][varint TYPE_INDEX][type-specific payload]
```

The header is **exactly two varints and there is no length field**. Measured with
a live Frida probe that hooks the shared varint reader plus both readers and logs,
per fragment, every varint read with its offset from the fragment start: across
**300 fragments the first two varints sit at offset 0 and 1 in every single one**,
zero exceptions; further varints begin at offset 5 or later and are
payload-internal. 48 distinct keys, 47 distinct types, and the key→type binding is
**1:1** — no key ever maps to two types. The keys are **sparse**
(0,1,2,4,5,9,10,12,13,14,16,19,20,22,27,29,31,…,77), which is what a component
slot table with freed slots looks like, and the spawn record carries exactly 48
fragments with exactly 48 distinct keys.

Because no length is stored, the payload length is **implied by the type**: the
reader consumes it through the type object's vtable `+0x90`, so each type's reader
knows its own length. That also explains the measured fragment sizes
(23, 146, 109, 40, 5913, 14, 28, 10, 4754, …): they are per-type, not encoded.

**Still open:** (a) what `SEQ` means beyond being the gate counter, and (b) the
**per-type payload encoding** — one codec per component type. The container is now
understood down to the fragment; this is the remaining long tail, and it is also
what physics needs, since a physics component would arrive as one of these
fragments.

Implementation with tests: `services/world/src/azoth_world/javelin/bundle.py`.

**The replication gate.** The client accepts an unreliable replication message
only when both hold (`FUN_14643e7b0`): its `clientContextInstanceId` equals
`port[+0x80]` (a byte, live value 1), and its counter is strictly greater than
`port[+0x78]` (`m_lastUnreliableReplicationSeq`). That counter is the
`record_id` varint. Because it is a varint, advancing it must **re-encode** it:
writing a byte `>= 0x80` turns a one-byte varint into a two-byte one and shifts
every following fragment, which is the `Failed to unmarshal ... ValidationError`
measured in `DECOMP-BACKLOG.md` section 12.3. Also note that with the rewrite
OFF the bundles are not fixed, they are **dropped** before deserialization, so
"0 unmarshal failures" does not mean they applied.

### 2f. The message registry (name -> GUID -> wire type)

`research/atlas/javelin-messages.json` lists all **144** Javelin message types
this build ships, each with its AZ type GUID and the **wire type number** that
actually goes on the wire. The wire carries the message type's *position* in the
per-build type table (`private-client/runtime/typeindex.json`, 7052 entries),
not the GUID, so a name cannot become bytes without this mapping. 142 of 144
resolve; `ActorQueryMsg` and `RoutingUnsubscribeMsg` are in the binary but not
in the type table. All 12 movement wire types derived from capture bytes
reproduce exactly, which is the independent check. Regenerate with
`python reverse/tools/scan-message-registry.py`.

### 2g. Where physics and NPCs come from: the AOI trait system

The server-side architecture behind every entity and component is an
**area-of-interest trait** system (`Amazon::Hub::Aoi`, 185 traits in this
build). Each trait replicates state as **records** carrying **fragments** —
exactly what the `0x08` bundle transports — with Javelin-level counterparts
`UpdateRecordsMsg`, `FragmentUpdateMsg`, `RequestRecordsMsg`, `ResetRecordMsg`,
`StartObservingFragmentMsg`. Physics is one trait: `PhysicsTrait` owns a state
type `{F05E34C6-AF1E-476D-9472-5FC118FC4503}` and registers
`RegisterRigidBodyMsg` / `UnregisterRigidBodyMsg` / `UpdateRigidBodyMsg` /
`UpdateRigidBodyFilterMsg` / `UpdateRigidBodyRaidIdMsg` /
`RegisterRigidBodyByAssetMsg`.

This matters for the movement blocker: rigid bodies reach the client through
this record/fragment path, **not** through the by-name component creator
(`FUN_141416740`, measured never to run during world entry) and **not** through
the replay, whose 79 captured fragments all carry `type_index` 1. Giving the
local player physics means implementing record/fragment replication for
`PhysicsTrait` — the same machinery NPCs need.

## 3. The client inbound pipeline (from `JAVELIN-DISPATCH.md`)

```
transport -> iface 0x1485915B8 slot+0x10 (thunk 0x146b71594)
  -> FUN_146b6eb70            inbound decode entry (byte count -> proc+0x710)
       FUN_146154030          decode context
       FUN_1461ac8d0          typed-envelope unmarshal
  -> FUN_146b6f190            10-GUID inline compare (table 2a)
       hit  -> inline handler
       miss -> FUN_146b6bf50 push {object, owner} -> proc+0x120 ring
FUN_145aa23f0                  per-frame tick
  -> FUN_146b6d180(proc,...)   pop LIFO from proc+0x50
       object->vtable[+0x30]   -> type GUID
       FUN_140a174c0           -> 16-byte key, hash = lo ^ hi
       bucket proc+0x20[hash & proc+0x38], 0x20-byte nodes
       hit  -> handler ; miss -> proc->vtable[+0x08]
```

**Open:** the writer of the `proc+0x20` GUID->handler map (binds actor/replica
type GUIDs to handlers). Not `FUN_146b70af0`.

## 4. Session / login sequence (server side)

```
C: CONNECT_REQUEST (ch3 sys1)  -> S: CLOCK_SYNC(sys4) + CONNECT_ACK(sys2) + CT_ACKS(sys6)
C: RegistrationRequestV3Msg (ch0, 832 B)  -> S: RegistrationResponseMsg (88 B)  [rep.ready 0->1]
S: SelfIdentification (header 00 01 + type 0x5d1, then 21 B) -> 10->11
S: LevelInfoChanged (0x663)               -> 12->13
S: replica-create for the player actor    -> 13->14 (spawn)
```

`91 17` read as a little-endian integer is `0x1791`. Under the prefix varint
it is type `0x5d1`. Corrected 2026-10-25 from the lab encoder. The 10→11
effect is still the external ladder note, not a new measurement.

The live session does NOT follow this cleanly (see §6).

## 5. Capture message inventory (`messages-redacted.txt`, 177 msgs)

Directions: R (server->client) 138, W (client->server) 39.

R (server->client), by type: `0x08` x79, `0x1b88` x23, `0x15d` x10, `0x14f` x4,
`0x18a6` x4, `0xa4` x2, `0x663` x2, `0x16a0` x2, plus `0x03 0x40a 0x1be 0x65c
0x651 0xca4 0x136a 0x1096 0x1097 0x8e6 0x1033 0x1067 …`.

W (client->server): `0x15d` x10, `0x635` x5, `0x5b2` x4, `0x1a59` x3, `0x13`,
`0x1098`, `0x9d3`, `0x9fc`, `0xa95`, `0x10b0`, `0x101a`, `0x187c`, `0x187f`,
`0x102e`, `0x102f`, `0x192c`, `0x101d`, `0xf7f`, `0x66b`, `0x143d`, `0x12f6` …

The capture is a SHORT session: it has no ongoing server->client player
replication, and `0x635` appears ONLY in the W direction.

## 6. What the client is missing (measured 2026-10-06)

1. **`obj+0xAA8` (the "Time since last response" stamp) is never written** while
   the world renders: sampled every 250 ms for 85 s it stayed frozen. The client
   shows the gauge climbing from the loading screen and it never drops.
2. **The client processes almost none of our messages**: the typed-stream reader
   `FUN_146b6eb70` counts `n=0` (the archived probe saw only 4/session). So the
   world loads slowly and the session starves.
3. **The server resends ~1659 datagrams** and the first `OnLocalNetworkConnectionWarning`
   lands at the exact moment the resend burst peaks (~+4 min): the client stops
   ACKing.
4. **Replaying captured bundles does not fix it** and can cost the `ClientContext`
   (state-stream lesson). Incremental replay of the small `0x08` bundles (ch0,
   seq 0x73..0xb0) was implemented and tested → world renders, gauge still climbs,
   WASD still dead.

**Root:** the message the client counts as "the response" is not among what we
send. It is not in the capture (short session) and has not yet been isolated in
the binary.

## 7. Open items (in priority order)

1. **Find what writes `obj+0xAA8`.** It is not a plain `mov64 [x+0xAA8]` store
   (0 such in `.text`); it is reached some other way. This is the "response"
   the client waits for. Hook its *readers* (`FUN_14486c740`, `FUN_14487b300`)
   to get the object, then a hardware watchpoint / access monitor on the exact
   field.
2. **Writer of the `proc+0x20` GUID->handler map** (binds replica types).
3. **The ch1/ch2 server->client replication format** the real server emits.
4. `0x635` body layout (input vs state) — float scan + delta between held-W
   frames.

## 7b. GameConnectionWrapper (client session object)

The client's session object (the "connection") lives behind the global
`_DAT_14a7ba0e0`; `[+0x60]` is the game-connection sub-object and `[+0x78]` a
related interface. Log strings (`.rdata`, VA = string):

| VA | string |
| --- | --- |
| 0x1484fe8f0 | `GameConnectionWrapper: start REP connection RepAddress = %s, worldId = %s` |
| 0x1484fe940 | `GameConnectionWrapper: REP socket connection established, now waiting to register` |
| 0x1484fe9c8 | `GameConnectionWrapper: received registration response from REP` |
| 0x1484fea18 | `GameConnectionWrapper: start actor game connection` |
| 0x1484fea50 | `GameConnectionWrapper: actor game connection succeeds` |
| 0x1484fea88 | `GameConnectionWrapper: spawn point found` |
| 0x1484feab8 | `GameConnectionWrapper: player spawn succeeds, in game` |
| 0x1484fe998 | `GameConnectionWrapper: disconnected from REP` |

State-machine / handlers:

- `FUN_14644a070` (2676 B) — the ladder writer: logs `start actor game connection`,
  `actor game connection succeeds`, `spawn point found`, `player spawn succeeds`.
- `FUN_146474e80` (0 B) — socket-connected listener (logs `REP socket connection established`).
- `FUN_146475490` (129 B) — disconnected listener.
- `FUN_1464755e0` (381 B) — registration-received listener (logs
  `received registration response from REP`); only logs + delegates to
  `[lVar5+0x28]` vtable `+0x2d0` and `+0x110`. It does NOT stamp `+0xAA8`.

**The `+0xAA8` field.** The per-frame update `FUN_14486c740` reads
`now - *(obj+0xAA8)`; the HUD `FUN_14487b300` prints the same. `FUN_14486c740`'s
callers pass `param_1 - 0x160`, i.e. the field belongs to a **sub-object of a
larger structure**, not to a top-level class. There is **no** `mov64 [x+0xAA8]`
store in `.text` (0 hits with a precise scan); 267 sites reference the offset
across many object types. Live, the field is **never written** while the world
renders (frozen 85 s). Two callers of the per-frame update pin the offset:
`FUN_14485d5e0` passes `param_1 - 0x160`, `FUN_14485e610` passes `param_1 - 0x28`,
so the object embedding this field sits at a different offset in each host class
(a shared connection sub-object). Finding its writer needs full Ghidra type
propagation on that structure.

## 8. Levers / tools

- `scripts/frida-aa8-poll.py` — sample the connection `+0xAA8` stamp.
- `scripts/frida-component-names.py` — log by-name component creation.
- `scripts/frida-reader-capture.py` — count/messages at the typed-stream reader.
- `AZOTH_REPLAY_INPUT_RESPONSE=1` — server re-sends `0x1096/0x1097` post-replay.
- `AZOTH_REPLAY_STATE_STREAM=1` + `_MIN_SEQ`/`_PERIOD_S` — loop the small `0x08`.
