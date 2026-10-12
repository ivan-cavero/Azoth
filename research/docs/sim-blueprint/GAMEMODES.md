# The 53 game modes (javelindata_gamemodes, decoded 2026-10-11)

The master gamemode table (53 rows x 181 columns) is the authoritative list
of every instanced/structured mode the server can run. Decoded from
SharedDataStrm-part4.pak. Columns cover queueing (level buckets, ready
thresholds, backfill), teams (NumTeams, TeamCapacity, CombineTeamGroups),
gear-score overrides, item-class restrictions per mode, loot table overrides,
and battle tokens.

## The definitive list

**PvP structured modes (8):**
BattleRoyale, CaptureTheFlag, Duel, OutpostRush, OutpostRush_NoPerks,
Arena3v3, FFA (implied by pvpbalance_ffa), openworld (pvpbalance_openworld)

**Dungeons/Expeditions (13):**
Dungeon (generic), Mutation, DungeonAmrine, DungeonShatteredObelisk,
DungeonRestlessShores01, DungeonEbonscale00, DungeonEdengrove00,
DungeonReekwater00, DungeonCutlassKeys00, DungeonGreatCleave01,
DungeonShatterMtn00, DungeonBrimstoneSands00, DungeonFirstLight01,
DungeonGreatCleave00, DungeonDunwood02

Note: DungeonFirstLight01 is a dungeon we had not mapped (First Light was
removed from the live map — it survives as a gamemode + PAK subworld
nw_dungeon_firstlight_01).

**Trials (5):**
TrialBrimstoneSandworm, TrialSeason01, TrialSeason04, TrialSeason02Q12,
TrialSeason02Q13, TrialSeason04Q02/Q05/Q06

**Raids (2):**
RaidCutlassKeys00, RaidMonarchsBluffs00 (plus Isle of Night in season 10
tables)

**Instanced quests (15):**
QuestAdiana, QuestApophis, QuestCaerDun, QuestEmpressZhou, QuestIsabella,
QuestMammoth, QuestMedusa, QuestMotherwell, QuestMedea, QuestNihilo,
QuestYonas, QuestHeartforge, QuestLiang, QuestGawain, QuestDracula,
QuestWolf, QuestMorgaine, QuestVarlaam, QuestSeraphim

**New content (1):**
Catacombs (Season 10 roguelite)

**Test (2):** TestMode1, TestMode2

## Corrections to the web roadmap

1. Duel is a formal gamemode (pvpbalance_duels exists too) — not just a
   facet condition.
2. DungeonFirstLight01 exists (was unmapped).
3. TrialBrimstoneSandworm is a world-boss trial (the Sandworm).
4. Instanced quests are 15+, not 5 — each named quest is a gamemode row.
