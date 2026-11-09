# Live status

Everfall. Private New World server. `server/` is a Cargo workspace again
(2026-10-31), one crate: `everfall-wire`. Inventory: `research/atlas/meanings.md`. Command: `python ef.py`.

## Now

The Python gateway, Python world, and Caddy are the measuring lab (`python ef.py dev`).
They can put a client into a world by sending captured traffic. That is a rig, not the game.

**The lab runs 1.460 now.** On 2026-10-26 the private copy was refreshed from
Steam (`patch-dtls-disk.py restore`, then `apply` at `0x145DCF9F5`) and reproduces
`97f17df3…` exactly. Install and lab copy are the same build for the first time.

## Measured run, 2026-10-26 10:00

Launched without the patch set, which is what the run below records. Evidence in
`.azoth/logs/runs/run-20261026-1460-ladder/`.

Rungs 14→17 in order: `StartREPConnection` → `WaitingForREPConnection` → (15)
`WaitingForActorGameConnection` → (16) `WaitingForSpawnPoint` → (17)
`WaitingForPlayerSpawn`, then `OnCampfireLoginComplete, ownership=permanent`, then
`State(WaitingForPlayerSpawn) is timeout: frames 10` → `Disconnected`.

**Rung 15 is confirmed on 1.460** and closed itself with no forced gate. **Auth is no
longer the wall**: the persona login completes and the client renders character select.
**Rung 17 is passed and the world renders** (2026-10-26). The 120 s timeout was never
the bundle: `ClientContext::Initialize` self-cleans when a predicate returns 0, so every
bundle was dropped with `clientContext == nullptr`; the world-phase patch set fixes that.
**`-Watch` now works (2026-11-09)**: the EOS stub points at the build-scoped resolver
(`0x1444F8B20`) and the launcher waits for `OnCampfireLoginComplete` plus 60 s, so
`python ef.py game` reached character select, Play, the ladder and `InGame` with a body,
staying up 26 min with 0 disconnects (baseline: 19 s). Terrain still does not stream
(0 `Slice:` lines, gate 6).

## Named, 2026-10-26

Two ladder wire types had no name and now do, through the client's own registration
hook (GUID to name, validated on the proven controls `0x663` and `0x65c`):

| Wire | Name | Trait |
| --- | --- | --- |
| `0x651` | `ReceivePlayerSpawnPointMsg` | `ClientViewListenerTrait` |
| `0x18a6` | `GridTrackingComponentClientFacet_UpdatePhasing` | `ClientMessages` |

`0x651` has no body; `0x18a6` is a 40-byte periodic record with unnamed fields.
**The type table is one name per wire**: all 3,390 named types carry a single answer, because
the "ambiguity" was the reader taking eight qwords from the table base instead of the
lambda's own 48-byte row. No settled name changed.

The spawn's **48 fragments are named too**: a fragment's second varint is a type-table
index, so the hook names it — 47 distinct types, all `*ReplicatedState`. The boundaries
are not derivable from the bytes, because a fragment has no length field at all; they
were measured live. The position is in fragment 36, `ALCReplicatedState`.

## Next

**The entry path is mapped; the first Rust crate exists.** `everfall-wire` (2026-10-31)
encodes and decodes the laid-out fields; `cargo test` round-trips the three entry bodies
the server must SEND (`0x3`, `0x663`, `0x65c`) byte-exactly. The atlas closed the
client-facing entry side: the channel document and region HTTP bodies are inventoried
(with the smallest must-own set to reach character select), registration `0x3` is laid out
to the byte (`server_version` named), and `0x65c`'s 56x56 grid is a consumed spawn layout.

Interaction layouts decoded the same night (all `partial` - writer and reader agree, no live
record): Groups, Entitlement/Store, Ability/Progression, Trade, Mount + remaining Paperdoll,
Journal (Objectives 30 / Contracts 16), Territory (Interactor 47 / Detector 5), Crafting,
Inventories/GlobalStorage, Social (50), Vitals (25), Aoi, Paperdoll, the Contracts
sub-codecs and the prefix-varint width table. Only `0x5de` and `0xf37` are `measured`.

The long tail is the next step: one card + one fixture per remaining message. Plan and
per-system method: `research/docs/INTERACTION-DECOMP-PLAN.md`; the decoded layouts, each
with its build and evidence word, are rows in `research/atlas/meanings.md` § *The interaction contract*.

## Do not

Never add a crate or field the atlas does not name, or embed an unnamed byte
string in a crate (a raw run is an `Opaque` with its Atlas id). Send a datagram
because a capture contained it. Rename the resource Azoth. Read `docs/archive/`
or `docs/journal/raw/` whole.
