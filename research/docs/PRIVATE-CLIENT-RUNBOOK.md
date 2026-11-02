# Private client runbook — REP carrier live attempt

Operational reference for one narrow experiment: **point the real New World
client's REP connection at the Rust server in `server/crates/everfall-net` and
watch whether the client passes REP registration.** The server now runs the
Carrier layer: it answers the Carrier `SM_CONNECT_REQUEST` with the acceptance
flight (`SM_CLOCK_SYNC` + `SM_CONNECT_ACK` + `SM_CT_ACKS`) and answers the
client's V3 registration (`wire 0x13`) with the `0x3` response from the Atlas
card `flow.world-entry.rung.registration`. The claim this run checks is that the
client moves `WaitingForREPConnection` (14) → `WaitingForActorGameConnection`
(15) and logs `received registration response from REP`. The server also now
arms the **post-registration ladder** once the registration is answered: the
self-identification record (`0x65c`), level info (`0x663`) and the emitted
state bundle (`0x08`), sent on the server's own clock, with the reference's
`SM_CLOCK_SYNC` **keepalive** opening the stream and repeating once a second.
See "Post-registration ladder" below for what that can and cannot reach.

**What the differential test settled (2026-11-02).** The twenty ladder records
were compared byte for byte against the Python reference and are identical:
envelope, flags, sub-headers, `numChunks`, sequence, relative sequence, payload
and total length, all twenty. The stream was not: the reference's
`PeerSession.tick` runs `maybe_keepalive` before `maybe_pump_replay`, so the
datagram immediately after the `0x3` answer is an `SM_CLOCK_SYNC` keepalive at
envelope `inbound + 1`, and the ladder then occupies `inbound + 2` onwards. The
spike sent the ladder and nothing else, and the reference's own note on that
keepalive is "CLOCK_SYNC ~1/s after V3 so ClientSDK does not disconnect (4) at
10s of server silence" — the exact symptom (`transportError 4`, about ten
seconds after the last `ladder sent`). The session now emits it. The gate is
`everfall-world/tests/oracle_differential.rs`, regenerable with
`everfall-world/tests/fixtures/oracle_ladder.py`.

The spike is **OpenSSL** presenting an **RSA 2048 self-signed certificate**
(`CN=New World`), matching the Python lab. That was decided by measurement:
`dimpl` (pure-Rust, ECDSA-only) was bound on the REP port and the client sent
**twelve 159-byte ClientHellos and `dimpl` produced no flight at all**
(`dtls error: timeout: connect`), while the client's DTLS works against the
Python world that signs with RSA 2048.

## Preconditions

- The client's REP address is `127.0.0.1:9000`; it comes from
  `services/gateway/src/azoth_gateway/data/worlds.json`. No edit is needed to aim
  the client at the spike server — free that port instead.
- `services/world` (the Python REP server) also binds `127.0.0.1:9000`, so the
  world must **not** be running.
- `python ef.py dev` starts gateway **and** world **and** Caddy. Do not use it
  here; it would bind 9000.

## Commands

```powershell
# 1. free 127.0.0.1:9000 — stop the world (and anything else on the stack)
python ef.py dev status
python ef.py dev stop

# 2. start ONLY the gateway (port 8080); the world stays down
python ef.py gateway start
python ef.py gateway status

# 3. start the REP server on 127.0.0.1:9000 (leave it in the foreground)
cd server
cargo run -p everfall-net --bin everfall-netd
#    port override:  cargo run -p everfall-net --bin everfall-netd -- 9000
#    or:             $env:EVERFALL_NET_PORT = '9000'

# 4. in a second shell, launch the private client and drive it to character select
python ef.py game
#    unattended driver:
#    python scripts/session/private-run.py

# 5. when done: Ctrl-C the server, then
python ef.py gateway stop
```

Environment: `EVERFALL_NET_PORT` selects the bind port (default `9000`). The
server always binds `127.0.0.1`. The certificate is an **RSA 2048 self-signed**
cert with `CN=New World`, minted in memory at process start; nothing is written
to disk. `everfall-net` links a **prebuilt OpenSSL development package** (the
Windows OpenSSL installer, e.g. `ShiningLight.OpenSSL.Dev`); it does not build
OpenSSL from source, and the package is a prerequisite like the Windows SDK.

