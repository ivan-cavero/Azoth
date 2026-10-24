# Azoth backend, from zero, in Rust

Planning document. **No implementation is authorized by this file.** It fixes
the shape, the order, the acceptance criteria and the open measurements, so that
implementation phases can start without designing something that must later be
thrown away.

| | |
| --- | --- |
| Client build in scope | **1.460.6033.6024067** |
| Executable SHA-256 | `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033` |
| Size | 179,214,008 B (`research/atlas/builds.json`) |
| Floor already proven | the Python stack reaches `InGame` with a rendered world (`STATUS.md`, 2026-10-22 final) |
| Supersedes | the Rust target shape in `docs/ARCHITECTURE.md` §"Rust runtime shape" — amended here, with reasons, in §2 |

Every claim about the client below is either traceable to a file in this
repository or is marked **open** with the measurement that would close it. Where
this document disagrees with the research brief that commissioned it, it says so
and states what the alternative buys in *this* system.

---

## 0. Evidence discipline, and the debt this plan must pay first

The repository's rule is that a fact is only valid for the exact build it was
measured on (`AGENTS.md`, `research/atlas/builds.json`). The plan inherits that
rule, and applying it honestly produces an uncomfortable finding that shapes the
port order.

### 0.1 What is measured on 1.460

| Fact | Evidence |
| --- | --- |
| The client renders a world against our own server | `STATUS.md` 2026-10-22 (final): `InGame`, 26 `Slice:` lines, player possessed |
| Two private clients hold two REP sessions at once | `STATUS.md` 2026-10-22 (late): `dtls-established` with `peers: 2` |
| The six actor-replication message types exist, with ids | `research/atlas/presence-codecs.json` |
| Live unmarshal payload heads for the state bundle and four typed shapes | `research/atlas/presence-live-capture.json` |
| DTLS ClientHello: offered cipher suites, extensions, cookie, versions | measured for this plan from `research/sessions/live_20261022_r1460_trading_timed/network/pktmon.pcapng`; §0.3 |
| REP per-player bandwidth, both directions | same capture; §0.4 |
| A zone transition does not move the REP endpoint or the connection state | `research/sessions/live_20261022_r1460_zones/ANALYSIS.md` findings 2–3 |
| A zone transition issues 5 parallel TLS handshakes to the catalog service | same, finding 1 |
| Wire numbering unchanged from 1.400: all 7,052 type GUIDs identical | `docs/EXTRACTION-2026-10-22.md` |
| The remote-actor render blocker is structural and unchanged by the build move | `STATUS.md` 2026-10-22 (close) |
| The launcher patch suite, re-derived per build hash | `STATUS.md` 2026-10-22 |
| **The 1.460 Ghidra corpus exists** (1.1 GB, 423,609 ranges) | `reverse/builds/30fe6461…/corpus/`; `research/atlas/builds.json` still says otherwise and is stale |
| **The channel-1 container, locator and field layout** | `docs/archive/odd-tasks/remeasure-1460.md` L3: 229,304 records, len+crc valid on all, 222,389 with exactly one marker |
| **The yaw frame `forward = (−sin, cos)`** | same, L4: W/A/D give offsets 90/180/0 at fixed camera yaw; S is predicted only |
| **Walk speed 5.39 u/s** (not 3.83) | same, L4: nine episodes, three directions, 5.21–5.59 |
| **The five-position sliding buffer, newest-first** | same, L4: 343 records with 5 pairs; `buf(n+1)[1] ~ buf(n)[0]` at 0.0073 u on 341/342 |
| **State-stream cadence 1.00 Hz** for both kinds | same, L3 and L4 |
| **The spawn-record position reaches the client** | same, L5: server wrote (9500,2800), client reported (9498.4, 2801.4) |
| **The correction ladder fires on 1.460** | same, L5: HOLD → FREEZE → 1,478 `movement-correction-disconnect` |
| **The remote-config path carries the client's build version** | `research/atlas/observed-endpoints.json`: 24 families with `6033%3B6024067` (1.460) beside 26 with `6031%3B6004151` (1.400) |

### 0.2 What was **not** measured on 1.460 before Phase 0, and the status after it

Phase 0 ran on 2026-10-22 and its results are in `docs/archive/odd-tasks/remeasure-1460.md`. The table
below is the live state of the debt; a row is only safe to port from when it says
**verified**.

Everything in the second column was derived on `1.400.6031.6004151` / `8654f01d…`. The 1.460
client *accepts* the same bytes — it reaches `InGame` through them — which proves the
**codecs** still work. It does **not** prove that any field *offset* inside a fragment is
unchanged.

| 1.400-derived fact | Where it lives | Status on 1.460 |
| --- | --- | --- |
| channel-1 container, locator, `(yaw,pitch,x,y)` layout | `javelin/alc.py` | **verified** — 229,304/229,304 records pass len+crc; 222,389 carry exactly one `0.05` marker and the pair sits at `marker+12`, body offset 103 |
| yaw frame `forward = (−sin, cos)` | `movement.py` | **verified** — W/A/D give 90/180/0 at fixed camera yaw; S is predicted, not measured |
| walk speed 3.83 u/s | `movement.py` | **superseded** — 1.460 walks at **5.39 u/s** (9 episodes, 5.21–5.59) |
| five-position sliding buffer | `alc.py` | **verified**: 5 pairs in the 351/401-payload forms, 1 in the idle form, and **newest-first** (341/342 transitions at 0.0073 u vs 0.1847 u for oldest-first) |
| state-stream cadence (1 Hz world / 4 Hz player) | `rep.py` | **measured 1.00 Hz for both**; whether 4 Hz is needed for the ALC cable is still open |
| spawn-record position | `rep.py::apply_position_override` | **verified by effect** — the client spawned where the server wrote |
| State-bundle layout: `[00 01][varint 08][prologue][len][records]` | `javelin/bundle.py` | layout accepted in practice; **prologue invariants unverified** |
| Spawn record: 46,393 B, 48 fragments, replay seq `0x2a..0x6c` | `services/world/replay/messages-redacted.txt` | replayed and accepted; **fragment boundaries unverified** |
| Position at payload offset **38332/38336**; **fragment #35**, `key=16 type=11` | `rep.py`, `position_fragment_from_spawn` | **unverified** — but the write is value-anchored, so the port needs the anchor value, not the offset |
| Entity template: record 70, 2 fragments, 162 B, position at 6 and 74 | `entities.py` | **unverified** |
| Inventory response `0x16a0`: 427 entries, entry marker `00 01 82 5a`, start 68 B before it | `inventory.py` | **verified** — the corpus block is 99,819 B with 428 markers / 427 gaps, and `marker−68` lands on the NUL-padded container name. Only the `u32`-vs-`u8` type-name length at `marker+4` needed correcting (`docs/archive/odd-tasks/remeasure-1460.md` L5 §3) |
| `MEASURED_USED_SLOTS` 1..94 occupied, 95..255 NULL | `entities.py` | slot 95 re-confirmed NULL in the 1.460 lever run (`STATUS.md` 2026-10-22 close) |
| Entity transform `+0x14c/+0x15c/+0x16c` stride `0x10` | `STATUS.md` 2026-10-20 | **not measured** — `frida-actor-transform` timed out twice (3 GB scan, 15 min) |
| The reference frame offset `wire = accessor + (−2.2002, +3.3777)` | `movement.py` | **not a dependency** — documented per-session; calibrated at runtime |

**Consequence, and it was the first work item of the port:** the Rust `protocol` crate may
not embed a fixed offset until it is re-measured on `30fe6461…`. Phase 0 did most of that
and found the answer was mostly reassuring — the layouts did **not** move — while turning up
three rows that still need a different tool rather than a re-run.

The plan therefore separates two things the Python prototype mixes:

* **Format** (varint, framing, bundle grammar, fragment grammar, LZ4, V3,
  Carrier). Stable, and portable now.
