# Phase 3: the world, from registered to in-game

Specification for the rungs between the V3 registration response and `InGame`, and for the world
binary that drives them. Read `docs/PLAN-backend-rust.md` §8.1 and §15 Phase 3 first.

Build under test: `1.460.6033.6024067` /
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1.** The ladder is sent in the measured order, and no two rungs are batched: sending
  `SelfIdentification` and `LevelInfoChanged` in one burst **crashed the client** (recorded in
  `rep.py`).
- **S2.** `LevelInfoChanged` is wire type **`0x663`** and its body is the **captured 106-byte
  form**, not a composed one. The prototype's `level_info_changed_body()` is dead code whose
  layout disagrees with the capture (92 bytes, plain name twice instead of
  `coatlicue/NewWorld_VitaeEterna`).
- **S3.** The spawn record is `record_id 1` with **48 fragments**, payload **46,393 bytes**, and it
  is what moves the client from `WaitingForPlayerSpawn` to `InGame`.
- **S4.** The ongoing state stream is `record_id 1` with **9 fragments**, payload **7,154 bytes**,
  and it carries **no position**. Its job is to keep the ALC cable clear; it cannot move the player.
- **S5.** `worldd` owns one UDP socket, a fixed 50 Hz tick, and the state stream. It must not have
  a replay pump or any `AZOTH_REPLAY_*` environment variable: the acceptance is that the client
  reaches `InGame` with none of them set.
- **S6.** A session enters the world only with a **validated ticket**: the V3 `client_signature` is
  `sig:<ticket_id>`, the ticket has not expired, and it has not been consumed before.
- **S7.** No captured byte string enters a library crate. Captured payloads live as templates in the
  app layer, each with its capture id and a test that it still parses.
- **S8.** Every fact is build-scoped to the SHA-256 above.

## Tasks

| ID | Specs | State |
| --- | --- | --- |
| T1 | S1, S2 | done — `azoth-wire::ladder`, 7 parity tests against the captured fixture |
| T2 | S3, S7 | done — `azoth-wire::spawn` + fixtures; the brief was wrong about the framing |
| T3 | S4 | done — `azoth-wire::player_record` with a byte round trip |
| T4 | S5, S6 | pending — `worldd` |
| T5 | S1–S6 | pending — the client-in-the-loop acceptance |

## Log

### L1 — the user's request, verbatim

> Vale pues sigue toda la noche sin pararse con el servidor de rust real con las buenas prácticas que
> llevamos haciendo etc

### L2 — what the ladder actually is, measured

The capture's R-direction messages below replay seq `0x95`, in order:

```text
seq  type    size      what
0x01 0x3     88        RegistrationResponse (V3)
0x25 0x8  46,423       the state bundle: record 1, 48 fragments  <- the spawn
0x2a..0x6c 0x8 46,407  the same spawn bundle, repeated
0x73 0x8   7,166       record 1, 9 fragments — the ongoing player record
0x74..0x94 0x8 427..9,978  the world's other records
```

and `LevelInfoChanged` at `0x10` and `0x4d`, both 110-byte blocks, byte-identical, wire `0x663`.

**There is no separate `SelfIdentification` in the capture**, so that rung stays composed — which is
what the prototype does and what works.

### L3 — the discovery that changed this phase's shape

The prototype has a `level_info_changed_body()` function. It is **never called**, and its layout is
**wrong**:

| | prototype claims | capture |
| --- | --- | --- |
| body length | 92 | **106** |
| second string | the level name again | `coatlicue/NewWorld_VitaeEterna` |
| wire type | none (the caller supplies a placeholder header) | **0x663** |

So a port that followed the prototype's source would have sent a malformed message which the client
reads as a state trigger and silently fails to act on — the exact failure shape this project keeps
paying for. The ladder now takes the body from the capture and has **no builder** for it.

Its decoded structure: two length-prefixed strings, four big-endian `f32`
(`2048.0, 16.0, 12272.0, 10250.0`, identical in both captures so constants of the level), two zero
`u32`, four flag bytes, and **26 unexplained bytes**. Because those 26 are unexplained the message
cannot be composed; it is served from a template.

### L4 — a constant I got wrong, caught by a test