## What to watch (server stdout, timestamped)

| Line | Meaning |
| --- | --- |
| `datagram received: N bytes from …` | the client's DTLS stack reached our port and sent bytes |
| `flight sent: N bytes to …` | we answered with a real DTLS record |
| `Connected` | the DTLS 1.2 handshake completed end-to-end |
| `application data: N bytes` | a decrypted Carrier datagram reached the world |
| `rep reply sent: N bytes` | the world answered with the acceptance flight or the registration response |
| `registration answered: …` | the `0x3` response went out; the client should leave `WaitingForREPConnection` |
| `connect request answered (1): acceptance flight sent` | the client's `SM_CONNECT_REQUEST` opened the REP Carrier connection |
| `connect request answered (N>1): acceptance flight sent again …` | the client asked for a Carrier connection **after** the REP one was already accepted. That is the only wire shape a late actor-game-connection handshake can take, and it is the measurement rung 15 depends on (see "Rung 15" below) |
| `post-registration ladder armed: N record(s) …` | the three post-V3 rungs loaded and framed from the committed corpus |
| `ladder sent: N bytes` | one post-V3 record went out on the server's clock: 300 ms after the registration, then one record per interval (4 ms between chunks of one message, 30 ms between messages). The 17-byte line that repeats once a second is the `SM_CLOCK_SYNC` keepalive, not a rung |
| `no carrier reply` | the datagram carried no message this layer answers (e.g. a piggyback ACK) |
| `fatal Error: …` | OpenSSL gave up; the connection must be dropped |

The expected shape of a successful run is: `datagram received` (ClientHello)
→ `flight sent` (HelloVerifyRequest / cookie) → `datagram received` (ClientHello
with cookie) → `flight sent` (ServerHello, Certificate, ServerHelloDone)
→ `Connected` → `application data` (the `SM_CONNECT_REQUEST`) → `rep reply sent`
(the acceptance flight) → `application data` (the V3 registration) →
`rep reply sent` (the `0x3` response) → `registration answered`.

On the client side, `Game.log` should show the registration handler running:
`GameConnectionWrapper: received registration response from REP`, and the state
machine should move `WaitingForREPConnection -> WaitingForActorGameConnection`.

## What falsifies it

| Observation | Reading |
| --- | --- |
| No `datagram received` at all while the client reports connecting | The client never tried our port. Wrong host/port or wrong `RepAddress`; or it aborted before REP. **Not** a certificate result. |
| `datagram received`, `flight sent` (HelloVerifyRequest), then only repeats with no `Connected` and no `fatal Error` | Cookie roundtrip stuck: the client ignored or replayed the HelloVerifyRequest. Look for a second ClientHello datagram. |
| `datagram received`, `flight sent` (ServerHello/Certificate), then `fatal Error` naming a certificate or signature failure | The client reached our `ServerHello` and rejected the certificate. A "no" for this cert shape, not necessarily for RSA. |
| `Connected`, then `application data` but never `registration answered` | The DTLS layer is fine; the Carrier layer did not recognise the registration. The client's V3 may not carry the `00 01 13` marker where the server looks, or the reply was not ACKed. |
| `registration answered`, but `Game.log` never logs `received registration response from REP` and the state stays `WaitingForREPConnection` | The `0x3` body was sent but rejected. The card layout, the VLQ32 length, or the session token is wrong; the response did NOT do its job. |
| `registration answered` and `Game.log` logs `received registration response from REP`, state `WaitingForActorGameConnection` | The client passed REP registration. Proceed to the post-registration ladder. |
| The `ladder sent` lines share one timestamp (a burst) | The pacing regressed. The reference sends one record per interval and the client's Carrier queue truncates a burst; the session's scheduler must release one record per tick, not sweep a deadline. |
| `ladder sent` lines stop and the client logs `Unexpected client disconnect! {"transportError":4}` about ten seconds later | The keepalive stopped. The 17-byte `SM_CLOCK_SYNC` must keep leaving once a second for the whole session — the reference sends it forever, not only while replaying. |

## Post-registration ladder

The rungs above registration, in the order and at the pacing the reference uses
(`services/world/src/azoth_world/rep.py::maybe_send_post_v3` and
`::maybe_pump_replay`):

