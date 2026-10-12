# Javelin Data Sheets — the game's server-side data tables (in the client PAK)

Discovered 2026-10-11 while mining the PAK index for the web roadmap.

## What this is

`sharedassets/springboardentitites/datatables/` ships **2,250 `.datasheet`
files** — the game's actual data tables. Most are prefixed `javelindata_*`
(Javelin = the netcode/server stack) or `npcdata_*` / `objectives_quest_*`.
They live in the **client** PAK, which means every server rule the client can
verify is shipped to the client as data. We do not need to guess economy
numbers, loot tables, or XP curves: **the tables are on disk.**

## Catalog highlights (the server-relevant tables)

### Combat
- `javelindata_damagetable_*` — one damage table per enemy (450+ named: every
  boss, family, variant incl. `_worldboss`, `_invasion`, `mutators`)
- `javelindata_damagetypes`, `javelindata_statmultipliers`,
  `javelindata_diminishingreturns`, `javelindata_spelltable_<weapon>` (one
  spell table per weapon + AI + gamemode variants)
- `javelindata_staminacosts_player`, `javelindata_manacosts_player`,
  `javelindata_cooldowns_player`
- `javelindata_statuseffects_*` (per weapon, perks, gems, artifacts, AI)
- `javelindata_combatprofiles`, `javelindata_combatsettings`

### Progression
- `javelindata_xpamountsbylevel` — the literal XP curve
- `javelindata_weaponmastery`, `javelindata_weapontiers`,
  `javelindata_skills`, `javelindata_skillexperience`
- `javelindata_tradeskill<name>` — all 16 trade skills individually
  (arcana…woodworking + azothstaff, fishing, musician, riding)
- `javelindata_territory_standing`, `javelindata_territoryprogression`,
  `javelindata_progressionpools`, `javelindata_progressionpointdata`
- `javelindata_categoricalprogression` — the standing category system

### Items & economy
- `javelindata_itemdefinitions_*` — master item tables: weapons, armor,
  consumables, ammo, dye, fish, lore, resources, runes, skins, blueprints,
  **per store month (mtx_2023-01 … 2025-03)**, and per source: master_faction,
  master_pvp, master_quest, master_loot, master_named, master_artifacts,
  master_setitems, master_omega
- `javelindata_perks*` (incl. gems, artifacts, buckets, exclusive labels)
- `javelindata_socketables`, `javelindata_dyecolors`, `javelindata_itemskins`
- `javelindata_loottables_*` (salvage, seasons, pvp rewards track, mtx),
  `javelindata_lootbuckets*`, `javelindata_lootlimits`,
  `javelindata_divertedloot`
- `javelindata_currencyexchangerates`, `javelindata_economytrackers`,
  `javelindata_umbralcurrency`, `javelindata_umbralgsupgrades`
- `javelindata_refiningrecipes`, `javelindata_crafting_<station>`,
  `javelindata_craftingcategories`, `javelindata_generatorrecipes`

### World & territory
- `javelindata_territorydefinitions`, `javelindata_territorygovernance`
- `javelindata_factiondata`, `javelindata_factioncontrol_buffs`,
  `javelindata_factioncontrol_towerdefinitions`,
  `javelindata_factionstatuseffects`
- `javelindata_poidefinitions_*` (per map version), `javelindata_gatherables*`
  (incl. per-variation families: trees, minerals, bushes, essences, holiday…)
- `javelindata_housebonus`, `javelindata_housetypes`, `javelindata_housingitems*`
- `javelindata_mounts`, `javelindata_mounttypes`, `javelindata_mount_movement`
- `javelindata_fishing_*` (bait, behaviors, catchables, hotspots, poles, water)

### PvE encounters
- `javelindata_npcs` + `npcdata_npc_<id>` (250+ individual NPCs) +
  `conversationstatedata_npc_<id>` (dialog state machines)
