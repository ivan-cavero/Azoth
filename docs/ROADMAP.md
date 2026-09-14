# Roadmap — Azoth

Performance contract: [services/docs/PERFORMANCE.md](../services/docs/PERFORMANCE.md).  
Architecture: [ARCHITECTURE (archived, Spanish)](archive/ARQUITECTURA.md).  
Method lessons: [research/docs/LESSONS.md](../research/docs/LESSONS.md) — read before any RE round.  
REP wire spec: [research/docs/REP-PROTOCOL.md](../research/docs/REP-PROTOCOL.md).

Amazon’s servers lagged with relatively few people **stacked in one place**. Azoth is built for **density** (many players together) and only then for raw CCU. Capture work stays **in parallel** until 2027-01-31: every session is protocol we cannot get after shutdown.

---

## Language decision (2026-09-14, frozen)

**Python until protocol freeze; Rust after.** The reasoning lives in
`research/docs/LESSONS.md` (#11 not needed — this entry is the decision).

1. **Now (Phase 2 frontier): Python** stays the protocol lab. We iterate
   CONNECT_ACK / V3 / first spawn against the live client there — RE work,
   where iteration speed beats everything. `services/world` (pyOpenSSL
   DTLS) already proved it holds a real client handshake.
2. **Freeze point:** the moment Game.log shows `player spawn succeeds, in
   game`. At that point the protocol stops changing:
   - `research/docs/REP-PROTOCOL.md` becomes the normative spec (every
     message, every field, byte order, with capture evidence).
   - Golden captures: `services/world/rep_traffic.jsonl` dumps from real
     sessions are stored as fixtures (`research/fixtures/rep/`) and every
     parser/serializer is locked by round-trip tests against them.
3. **Port to Rust** (`services/world-rs/`): tokio + openssl crate (DTLS) +
   hecs/bevy_ecs for the 60Hz simulation. Module-by-module, each validated
   against the same golden captures: the Rust bitstream must produce byte-
   identical output to the Python reference on every fixture. The compiler
   is the first oracle, the golden bytes are the second.
4. **Gateway stays Python permanently** — stateless login/CMS doorman, no
   hot path, no reason to port. `services/gateway` is the long-term form.

Not Go, not Bun/JS: Go loses to Rust on the 60Hz no-GC-jitter requirement
(sub-ms pauses still steal CPU from the tick at scale) and on the ECS
story (hecs/bevy_ecs is the data-oriented architecture the simulation
wants); Bun/JS has no serious DTLS. Rust's compile-time-as-oracle suits
agent-driven development, and the "no hot-reload" concern is moot —
cargo-watch gives the same save→rebuild→restart loop as our Python watcher
(~2-5s incremental), and the real iteration bottleneck is the 2-minute
game restart, identical in every language.

Services/DB (characters, guilds, friends, inventory): they live as RMI
behind the world server (as the real game's Stubbed*Service architecture
dictates), NOT in the gateway. Schema design starts after spawn works,
using the client's gRPC catalog (`research/derived/grpc.json`) as contract.

---

## Now (done)

- [x] Brand **Azoth**, world `azoth-1`
- [x] Repos: `research` / `emulator` / `launcher`
- [x] Analysis docs + live sessions (login, FTUE create, open world)
- [x] Capture kit paths: `research/sessions/` (not `capture`+`captures`)
- [ ] Spike: `launcher/src/Start-NwPrivate.ps1` (exe without EAC)

---

## What to capture next (you)

We already have: full login ladder, character create (`FTUE_V2_CC`), tutorial, open-world spawn, map change, Vivox, CMS, a few RMI **names**. We do **not** have combat, inventory payloads, instances, or death.

Use `research\tools\capture\Start-NwCapture.bat` (admin), play **5–12 minutes**, one theme per session, then ENTER. Rename the folder if you want (`sessions/combat_dummy`, etc.).

### Must-have (do these first)

| # | Session | What to do in-game | Why we need it |
| --- | --- | --- | --- |
| 1 | **Move** | Walk/run 2–3 min, camera, stop, jump if you can | Done `live_20260906_173554` (Vivox grids + DTLS). Payloads still ciphertext. |
| 2 | **Combat** | Hit a dummy or a weak mob, use 2–3 abilities, block/dodge | Done same session: `CameraLock` + `SlayerScript` CRCs. Ability wire is DTLS. |
| 3 | **Inventory** | Open bag, move an item, equip/unequip, open storage if any | Done in-game; **no Game.log**. DTLS only. |
| 4 | **Gather** | Harvest a plant/ore/tree until the node depletes | Done: 7 nodes, `GatheringInterrupted` only. |
| 5 | **Death** | Die on purpose, respawn at shrine | Done: **stays InGame**. No Death/Respawn string. |
| 6 | **Expedition** | Queue and **enter a dungeon** (any expedition) | **Still open** — no group on live. Need instance or solo queue. |

# 6 is the highest-value “new endpoint” session. Official used a pool of instance boxes; we need to see whether `RepAddress` changes, `LevelInfoChanged` name, and queue RMI (`GameModeParticipant*`).

### High value (after 1–6)

| # | Session | What to do |
| --- | --- | --- |
| 7 | Fast travel / shrine | Two shrines, travel |
| 8 | Crafting | One recipe at a station |
| 9 | Trading | Buy from a vendor **or** trade with another player |
| 10 | Mount | Summon, ride, dismount |
| 11 | Chat | Say something in area / party if you have one |
| 12 | Territory | Cross a zone border, watch phasing (`GridTracking*`) |

War / company / OPR: only if you already play them; they are huge. Better after 1–6 are in the box.

### How to run it

1. Steam + official New World as usual (EAC on).
2. Start the BAT, accept UAC, **then** play the theme.
3. Stay in that theme; do not also switch characters unless the theme is “switch”.
4. ENTER when done. Send me the session name (`live_…` or whatever you renamed). I read `REPORT.md` + `events.jsonl` + RMI names.

Network bodies stay TLS/DTLS on official. The win is **Game.log names + timing + which maps/REPs**. When the client talks to Azoth we see JSON in the clear.

---

## Build order (us)

### A-private — client without EAC

`Start-NwPrivate.ps1`. If frontend loads: copy exe, patch channel URL + DTLS pin. Play button on the Azoth launcher. Steam stays for **official capture only**.

### Fase 1 — Gateway HTTPS

Channel + CMS (ETag) + Omni + S3 remote-config + characters + queue `RepAddress`.  
Done when Game.log says `StartREPConnection` to localhost.

### Fase 2 — World stub (spawn frozen) ← CURRENT

DTLS (pyOpenSSL now, Rust later per the language decision above) + Carrier
CONNECT + V3 + `LevelInfoChanged` + `Cmd_NewProxy`.  
Done when `player spawn succeeds, in game`. Character may stand still.

**Current blocker:** the client loops CONNECT_REQUEST (system channel 3,
msgId last byte, payload `[u32 BE len][cookie]`) and rejects our echo-ACK.
Live raw-hex capture runs automatically in `services/world/rep_traffic.jsonl`.

**Protocol freeze + Rust port trigger:** `player spawn succeeds, in game`.
See the language decision at the top of this file.

### Fase 3 — One player moves

Input → transform replica. Tick metrics on. **This is where PERFORMANCE.md starts being enforced.**

### Fase 4 — Persistence + N players

Postgres characters/inventory. AOI. 2–N visible players. Density test in one cell.

### Fase 5 — Systems, one at a time

Gather → combat → inventory → death → expedition instance process. Each system needs its capture session above.

### Fase 6 — Content + launcher updater

Datasheets, PAK packs, Azoth news. Not before spawn+move work.

---

## Parallelism

| Track | Who | Blocks |
| --- | --- | --- |
| Official capture 1–6 | You, this week if possible | Combat/instance protocol |
| Skip-EAC spike | Us | Private URL/pin patches |
| Gateway channel/CMS | Us | Login mock |
| Pin extract (exe as file) | Us | DTLS stub |

Gateway can start **without** dungeon captures. World combat **cannot** be guessed; session #2 and #6 are the ones that save months.