| Order | Rung | Wire | Kind | Pacing |
| --- | --- | --- | --- | --- |
| 14 → 15 | `SM_CLOCK_SYNC` keepalive (system channel 3) | — | SEND | the first tick after the `0x3` answer, then once a second for the rest of the session |
| 15 → 16 | self-identification, `PlayerManagerSelfIdentificationMsg` | `0x65c` | SEND (relayed on the server's clock) | 300 ms after the `0x3`, chunked at 1,100 B with a 4 ms gap |
| 16 → 17 | level info, `LevelInfoChangedMsg` | `0x663` | SEND | one message interval (30 ms) after the self-ident |
| 17 → 18 | spawn state, `ReplicatedStateBundle` | `0x08` | SEND (the emitter's `Emission`) | right up to the state bundle, chunked |

The keepalive row is why the ladder's envelopes start at `inbound + 2`: the
reference's outbound counter is `max(1, inbound + 1)`, its `0x3` answer is built
from `inbound + 1` without consuming it, and the keepalive takes that slot. Send
the ladder at `+ 2` with no keepalive and the reference's `+ 1` datagram is
simply missing from the stream.

The `WaitingForREPConnection` → `WaitingForActorGameConnection` transition is
**not** one of these: the atlas measures it as the Carrier actor game connection
reaching state 2 (`[carrier+0xA0] == 2`, getter `0x145A934A0`), a
**transport job**, not a message. The local rig satisfies it with the
client-side patch set `private-run` applies.

## Rung 15: what state 2 is, and the part the server owes

`[carrier+0xA0] == 2` is a field the client writes, not a value it parses:

- the getter is a pure comparison — `0x145A934A0` is
  `cmp dword [rcx+0xA0],2 ; sete al ; ret` (`research/atlas/meanings.md`, the
  Carrier flag table); and
- a scan of the whole 1.460 image finds **no** `mov dword [reg+0xA0], 2` — every
  such byte pattern in `.text` is a stack local (`c7 45 a0`). The value comes from
  the client's own connection state machine.

GridMate's state machine puts a connection in state 2 on the CONNECT_ACK path
(`conn->m_state = CST_CONNECTED`, the sequence the reference quotes from
`Carrier.cpp` in `services/world/src/azoth_world/rep.py::carrier_state_datagram`),
and the client's Carrier keeps resending its `SM_CONNECT_REQUEST` until one of our
datagrams is acknowledged. So the server's part is an **answer**, not a message:
whichever Carrier connection is waiting, the request it sends must get the
acceptance flight.

What the server used to do: answer the **first** request only, then go silent for
every later one (`no carrier reply`). The reference latches the same way, and the
measured 1.460 session against it still crossed rung 15 in 167 ms
(`Game.log` 13.210 `start actor game connection` → 13.377 `actor game connection
succeeds`), so the latch is not proven to be the cause — but it made the two cases
indistinguishable. The session now answers a request every
`CONNECT_REPLY_COOLDOWN_MS` (1 000 ms, the client's own lost-packet retransmit
timeout), so the live log says which case it is:

| Server log | Reading |
| --- | --- |
| one `connect request answered (1)` for the whole session | the client never asks for a second Carrier connection: rung 15 is client-owned, and the force is the client-side patch (`frida-rep-force-ladder.py`, VA `0x145A934A0`) |
| `connect request answered (2)` or more, and the client leaves rung 15 | the late handshake was the missing part; keep the answer and watch `WaitingForSpawnPoint` |
| `connect request answered (2)` or more, and the client still times out at rung 15 | the answer reached the client and did not move it: the condition is upstream of the handshake, and the next lever is the write side (a Frida watchpoint on `[carrier+0xA0]` naming the writer) |

The client-side force, if it comes to that, is the patch set in
`services/launcher/runtime-tools/frida-rep-force-ladder.py`: it patches
`0x145A934A0` (and the two rung flags after it) to `mov al,1; ret`, which is a
local answer, not a protocol fact.

**Provenance.** The rungs are re-encoded through their Atlas cards from the
committed corpus (`research/fixtures/wire/wire-bodies.json`,
`research/fixtures/wire/wire-fixtures.json`, `research/derived/state-bundle-fragments.json`),
so the BYTES are the server's framing. The VALUES are still the capture's until
the simulation owns them — `PostV3Ladder::from_captured` says so by name.

Report the server's lines and the two `Game.log` lines verbatim: they are the
evidence.

### What to watch on the client side

After `received registration response from REP`, `Game.log` should show, in
order:

* `GameConnectionWrapper: start actor game connection` then `Update state
  WaitingForREPConnection to new state WaitingForActorGameConnection`;
* `GameConnectionWrapper: actor game connection succeeds` → `WaitingForSpawnPoint`;
* `[GameMessagePort] LevelInfoChanged`, then `GameConnectionWrapper: spawn point
  found` → `WaitingForPlayerSpawn`;
* `GameConnectionWrapper: player spawn succeeds, in game` → `InGame`.

The measured 1.460 boundary is `WaitingForPlayerSpawn`: the client passes
`actor game connection succeeds` and `spawn point found`, then times out at
`State(WaitingForPlayerSpawn) is timeout`. A stall there is the interior of the
spawn bundle, not the transport above it.

**Pass condition for the rung-15 attempt:** the client leaves
`WaitingForActorGameConnection` for `WaitingForSpawnPoint` instead of timing out.
The two lines to grep in its `Game.log` are
`GameConnectionWrapper: actor game connection succeeds` and `Update state
WaitingForActorGameConnection to new state WaitingForSpawnPoint`; the failure is
`State(WaitingForActorGameConnection) is timeout : frames 10,
currentTimeoutIntervalCount 2`.

### What falsifies the ladder

| Observation | Reading |
| --- | --- |
| `connect request answered (N>1)` never appears, and the client times out at `WaitingForActorGameConnection` | no late Carrier handshake was attempted, so the rung is client-owned; see "Rung 15" above |
| `post-registration ladder armed` never appears in the server log | the corpus or its extents were not found; the server still answers registration |
| `ladder sent` lines appear but `Game.log` shows no `LevelInfoChanged` | the rung reached the Carrier but the client did not dispatch it: check the `0x65c`/`0x663` card framing (marker/varint) |
| The client stalls at a NAMED state (`WaitingForActorGameConnection`, `WaitingForSpawnPoint`, `WaitingForPlayerSpawn`) and then logs `State(<name>) is timeout` | the rung above that state did not land; name the state in the report — it is the falsifier, not the fix |
| `@mm_csdkerr_disconnect (4)` / `transportError` right after `ladder sent` | the chunk framing is wrong (flags `0x25`, `num_chunks`, one chunk per datagram) — the differential test says these bytes are identical to the reference, so read the next row before blaming them |
| `transportError 4` about ten seconds after the last `ladder sent`, with the state still `WaitingForREPConnection` | the server went silent; check that the 17-byte keepalive keeps leaving once a second |

## Local proof (no client required)

`cargo test -p everfall-wire` and `cargo test -p everfall-world` replay **real
captured datagrams** through the carrier layer and assert the reply bytes:

- `everfall-world/tests/rep_carrier.rs` replays the captured `SM_CONNECT_REQUEST`
  and the captured (LZ4-compressed) V3 registration from `.azoth/logs/` and
  asserts the acceptance flight, the `0x3` response and the `SM_CT_ACKS` byte for
  byte;
- `everfall-world/tests/post_registration.rs` builds the three post-V3 rungs from
  the committed corpus through the Atlas cards and asserts the session releases
  them only after the 300 ms delay, that the self-ident and level-info bodies
  re-encode byte for byte, and that the state rung is the emitter's payload,
  chunked; and
- `everfall-world/tests/oracle_differential.rs` is the differential gate: it
  drives the session through the V3 answer and compares the whole post-V3
  stream, datagram for datagram, against the Python reference's own encoding
  (`tests/fixtures/oracle_ladder.py` prints the table it pins). A one-byte
  payload change, a flag, a chunk count, a sequence or a missing keepalive
  fails it by record index; and
- `everfall-wire/tests/carrier_parity.rs` pins the envelope/record framing against
  the same captures.

`cargo test -p everfall-net` runs
`openssl_dtls12_handshake_and_round_trip_over_loopback`: an `openssl`-crate DTLS
1.2 client against this server over loopback, asserting `Connected` on both sides
plus one application-data round trip, and
`certificate_is_rsa_2048_with_cn_new_world`, which pins the certificate shape.
Both require the prebuilt OpenSSL development package (see `server/README.md`);
with it installed, a plain shell with no environment variables runs them.