- `javelindata_objectives*`, `objectives_quest_*`, `objectivetasks_quest_*`
  (every quest's objective tree)
- `javelindata_invasiondefinitions`, `javelindata_defendobjectdefinitions`,
  `javelindata_destructiblewalls`, `javelindata_darkness*` (invasion darkness)
- `javelindata_dungeonclusters`, `javelindata_dungeongrammars`,
  `javelindata_dungeonrooms`, `javelindata_dungeontiles` — procedural dungeon
  grammar!
- `javelindata_vitals*` (per level variant: catacombs, cutlasskeys, dunwood,
  firstlight, raid_cutlasskeys, worldboss, player)
- `javelindata_randomencounters`, `javelindata_owg_*` (open-world game:
  bounty, explorer, merchant, mission, procurer + faction token progression)

### PvP & modes
- `javelindata_pvpbalance_*` — **one balance table per mode**: arena,
  capturetheflag, duels, ffa, openworld, outpostrush (also `_noperks`), war
- `javelindata_pvp_rank`, `javelindata_pvp_rewards_v2`, `javelindata_pvp_store_v2`
- `javelindata_gamemodes`, `javelindata_gamemodemaps`,
  `javelindata_gamemodescheduler`, `javelindata_gamemodedynamiccreaturedifficulty`
- `javelindata_warboardaggregates`, `javelindata_orwarboardaggregates`,
  `javelindata_pvparenawarboardaggregates`, `javelindata_ctfwarboardaggregates`,
  `javelindata_catacombsswarboardaggregates` — war-board scoring per mode
- `javelindata_contribution_*` (arena, darkness, defendobject, invasion,
  questencounter, worldboss) — contribution scoring systems

### Seasons & live ops
- `javelindata_chapterdata_season1..10`, `javelindata_rewarddata_season1..10`,
  `javelindata_seasonpassdata_season1..10`, `javelindata_seasonsrewards*`
  (activities, tasks, cards, journeys, stats per season)
- `javelindata_gameevents`, `javelindata_worldeventcategories`,
  `javelindata_worldeventrules`, `javelindata_schedules`
- `javelindata_progression_<event>` (halloweenevent, springevent, summerevent)
- `javelindata_twitchdrops`, `javelindata_twitchtags`
- `javelindata_leaderboard`, `javelindata_leaderboardrewards`,
  `javelindata_leaderboardstats`

### Misc server-relevant
- `javelindata_entitlements`, `javelindata_shopdata`,
  `javelindata_storecategories`, `javelindata_storeproducts`
- `javelindata_encumbrancelimits`, `javelindata_equipmentsets`
- `javelindata_emotedefinitions`, `javelindata_songbook`,
  `javelindata_songbooksheets`, `javelindata_musicalperformancerewards`
- `javelindata_mutationdifficulty`, `javelindata_mutationrankdata`,
  `javelindata_cursemutations`, `javelindata_elementalmutations`
- `javelindata_difficulty_darkness`,
  `javelindata_difficultyscaling_worldencounter_participants`
- `javelindata_expansions`, `javelindata_playertitles*`,
  `javelindata_metaachievements*`, `javelindata_milestonerewards`
- `javelindata_quickcourses` (mount races!), `javelindata_huntersight`

## JSON files (2,218)

World-layout JSON per subworld: `newworld_vitaeeterna` (1,513 files), and
per-mode files (battleroyale, opr, ctf, raids, arenas, dungeons…). These
describe level composition/triggers — relevant for spawn placement later.

## Why this changes the plan

1. **The server can load the game's own data tables.** Any table we can decode
   becomes server truth without datamining by hand. Format work: one
   `.datasheet` decoder (see `reverse/tools/pakindex.py` for extraction).
2. **The balance tables per PvP mode** (`pvpbalance_*`) are exactly what our
   "vanilla vs custom params" feature needs: we can diff and override.
3. **The XP curve, damage tables, loot tables, mutation ranks, season tracks**
   are all data — roadmap items shrink from "design + implement" to
   "decode + load + serve".

## Next step

Write a `.datasheet` format decoder (reverse the reader in the client — likely
a simple tagged record format given `javelindata` naming), then extract a
handful of key tables (xpamountsbylevel, territorydefinitions, pvpbalance_war)
as fixtures. Add `reverse/tools/datasheet.py` for extraction.


## Spawn placement data (dynamicslice files)

248,826 `.dynamicslice` files carry the per-level entity composition. The
spawn-relevant families:

- `slices/catacombs/gameplay/spawners/` (94) and
  `slices/dungeon/raid_*/spawners/` (83) — explicit spawner graphs per
  instanced level
- `slices/pois/<zone>/<kit>/` — POI composition kits (crafting 579,
  collectibles 100, gatherables 28...)
- `slices/worldevents/<zone>/randomencounter/` and `/encounters/` — world
  event encounter placement
- `slices/dungeon/raid_monarchbluff/encounter1_jester` (52),
  `encounter2_heiressandpg` (96) — raid encounter layouts
- `slices/characters/worldboss/` (e.g. `mammoth_firstlight`, 31) — world boss
  definitions
- `slices/structures/siege/invasion/` (32) — invasion siege structures
- `slices/characters/expeditions/isleofnight/` (37) — raid characters

Plus per-level XML inside each `levels/<subworld>/level.pak`:
`levelinfo.xml`, `leveldataaction.xml`, `mission_mission0.xml` (environment +
mission graph, e.g. frontend: 126 CGFs).

Conclusion: spawn placement is fully data-driven per subworld; the emulator
can load these instead of hand-placing NPCs. The slice format reader is the
missing tool (see `pakread.py` for extraction; format = CRYENGINE component
entity slices, already partially understood from the `.slice` ext count).


## Territory bounds from the world slice (decoded 2026-10-11)

`slices/pois/territories/territories_master.dynamicslice` (SharedDataStrm-part8)
contains the master territory bounds entity with named area bounds:

- Internal zone names found: monarchsbluffs, southwindsward, brightwood,
  greatcleave, northwindsward, shatteredmountain, ancientcrater,
  eastconsolation, firstlight, morrowtide, weaversfen, windswardshores,
  reekwater, queensport, brimstonesands, dunwood (+ more truncated)
- Note: `firstlight`, `morrowtide`, `queensport`, `eastconsolation`,
  `ancientcrater` are removed/cut zones that still ship in the bounds data —
  the world geometry supports zones beyond the live 14.
- 24 per-region POI slice files (`r_+XX_+YY_pois`) map grid regions to POIs.

The emulator can read `territories_master` + `javelindata_territorydefinitions`
(161 rows) to place all zone borders and POIs exactly.