* **Field map** (which offset inside fragment #35 is x). Build-scoped. Must be
  re-derived.

### 0.3 Measured for this plan: the client's DTLS offer

Parsed from the pcapng byte by byte: pcapng SHB/IDB/EPB blocks, then a strict IPv4
scan (pktmon wraps frames in an 18/20-byte L2 header, so a fixed offset does not
work), then the 13-byte DTLS record header and the 12-byte handshake header. Every
one of the 125,485 (trading session) and 55,563 (first session) UDP packets of the
REP flow parses as exactly one DTLS record, which is what identifies the flow.
Both 1.460 captures agree, and the three ClientHellos in each session are identical
after zeroing `random` and `cookie`.

| Item | Value |
| --- | --- |
| DTLS record versions present | `0xFEFD` (DTLS 1.2) for handshake and application data; **`0xFEFF`** on exactly two server records (HelloVerifyRequest, ServerHello) — that is the *official server's* OpenSSL build, not a requirement; ours sends `0xFEFD` on the ServerHello (§0.3, item 3) |
| `client_version` | `0xFEFD` |
| ClientHellos per session | 3: no cookie → HVR → cookie → **fresh** handshake (different `random`, same 5-tuple) |
| Cookie | 20 bytes on the second ClientHello only |
| `session_id_len` | 0 |
| Compression methods | `[0]` (null) |
| **Cipher suites offered** | **`0xC030` `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`, `0x00FF` `TLS_EMPTY_RENEGOTIATION_INFO_SCSV`** — nothing else, in any of the six ClientHellos |
| Extensions (6, in order) | `0x000B` ec_point_formats, `0x000A` supported_groups, `0x0023` session_ticket (empty), `0x0016` encrypt_then_mac (empty), `0x0017` extended_master_secret (empty), `0x000D` signature_algorithms (48 B, 23 algorithms) |
| supported_groups | x25519, secp256r1, x448, secp521r1, secp384r1 |
| Absent | renegotiation_info `0xff01`, use_srtp `14`, SNI `0`, supported_versions `43`, ALPN `16`, key_share `51`, heartbeat `0x0015` |

Product / swap policy for the crypto crate (OpenSSL now, measure before
alternatives, Windows link hygiene): [`docs/adr/0004-dtls-crypto-stack.md`](adr/0004-dtls-crypto-stack.md)
and master plan §0B. Mechanics below stay authoritative for the wire.

Three design consequences, and they are not negotiable:

1. **There is exactly one usable cipher suite.** The server must negotiate
   `0xC030` or the handshake fails; there is no fallback the client will accept.
   Any DTLS library that cannot do `ECDHE-RSA-AES256-GCM-SHA384` is disqualified
   outright, before maintenance or dependency-tree arguments are considered.
2. **The server's key must be RSA**, because the suite is `ECDHE_**RSA**`. The
   Python prototype already generates an RSA-2048 self-signed certificate with
   `CN=New World` (`rep.py::make_self_signed_cert`) and the client accepts it
   because its verify path is patched on disk
   (`STATUS.md` 2026-10-22: `CMP [rdi+0x288],0` at `0x145DCF9ED`, patch
   `e9 1a 01 00 00 90`). The certificate stays cosmetic; the **key type does
   not**.
3. **The record-layer version is OpenSSL's to choose, and it is not the negotiated
   version.** The official server sent `0xFEFF` (DTLS 1.0) for its HelloVerifyRequest
   and ServerHello while negotiating 1.2. **Our** OpenSSL 3.6.5 sends `0xFEFF` for the
   HelloVerifyRequest and `0xFEFD` for the ServerHello, and the client accepts both: the
   OpenSSL-based Python prototype never sets a record version at all
   (`SSL.Context(SSL.DTLS_METHOD)` and nothing more; `grep -rn FEFF services/world/` finds
   no code that sets one) and reaches `InGame`. So the byte is not a client requirement
   and not a server requirement — it is a property of the OpenSSL build on each side. A
   crate that tried to force either value would be pinning someone else's internal
   decision. This is still a reason to prefer a mature implementation over a new one, but
   for the correct reason: we do not control this byte and do not need to.

`extended_master_secret` is offered, so the server should honour it. A cookie
exchange is mandatory: the client re-handshakes with a cookie, which means the
server must implement HelloVerifyRequest, not just answer a bare ClientHello.

### 0.4 Measured for this plan: per-player bandwidth on the REP flow

Same two captures. `c2s` = client→server (the direction carrying the
ClientHellos).

| Metric | trading_timed (A) c2s | A s2c | first (B) c2s | B s2c |
| --- | --- | --- | --- | --- |
| Packets | 31,266 | 94,219 | 13,186 | 42,377 |
| UDP payload bytes | 8,614,963 | 17,806,943 | 3,323,770 | 9,529,641 |
| Duration | 1524.7 s | 1524.2 s | 679.3 s | 678.8 s |
| Packets/s | 20.5 | **61.8** | 19.4 | **62.4** |
| Payload B/s | 5,650 | **11,683** | 4,893 | **14,038** |
| Mean payload B | 275.5 | 189.0 | 252.1 | 224.9 |
| p50 / p95 / max payload B | 309 / 341 / 1152 | 180 / 225 / 1166 | 260 / 375 / 1152 | 191 / 362 / 1166 |

This is the single most useful number the extraction produced, and the plan uses
it three times: as the per-player bandwidth budget (§14), as the AOI tuning
target (§8.3), and as the load-harness profile (§14.2).

**Derived budget per player, from measurement:** ~12–14 kB/s egress, ~5–6 kB/s
ingress, ~62 datagrams/s egress, ~20 datagrams/s ingress. The 1,152/1,166 B
maxima confirm the ~1200-byte MTU constant the prototype already respects
(`REPLAY_CHUNK_SIZE = 1100`).

Two further readings that constrain the design:

* **The client sends ~20 datagrams/s** — one input record every ~50 ms, i.e. it
  runs its own 20 Hz input cadence against a 50 Hz server tick
  (`world tick_hz 50.0`, `TICK_HZ = 50` in `rep.py`). Input arrival and tick
  rate are therefore *not* the same clock, and the tick must not assume one
  input per tick.
* **90% of egress packets come from 74 distinct payload sizes**, and p50 is 180
  B. The official server was not filling datagrams. A design that batches to
  ~1200 B would cut packet count by an order of magnitude — and is therefore a
  *hypothesis to be validated against the client*, not a free win: the client's
  Carrier reader has a measured history of mishandling large records
  (`REPLAY_SINGLE_LIMIT = 256`, and the 12.7 KB record that was acked and never
  delivered, `rep.py` comments of 2026-09-24).

---

## 1. Scope, non-goals, and the process boundary

### 1.1 In scope — nothing here is optional

| Area | Contents |
| --- | --- |
| Identity and accounts | real accounts, real registration, real login, sessions, reconnect tickets, entitlements |
| Discovery | the channel document generated from live state; region and world directory; remote config layers |
| Content and assets | CMS (news, marketing tiles, MOTD), our own object storage, our own privacy surface, our own image serving |
| Character lifecycle | create from zero, persist everything, load, delete, name rules |
| World entry | region → world routing, login queue, prologue, appearing |
| Living in the world | levelling, movement, combat, gathering, inventory, crafting, auction house, instance content |
| Operations | gateway request logs, world monitoring, a real-time 3D map with observe-and-act |

### 1.2 Non-goals

* **Not a client modification.** The one client-side patch the project already
  requires (DTLS verify bypass, applied to a *private copy* of the executable,
  never to Steam's install) is a precondition, not a deliverable. Anything that
  would need a new client hook — including making remote bodies render, §8.6 —
  is out of scope and is reported as blocked, not worked around.
* **Not a re-implementation of AWS's internal topology.** The client sees one
  HTTP entry per region and one UDP endpoint per world. We reproduce what the
  client can observe; we do not build eleven services because Amazon had eleven.
* **Not a research harness.** Frida probes, Ghidra helpers, packet tooling and
  content authoring stay outside the production binaries
  (`docs/ARCHITECTURE.md`, and the plan keeps that boundary).
* **Not a language port of `rep.py`.** That file is 5,343 lines of accumulated
  experiment levers. Its *conclusions* are ported; its structure and its
  environment-variable zoo are not (§2.3).

### 1.3 The process boundary

Four processes. Each is justified by a different failure domain, a different
scaling axis, or a different reason to change — not by a folder.

```text
                        ┌──────────────────────────────────────────────┐
  client ── HTTPS ──▶   │ channeld   channel doc · CMS · content ·     │  N instances,
   (Caddy TLS on        │            images · privacy · entitlements    │  stateless,
    loopback)           │            platform tokens                   │  cacheable
                        └──────────────────────────────────────────────┘
                                        │ reads region/world registry
                                        ▼
                        ┌──────────────────────────────────────────────┐
  client ── HTTPS ──▶   │ regiond    world directory · login queue ·   │  1 per region,
                        │  (per region)  character directory · tickets │  own endpoint,
                        │            session/identity context          │  answers with no world up
                        └──────────────────────────────────────────────┘
                                        │ tickets carry RepAddress
                                        ▼
                        ┌──────────────────────────────────────────────┐
  client ── UDP/DTLS ─▶ │ worldd     REP · simulation · replication ·  │  1 per world,
   (direct, never       │  (per world)  partition ownership · the DB    │  own UDP socket,
    via a gateway)      │            that owns player state             │  registers with regiond
                        └──────────────────────────────────────────────┘
                                        │ read-only feeds
                                        ▼
                        ┌──────────────────────────────────────────────┐
                        │ opsd       metrics · audit · 3D map feed ·   │  read-only,
                        │            admin actions                     │  never on the tick
                        └──────────────────────────────────────────────┘
```

**Why these four and not fewer.** `channeld` is content and caching: it changes
when we publish a news item, and it must serve while every world is down.
`regiond` is entry and identity: it changes when a region opens, a world moves or
a login rule changes. `worldd` is simulation and truth: it changes when gameplay
changes, and it is the only process with a tick budget. `opsd` changes when we
want to look at something. Those are four different reasons to change, which is
the only justification this plan accepts for a process.

**Why not one process.** Because the client's own data says so. §0.4 shows the
egress path is ~62 datagrams/s per player; a GC pause, a `spawn_blocking` queue
backup or a slow SQLite write in the *same* process would land inside a 20 ms
budget. Separation is not a scalability claim; it is a blast-radius decision.

**Why the world is never behind the gateway.** Measured, not assumed: the client
takes `RepAddress` from the queue ticket and sends gameplay straight to
`35.71.153.244:53731` (`research/atlas/builds.json`, session `rep` block). The
gateway leaves the data path at the first packet.

---

## 2. Crate and module layout

### 2.1 The workspace

```text
server/
  Cargo.toml                 [workspace] + [workspace.dependencies] + [workspace.lints]
  rust-toolchain.toml        pinned toolchain, so a build is reproducible
  xtask/                     repository checks (§2.3); never shipped
  apps/
    channeld/
    regiond/
    worldd/
    opsd/
  crates/
    azoth-wire/              Javelin codecs
    azoth-dtls/              DTLS transport and per-peer demux
    azoth-session/           session state machine and delivery guarantees
    azoth-replica/           actor/record/fragment model and snapshot building
    azoth-aoi/               spatial interest management
    azoth-sim/               tick loop and authoritative rules
    azoth-model/             domain types
    azoth-store/             the two databases
    azoth-content/           datasheets, ids, object storage
    azoth-contract/          the client's exact JSON wire models
    azoth-http/              HTTP mechanics shared by channeld and regiond
    azoth-observe/           metrics, logs, audit, map feed
```

### 2.2 One sentence each: what it owns and why it is separate

| Crate | Owns | Why it is a separate crate |
| --- | --- | --- |
| `azoth-wire` | prefix varint, VLQ32, Carrier envelope, MessageRecord framing, the type-0x08 bundle grammar, fragment grammar, LZ4 block, V3 registration | Changes only when a *codec* is found to be wrong. It has no I/O and no state, so its parity tests can run against the whole captured corpus in a unit test. |
| `azoth-dtls` | DTLS 1.2 server role, cookie exchange, record layer, one socket + peer demux | Changes for crypto/library reasons, never for protocol reasons. Isolating it means a DTLS crate swap touches one crate and no game code. |
| `azoth-session` | the `transport → authenticated → active → draining → closed` machine, ticket validation, heartbeat, ACK windows, resend tables | The measured failure modes of this project all live here (ACK window wrap at 32,768, resend storms, teardown at ~1 h). It is pure logic over abstract I/O, so every one of those is unit-testable. |
| `azoth-replica` | the record/fragment model, interest groups, and the per-tick snapshot build | The bridge between "what the server believes" and "what the client is told". It owns the *one* place where a fragment byte is produced. |
| `azoth-aoi` | the grid, cell membership, incremental subscription deltas | The dominant cost of a tick (§8.4) and the primary scaling lever, with its own tuning measurements. |
| `azoth-sim` | the tick loop, entity storage, movement validation, correction policy, gameplay rules | The only crate with a latency budget. Kept free of transport, storage and HTTP so the budget can be reasoned about. |
| `azoth-model` | `Account`, `Session`, `Character`, `Region`, `World`, `Partition`, `Entity`, `Item`, `Currency`, ids and newtypes | Every other crate needs these types; none of them should own them. |
| `azoth-store` | two databases, migrations, blob codec, write-through cache, ledger | Persistence has its own failure mode (durability) and its own cadence (never on the tick). |
| `azoth-content` | datasheets, stable content ids, validation, object storage client | Changes when content changes, which is a different rhythm from code. |
| `azoth-contract` | the client's exact JSON models, field-for-field | This is the client contract. A field cannot be added here without a capture or a re-measurement. Separating it makes contract drift a diff in one crate. |
| `azoth-http` | routing, HTTP/1.1 semantics, ETag, `x-amzn-*` headers, `TCP_NODELAY` | Pure mechanics with measured quirks (§5.2). Contains no knowledge of what a world is. |
| `azoth-observe` | metric/log/audit split, tick-time manager, bounded exporter, map feed | Observability must be callable from the tick without allocating and without blocking, which is a hard enough constraint to deserve its own boundary. |

**Why the crate count is larger than `docs/ARCHITECTURE.md` proposes.** That
document sketched `protocol`, `simulation`, `content`. It was written before the
region model, the two databases, the ops surface and the observability
requirements existed. Each crate above earns its place by owning something with a
distinct reason to change; the plan amends ARCHITECTURE.md rather than silently
diverging, and the amendment is exactly "a region is a process, persistence is a
database pair, and operations is a consumer".

**What is deliberately *not* a crate:** one crate per endpoint, per packet type,
per component, or per game system. A component codec lives in `azoth-replica`
next to its siblings; a route lives in its app's `routes/` module.

### 2.3 The rule that keeps files small and the codebase coherent

Stated as admission rules, because "keep it clean" is not enforceable and these
are. `xtask` (§2.4) checks the mechanical ones.

1. **A module exists because a measured client behaviour or an authored gameplay
   rule requires it.** Its module doc states which, and cites the evidence path
   (`research/atlas/…`, `docs/…`) or the measurement id. A module that cannot
   name its requirement does not get merged.
2. **A file over ~400 lines means the boundary is wrong.** Split by
   responsibility, not by line count. (The Python prototype's `rep.py` is 5,343
   lines and is the counter-example this rule exists for.)
3. **No environment variable outside one `config` module per binary.** A setting
   is either configuration (declared, typed, documented, validated at startup)
   or it does not exist. This alone prevents the failure recorded in `STATUS.md`
   on 2026-10-22: a missing `AZOTH_REPLAY_*` variable was "not an error — a
   silently different experiment", and it cost an afternoon.
4. **No lever that selects between two behaviours.** Every A/B experiment this
   project ran has a recorded outcome in `research/atlas/client-functions.json`
   or `STATUS.md`. The port implements the winner and deletes the loser. A flag
   that toggles an unresolved question means the question is not resolved.
5. **Captured bytes are not production data.** If a captured body is genuinely
   required as a template, it lives in `azoth-replica::templates` as a named
   constant with its provenance, its capture id, and a test asserting it still
   parses and still produces the measured effect. Everything else is authored.
6. **A comment explains *why* or names a non-obvious constraint.** Never
   narrates the next line. This is already the repository standard
   (`AGENTS.md`) and the Python code mostly honours it; the port keeps it.
7. **Every public error is a typed enum.** The client's failure modes are
   specific (`@mm_csdkerr_*` codes, `Errors::connection_server_requires_anticheat`,
   `203` = parse error). A `String` error cannot be mapped back to the client's
   vocabulary.
8. **A `Risk:` line closes every change.** Per the repository's own harness
   rules, so the reviewer sees blast radius before the diff.

### 2.4 The mechanical checks (`xtask`)

```text
cargo xtask check
  ├─ no file in crates/ or apps/ exceeds 400 lines
  ├─ no `std::env::var` outside a crate's `config` module
  ├─ every crate has a module doc whose first paragraph names its requirement
  ├─ no `unsafe` outside azoth-wire (SIMD/LZ4) and azoth-dtls (FFI), each with a SAFETY note
  ├─ workspace lints are inherited, not re-declared per crate
  └─ the parity fixtures are present and hash-match the corpus manifest
```

---

## 3. Domain model, and who owns the authoritative copy

The single most important decision in the whole plan, stated first: **truth lives
in the world process that owns the entity, and every other component holds a
projection.** A projection may be stale; it may never be treated as truth.

| Aggregate | Identity | Authoritative copy | Projections | Notes |
| --- | --- | --- | --- | --- |
| **Account** | UUID + platform identity (`steam:7656119…`) | identity DB (via `regiond`) | `channeld` entitlements cache | One account, many personas is not modelled: the client carries exactly one persona through the whole chain (`routes/identity.py`) |
| **Session** | UUID, per connection | `regiond` until the ticket is redeemed; then `worldd` | — | Two phases, two owners, one handover (§6.3) |
| **Character** (directory) | UUID v4 | identity DB: id, name, persona, world binding, dates | `regiond` cache | The client's `CharacterMetadata` model carries **32** fields (`registry._seed_character`); the directory owns the ones the client *reads* and the rest are derived |
| **Character** (live state) | same UUID | world DB: position, vitals, attributes, progression, inventory, currency, quests | write-through cache in `worldd` | The split is the two-database split, and it is not arbitrary: the directory is read at login, the live state is read at spawn |
| **Region** | `fra-prod`, `gru-prod`, … | control store, single writer = that `regiond` | `channeld` channel document | A region record is its own `publicApis` + status + placement policy |
| **World** | UUID + name | `regiond` placement record; `worldd` lease | channel document, world list | Topology authority is the world; the region stores the committed projection (research: "directories and gateways store committed location projections") |
| **Partition** | `(world_id, cell_range)` | exactly one `worldd` at a time, with an **ownership epoch** | peer partitions during handoff only | Single writer per partition; §8.5 |
| **Entity** | `EntityId` (spawn-scoped, 64-bit) + `ActorId` (16-byte, client-visible) | the owning partition | replication snapshots | Two ids because the client has two: the actor id is what the wire carries, the entity id is what the server indexes |
| **Item** | UUID + content id | world DB (ownership), append-only ledger (movement) | replication | Duplication is prevented by the ledger, not by a column |
| **Currency** | per character, per currency id | **projection of the ledger** | replication | §9.5 |

**Deliberate non-modelling.** There is no `Player` type distinct from
`Character`, and no `GameServer` distinct from `World`. The Python prototype
grew a `PeerSession` that conflates connection, identity and player state
(`rep.py`), and every identity bug in `STATUS.md` (two clients = the same
character; `fill_local_player_uuid` rewriting each session's copy) traces to that
conflation. The Rust model keeps `Session`, `Account` and `Character` separate
and lets the ticket join them once.

---

## 4. Discovery: the channel document is generated from live state

The client fetches **one** document and reads regions out of its top-level keys
(`services/gateway/src/azoth_gateway/data/channel-azoth.json`, 187 requests to
`/STEAM_APP_ID.json` in `research/atlas/observed-endpoints.json`). This is the
lever the whole region model hangs on.

### 4.1 What the document is made of

```json
{
  "channelName": "Azoth",
  "<region-id>": {
    "displayName": "EU Central",
    "localizedName": "@mm_eu_central",
    "poolId": "us-east-1:0de93f7c-…",
    "publicApis": [
      {"clientTag": "authStack",               "apiEndpoint": "…", "awsRegion": "…", "stage": "prod", "version": "1.0"},
      {"clientTag": "loginGateway",            "apiEndpoint": "…"},
      {"clientTag": "JavelinGatewayServiceV2", "apiEndpoint": "…"},
      {"clientTag": "JavelinGatewayService-CF","apiEndpoint": "…"}
    ],
    "omni.privacy-settings.region": "us-west-2",
    "omni.privacy-settings.client-endpoint": "…"
  },
  "platformMetadata": {…},
  "omni": {…},
  "omni.privacy-settings.*": "…"
}
```

Two things about this shape matter and are easy to lose:

* The four `clientTag` values are **fixed vocabulary**. `regiond` supplies
  endpoints; it does not invent tags. A missing tag is a different client
  behaviour, not a fallback.
* `poolId` is `us-east-1:<cognito-pool-uuid>` and appears **verbatim as a path
  segment** in the remote-config requests (`…/configuration-sets/CognitoId/us-east-1:0de93f7c-814e-4d48-a8fd-b6efc2f9ed93/versionless`,
  155 hits). So a region's identity is not cosmetic: it is an addressing key the
  client uses elsewhere. `regiond` must allocate the pool id when the region is
  created and never change it.

### 4.2 The document is a rendering of live state, never a checked-in file

```text
channel document = f(region registry, per-region liveness, world placement)
```

* **Region registry** — durable, one row per region: id, display name, pool id,
  aws region, public API set, status. Single writer: that region's `regiond`.
* **Per-region liveness** — `channeld` asks each `regiond` for its health on a
  short interval and caches the answer. A region that fails its health check is
  rendered with `status: "MAINTENANCE"`, not removed: removing a key changes the
  client's region list length and is a *visible* product decision, while a status
  flip is the documented maintenance path.
* **World placement** — read from the same registry (each `regiond` publishes its
  worlds' placement records; §7.3).

The Python prototype already proved the rendering path works but keeps the base
document as a checked-in file and patches only `displayName`
(`routes/channel.py`). The Rust version inverts that: **nothing about a region is
in the repository except the seed of the first one.** Opening a region is a
registry write.

Consequences to build in from day one:

* **ETag is mandatory** — a CMS response without an ETag crashes the client
  (`routes/cms.py`, `docs/CLIENT_CONTRACT.md`). The channel document's ETag is
  derived from its rendered bytes, so a region status flip changes it and the
  client re-reads. That is the mechanism that makes a region change *live*
  instead of requiring a client restart.
* **`max-age` is part of the contract.** The prototype serves the channel at
  `max-age=30` and CMS at 60. A region opened at runtime becomes visible within
  one TTL. That is acceptable and is a documented operational property, not a
  bug.
* **The document must be renderable while every world is down.** A region with
  zero worlds still renders, with an empty world list. This is the requirement
  that forces the region/world split in the first place.

### 4.3 How a region is opened and closed at runtime

| Operation | What happens | What the client sees |
| --- | --- | --- |
| **Open** | insert the region row (id, pool id, display name, aws region, API set); start `regiond` with that id; `regiond` registers itself as healthy | the region appears in the dropdown after one channel TTL; `/prod/game/getlogininfo` for that region answers |
| **Close (graceful)** | set region status `MAINTENANCE`; `regiond` stops issuing tickets and refuses new logins; existing sessions keep playing | region still listed, marked maintenance; new logins refused with the client's own maintenance path |
| **Close (hard)** | stop `regiond`; health fails | region renders `MAINTENANCE` automatically; no redeploy, no code change |
| **Re-open** | reverse of close | as before, and existing characters are unaffected because the character directory is per-account, not per-region-process |

### 4.4 How a world announces itself to a region

Fleet-orchestration pattern (Agones' shape), applied because it removes the
failure mode the brief names — a claim nobody confirms must release itself.

```text
worldd start
  → RegionRegister { world_id, region_id, rep_address, build_sha256,
                     capacity, world_type, world_set }
  ← RegionAccepted { lease_id, lease_ttl, placement_epoch }
  → RegionRenew    { lease_id }            every lease_ttl / 3
  ← RegionRenewed  { lease_ttl }
  (missed renewals → regiond marks the world UNREACHABLE and stops issuing tickets)
```

Properties this buys:

* **A world has no heartbeat code of its own.** Renewal is one message on the
  same control channel; there is no separate monitoring protocol to keep in sync.
* **A crashed world disappears on its own** within one lease TTL. No operator
  action, no zombie in the world list.
* **Eligibility is a pure function** of the projection, so it is testable
  without a world:

```text
eligible(world, region, build) :=
      world.region_id == region.id
   && world.status == ACTIVE
   && world.lease_valid
   && world.population < world.capacity
   && world.build_sha256 == CHANNEL_BUILD_SHA256     // build-scoped, §0
   && world.world_type == requested_type
```

The build check is not decoration. Every fact in this repository is build-scoped;
a world built for `8654f01d…` serving a `30fe6461…` client is exactly the kind of
silent mismatch that produces "accepted, zero errors, no effect" — the failure
signature this project has paid for repeatedly (`STATUS.md`, 2026-10-18 and
2026-10-20).

### 4.5 How a world moves between regions without a redeploy

A world's region is **one field in its placement record**, and the client already
treats it that way: the world list carries `regionId` and `worldSet` per world
(`services/gateway/src/azoth_gateway/data/worlds.json`), and `getlogininfo` is
scoped by the requesting region so a world does not appear under every region
(`registry.worlds_for_region`).

Move procedure:

1. `regiond(A)` marks the world `DRAINING`. New tickets stop; the world keeps
   serving everyone already inside.
2. `worldd` flushes persistence (write-through cache → DB), then either keeps
   running until empty or disconnects at a deadline.
3. `worldd` restarts pointed at `regiond(B)` and registers. `regiond(B)` writes
   the placement record with the new `region_id`/`world_set` and a new
   `placement_epoch`.
4. `regiond(A)` drops its projection. The channel document re-renders; the world
   now appears under region B.

**What the players see:** they are disconnected and, on reconnect, get a ticket
from region B. That is the honest behaviour — a region change moves a *datacenter
placement*, and the client's region selection is per-login. What the plan refuses
to do is pretend a live player can be teleported across regions mid-session: the
client would have to re-run its whole login ladder, and `STATUS.md` shows the
ladder is where the fragile client-side state lives.

**No redeploy, no code change, one record and one restart.** That is the test.

---

## 5. Endpoint inventory

Source: `research/atlas/observed-endpoints.json` (75 families, generated
2026-10-20), `research/atlas/endpoints.json` (curated REST operations),
`research/atlas/models.json` (13 response models), and
`services/gateway/src/azoth_gateway/routes/`.

**The inventory is a lower bound, and the plan treats it as one.** That file is
regenerated from `services/gateway/traffic.jsonl`, which is gitignored; on
2026-10-22 a fresh run truncated it from 75 families to 42 and the file had to be
restored by hand (`STATUS.md`). The Rust gateway must therefore *accumulate* the
inventory rather than regenerate it, and unknown paths must be recorded with
their full request, not just counted.

**That trap fired again during Phase 0 and produced a finding.** Running the
Python stack for the re-measurement truncated the file from 75 families to 60
(39 lost, 24 gained); it was restored by **merging** rather than reverting, and
the merge exposed something the plan needs: the gained families are all the
**1.460 version segment `6033%3B6024067`**, where the committed inventory held
the 1.400 segment `6031%3B6004151`. So the client puts **its own build version**
into the remote-config path (`/<major><minor>%3B<build>`). Two consequences:

* the `versionless` and versioned forms are **different requests**, and a server
that only answers `versionless` leaves 24 families 404ing;
* the versioned path is **build-scoped data in the URL**, which is one more reason
§4.4's eligibility check compares the world's build to the channel's.

The merged file now holds **99** families (26 for 1.400's segment, 24 for
1.460's), which is the accumulated record rather than either snapshot.

Status legend: **known** = shape captured or RE'd and confirmed live · **partial**
= some fields proven, others not · **open** = required by the client but the
shape is not measured.

### 5.1 Identity and platform

| # | Endpoint | Hits | Client need | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | `POST /games/new-world/tokens` | 163 | Omni token exchange; supplies persona id and the account type that selects the entitlements path | `routes/omni.py` (parser order RE'd from OmniSDK 1.6.7; malformed = code 203) | known |
| 2 | `POST /auth/platform/user/code` | 163 | account-link code; a 404 makes Omni log "account link error … code: 202" | `routes/getlogininfo.py::is_platform_user_code_path` | partial — served as a stub `{"code","statusCode"}`; the *real* semantics (linking a Steam identity to a persona) are unmeasured |
| 3 | `GET /prod/credentials/omni` | 311 | SigV4 credentials for signing the `JavelinGatewayService` calls | `routes/credentials.py`: camelCase `accessKeyId`/`secretAccessKey`/`sessionToken`/`expiration` (**number**, not ISO) / `region`; the PascalCase+ISO shape crashes the client at `+0x7465476` | known |
| 4 | `GET /prod/game/getlogininfo/jwt/omni` | 842 | persona + character directory + region/world dropdown | `routes/registry.py::getlogininfo_doc`: **two schemas in one body** (lowercase `worlds` for the dropdown with int enums, PascalCase `LoginInfoList` object for the character gate) | known, fragile |
| 5 | `GET /players/{persona}/games/new-world/platforms/steam/entitlements` | 121 | ownership list | `routes/entitlements.py`: `{hasMoreResults, lineItems[]}` | known |
| 6 | `POST …/entitlements/sync` | 309 | sync; no response parser | same file: `{}` is the intended stub | known |
| 7 | `…/privacy-settings` (`GetPrivacySettingsForPlayer`, `CreateOrUpdatePrivacySettingsForPlayer`) | **0 in the inventory** | **required**: the client's `LevelInfoChanged` handler drops the world load unless byte `+0xa2` of the javContext is 1, and the only writer of that byte is inside the privacy endpoint client | `routes/privacy.py` cites `FUN_146446800`, `0x14160a754`, `FUN_14160a1f0` | **open** — the requirement is measured statically and is load-bearing; the wire shape is RE'd from strings with **no live capture**. Its absence from the inventory is itself a gap to close |

The privacy row deserves emphasis: it is the one endpoint where the plan knows
the *effect* (world does not load without it) and does not have a captured
response. §17 lists the measurement.

### 5.2 Discovery and remote configuration

| # | Endpoint | Hits | Need | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 8 | `GET /STEAM_APP_ID.json` (channel document) | 187 | **the** bootstrap: regions, their API endpoints, omni/privacy settings | `routes/channel.py`; shape in `data/channel-azoth.json` | known |
| 9–16 | `GET /applications/{public,publicGameplay}/configuration-sets/{ProductId,CognitoId,RegionId,WorldId}/{versionless \| <version>}` | 310/309/155/154/125/125/59/59/40/40/32/32/30/30/24/24 | StackConfig layers the client merges | `routes/s3.py`: sizes were captured, the *bodies* were not (TLS). Two key families are load-bearing and measured: `enable-anticheat` (bare key, read by `FUN_146193620`; without it REP registration fails with `connection_server_requires_anticheat`) and `javelin.offline-id-version`/`javelin.enable-offline-capitals` (the portrayal gate `FUN_146165f20`) | **partial** — sizes and required keys known, full document open |
| — | `GET /prod/game/worlds/list/jwt/omni` (+POST) | 6 | landing-screen world table, 16 `WorldMetadata` keys | `routes/worlds_list.py`, `registry._world_metadata` | known |
| — | `GET /` (DynamoDB POST target) | 5 | the client POSTs SigV4'd table queries | `app.py` answers `{"Items":[],"Count":0,…}` | partial — the target names are logged, not modelled |
| — | `GET /ping` | 8223 | region latency probe, shown in the UI | `app.py`: `text/plain` `healthy: …` | known |
| — | `GET /healthz` | 31 | liveness | — | ours, not the client's |

**Two quirks in this group that a naive Rust port loses, and they are measured:**

1. **HTTP/1.1 is mandatory.** `aws-sdk-cpp` (WinHTTP) *discards the body of a
   `200` served as HTTP/1.0* (`app.py` comment). A Rust stack that answers
   HTTP/1.0 or omits `Content-Length` reproduces a bug that took a session to
   find.
2. **`TCP_NODELAY` is mandatory.** Without it, headers+body writes hit Windows
   delayed-ACK/Nagle and the region ping the client displays measured 40–70 ms on
   loopback; with it, ~2 ms (`app.py`, `disable_nagle_algorithm = True`). This is
   a user-visible number in the UI and therefore part of the contract.
3. `x-amzn-RequestId`, `x-amz-apigw-id`, `x-amz-cf-id`, `x-amz-cf-pop`, `x-cache`,
   `via`, `age` are emitted on the `aws_id` routes because `aws-sdk-cpp`
   correlates responses by request id. Cheap to keep, expensive to discover.

### 5.3 Content and assets

| # | Endpoint | Hits | Need | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 17 | `GET /newsstories/{app}/metadata.json` | 4339 | news stories on the landing screen; polled continuously | `routes/cms.py` + `research/schemas/live/cms_news.json` | known |
| 18 | `GET /marketingtiles/{app}/metadata.json` | 11 | marketing tiles | `cms_tiles.json` | known |
| 19 | `GET /motd/worlds_{app}.json` | 3 | message of the day: per-locale `announcement`/`warning` per world, plus a global title/description | `registry.motd_doc` (locale list: `registry.LOCALES`) | known |
| 20 | `GET /cms/manifest` and `/cms/manifest.json` | 15 + 1 | **unknown** — nothing in the gateway handles it; it currently 404s into discovery | `observed-endpoints.json` only | **open** |
| 21 | `GET /images/{tenant}/{hash}/{id}/{name}.dds` | 12/11/11 | maintenance modal, news tile art; **a 404 makes the client retry 5× and show blank art** | `routes/images.py` serves a generated 256×256 BGRA DDS placeholder | known (placeholder), open (real art pipeline) |
| 22 | `GET /cms/manifest` and `/cms/manifest.json` | 15 + 1 | **unknown** — nothing in the gateway handles it; it currently 404s into discovery | `observed-endpoints.json` only | **open** |
| — | `client.catalogservice.amazongames.com` | not in inventory | **required for travel**: a zone transition issues exactly 5 parallel TLS handshakes in the same second, 5 at each transition and 0 at every other marker | `research/sessions/live_20261022_r1460_zones/ANALYSIS.md` finding 1 | **open** — host known, paths and shapes unknown; the only measurement is the 5-request pattern |

**Object storage is ours, and the client never sees it.** The client's credentials
(`#3`) are SigV4 credentials for signing gateway calls — they are not storage
credentials, and no captured flow shows the client touching an object store
directly. So: our object store sits behind `channeld`'s content routes, and
`azoth-content` owns the id → object mapping. That is what "our own object
storage" means here, and it keeps the storage backend swappable without a client
contract change.

### 5.4 Character

| # | Endpoint | Hits | Need | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 22 | `POST /prod/game/worlds/{worldId}/characters/jwt/omni` | 0 | create a character | path from `.rdata` @ `0x84ff388` (`endpoints.json`) | **open** — request body unmeasured |
| 23 | `PATCH /prod/game/characters/{characterId}/jwt/omni` | 0 | rename / update | same | **open** |
| 24 | `POST /prod/game/worlds/{worldId}/characters/validator/jwt/omni` | 0 | name validity gate | same; gateway serves `{"valid": true}` as a guess | **open** |
| 25 | `/characters` (list, any path containing it) | 0 | character panel | `routes/characters.py` — its own docstring says the shape is **GUESSED** | **open**, and honestly labelled as such by the prototype |

This is the largest open area in the inventory, and it is the one the plan
front-loads in Phase 2 (§15), because "create from zero" cannot be built on a
guessed envelope. §17 gives the measurement: run the create flow against a
gateway that records and 404s, and read the client's own parse errors.

### 5.5 Queue and world entry

| # | Endpoint | Hits | Need | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 26 | `POST /prod/game/login/queue/v2/jwt/omni` | 4 | enqueue; returns the ticket | `routes/queue.py::_ticket` | known |
| 27 | `POST /prod/game/login/queue/v2/{id}/jwt/omni` | 4 | refresh; `Position: 0` + a full `Token` is what moves the client from `WaitingForQueuedLogin` to `StartREPConnection` | same | known |
| 28 | *(no HTTP)* | — | world entry: the ticket's `RepAddress` is a UDP endpoint; the client speaks DTLS/REP to it directly | `research/atlas/builds.json` `rep` block | known |

The ticket is the identity handover, and two of its fields are load-bearing in a
way that is easy to miss:

* `Signature` **must be non-empty**: the queue handoff gate
  (`FUN_14643d110` → `FUN_14114b200`) compares the transformed token's leading
  string field, and an empty signature never triggers the next stage.
* `RepAddress` **must be a routable UDP `host:port`**, and it is the only place
  the client learns where the world is.

---

## 6. Identity, session and character lifecycle

### 6.1 Accounts, seeded but not faked

The brief is explicit: hardcoded credentials are a seed, never a dead end. The
implementation of that is a schema decision, not a code decision.

```sql
-- identity DB
CREATE TABLE accounts (
  account_id      TEXT PRIMARY KEY,          -- UUIDv4
  created_at      INTEGER NOT NULL,
  status          TEXT NOT NULL,             -- active | locked | deleted
  display_name    TEXT NOT NULL
);
CREATE TABLE identities (                    -- one account, many platform identities
  account_id      TEXT NOT NULL REFERENCES accounts(account_id),
  provider        TEXT NOT NULL,             -- 'steam'
  provider_id     TEXT NOT NULL,             -- '76561197960287930'
  linked_at       INTEGER NOT NULL,
  PRIMARY KEY (provider, provider_id)
);
CREATE TABLE credentials (                   -- the seed lives HERE, as data
  account_id      TEXT NOT NULL REFERENCES accounts(account_id),
  kind            TEXT NOT NULL,             -- 'password'
  verifier        BLOB NOT NULL,             -- argon2id
  updated_at      INTEGER NOT NULL,
  PRIMARY KEY (account_id, kind)
);
CREATE TABLE personas (
  persona_id      TEXT PRIMARY KEY,          -- 'amzn1.developerPersonaId.<uuid>'
  account_id      TEXT NOT NULL REFERENCES accounts(account_id),
  is_primary      INTEGER NOT NULL
);
```

The seeded account is one row per table plus a verifier. Adding real registration
is then: a new endpoint that inserts rows. **No schema migration, no code path
rewrite.** That is the test of "grows into real registration without redesign" —
the shape is already there and only the entry point is missing.

Three rules that come from measured client behaviour:

1. **The persona id must be `amzn1.developerPersonaId.<uuid>`.** The credentials
   override reader looks for a value starting with `amzn1.`
   (`routes/credentials.py::_override_persona`), and the client's own log prints
   `persona id OK`. Anything else is a different string in a field the client
   validates.
2. **The character UUID is a UUIDv4 and stable across restarts.** Measured
   requirement: `character_for_instance` is deliberately deterministic "because a
   restart must return the SAME character, or the client's savedata and the
   world's session disagree".
3. **The character *name* must differ per character.** Measured 2026-10-22: a
   derived id with the default name produced a level-1 placeholder called
   `Azoth_Dev` and **the Play button did nothing** — that client never opened a
   REP socket at all. Identity is not just an id.

### 6.2 The login chain, end to end

```text
channel document      → which region, which endpoints
Omni tokens           → persona id, account type ('shadow' | 'full')
credentials/omni      → SigV4 signing material (5-minute refresh)
entitlements          → ownership; determines the store/ownership gates
getlogininfo          → region-scoped worlds + this account's characters
worlds/list           → the landing-screen table
queue/v2              → a ticket: { TicketId, Signature, RepAddress, WorldId,
                                     WorldName, CharacterId, PersonaId, SteamAppId,
                                     SteamUserId, IssueTime, GenerateTime,
                                     TokenVersion }
DTLS + V3 registration→ the ticket is redeemed against the world
```

Each arrow is a place the client can stall, and `research/docs/SERVER-CONTRACT.md`
records the observed state machine for every one of them. The Rust services
implement that machine as a state enum per phase, not as a chain of `if`s, so a
stall is reportable as "which arrow" instead of "the client is stuck".

### 6.3 Session states, and the two owners

```text
   ┌──────────┐  DTLS ok   ┌──────────────┐  V3 ticket ok  ┌────────┐
   │transport │───────────▶│ authenticated│───────────────▶│ active │
   └──────────┘            └──────────────┘                └────────┘
        │  no handshake within deadline   │  bad ticket         │  drain
        │                                 ▼                     ▼
        │                          ┌──────────┐          ┌─────────┐
        └─────────────────────────▶│  closed  │◀─────────│ draining│
                                   └──────────┘          └─────────┘
```

| State | Owner | Deadline / rule |
| --- | --- | --- |
| `transport` | `worldd` | **authentication deadline**: a DTLS session that has not registered within the window is dropped. The Python prototype has no such deadline and instead relies on the client's 15 s registration timeout — which is why a failed handshake is invisible server-side and `AZOTH_LOG_RAW` exists. |
| `authenticated` | `worldd` | the ticket is validated here: `TicketId` + `Signature` against the claim `regiond` recorded, plus `WorldId`/`CharacterId` matching. **This is the identity handoff and the Python prototype does not do it** — it accepts any registration and rewrites the character uuid per session. |
| `active` | `worldd` | heartbeat + idle timeout. The measured reason heartbeats exist: the client's state watchdog (`FUN_146445e10`) counts frames with no expected message and tears down when the budget is exhausted (`rep.py`, 2026-09-27). |
| `draining` | `worldd` | no new spawns; existing players finish; persistence flushed |
| `closed` | `worldd` | release the ticket, emit an audit record |

**Ticket expiry must not close an authenticated session.** The ticket's job ends
at `authenticated`. On success the world issues a **fresh reconnect ticket with an
explicit expiry** and the client keeps only the latest. The plan encodes that as
two distinct types, so the mistake is unrepresentable:

```rust
struct LoginTicket { id: TicketId, signature: TicketSignature, expires_at: Instant, .. }  // entry
struct ReconnectTicket { id: TicketId, expires_at: Instant, generation: u32 }              // post-auth
```

### 6.4 Character lifecycle: create → persist → load → delete

| Step | Where | What must be true |
| --- | --- | --- |
| **create** | `regiond` writes the directory row (id, name, persona, world binding) inside one transaction | the id is a UUIDv4 minted here; the name is validated by whatever `#24` turns out to require |
| **persist** | `worldd` writes the live aggregate through the write-through cache | position, vitals, attributes, progression, inventory, currency, quests. **Compact binary blob**, versioned (§9.3) |
| **load** | `worldd` at spawn | the *only* moment the server decides the player's position (measured: the spawn record carries x/y; the ongoing state variant does not — `STATUS.md` 2026-10-18 "the position is SPAWN-ONLY in replicated state") |
| **delete** | `regiond` marks the directory row deleted and enqueues a world-side purge | the ledger is **never** deleted (§9.5); the aggregate is tombstoned, then purged |

**The load step is where this plan differs most from the prototype.** Today the
prototype sends a captured 46 KB spawn record with the position rewritten by
value search. The Rust server composes that record from the character's own
persisted state: actor id, appearance, position, level, vitals, inventory
summary. That is only possible once the fragment field map is re-measured on
1.460 (§0.2) and the per-component codecs are decoded (§8.6) — which is exactly
why those two items sit in Phase 0 and Phase 4 rather than being assumed.

---

## 7. Region and world model

### 7.1 A region owns

| Owns | Not owned |
| --- | --- |
| its world directory (the placement projection) | the world's simulation or its state |
| its players' session and identity context until a ticket is redeemed | a session's authoritative state after redemption |
| routing into a world (allocation) | the game data path — that is UDP straight to the world |
| its own public API endpoint set, rendered into the channel document | the channel document itself (that is `channeld`) |
| its own availability, independent of any world | — |

**It must start, answer and survive with no world up.** That is the requirement
that makes the region a real component rather than a naming convention: a region
with zero ACTIVE worlds still answers `getlogininfo` (with an empty world list),
still answers the queue (with a refusal the client can render), and still renders
in the channel document.

### 7.2 Allocation

When a queue request arrives, `regiond` allocates:

```text
allocate(request) :
  candidates = worlds where eligible(world, region, build) && world.type == request.type
  best       = argmin(candidates, by = (queue_depth / capacity, population))
  if none  → refuse with the client's own "no worlds" path (documented: an empty
             world vector produces login_no_worlds / 0x11)
  claim    = { claim_id, world_id, character_id, expires_at = now + CLAIM_TTL }
  persist claim (so a regiond restart does not lose it)
  return ticket { RepAddress: best.rep_address, WorldId, WorldName, .. }
```

**A claim nobody confirms releases itself.** `CLAIM_TTL` is short (30–60 s) and
expiry is a lazy check on read, not a timer per claim: the region never holds a
timer per pending login. If the client never connects, the capacity is available
again after one TTL. If it does connect, the world's registration is what
confirms it — the world sees the `CharacterId` in the V3 body and reports
`ClaimConsumed { claim_id }` to its region.

This is Agones' allocation contract with the parts we need: atomic claim,
eligibility filter, self-release on non-confirmation. It buys the property the
brief asks for — a crashed handoff costs nothing — without importing a
Kubernetes-shaped fleet manager for a private server.

### 7.3 What the world owns, and what it publishes

The research is unambiguous and the plan follows it: **the world owns topology
and placement.** The region stores a committed projection.

| World publishes | Cadence | Consumed by |
| --- | --- | --- |
| lease renewal | `lease_ttl / 3` | `regiond` |
| placement record (`world_id`, `rep_address`, `region_id`, `world_set`, `status`, `population`, `capacity`, `build_sha256`) | on change + every 5 s | `regiond` → channel document, world list |
| `ClaimConsumed { claim_id }` | on session authentication | `regiond` |
| health (tick p99, players, overruns) | 1 s | `opsd` |

The world never asks the region where a player is; the region never tells the
world what to simulate.

### 7.4 Draining

| Trigger | Behaviour |
| --- | --- |
| operator | `DRAINING`; region stops new tickets; world keeps everyone, refuses new spawns |
| lease expired (region lost the world) | region marks `UNREACHABLE`; **players keep playing** — the world's authority does not depend on the region being reachable, which is the point of not putting the region on the data path |
| world shutting down | flush persistence, then disconnect at a deadline; a client that reconnects gets a ticket from the same region for another eligible world |
| region shutting down | region refuses new logins, existing worlds keep serving their players; on region restart the worlds re-register |

### 7.5 Independent failure

| Failure | Blast radius | Recovery |
| --- | --- | --- |
| `channeld` down | no new bootstrap; existing clients keep their region endpoints because they already read the document | restart; ETag changes if state changed |
| `regiond` down | that region cannot accept new logins; **existing worlds and players are unaffected** | restart; worlds re-register within one lease |
| `worldd` down | that world's players disconnect | restart; persistence is already flushed (write-through) |
| `opsd` down | no dashboards, no map | restart; **no gameplay impact by construction** (§12.4) |
| identity DB down | no new logins; running sessions unaffected | restore |
| world DB down | the world cannot flush; it must **stop accepting new spawns and keep ticking**, then drain | restore |

That last row is a policy decision worth stating: a world whose persistence is
unavailable must not silently keep accepting players, because their progress
would be lost. It degrades to "no new spawns", which is visible, instead of
"silent data loss", which is not.

---

## 8. Simulation model

### 8.1 Tick rate, budget, and the accumulator

* **50 Hz, 20 ms** (`world tick_hz 50.0` measured in the capture;
  `TICK_HZ = 50` in the prototype).
* **Keep tick work under ~50% of budget**, i.e. under 10 ms, so an input spike has
  headroom. A tick that normally takes 19 ms is already broken.
* **Fixed timestep with a time accumulator.** The simulation is a function of
  accumulated simulated time, never of wall-clock deltas. A slow tick does not
  change the amount of simulation; it changes how many steps run next time, and
  the loop reports the overrun.
* **One tick = input → simulate → replicate**, with the three rates kept
  separate: script/game logic per tick, movement at a fixed delta derived from the
  tick, replication at its own cadence (measured: the official server emits ~62
  datagrams/s, i.e. ~1.2 per player per tick at the population we can infer).

Budget arithmetic that the design must respect:

| Population | Budget per player per tick (10 ms target) |
| --- | --- |
| 2,500 (first gate) | **4 µs** |
| 10,000 (design target) | **1 µs** |

4 µs per player per tick is the number that rules out allocation in the hot path,
per-recipient serialization, and any per-player hash map rebuild. §8.4 says what
the design does instead.

### 8.2 Where authority actually lives — and where the brief is wrong

The brief says: "The server owns authoritative world state; clients propose
inputs." That is correct for **everything except the local player's locomotion**,
and the repository has measured the exception thoroughly enough that building on
the general statement would repeat a closed dead end.

Measured facts (`STATUS.md` 2026-10-18, `docs/ROADMAP.md` §3):

* The ongoing player-state variant of `record_id 1` (9 fragments, 7,154 B) carries
  `key=16 type=11` with a **49-byte payload and no position at all**. The position
  exists only in the 48-fragment spawn variant.
* The component maps are **first-write-wins**: re-sending a key is discarded, so a
  correction cannot travel by re-sending state.
* `ReceivePlayerPositionClientMsg` (4216) → `IPositionReceiver`: the interface's
  apply method is `ret 0` on the vtable, and a full `.rdata` search finds exactly
  two occurrences of the QI pointer, both inside that same vtable — no concrete
  class implements it statically, and none is built at runtime.
* Every correction cvar in the client is **client-side**; every server-side cvar
  is **validation or input control** (`alc-speed-hack-fix-v2-enabled`,
  `-wipe-inputs`, `-max-buffered-inputs`, `num-inputs-to-wait-for`,
  `alc-request-input-throttle-server-override-delay-ms`).

So the authority the server has over the local player is:

| Over | Mechanism | Proven |
| --- | --- | --- |
| the spawn position | the spawn record's x/y pair | 0.0000 u from what the server wrote (1.400; re-verify on 1.460) |
| the *accepted* trajectory | validate the client's claim against the server's own position | 3,317 samples adopted, 0 violations, 0.0027 u mean prediction error, live |
| the *right to keep playing* | the correction ladder: ACCEPT → HOLD → FREEZE → DISCONNECT, where **FREEZE** is the measured lever (stop the player state stream and the client's simulation freezes) | live, twice: HOLD(1) → FREEZE(5) → DISCONNECT(1000), channel-1 payload collapsed 405 B → 120 B and the player froze for 8 s of held W |
| what other clients are told | replicated state | the mechanism the client demonstrably applies |

**What this buys in this system:** the simulation does not need a
server-authoritative locomotion model that the client would ignore, and it does
not need to invent a correction message the build does not have. It needs a
*validator with teeth* (FREEZE is proven to work) and an authoritative record of
the accepted trajectory for persistence, AOI and anti-cheat.

**What it costs:** the server cannot teleport a player, cannot rubber-band a
cheater back, and cannot express "you are not where you think you are" other than
by freezing input. That is a real limitation of this build, not a design
preference, and the plan states it rather than designing around a message that
does not exist.

Everything else — NPCs, gatherables, structures, other players, loot, combat
results — is server-authoritative in the ordinary sense, because the server
*originates* those records and the client applies them.

### 8.3 AOI: the primary scaling lever, as a first-class concept

Replicating everything to everyone wastes the measured 12–14 kB/s budget and
leaks information. AOI gives each client a spatial subscription; only objects
inside it are replicated.

**Structure: a uniform grid, not a quadtree.** Reasons, in this system:

* The tick cost is dominated by *membership maintenance* (a player crosses a cell
  boundary a few times a second at 3.83 u/s measured walk speed), not by query
  sophistication. A grid's insert/remove is O(1) with a flat `Vec<EntityId>` per
  cell; a quadtree's is O(log n) with rebalancing.
* A grid is cache-friendly and allocation-free after init, which the 4 µs budget
  requires.
* Incremental updates are trivial to state as a *delta*: a player's subscription
  changes only when it enters or leaves a cell, so the per-tick work is
  proportional to movement, not to population.

Quadtrees win when density is extremely skewed over a huge extent. New World's
world is a fixed set of zones with bounded extents, so a grid's worst case is
bounded and known. **The plan therefore commits to a grid and makes the
subscription boundary a first-class concept** — `Subscription` is a type in
`azoth-aoi`, not an `if` in the replication loop — so a hierarchical AOI can
replace it later without touching `azoth-sim`.

| Parameter | Initial value | How it is set |
| --- | --- | --- |
| cell size | 64 u | hypothesis; a 3.83 u/s walk crosses it in ~17 s, so membership churn is negligible |
| subscription radius | 2 cells (~128 u) | **tuned by measurement, not chosen**: the target is our bytes/player/s against the measured 11.7–14.0 kB/s at comparable entity density. If our radius produces more, it shrinks |
| update policy | enter/leave deltas every tick; full re-send never | a full re-send is what the prototype does and what the first-write-wins map rejects |
| recomputation | staggered: one cell-ring per tick | spreads the dominant cost (§8.4) |

**What this buys:** the egress budget is a function we control, and the
information a player's client receives is a function of position rather than of
who else is online. **What it costs:** a player at a cell boundary sees
entities appear/disappear, so the radius must be larger than the visible range,
and the "appear" event must be a complete record rather than a delta — which is
what the client's record-slot model already requires (creation applies the whole
record; updates are filtered).

### 8.4 Where the tick time goes, and what the design does about it

For hundreds of players in one area the dominant costs, in order, are **AOI
recomputation**, **replication serialization**, then **the network write**. The
design attacks each explicitly:

| Cost | Design response | Measured justification |
| --- | --- | --- |
| AOI recomputation | incremental; only on cell-boundary crossing; ring-staggered | churn is proportional to movement, not population |
| replication serialization | **serialize once per interest group per tick, share the bytes** | the prototype re-encodes per recipient, and the official server's p50 of 180 B suggests it was *not* batching at all — so there is headroom, but it must be validated (§0.4) |
| network write | batched per tick, non-blocking, bounded queue | one datagram per event is what produced the prototype's 1:1 reply storm (286 outbound for 185 inbound, measured 2026-10-09) |
| everything else | round-robin: AI for 1/N of entities per tick, staggered AOI, deferred persistence | a tick that does everything every tick has no headroom |

**Serialization is not the same as the wire format.** The client's format is
fixed Javelin. What is shared per interest group is the *encoded Javelin payload*
(`Arc<[u8]>` of the bundle's payload region), not an rkyv archive. rkyv's role is
internal (§10).

### 8.5 The partition handoff protocol

This is the part the brief warns about, and the measurement changes the shape of
the problem in a way worth stating first.

**Measured: a zone transition does not move the REP endpoint and does not touch
the connection state machine.** `GameConnection` stayed `InGame` across two
transitions; the REP endpoint and world id were unchanged; the packet rate was
flat (85.9 → 84.1 → 82.2 pkt/s); and the only network signature was 5 parallel
catalog TLS handshakes for the destination metadata
(`research/sessions/live_20261022_r1460_zones/ANALYSIS.md` findings 1–3).

Consequences:

* The handoff is **entirely server-side**. There is no new ticket, no new DTLS
  session, no new actor id, and the client keeps streaming input to the same
  session throughout.
* Because the client never pauses, **input crosses the switch**, and exactly-once
  semantics is not a nicety: the naive delete-from-A/create-in-B produces the gap
  the brief describes *while the client keeps sending*.
* A "zone transition" is a change of *which partition arbitrates the player*, and
  the client's own visible event (the 5 catalog fetches) is a **separate,
  required** endpoint we do not yet know the shape of (§5.3).

Protocol:

```text
                     ┌──────────────── PREPARE ────────────────┐
source partition A                                          target partition B
  lock migration intent (player may not be migrated twice)
  epoch_A = current epoch
  snapshot = rkyv(player aggregate)  ───────────────────────▶ accept snapshot
  input_seq_floor = last applied input sequence               allocate entity id
  open an overlap zone: A keeps arbitrating                 prewarm visibility
  ─────────────────────── COMMIT ──────────────────────────▶
  stop applying new input to A's copy                         B applies buffered input
  ownership = B, epoch = epoch_A + 1 ◀──────────────────────  ack(epoch, applied_seq)
  notify subscribers (both directions, ordered)
  ─────────────────────── RELEASE ──────────────────────────▶
  drop A's copy after release_grace                          A's snapshot discarded
```

Four properties, each with the mechanism that provides it:

1. **Single writer per partition, with an ownership epoch.** Every write carries
   `(partition_id, epoch)`. A write with a stale epoch is rejected, not merged.
   This is what makes "A still thinks it owns the player while B already accepts
   input" unrepresentable rather than unlikely.
2. **Exactly-once input across the switch.** The client's input is already
   sequenced by the Carrier layer (per-session reliable sequence) and carries a
   record sequence the server reads. During the handoff A forwards inputs above
   `input_seq_floor` to B in order; B deduplicates against a small window. Because
   the switch is server-side and the session is unchanged, the input sequence is
   continuous — the property the brief asks for is achievable here, and it is
   achievable *because* the client does not reconnect.
3. **An overlap zone at borders.** At a partition border both partitions have the
   player's cell in their AOI; A keeps arbitrating until B confirms commit, and B
   prewarms visibility and entity state during prepare. The overlap exists to make
   the commit window invisible, not to duplicate authority.
4. **Self-release.** Prepare carries a TTL. If commit does not arrive, A keeps
   ownership, B discards the snapshot, and nothing is lost. A crashed target costs
   one TTL and no state.

**What this buys:** a partition switch that is invisible to the client, with no
double-write window and no lost input. **What it costs:** a player's aggregate
must be snapshot-able at any moment, which forces the persistence model to have a
canonical serializable form (§9.3) — that requirement is why the blob codec is
designed before the handoff is implemented, not after.

**Scope note.** Partitions are a *within-world* concept in this plan. A world
process starts with one partition covering its whole extent, and the handoff
machinery is exercised from the beginning (a single-process handoff between two
partitions in the same runtime) so that distributing partitions across processes
later is a transport change rather than a redesign. Building multi-process
partitions before the single-process handoff is correct would be exactly the
premature distribution `docs/ARCHITECTURE.md` forbids.

### 8.6 The presence blocker, stated plainly

The server cannot currently tell a client that another player exists, and after
that it cannot make one render. Both halves are measured:

| Half | State | Evidence |
| --- | --- | --- |
| Which messages carry actor replication | **known**: `AddActorMessage` 449, `SpawnActorsMsg` 574, `Replicate` 391, `ReplicateClient` 407, `FragmentUpdateMsg` 422, `UpdateMsg` 106 | `research/atlas/presence-codecs.json` |
| Their wire layouts | **not decoded**, and the static route that worked on 1.400 is gone: the name and GUID strings have **zero** static referrers, both 16-byte GUID forms occur zero times, and `FUN_1407de270` has no callers. The descriptor tables are assembled at runtime | same file |
| How to decode them | **live instrumentation**: hook the type dispatch (atlas already names `vtable+0x90`) and read the unmarshal when a message arrives; `reverse/probes/client/frida-unmarshal.py` already works for exactly this | `presence-codecs.json`, `presence-live-capture.json` |
| Whether a replicated remote actor **renders** | **no**, and it is not a server problem: all 26 `Couldn't get Transform component on the slice!` warnings name `slices/remoteplayer.dynamicslice`; the slice job's `QueryInterface` returns null for `{83482F97-84DA-4FD4-BF9E-7FE34C8E091F}` while **274 vtables** implement it. Both ways of supplying the Transform from outside were tried and both crashed the client | `STATUS.md` 2026-10-19, 2026-10-20, 2026-10-22 (close) |

So Phase 4 (§15) delivers the **wire-level** half: the server originates actor
records, the client accepts them with zero unmarshal and zero validation errors,
and the client's own entity table contains the actor at the server's position
(provable with the existing transform probe at `Transform +0x14c/0x15c/0x16c`,
stride `0x10`). The **render** half is reported blocked, with the two honest
options the roadmap already names, and the plan does not spend a phase on it.

---

## 9. Persistence

### 9.1 Two databases, because they have two load shapes

| | Identity DB | World DB |
| --- | --- | --- |
| Contents | accounts, identities, credentials, personas, characters (directory), sessions, tickets, claims, region/world registry | characters (live state), inventories, ledger, quests, territory, world entities that must survive a restart |
| Read pattern | small rows, per login, high burst at launch | large blobs, per spawn, then never on the tick |
| Write pattern | rare, transactional | periodic flush from the cache + ledger appends |
| Lifetime | survives world resets | survives world resets, per world |
| Failure means | no new logins | no persistence; the world must stop accepting spawns (§7.5) |

**Engine: SQLite, two files, WAL mode, via `rusqlite` with the bundled SQLite.**
Reasons specific to this system:

* It is a private server on one machine. A PostgreSQL server process is an
  operational dependency with no payoff at this scale, and the capacity gate
  (2,500) is about simulation, not about database throughput — persistence is
  off the tick path by construction.
* **The driver is blocking, and that is a feature.** The brief's own warning is
  that blocking work on the async executor starves everything else. A blocking
  driver makes it impossible to accidentally call the database from the tick; every
  access goes through `spawn_blocking` or a dedicated persistence thread by
  necessity rather than by discipline.
* WAL gives concurrent readers with one writer, which matches the access pattern:
  the world writes flushes, the region reads directories.
* ACID transactions and real migrations are exactly what the ledger needs.

**What it costs:** one C dependency (SQLite, vendored, builds with MSVC on
Windows), and no cross-machine scale-out. The mitigation is a trait boundary
(`azoth-store::WorldStore`) so a Postgres implementation can be added when a
measurement demands it. **Rejected:** `sqlx`/Postgres (a server process and an
async driver that invites the exact mistake the brief warns about), and an
embedded KV store (no real transactions, no SQL for the ledger's audit queries).

### 9.2 Migrations: versioned, forward-only, checked in

```text
migrations/identity/0001_accounts.sql
migrations/identity/0002_characters.sql
migrations/world/0001_characters.sql
migrations/world/0002_inventory_ledger.sql
...
```

Rules:

* Forward-only. No down migrations — a private server can restore a backup, and
  a down migration is a second code path that is never tested.
* The applied version is recorded in the database, and startup **refuses to run**
  if the database is ahead of the binary. That is the check that prevents a
  rolled-back binary from silently corrupting newer data.
* A migration that touches a blob column ships with the blob migration function
  (§9.3) in the same commit.
* Tests run every migration from empty and assert the resulting schema hash, so a
  migration cannot drift.

### 9.3 The player aggregate: compact binary, versioned, evolvable

The brief is right that JSON is too loose and too large for a hot persistence
path, and right that zero-copy archived formats are the wrong choice for state
that must survive format changes. The design takes both halves:

```text
blob = [magic "AZP1"][u16 schema_version][u32 payload_len][payload]
```

* `payload` is a compact serde encoding of the versioned `PlayerAggregate`.
* `schema_version` is the authority. Reading is: decode with the version's own
  type, then run the chain of `migrate_v(n) -> v(n+1)` functions to the current
  version. The migration functions live next to the type, and a test asserts that
  every historical version has a path to current.
* **Why not rkyv here:** archived layouts are not schema-evolution friendly
  (rkyv's own tracker has append-only evolution as an open, unfinished item), and
  a persisted aggregate is precisely the case that must survive a format change.
  A zero-copy read on a spawn path that happens once per login buys nothing.
* **Why not `bincode` 1.x:** it is flagged unmaintained (RUSTSEC-2025-0141) — a
  fact visible in this ecosystem, since webrtc-rs migrated off it for exactly that
  advisory. We do not need to adopt an unmaintained serializer to save a
  dependency we can audit in an afternoon.

**De-normalisation, stated where it is used.** The aggregate keeps a `level` and
`gear_score` next to the attribute map even though both are derivable, because
the world list, the character panel and the AOI broadcast all need them without
loading the attribute set. The rule: a denormalised field must name its source of
truth in a comment and must be recomputed by the same function that mutates the
source. Anything else is a cache with no invalidation.

### 9.4 The write-through cache

* The world holds the authoritative in-memory aggregate for every loaded
  character. Mutations mark the aggregate dirty.
* A dedicated persistence task flushes dirty aggregates on a fixed cadence
  (1–5 s) and on every lifecycle boundary (spawn, drain, disconnect, shutdown).
* **Persistence is never on the tick path.** The tick only sets a dirty bit; the
  flush happens on another thread, with a bounded queue that drops a *duplicate*
  dirty mark rather than growing.
* On disconnect the flush is synchronous and must succeed before the session is
  reported closed — otherwise a crash between "closed" and "flushed" loses the
  session's last seconds silently.

### 9.5 Economic state is an append-only ledger

For anything economic — currency, item acquisition, item transfer, auction
settlement, crafting consumption — the balance is a **projection of movements**,
not a mutable column.

```sql
CREATE TABLE ledger (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  at            INTEGER NOT NULL,
  character_id  TEXT NOT NULL,
  kind          TEXT NOT NULL,      -- gain | spend | transfer_in | transfer_out | craft_in | craft_out | auction_settle
  item_id       TEXT,               -- NULL for currency
  currency_id   TEXT,               -- NULL for items
  amount        INTEGER NOT NULL,   -- signed, in minor units
  reason        TEXT NOT NULL,      -- the gameplay event that caused it
  correlation   TEXT NOT NULL       -- groups the movements of one transaction
);
CREATE INDEX ledger_character ON ledger(character_id, seq);
```

* Balances are `SELECT SUM(amount) … GROUP BY item_id/currency_id`, cached in
  memory and rebuilt on load.
* Every movement has a `correlation` id, so a trade is two rows with the same
  correlation and an audit can prove they sum to zero.
* **A ledger row is never updated and never deleted.** A correction is a new row.
* The invariant is enforced by a test, not by hope: for every `correlation` that
  represents a transfer, the sum across characters is zero, and no character's
  balance can go negative without a matching `spend` row.

**What this buys in this system:** the bug class the brief names — duplication
that ruins a private server's economy — becomes detectable by a query instead of
by a player report. **What it costs:** a balance read is an aggregate query, which
is why the in-memory cache exists; and the ledger grows forever, which is
acceptable because it is the audit record and it is the one table that must never
be pruned.

---

## 10. Serialization, per use

| Use | Format | Why | Rejected |
| --- | --- | --- | --- |
| **Wire** (client traffic) | Javelin: prefix varint, Carrier envelope, MessageRecord, type-0x08 bundle, fragments | It is fixed by the client. There is no choice here; the only question is how faithfully we implement it | anything else |
| **Replication payload sharing** (per interest group per tick) | the encoded Javelin payload bytes, shared as `Arc<[u8]>` | the cost to remove is *encoding per recipient*, not the format | rkyv — it cannot be the wire format, because the client does not read rkyv |
| **In-memory snapshots** (handoff, map feed, ops) | **rkyv** | zero-copy archived reads; built once, read by several consumers in the same process; ephemeral, same version on both ends | serde+bincode (a copy per reader), JSON (size and speed) |
| **Cross-process high-rate** (world → ops map feed) | **rkyv** | same reasoning, and the producer and consumer ship together so schema evolution is not a requirement | protobuf (a schema compiler for one internal message), JSON |
| **Cross-process control** (region ↔ world) | compact serde (postcard) | low rate, debuggable, versioned envelope; a control message is read by a human when something breaks | rkyv (opaque on the wire, and debugging matters more than speed here) |
| **Persistence** (player aggregates) | **versioned envelope + compact serde** | must survive format changes; read once per login | rkyv (no schema evolution), JSON (too large for the hot path), bincode 1.x (unmaintained) |
| **Ledger** | SQL rows | queryable, auditable, transactional | a blob |
| **Content** (datasheets) | the client's own formats, read by `azoth-content` | 2,250 `.datasheet` files already contain the game's numbers; inventing a format would discard them | a new DSL |

The distinction that matters and is easy to blur: **rkyv is never on the wire and
never in the database.** It is the internal shared-snapshot format. The wire is
Javelin and the database is a versioned envelope, and both of those are
requirements, not preferences.

---

## 11. Wire model strategy: how a field cannot drift silently

Two different problems, two different mechanisms.

### 11.1 The JSON contract (`azoth-contract`)

The client's HTTP models are **strict**. The evidence is not theoretical:

* `getlogininfo` needs **two schemas in one body** — lowercase `worlds` with int
  enums for the dropdown, and a PascalCase `LoginInfoList` **object** (not array)
  for the character gate. Without the envelope the candidate vector stays zeroed
  and the dropdown shows `0/0` (`registry.getlogininfo_doc`).
* `WorldMetadata` is **exactly 16 keys**; an unknown-typed key drops the whole
  element on strict parse (`registry._world_metadata`).
* The dropdown model and the gate model want **different types for the same
  field**: `status` is `"ACTIVE"` (string) in one and `1` (int) in the other, and
  `publicStatusCode` is `0` in the gate and `1` in the dropdown. The prototype
  keeps them as three separate functions (`_login_world_dropdown`,
  `_login_world_gate`, `_world_metadata`) precisely because of this.
* A missing field in `credentials/omni` **crashes the client** (`+0x7465476`,
  a null-deref of a parsed double), and a wrong type (`expiration` as ISO string)
  does the same.

Mechanism:

1. Every client-visible model is a **separate Rust type** with
   `#[serde(rename_all = "camelCase")]` or explicit renames — never a shared type
   with an enum that can serialize two ways. The three world shapes are three
   types, and the compiler makes it impossible to send the dropdown type where the
   gate type is expected.
2. Every field carries a doc comment naming its **evidence**: the capture file,
   the RE'd function, or "open — see §17". A field with no evidence does not
   exist.
3. `deny_unknown_fields` on request bodies we parse (so a client change is an
   error, not a silent ignore) and **allow** extra fields on responses (the client
   ignores unknown keys via FNV-1a runtime hashing, per `routes/privacy.py`).
4. A **golden-body test per route**: the exact bytes the prototype serves are a
   fixture, and the Rust route must produce byte-identical output for the same
   input, or the diff is reviewed and the fixture updated deliberately.

### 11.2 The binary contract (`azoth-wire`)

Parity is proven the only way that means anything: **against the corpus, byte for
byte, and against the client, behaviour for behaviour.**

| Layer | Parity test |
| --- | --- |
| prefix varint / VLQ32 | decode every varint in `services/world/replay/messages-redacted.txt` and re-encode; must round-trip exactly. Anchors already known: `0x15d`, `0x1b88`, `0x663`, `0x16a0`, lengths 692 and 46393 |
| Carrier envelope + MessageRecord | parse all 177 captured messages, re-serialize, byte-compare |
| type-0x08 bundle | parse every captured bundle, re-emit, byte-compare; then assert the structural invariants the client measured: `fragment_count` equals the client's own nested-call count for all 90 recorded records |
| fragment grammar | `[varint key][varint type_index][payload]`, first two varints at offset 0 and 1 — assert over the 300-fragment probe record |
| LZ4 block | decompress every compressed capture, recompress with the same settings, byte-compare |
| V3 registration | the 832-byte request round-trips byte-for-byte (a parser that cannot reproduce its input is wrong — the Python tests already enforce this) |
| typed containers | the two forms differ and both matter: the **client's** container is `[crc32][len][target][00 01][varint type][body]` (verified 40,279/40,279 channel-1 records), the **server's** is `[vlq32 len][00 01][type][body]`. A parity test asserts each on its own channel |

Then, and only then, the client: **the same fixtures produce the same observable
result on the real client.** The floor is defined and measured — `InGame`, 26
`Slice:` lines, player possessed, 0 `Exceeded max recursion for deferred actions`
(`STATUS.md` 2026-10-22 final).

### 11.3 The differential harness

A `python az.py` subcommand stays the oracle. For any wire behaviour:

```text
fixture ──▶ Python implementation ──▶ bytes A
        └─▶ Rust implementation   ──▶ bytes B
assert A == B, and record both in the run's evidence file
```

This is the mechanism that makes "keep the Python stack runnable" a tool rather
than a sentiment, and it is why the Python services are not deleted when the Rust
ones pass: they are the oracle for the next behaviour.

---

## 12. Observability and operations

### 12.1 The three things, kept separate

| | Metric | Log | Audit record |
| --- | --- | --- | --- |
| Shape | aggregate, numeric, always on | discrete structured event, per-component target | who did what, append-only |
| Cost budget | fixed, pre-allocated | bounded, sampled when high-rate | never sampled, never dropped |
| Cardinality | **no player id, no entity id, ever** | ids allowed (it is a log) | ids required |
| Retention | 15 days rolling | 7 days rolling, per component | forever |
| Consumer | dashboards, the map's health view, alerts | debugging a specific session | economy disputes, admin actions, bans |

The cardinality rule is not stylistic. A metric labelled by player id produces one
time series per player, and at 2,500 players a single histogram becomes 2,500 ×
buckets series. Per-player data belongs in a log line and in the audit table.

### 12.2 Metrics that speak the game

| Metric | Type | Why it exists |
| --- | --- | --- |
| `azoth_tick_duration_seconds` | histogram (p50/p95/p99) | the contract. A server that cannot state its p99 cannot claim 50 Hz |
| `azoth_tick_overruns_total` | counter | the visible failure mode: the loop wakes late and the rate sags |
| `azoth_tick_rate_hz` | gauge | measured, not assumed |
| `azoth_players_online` | gauge (per world, per region) | capacity gate input |
| `azoth_sessions_total{state}` | counter | where sessions die: transport / authenticated / draining |
| `azoth_entities{kind}` | gauge | NPCs, players, gatherables, props |
| `azoth_aoi_subscription_size` | histogram | the direct driver of egress bytes |
| `azoth_bytes_sent_per_player` | histogram | the budget check against the measured 12–14 kB/s |
| `azoth_datagrams_sent_total` | counter | batching effectiveness |
| `azoth_replication_encode_seconds` | histogram | isolates serialization from simulation |
| `azoth_input_latency_seconds` | histogram | per-player latency, as a distribution, never as a label |
| `azoth_resend_total{reason}` | counter | the ACK/resend failure modes this project already paid for |
| `azoth_db_flush_seconds` | histogram | proves persistence is off the tick path |
| `azoth_claim_expired_total` | counter | allocation health |

### 12.3 Not blocking the hot path

* **A bounded queue with a batch processor.** The tick writes into a
  pre-allocated ring buffer of fixed-size metric events. If the buffer is full,
  **the event is dropped and a drop counter is incremented.** Dropping telemetry
  is always cheaper than adding latency to a tick, and the drop counter is itself
  a metric, so the loss is visible.
* **Head sampling for traces at ~10%.** High-frequency per-tick spans are sampled
  at the head; errors and audit records are not sampled at all.
* **No allocation in the emit path.** Metric names and label values are `&'static
  str`; the ring buffer is fixed at startup.
* **Three sinks, three writers.** Metrics flush on a timer thread, logs on a
  bounded channel, audit writes synchronously to its own append-only table (it is
  low rate and must not be lost).

### 12.4 How the map and world monitoring consume it without touching the tick

Covered in §13. The one-line version: they are **subscribers to a snapshot
feed**, and a feed with no subscribers does no work.

### 12.5 Profiling, so "why is the tick slow" is measured

* `perf` with frame pointers plus flame graphs, on Linux for the capacity gate.
* A tick profiler built into the server: named scopes around each tick phase
  (input, simulate, aoi, encode, egress) with a rolling histogram per scope. The
  budget is per phase, so a regression names its phase instead of "the tick got
  slower".
* Allocations: a counting allocator behind a feature flag, reporting
  allocations-per-tick. Target: **zero steady-state allocations per tick** in
  input→simulate→encode; egress buffers come from a pool.

---

## 13. The 3D real-time map

The requirement: a real-time 3D view of the world showing every player, NPC,
enemy and gathering node, with the ability to observe and act.

### 13.1 The data the simulation must expose

A map needs a tiny projection of world state, not the world:

```rust
struct MapSnapshot {            // rkyv, built once per publish interval
    tick: u64,
    at: u64,                    // server time, ms
    world: WorldId,
    entities: Vec<MapEntity>,   // flat, pre-sorted by id
}
struct MapEntity {
    id: u64,
    kind: EntityKind,           // Player | Npc | Enemy | Gatherable | Structure | Node
    pos: [f32; 2],              // the wire is 2D (§0.2); height is derived client-side
    yaw: f32,
    hp_permille: u16,           // 0 for non-damageable
    level: u16,
    flags: u16,                 // dead | in_combat | mounted | gathering | in_instance
    label_id: u32,              // index into a per-snapshot string table, never a String here
}
```

Three deliberate choices:

* **Flat, id-sorted, no pointers.** It is rkyv-archived and read by the viewer
  process without copying; a string per entity would defeat that, so labels go
  through a string table.
* **2D position.** The client's own protocol carries a 2D position and the
  renderer derives height (`STATUS.md` 2026-10-18: "the wire carries a 2D position
  and the client derives the height"). The map does the same, and the ground
  height comes from the zone's own terrain data, not from the entity.
* **No player-identifying label in the snapshot.** A label id maps to a name in a
  side channel the viewer resolves only for an operator with the right permission.

### 13.2 The transport to the viewer

* **A snapshot feed, not a per-entity event stream.** The world publishes
  `MapSnapshot` at a configurable rate (default 2 Hz, 5 Hz for a "live" view).
* Transport: rkyv frames over a dedicated WebSocket (browser viewer) or QUIC/UDP
  (native viewer). The feed is served by `opsd`, which subscribes to worlds; the
  browser never talks to a world.
* **Delta option:** the snapshot carries a `base_tick`; the viewer may request
  deltas after the first full snapshot. Deltas are computed in `opsd` by diffing
  two archived snapshots, so the world still only produces snapshots.
* **Actions travel the other way as commands**, not as state: `opsd` → `regiond`
  or `worldd` with a typed, permissioned, audited command
  (`Teleport { character, to }`, `Spawn { kind, at }`, `Kick { session, reason }`).
  Every command writes an audit record **before** it is applied, so a command that
  crashes the target is still recorded.

### 13.3 Why it costs nothing when nobody is watching

* The feed is a **subscription with a reference count per world**. With zero
  subscribers the world's publish step is one atomic load and a branch; no
  snapshot is built, no allocation happens, no bytes are serialized.
* The snapshot build is **opt-in per world** and its cost is measured as its own
  histogram (`azoth_map_snapshot_seconds`), so if it ever enters the tick budget it
  is visible rather than suspected.
* The build runs **on the world's own thread at a tick boundary** — not inside the
  tick. It reads the same entity storage the tick just finished with, which is why
  it is cheap: no locks, no copying of the world, just a linear pass over the
  entities in the published interest set.
* `opsd` is a separate process, so a viewer that connects and asks for 60 Hz
  cannot affect a tick. If it overloads `opsd`, the map degrades.

**What this buys:** a live 3D view whose cost is proportional to the number of
people watching, with a hard process boundary that makes the worst case a broken
map rather than a broken world. **What it costs:** the map is not frame-exact —
it is a 2–5 Hz projection, which is the right fidelity for "who is where" and the
wrong fidelity for spectating combat.

---

## 14. The performance contract, and how "better" becomes falsifiable

### 14.1 The contract

| Property | Value |
| --- | --- |
| Tick rate | 50 Hz fixed, 20 ms |
| Tick budget target | p99 **< 10 ms** (≤ 50% of budget) |
| Overruns | 0 in a 10-minute sustained run at the stated population |
| Population gate 1 | **2,500** concurrent players in one world, clustered in one area |
| Population gate 2 | **10,000** (design target; not a claim until measured) |
| Per-player egress | ≤ the measured official budget: **≤ 14 kB/s** and ≤ 70 datagrams/s |
| Reconnect | 100% success across a 200-session reconnect burst |

### 14.2 The baseline: measure the Python prototype first

Without this, "better" is unfalsifiable. Method:

1. Instrument the Python world with the same tick-time manager (rolling window,
   mean/p50/p99/overruns) — the prototype already has a tick loop with a 20 ms
   socket timeout (`RepServer.serve_forever`), so the measurement is a wrapper
   around it, not a rewrite.
2. Drive it with the **real protocol**, not a mock: the load harness of §14.3 in
   client mode, pointed at the Python world.
3. Step population 1 → 2 → 4 → 8 → 16 → … and record at each step: ticks/s
   achieved, tick p50/p99, bytes/s each direction, and the first step where the
   achieved rate falls below 50 Hz.
4. Record the hardware, the client build, the commit, and the run id alongside the
   numbers.

**Expected finding, and it must be reported even if it is this:** the Python world
is single-threaded with per-peer `pyOpenSSL` memory BIOs, so it will fall behind at
a very small population. That number *is* the baseline, and stating it is more
useful than pretending the comparison is close. The honest framing is "the
prototype's ceiling is N synthetic peers; the Rust target is 2,500 at p99 < 10 ms".

### 14.3 The load harness

* A separate binary (`worldd --harness` or a dedicated `azoth-loadgen`) that uses
  **`azoth-dtls` in client mode and `azoth-wire` to speak the real protocol**:
  real DTLS handshake with the real cipher suite, real Carrier framing, real
  channel-1 input records at 20 Hz, real typed requests.
* It does **not** need the client's DTLS-verify patch, because it is not the
  client — it accepts the self-signed certificate deliberately. That is the point
  of a protocol-level harness: it is faithful on the wire and free of the client's
  UI.
* It replays a **captured input trace** (channel-1 `0x635` bodies recorded from a
  real session) so movement is realistic rather than synthetic, and it can
  optionally cluster all peers into one AOI cell to create the worst case the
  contract names.
* It reads the server's own metrics at each step (scrape `/metrics` from the
  world's loopback listener), so the harness never has to infer server state.
* Stepping, not ramping: hold each population for a fixed dwell (60 s), record,
  then step. A ramp hides the knee.

### 14.4 Hardware, named

The gate must run on the intended server hardware. The development machine is
measured and is the *lower* bound:

| | Development machine (measured) |
| --- | --- |
| CPU | Intel Core i7-7700HQ @ 2.80 GHz, 4 cores / 8 threads |
| RAM | 15.9 GB |
| Disk | 240 GB SSD (TOSHIBA-TR200) |
| OS | Windows (dev); the gate should run on Linux |

A 4-core laptop CPU is not the target. The plan requires the gate to name the
machine it ran on, and forbids quoting a number measured on the dev box as a
capacity claim.

### 14.5 Where the original is slow or wasteful, and how this design beats it

| Python prototype | Cost | Rust design |
| --- | --- | --- |
| One OS thread for socket + DTLS + simulation + encoding | no parallelism; a slow tick delays reads and the socket buffer grows | one reader pool + a dedicated simulation thread; the tick never touches a socket |
| `pyOpenSSL` `SSL.Connection` per peer with memory BIOs (copy in, copy out) | 2+ copies per datagram per peer, per direction | DTLS record layer over pre-allocated buffers; zero-copy where the cipher allows |
| Replay pump re-sends captured bytes on a timer | unbounded, unmeasured; the "levers" are all timing knobs | server-originated state, no replay path at all |
| Per-recipient re-encoding | O(recipients × payload) | encode once per interest group, share `Arc<[u8]>` |
| 1:1 reply behaviour, coalesced only by a hand-tuned timer (`ACK_COALESCE_S = 0.05`) | measured 286 outbound for 185 inbound | ACK batching is part of the tick's egress phase, with a bounded budget |
| `Arc<Mutex<World>>`-shaped access (single thread, so no contention, but no scale either) | cannot use more than one core for simulation | actor-owned world state, no shared mutable world, no lock on the tick path |
| A 5,343-line module with ~40 environment levers | every behaviour is a runtime branch | compiled decisions; one config struct |
| Logging every datagram as hex (opt-in, but exists) | 1 MB/s, 7.3 GB in an afternoon | structured events with a level; payload logging is a debug build feature |

Each row is a measured property of the prototype or a measured operational
incident recorded in `STATUS.md`/`rep.py`. None of them is an assumption about
what Rust does for free.

---

## 15. Port order: phases, each independently verifiable

Every phase names an **observable** acceptance criterion — a wire result or a
client result — not "the code is written".

### Phase 0 — Evidence debt and the parity harness (no server code)

| | |
| --- | --- |
| Work | (a) re-measure on `30fe6461…` every field map listed in §0.2, using the existing probes; (b) build `azoth-wire` with byte-for-byte parity against the Python encoders over the whole captured corpus; (c) build the differential harness (`python az.py` oracle + Rust comparator) |
| Acceptance | every field map in §0.2 is either **re-measured with a recorded id** or **removed from the plan's dependencies**; the parity report shows **0 mismatches** across all 177 replay messages + the full channel-1 corpus; the differential harness fails loudly on a one-byte change (prove it by mutating a fixture) |
| State after 2026-10-22 | **(a) mostly done, (b) and (c) not started.** The re-measurement ran all three batches and is recorded in `docs/archive/odd-tasks/remeasure-1460.md`: the channel-1 container, locator, field layout, walk speed, sliding buffer, state-stream cadence and spawn position are **verified**, and the yaw frame is verified on three of four directions; the entity transform is **unavailable** (probe timed out twice); the inventory entry codec is **undecoded**. The parity harness is untouched and is the remaining work |
| Why first | a single wrong offset produces "accepted, zero errors, no effect" — the failure signature this project has paid for repeatedly. Nothing may be built on an unverified offset |

### Phase 1 — `channeld`: the HTTP entry, byte-identical

| | |
| --- | --- |
| Work | channel document generated from a region registry; CMS (news, tiles, MOTD); ping/health; ETag and 304; `x-amzn-*` headers; `TCP_NODELAY`; HTTP/1.1 with `Content-Length` |
| Acceptance | the client reaches the **login screen** with the Python gateway stopped and only Rust serving; every route's body is byte-identical to the prototype's for the same input (golden-body tests); a 304 is returned for a matching `If-None-Match`; the region ping the client displays is **< 5 ms** on loopback |
| State after 2026-10-23 | **the document half is done, the HTTP half is not.** `crates/azoth-region` renders the channel document from the registry and is **byte-identical to the Python gateway** over a generated fixture (7,645 bytes). The two bugs that reaching that parity exposed — `serde_json` alphabetising every object, and a `BTreeMap` reordering the dotted privacy keys — are exactly what a semantic comparison would have missed. Not yet built: the HTTP surface (`azoth-http`, axum/hyper), CMS and MOTD routes, the `x-amzn-*` headers, and the 304 path |
| Deferred | real content authoring, real images, object storage — Phase 6 |

### Phase 2 — `regiond`: identity, queue, character lifecycle

| | |
| --- | --- |
| Work | accounts/identities/personas/credentials schema with the seed as data; `getlogininfo`; `worlds/list`; entitlements; queue + tickets; character create/load/delete; the region registry and its own channel contribution |
| Acceptance | (a) the client reaches **character select** with a character the Rust service created; (b) **restart the region, log in again, and the same character returns** (persistence proven); (c) a **second client gets a different character** (identity proven — this is the bug `STATUS.md` records as still open); (d) a region with zero worlds still answers `getlogininfo` and renders in the channel document |
| Closes | the "two clients are the same character" defect, because identity now comes from the ticket, not from an `X-Azoth-Instance` header the client never sends |

### Phase 3 — `worldd`: transport and world entry

| | |
| --- | --- |
| Work | `azoth-dtls` server (DTLS 1.2, `0xC030`, cookie exchange, RSA cert, record-version quirk); Carrier + MessageRecord; V3 registration with **real ticket validation**; session state machine with the authentication deadline; heartbeat; the spawn record composed from persisted character state; the state stream |
| Acceptance | the client reaches **`InGame` with 26 `Slice:` lines, player possessed, 0 deferred-action recursion errors**, against the Rust world, **with no replay pump and no `AZOTH_REPLAY_*` environment variables**; the client's own accessor reports the **server's** spawn position; a session survives **2 hours** |
| Hard gate | the 2-hour soak is the item `docs/ROADMAP.md` says has never passed. It is the acceptance for this phase and it caps everything after it |
| Risk carried | the DTLS cipher-suite spike (§17 Q2) must pass **before** this phase starts, not during it |

### Phase 4 — Presence: originate actors

| | |
| --- | --- |
| Work | decode the six codec layouts by **live instrumentation** (`frida-unmarshal.py` + a hook at `vtable+0x90`); implement them in `azoth-replica`; originate actor records; AOI over a grid; the record-slot allocation rule |
| Acceptance | a second actor record reaches the client with **0 unmarshal / 0 validation errors**, the client's entity table contains it, and its Transform is at the server's position (proven with the existing `Transform +0x14c/0x15c/0x16c` read); with two clients, each receives the other's actor |
| Reported, not delivered | a **rendered** remote body. Blocked by the client's slice `QueryInterface` (§8.6). The plan records the two honest options and spends no further phase on it |

### Phase 5 — Simulation: the tick and the contract

| | |
| --- | --- |
| Work | `azoth-sim` tick loop with the accumulator and the tick-time manager; movement validation and the correction ladder (ACCEPT/HOLD/FREEZE/DISCONNECT); AOI incremental updates; replication encoding once per interest group; batched egress; partitions and the handoff (single-process) |
| Acceptance | **50 Hz sustained, tick p99 < 10 ms, 0 overruns** at 2,500 synthetic players clustered in one cell, on the named hardware, with the harness of §14.3; per-player egress ≤ 14 kB/s; a synthetic partition handoff shows **0 lost and 0 duplicated inputs** |
| Then | the 10,000 gate, reported as measured or not met — never estimated |

### Phase 6 — Content, assets, economy

| | |
| --- | --- |
| Work | `azoth-content`: datasheet loader, stable ids, validation; object storage; real CMS content; the privacy surface; entitlements as real data; inventory with the ledger; crafting; auction house |
| Acceptance | a gathered node's depletion is reflected in replicated state so the action **stops repeating** (the acceptance signal `docs/ROADMAP.md` already names); an item bought at auction appears in inventory with a **balanced ledger**; a duplicated-currency attempt is rejected and **audited** |

### Phase 7 — Operations and the map

| | |
| --- | --- |
| Work | `opsd`: metrics aggregation, audit viewer, gateway request log with the accumulating endpoint inventory, the 3D map feed and viewer, admin commands |
| Acceptance | the map shows every player/NPC/node at 2 Hz with **zero measurable tick cost** with subscribers attached, and **exactly zero** cost with none; an admin teleport is applied and audited before it is applied |
| Note | this is deliberately last because it consumes what the earlier phases produce. The *interface* it needs (`MapSnapshot`, §13.1) is defined in Phase 5 so it is not retrofitted |

### What is deferred, and why

| Deferred | Why |
| --- | --- |
| Instance content (expeditions, PvP arenas) | **whether an instance opens its own REP is unmeasured** (`ANALYSIS.md`, zones session: the queue found no match in 20 minutes). The region/world model already represents it (a ticket can point at any `RepAddress`), but building it before measuring would be a guess |
| Multi-process partitions | the single-process handoff must be correct first; distributing it is a transport change |
| Postgres | no measurement demands it |
| A content DSL or editor | no repeated content work has demonstrated the need (`docs/ARCHITECTURE.md`) |
| Client-side work of any kind | out of scope, including the render blocker |
| The `AZOTH_*` lever surface | every lever's outcome is recorded; the port implements the winner |

---

## 16. Test strategy

### 16.1 Unit

* **`azoth-wire`**: round-trip every codec against the captured corpus; property
  tests for the varint boundary values (127/128, 16383/16384, 2²⁰ boundaries) and
  for the `encode(decode(x)) == x` invariant over random byte strings.
* **`azoth-session`**: the state machine's transitions and deadlines; the ACK
  window's wrap behaviour at 32,767/32,768 (the measured defect); resend backoff
  and the "a skipped resend must not consume a try" rule.
* **`azoth-aoi`**: cell membership under movement, enter/leave deltas, the
  incremental-vs-full equivalence (an incremental sequence must produce exactly the
  set a full rebuild would).
* **`azoth-sim`**: the tick accumulator under simulated slow ticks (the simulation
  must not drift); movement validation against the measured walk (3.83 u/s forward,
  0.00 lateral, 0.1265 u mean prediction error) and the measured teleport refusal
  (900 u in one sample refused); the correction ladder's escalation.
* **`azoth-store`**: every migration from empty; every historical blob version
  migrates to current; ledger invariants (a transfer's correlation sums to zero;
  no negative balance without a matching spend).

### 16.2 Fixture-driven wire parity

The core of the strategy, because the client is the only real oracle:

* **Golden fixtures** in `server/crates/*/tests/fixtures/`, hashed against a
  manifest, each naming its capture id and build.
* **Three-way parity** for every wire behaviour: fixture → Python → Rust, byte
  compare. A failure names the byte offset and the field.
* **Behavioural fixtures** for the things bytes cannot prove: the client's own
  probe readings (fragment counts, transform positions, unmarshal error counts)
  recorded as expected values with their session id.
* **Negative fixtures**: every refuted shape this project measured (the
  single-fragment position bundle, the hybrid reliable/unreliable sends, the
  duplicate 48-fragment record) becomes a test that asserts the server does *not*
  do it. Negative results are the most expensive knowledge in this repository and
  the plan refuses to lose them.

### 16.3 Load and capacity

* The harness of §14.3, stepping population, reading the server's own metrics.
* Scenarios that must be covered, per `docs/ARCHITECTURE.md`: login, idle
  sessions, movement, combat/replication, **uneven zone distribution**,
  disconnects, and **reconnect bursts**.
* A soak: 2 hours at the gate population, asserting tick p99, 0 overruns, memory
  flat (no leak), and reconnect success.
* The results are recorded with hardware, workload, build and run id, and a
  capacity number without those four is not a capacity claim.

### 16.4 What only the real client can prove

| Property | Why a harness cannot |
| --- | --- |
| The client applies a record | it may accept the bytes with zero errors and change nothing — measured four times (`STATUS.md` 2026-10-18: "accepted with zero client errors, left the character visible, and changed nothing") |
| The HUD cable stays clear | it is a client-side age of one timestamp, and it depends on the *cadence* of the player record stream |
| The world renders | 26 `Slice:` lines and a screenshot are the only proof |
| The login ladder completes | each arrow is a client-side state machine with its own timeouts |
| A session survives 2 hours | the teardown at ~1 h has never been explained; only a real run can say |

So the plan keeps a **client-in-the-loop acceptance** for every phase that
changes what the client sees, and it does not accept "the harness says it works"
for any of them.

---

## 17. Open questions, phrased as measurements

Each is a measurement someone can run, with the method and what it would settle.
Nothing here is phrased as a guess.

| # | Question | Measurement | Settles |
| --- | --- | --- | --- |
| Q1 | Are the 1.400-derived field maps still correct on 1.460? (§0.2) | re-run the existing probes: `frida-fragment-grammar` for the spawn fragment boundaries, `alc.read_live_position` against the accessor for channel-1, `frida-actor-transform` for the entity transform | whether Phase 3 may use offset 38332/38336 at all |
| Q2 | **Can a Rust DTLS stack negotiate `0xC030` as a server with an RSA certificate and a cookie exchange?** | a one-day spike per candidate: handshake against the real client (with the disk-patched binary) and against a recorded ClientHello replayed byte-for-byte; assert the negotiated suite, the HVR cookie, the `0xFEFF` record versions, and a completed handshake under 1% synthetic loss | the transport decision (§18.1). **Blocks Phase 3** |
| Q3 | What are the six presence codec layouts? | hook the type dispatch at `vtable+0x90` and read the unmarshal on arrival (`frida-unmarshal.py` already works); correlate with `presence-live-capture.json`'s eight observed shapes | Phase 4 |
| Q4 | Does the client require `/cms/manifest`, and with what shape? | serve it with a recorded 404 and read the client's own error; then iterate the shape against the client's parse | whether it is a route or noise |
| Q5 | What are the character create / validate / patch request shapes? | run the create flow against a gateway that records the request and returns a documented 404, then read the client's parse errors (`routes/characters.py` already labels its own shape as GUESSED) | Phase 2's acceptance |
| Q6 | Does the client ever call the privacy endpoint against our stack, and what does it send? | log `Host` + path for every proxied request (the inventory has **zero** privacy paths despite the endpoint being load-bearing) | the one endpoint whose requirement is proven and whose shape is not |
| Q7 | What does the catalog service answer on a zone transition? | 5 parallel requests per transition, measured; capture the responses by proxying `client.catalogservice.amazongames.com` and iterating the body against the client's travel flow | whether travel can work at all |
| Q8 | Does an **instance** (expedition) open its own REP session? | run an expedition (it needs no other players) and compare the UDP flows before/after: new 5-tuple and DTLS handshake, or the same session? | the whole instance-content model. Named in `ANALYSIS.md` as the single most valuable next experiment |
| Q9 | What is the sprint/teleport speed bound for the validator? | measure displacement per input sample while sprinting and while mounting. **STILL OPEN**: Shift+W produced zero displacement, so the binding is unknown, and the walk itself measured 2.76 u/s in one clean segment against 5.39 u/s in an earlier set — the constant is not settled either | the validator's thresholds. Until it closes, the validator must not use a hard speed constant: it validates against the server's own previous position with a per-session calibrated reference, which is the structure the Python code already has |
| Q10 | What is the official state-stream cadence (world state vs player record)? | count the `0x08` bundle records per second in the capture and separate by `record_id`; the prototype's 1 Hz world / 4 Hz player is a tuning choice, and the ALC cable's ~2 s amber threshold depends on it | the replication cadence, which is a bandwidth and a cable-correctness input |
| Q11 | **What arms the client's teardown at ~1 h?** | probe-free soak runs; the four teardown anchors recorded zero hits in 24 clean minutes and the session reached 1 h 24 min once, so the question is what *occasionally* arms it | the 2-hour gate, which caps every phase after Phase 3 |
| Q12 | Is batching to ~1200 B safe for the client's Carrier reader? | send the same logical stream in one-datagram-per-record and in batched datagrams, and compare the client's own unmarshal/validation error counts and the delivered message counts | whether the biggest available egress saving is available at all (the 12.7 KB record was acked and never delivered) |
| Q13 | Does `builds.json` understate the 1.460 analysis? | it records "no Ghidra project, no corpus" while `docs/EXTRACTION-2026-10-22.md` records a 423,609-range corpus at `reverse/builds/30fe6461…/corpus/` | which of the two is current, so the plan's static-analysis assumptions are right |
| Q14 | Which of the 75 endpoint families are actually the client's? | `/v1/models` (2 hits) and `/images` (1 hit) have no plausible game purpose and the capture is machine-wide | keeps the inventory honest |

---

## 18. Technology decisions, each with what it costs

The requirement is that every dependency is justified against "more modern, better
maintained, more stable". A choice that cannot be justified that way is a habit.
For each: why this one, what it costs, what was rejected and why.

### 18.1 DTLS — the project's biggest transport risk

**The constraint is measured, not argued (§0.3): the client offers exactly
`0xC030` `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384` and nothing else, over DTLS 1.2,
with a cookie exchange, an RSA certificate, and `0xFEFF` record versions on
HelloVerifyRequest and ServerHello.**

| Candidate | Server-side DTLS | Can it do `0xC030`? | Maintenance | Cost | Verdict |
| --- | --- | --- | --- | --- | --- |
| **`openssl` crate (DTLS method)** | yes — OpenSSL's `DTLS_method` is the reference implementation, and the *prototype already uses exactly this* via `pyOpenSSL` with `SSL.DTLS_METHOD` | **yes** — it is a stock TLS 1.2 suite | mature, frequent releases, widely deployed | a C dependency; `openssl-sys` build complexity; on Windows the `vendored` feature compiles OpenSSL from source (perl + a C toolchain). Cross-compilation is a documented pain point | **primary** |
| `dtls` 0.17.x (webrtc-rs) | yes | **unknown** — its documented suite set is the WebRTC set (`ECDHE_ECDSA/RSA` + AES-128-GCM-SHA256, AES-256-CBC-SHA, ChaCha20 in newer); `AES_256_GCM_SHA384` is not a WebRTC suite and must be *tested*, not assumed | active again (0.17.x in 2026), but the project announced a feature freeze of the Tokio-coupled implementation and a move to a sans-I/O `rtc` crate, so the API surface is in transition | pure Rust, no C dependency, no build friction | **spike candidate** — Q2 decides. It would remove the C dependency, which is the single biggest build-friction win available |
| `webrtc-dtls` 0.12 | yes | same doubt as `dtls` (same codebase lineage) | ~4.9M downloads but a 34-crate tree, pre-1.0, and a long gap between updates; superseded by the `dtls` crate split | pure Rust | **rejected in favour of `dtls`** — same lineage, older packaging |
| `rustls` | **no** — it exposes no DTLS primitives, and the ecosystem is explicit about it; there is an open design discussion and an unmergeable draft PR, which is evidence the path is not settled | n/a | excellent, but irrelevant | — | **rejected on capability** |
| `str0m` | uses OpenSSL for DTLS today, with an open issue about replacing it | yes (via OpenSSL) | good, but it is a WebRTC stack, not a DTLS library | brings a WebRTC state machine we do not need | **rejected**: it would be OpenSSL with extra weight |
| `DusTLS` | work in progress, DTLS 1.2 PoC reusing rustls primitives, **no security audit** | unknown | experimental | — | **rejected on maturity** |

**Decision: `openssl` with the DTLS method, behind `azoth-dtls`'s own trait, with a
one-day spike on `dtls` 0.17 as the documented alternative.** The trait exists
precisely so the spike's outcome is a swap, not a rewrite.

**Why this is the right call here rather than the boring one:** the prototype
already proves the OpenSSL path works against this client, with this cipher suite,
with this certificate shape, on this machine. Choosing it means the *only*
unproven part of the transport is our own record-layer and demux code, not the
crypto. Choosing a pure-Rust stack means the crypto handshake itself becomes the
risk, on the one cipher suite the client accepts, with no fallback. The C
dependency's cost is real (a vendored build, a perl toolchain on Windows) and is
paid once at build time; a handshake failure is paid on every session.

**What must be measured before Phase 3 (Q2):** negotiated suite, cookie exchange,
`0xFEFF` record versions, handshake completion under 1% loss, and the per-handshake
cost on the target CPU (the handshake must never touch the tick — see below).

### 18.2 Async runtime

**Tokio.** Why: it is the runtime the rest of the chosen stack targets (hyper/axum,
`tokio::net`), it is the most widely deployed, and its `spawn_blocking` is the
documented mechanism for exactly the two blocking things this server has (DTLS
handshake crypto and SQLite). **Cost:** a large dependency tree and the
cooperative-scheduling trap the brief names — Tokio cannot preempt a task, and a
task that never yields starves everything else and Tokio will not add threads to
compensate. **Mitigation is architectural, not a flag:** the simulation runs on a
**dedicated thread** (`std::thread`), not on a Tokio worker, and the tick never
awaits. Async is the I/O plane; the tick is not part of it.

**Rejected:** `async-std`/`smol` (smaller but with a thinner ecosystem for the
HTTP and TLS sides), and a hand-rolled epoll loop (no reason to hand-roll when the
I/O plane is not the bottleneck and the measurement plan needs to exist first).

### 18.3 Simulation shape: actor at the ownership boundary, ECS inside it

The brief offers two shapes and asks for a justification against AOI and the tick
budget. The honest answer is that they are not alternatives at the same level.

* **Actor at the process/world boundary.** Each world owns its state; there is no
  `Arc<Mutex<World>>`, no shared mutable world, no lock on the tick path. Messages
  arrive on bounded channels, and a region or ops process cannot reach into a
  world's state.
* **Data-oriented ECS inside the world.** AOI is a spatial query over many
  entities, which is a column-shaped problem: positions in one `Vec`, kinds in
  another, AOI membership in a grid of index ranges. Iterating a dense `Vec` of
  positions is cache-friendly and allocation-free; iterating a map of `Entity`
  structs with boxed components is neither.

**Why not pure actor (one actor per entity):** an actor per NPC at 2,500 players
with hundreds of entities per area means millions of messages per tick and a
scheduler on the hot path. **Why not pure ECS across processes:** it gives no
ownership boundary, so the single-writer-per-partition rule (§8.5) would have to be
re-invented as a lock.

**Cost:** no shared-memory parallelism across worlds, and cross-world interaction
must be messages. Worlds do not interact in this game (a player is in exactly one
world), so the cost is zero in practice and the constraint is a benefit.

### 18.4 HTTP

**`axum` + `hyper` + `tower`.** Why: it targets the same Tokio runtime, it is
actively maintained, and its extractor model makes the "one strict model per
route" contract (§11.1) natural. **Cost:** a moderately deep dependency tree and
an API that changes across major versions.

**Rejected:** `actix-web` (its own runtime and an actor model we would not use,
duplicating §18.3's shape in the wrong place), and a hand-rolled HTTP/1.1 server
(the prototype is one, and it works — but the two measured quirks it needed,
HTTP/1.1-with-Content-Length and `TCP_NODELAY`, are exactly the kind of thing a
library has already solved; hand-rolling buys nothing and costs the security
surface of a parser we would write ourselves).

Note that Caddy already terminates TLS on loopback (`deploy/Caddyfile.json`), so
the Rust HTTP services speak plain HTTP/1.1 to Caddy. That is deliberate: TLS
termination stays in one place, and the client's certificate trust story stays in
the launcher.

### 18.5 Database

Covered in §9.1. **`rusqlite` + bundled SQLite, two files, WAL.** Rejected:
`sqlx`/Postgres (a server process and an async driver that invites DB calls onto
the tick), a KV store (no transactions, no SQL for the ledger).

### 18.6 Serialization

Covered in §10. The two headline rejections: **rkyv for persistence** (no schema
evolution) and **bincode 1.x** (unmaintained, RUSTSEC-2025-0141).

### 18.7 Observability

**`tracing`** for structured spans and events (it is the ecosystem standard and it
composes with the bounded-exporter requirement), **`metrics`** as the facade with
a Prometheus exporter, and a hand-written bounded ring buffer for the tick's
metric emissions because no off-the-shelf recorder guarantees "never allocate,
never block, drop on full". **Cost:** two facades, one of which we wrap. **Rejected:**
an APM SDK (the brief is right that generic APM has no concept of a tick, and an
SDK's exporter is not boundable in the way the tick requires).

### 18.8 Logging

`tracing-subscriber` with per-component targets and an env-filter, writing
structured JSON to a bounded channel. **Cost:** the format is ours to keep stable.
**Rejected:** unstructured logging (the prototype's `print`-based events are
parseable only by grep, and one of its incidents — a 7.3 GB log — is a direct
consequence of having no level discipline).

---

## 19. Risks, in the order they will bite

| # | Risk | Why it bites | Mitigation / decision |
| --- | --- | --- | --- |
| R1 | **The 2-hour session gate has never passed.** Sessions ended at 1 h 06 m once and 1 h 24 m another time, by the client's own graceful `SM_DISCONNECT`, with the four teardown anchors recording zero hits | a server that drops everyone after an hour is not usable, and it caps every phase after Phase 3 | it is Phase 3's acceptance, and Q11 is the measurement. **No phase after Phase 3 starts until it passes.** If it cannot be explained, the honest report is that the backend is stable for the measured duration and no longer |
| R2 | **The DTLS cipher constraint may not be satisfiable by a pure-Rust stack** | there is exactly one suite the client accepts | the `openssl` path is proven by the prototype; the pure-Rust path is a spike (Q2), not an assumption. The trait boundary makes the swap cheap |
| R3 | **Presence layouts are undecoded and the static route is gone** | without them the server cannot tell a client another player exists | live instrumentation is a known, already-working method; it is Phase 4's whole job, and it is not on the critical path for `InGame` |
| R4 | **Remote bodies do not render, and it is a client defect** | the "two clients see each other move" acceptance is unreachable by server work | reported, not worked around; the wire-level acceptance is what Phase 4 delivers (§8.6) |
| R5 | **1.400-derived field maps may be wrong on 1.460** | a wrong offset produces silent no-ops, the project's most expensive failure mode | Phase 0 exists solely for this; nothing is built on an unverified offset |
| R6 | **Character lifecycle shapes are unmeasured** | "create from zero" is a hard requirement and its request bodies are not captured | Q5; Phase 2 is gated on it, and the prototype's own docstring already labels the shape as guessed |
| R7 | **The catalog service is required for travel and its shape is unknown** | without it, travel — and therefore any zone transition — cannot work | Q7; the endpoint is additive and does not block Phases 1–5 |
| R8 | **Whether an instance opens its own REP is unmeasured** | it decides the whole instance-content model | Q8; the region/world model already represents both answers, so the design does not have to be redone either way |
| R9 | **Scope is enormous** (a complete live-service backend) | the realistic failure is a half-built system with no vertical slice | the phases are vertical slices, each ending in an observable client result; Phase 3 ends with a real, playable world |
| R10 | **A capacity claim measured on the dev box would be dishonest** | the dev machine is a 4-core laptop | the gate names its hardware, and §14.4 forbids quoting dev-box numbers as capacity |
| R11 | **Review workload** | this is a multi-month backend | work units stay reviewable, tests and docs ship with behaviour, and the feature document is the specification a reviewer reads |
| R12 | **The endpoint inventory is a lower bound and was once truncated by hand** | a regenerated inventory silently discarded accumulated knowledge on 2026-10-22 | the Rust gateway **accumulates** it; regeneration is never destructive |

---

## 20. What this plan changes in the repository

| File | Change |
| --- | --- |
| `docs/ARCHITECTURE.md` | §"Rust runtime shape" is superseded by §2 of this plan: four processes, twelve crates, and the reason for each. The capacity gates and content rules stand unchanged |
| `docs/ROADMAP.md` | item 4 ("Port understood behavior to Rust — the trigger is authority") now has a plan; the phases in §15 replace its sketch, and its "what is ready to port" list is superseded by the Phase 0 evidence debt (§0.2) |
| `STATUS.md` | the active frontier becomes Phase 0. The remote-render blocker stays recorded as blocked, not as work |
| `research/atlas/builds.json` | Q13: reconcile the "no corpus exists" claim with `docs/EXTRACTION-2026-10-22.md`'s 423,609-range corpus |
| `research/atlas/observed-endpoints.json` | becomes an accumulating file; the plan's §5 is its curated companion |
| `docs/INDEX.md` | add this plan next to the plan request |
| `services/` (Python) | **unchanged and runnable.** It is the parity oracle (§11.3) and stays until every behaviour has a Rust equivalent with parity evidence |

### The one sentence to review this plan against

If a reviewer asks "why is this better than what we have", the answer must be
measurable in three places: **the tick** (50 Hz at p99 < 10 ms with 2,500 players,
against a baseline that is measured first), **the wire** (byte parity against the
Python oracle over the whole captured corpus, and the same observable client
result), and **the operations** (a session that survives 2 hours, a ledger that
makes duplication detectable, and a map that costs nothing when nobody is
watching). Everything else in this document exists to make those three
falsifiable.
