# Server-side simulation blueprint — consolidated research

Compiled 2026-10-11 (overnight research session). This is the master reference
for what the Azoth emulator must implement, ordered by what the evidence says
the real server does. Every claim cites at least one of:

- **client** — `research/atlas/az-type-registry.json` (4,818 types), facet
  families (`facet-map.json`), decompilation findings in STATUS.md
- **pak** — the client PAK (44 subworlds, 2,250 javelindata_* tables;
  see `DATASHEETS.md`)
- **wiki** — public game documentation, 112 pages cached (`raw-wiki-1.json`,
  `raw-wiki-2.json`; extracted facts in `wiki-facts.json`)
- **steam** — official post-mortem communications (final live state;
  `steam-final-state.json`)

## The headline discovery

**The game ships its own server-side design data to the client.** 2,250
`.datasheet` files (mostly `javelindata_*`) contain the literal numbers:
XP curve, per-level health/attributes, gear-score caps, loot bias, all 5,237
loot tables, per-PvP-mode balance tables, territory definitions, mutation
ranks, season tracks 1–10, invasion definitions, house types, mounts,
encumbrance, trade-skill tables for all 16 skills, and the procedural dungeon
grammar for Catacombs. The reader is already built and verified
(`reverse/tools/datasheet.py`). **We do not have to invent or datamine the
game's rules — we can load them.**

## Server responsibilities by layer (what the evidence shows)

### 1. Session & transport (operational)
DTLS + REP channels, Javelin framing, heartbeat, input-response, replay.
Done and documented (STATUS.md, runbook).

### 2. Identity & persistence (nothing yet)
The client persists via `Persistent*ServerData` components and explicit
restore messages (`EntityRestoreInfo`, `RestoreCustomizedDataMessage`).
The server must own: accounts, characters, world state, and serve real
character UUIDs. Schema cheat-sheet = the Persistent* component set.

### 3. Replication (the current frontier)
AOI traits → records → fragments; one codec per component type. PhysicsTrait
unlocks the player body (movement). Then: character sheet, inventory, vitals.

### 4. Simulation rules (load from data)
Combat math (damagetypes, statmultipliers, diminishingreturns, spelltables),
progression (xpamountsbylevel, categoricalprogression, weaponmastery,
tradeskill*), economy (loottables, currencyexchangerates, economytrackers),
world (territorydefinitions, factiondata, gatherables, pois).

### 5. Encounters & AI (heaviest surface)
250+ individual NPC data blocks, conversation state machines, spawn systems
(AreaSpawner + variations_*), behavior trees (111 types), navigation, vitals
per level-variant, boss phases. The PAK's `npcdata_*` and
`conversationstatedata_*` files mean dialogue/NPC logic is data-driven too.

### 6. Instanced modes (44 subworlds + gamemode tables)
`javelindata_gamemodes` (53 rows × 181 cols) is the master mode table;
`pvpbalance_*` gives per-mode balance; war-board aggregates give scoring.
Modes: 12 expeditions, mutations (3 tiers + weekly rotation), Catacombs
(procedural, roguelite), Isle of Night raid (10p), OPR 20v20, arena 3v3,
battle royale, CTF, world raids.

### 7. Social & meta
Chat/voice components, companies (28 types), factions (39), friends, groups
with raid conversion, emotes + musical performances (5 instruments, buff
rewards), seasons (full seasonpass/chapter/reward tables 1–10), leaderboards,
titles, achievements (NPA model), Twitch drops, GM tools (10 facets),
entitlements/store.

### 8. Live-ops control
`javelindata_gameevents`, `worldeventcategories`, `worldeventrules`,
`schedules` — the game's own event scheduling system. Our "toggle any event"
feature maps directly onto these tables.

## Final live state (Steam, official)

- Season 10 "Nighthaven" (Oct 13, 2026) = final content release; free.
- Rise of the Angry Earth made free.
- Servers shut down **January 31, 2027**; delisted Jan 15, 2026.
- Nighthaven adds: new zone (dark castles/catacombs), Catacombs roguelite
  mode, Isle of Night 10-player raid, Daggers weapon (Season 10 minor notes).

Consequence for Azoth: the client build we ship with is the **final,
complete** version of the game — every system is present, and Amazon has no
reason to change anything again. The emulation target is stable forever.

## Priority order for the emulator (dependency-driven)

1. **A5 fragment codecs** → **B3 PhysicsTrait** → **B4 movement** (the unlock)
2. **C1 database** → **C2 character persistence** → **C3 real character UUID**
3. **A9 data-table loader** (parallel, feeds everything numeric)
4. **D combat rules** (data-driven from A9 tables)
5. **E world + F AI** (spawn from datasheets, not hand-authoring)
6. **H economy** (loot/coin/trading post from loottables)
7. **I social** (companies/factions needed by J)
8. **J war/territory** (the flagship)
9. **K instanced modes** (Catacombs first — smallest complete loop)
10. **O scale & Rust** (O1 gateway → O2 world, only with parity)

## Open questions (tracked in STATUS/HANDOFF, not here)

- State-stream idempotency on re-apply (live experiment pending)
- Player physics component list (re-measure with corrected GUIDs)
- The exact fragment-type → component-type mapping for A5


## Appendix: the server API surface, exactly (from the client)

The client registers **390 components with a server facet** and **702 named
server-to-client methods** (ServerFacet_*). This is the literal RPC surface a
real New World server exposes. Top families by method count:

| Component | Server methods | Domain |
|---|---|---|
| SeasonsRewardsComponent | 30 | season track ops |
| GameModeParticipantComponent | 25 | instanced mode lifecycle |
| PlayerHousingComponent | 14 | housing |
| TerritoryInteractorComponent | 14 | territory interaction |
| MetaAchievementComponent | 13 | achievements |
| ObjectivesComponent | 12 | missions |
| AchievementComponent | 11 | achievements |
| CategoricalProgressionComponent | 10 | standings |
| FishingComponent | 10 | fishing minigame |
| LeaderboardComponent | 10 | leaderboards |
| FactionComponent | 9 | factions |
| GameModeComponent | 9 | gamemode state |
| ItemRepairComponent | 9 | repair |
| LootTrackerComponent | 9 | loot |
| MountComponent | 9 | mounts |
| MusicalPerformancePlayerComponent | 9 | music |
| StatusEffectsComponent | 8 | status effects |
| BotComponent | 7 | AI bots |
| GameMasterComponent | 7 | GM tools |
| PlayerComponent | 7 | core player ops |

Full machine-readable list: `server-facet-methods.json` and
`all-server-facets.json`. A component whose ServerFacet has no named methods
(e.g. TradingPostComponentServerFacet) still exists — its traffic flows as
typed messages or replicated state rather than per-method RMIs.