The unexplained tail was first written as 38 bytes, by arithmetic done in prose. A test that adds up
the fields with the actual string lengths says 26. The constant is corrected and the mistake is
recorded here because "arithmetic in a comment" is how a layout claim rots.

### L5 — T2: the spawn template, and three corrections to my own brief

**The framing.** I told the worker the bundle starts after a 20-byte prefix. It does not: the
prefix is **17 bytes**, and the typed marker is **not intact anywhere** in block `0x25` — byte 16 is
`0x0d` where the marker's leading `00` belongs. So the bundle cannot be found by marker search at
all. The proof is the sibling block `0x2a`: the same bundle with an intact marker at offset 0, and
`0x25[17:] == 0x2a[1:]` byte for byte, asserted by the exporter rather than assumed.

Consequence for the send path: use `bundle::encode(seq, payload)` — the `0x2a` shape — and never the
`0x25` bytes. Recorded in `research/docs/JAVELIN-PROTOCOL.md` §2e.

**No spawn fragment census exists.** `research/derived/state-bundle-fragments.json` is the
9-fragment *ongoing* census only. The 48 spawn boundaries are recorded as `null` rather than
invented, which is the rule this repository applies to every unmeasured layout.

**The payload is redacted.** 1,802 bytes across 161 spans are zeros where identifiers were. The
actor id and the position are outside every span, so the two fields the module writes are sound —
but the fixture now *declares* the redaction instead of letting a reader assume "verbatim capture".

**What held:** payload 46,393 B, record 1, 48 fragments, replication seq 1, the actor id at 29,731
preceded by the `00 00 00 02` anchor, and the position at 38,332/38,336 as
`(9343.6416, 2786.7327)` big-endian f32.

**A process note worth keeping.** Three of my four briefs this session contained a wrong premise
that the worker corrected by measuring. That is the system working — a brief is a hypothesis, and
the corpus is the authority — but it is also a reminder that "I read this in the prototype" is not
evidence when the prototype is a replayer with dead code in it.

### L6 — the Carrier flight: sent, and the client still will not register

The acceptance flight is implemented and **goes out** — the diagnostics show our 76-byte datagram five times, and the client retries its `CONNECT_REQUEST` five times in response, so the request/answer loop is live and the client is receiving something.

The client still ends at `@mm_csdkerr_connection_failed` and never sends its V3 registration.

**What the evidence says, and what it does not:**

| Observation | Reading |
| --- | --- |
| our flight is sent, 5 times | the trigger and the encoder work |
| the client re-sends `CONNECT_REQUEST` 5 times | it is **not** accepting our flight as an ACK |
| the client sends 10 records of **397 bytes** | that is *not* the V3 shape: the prototype's V3 arrives as **chunked** records of 1115 bytes |
| no `note=` lines | `registration()` never parsed anything, because no record reached it with a V3 body |

So the loop is: we answer, the client does not accept the answer, it retries, we answer again. That is exactly the "V3 retry storm" the prototype's own comment names — and the prototype fixed it with the **CT_ACKS piggyback**, which we do send.

**Two candidate causes, and they are distinguishable by one measurement:**

1. **The CT_ACKS range is wrong.** We echo `(ack_first, ack_last) = (sequence, sequence)` — the request's own envelope sequence. The prototype computes `ack_window_first(ack_last, datagrams_seen, ACK_WINDOW)`, i.e. a *window* over everything received, not a degenerate one-datagram range. If the client requires the range to cover its earlier datagrams, our reply does not acknowledge them and it keeps retrying.
2. **The `welcome` bytes are wrong.** We take the request payload minus its sys-id byte, truncated to 4. The prototype does the same, so this is less likely — but the prototype's fallback is `\x00\x00\x00\x05` and ours may be taking a different 4 bytes from a longer payload.

**The next measurement is narrow:** log the exact `CONNECT_REQUEST` payload we receive (we currently classify only its content type), and compare it against the prototype's `welcome` derivation on the same bytes. That single line tells us whether we are echoing the version the client wrote.

**What is NOT the problem, and is now proven:** the DTLS handshake, the one-socket demux, the peer lifecycle, and the fact that the client reaches us at all. Four separate defects were found and fixed to get here, each invisible before the diagnostics existed.
