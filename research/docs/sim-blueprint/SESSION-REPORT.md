# Reporte de sesión — investigación del juego + web bilingüe + roadmap definitivo

Fecha: 2026-10-11 (sesión nocturna, ~7 h). Estado al amanecer: todo entregado
y verificado.

---

## 1. Investigación: qué se descubrió

### El descubrimiento de la noche: los datos del servidor viajan en el cliente

El PAK del juego incluye **2.250 archivos `.datasheet`** (casi todos
`javelindata_*`) con las tablas de datos reales del servidor:

| Tabla | Contenido | Tamaño decodificado |
|---|---|---|
| `javelindata_xpamountsbylevel` | XP por nivel, vida, attribute points, caps de gear score por nivel, loot bias, house trophy slots | 70 filas × 51 cols |
| `javelindata_loottables` | Todas las loot tables del juego | 5.237 filas × 113 cols |
| `javelindata_gamemodes` | Los 53 modos de juego con cola, equipos, balance, gear override, loot override | 53 × 181 |
| `javelindata_territorydefinitions` | Definición de todos los territorios | 161 × 37 |
| `javelindata_pvpbalance_war` / `_outpostrush` / `_arena` / `_ctf` / `_duels` / `_ffa` / `_openworld` | Balance por modo PvP | 12 × 12 c/u |
| `javelindata_itemdefinitions_weapons` | Armas | 563 × 101 |
| `javelindata_perks` | Perks | 659 × 38 |
| `javelindata_gatherables` | Nodos de recolección | 1.779 × 49 |
| `javelindata_mounts` | Monturas | 62 × 42 |
| `javelindata_weaponmastery` | Árboles de maestría | 20 × 9 |
| `javelindata_mutationdifficulty` | Rangos de mutaciones | 3 × 51 |
| `javelindata_territorygovernance` | Gobernanza | 46 × 24 |
| `javelindata_housetypes` | Viviendas | 5 × 7 |
| `javelindata_invasiondefinitions` | Invasiones | 1 × 6 |
| `javelindata_dungeongrammars` | Gramática procedural de Catacombs | 45 × 9 |
| `javelindata_seasondata` | Temporadas 1-10 | 10 × 8 |
| `javelindata_encumbrancelimits` | Peso y límites | 11 × 52 |
| `javelindata_factiondata` | Facciones | 4 × 9 |
| `javelindata_schedules` | Horarios de eventos | 34 × 10 |

**Consecuencia**: no hay que inventar ni dataminer las reglas del juego —
el lector `.datasheet` ya existe y está verificado
(`reverse/tools/datasheet.py`, escrito el 2026-10-05). El roadmap pasa de
"diseñar + implementar" a "decodificar + cargar + servir" en cada sistema
numérico.

### La lista definitiva de los 53 gamemodes

Decodificada de `javelindata_gamemodes` (`GAMEMODES.md`):

- **PvP estructurado (8)**: BattleRoyale, CaptureTheFlag, Duel, OutpostRush,
  OutpostRush_NoPerks, Arena3v3 + FFA/openworld (en pvpbalance)
- **Expediciones (15)**: las 12 conocidas + DungeonFirstLight01 (que faltaba)
  + Dungeon (genérico) + Mutation
- **Trials (7)**: TrialBrimstoneSandworm (¡gusano de mundo!), TrialSeason01/04,
  Q-variants
- **Raids**: RaidCutlassKeys00, RaidMonarchsBluffs00 (+ Isle of Night S10)
- **Quests instanciadas (19)**: Isabella, Liang, Medusa, Nihilo, Gawain,
  Dracula, Morgaine, Seraphim, Varlaam, Apophis, CaerDun, EmpressZhou,
  Mammoth, Motherwell, Medea, Yonas, Heartforge, Wolf, Adiana
- **Catacombs**: el roguelite procedural de la S10

### El estado final del juego (Steam, oficial)

- **Season 10 "Nighthaven"** (13 oct 2026) = último contenido, gratis.
- **Rise of the Angry Earth** ahora gratis para todos.
- **Servidores se apagan el 31 de enero de 2027**; delisting el 15 ene 2026.
- Nighthaven añade: zona nueva (castillos góticos/catacumbas), modo
  Catacombs (roguelite procedural 1-3 jugadores, extracción con timer,
  Sterlings/Cursed Crowns), raid de 10 "Isle of Night", arma Daggers.

**Consecuencia para el emulador**: el cliente que usamos es la versión final
y completa del juego. Nada va a cambiar bajo nuestros pies. El objetivo es
estable para siempre.

### Los bounds de territorios desde el world slice

`slices/pois/territories/territories_master.dynamicslice` contiene los
límites nominales de todas las zonas: monarchsbluffs, northwindsward,
southwindsward, brightwood, greatcleave, shatteredmountain, weaversfen,
reekwater, brimstonesands, dunwood… **más zonas cortadas que siguen en los
datos**: firstlight, morrowtide, queensport, eastconsolation, ancientcrater.

### La superficie RPC del servidor, exacta

El cliente registra **390 componentes con ServerFacet** y **702 métodos
servidor nombrados** (`all-server-facets.json`). Los mayores:
SeasonsRewards (30 métodos), GameModeParticipant (25), PlayerHousing (14),
TerritoryInteractor (14), MetaAchievement (13), Objectives (12)…
Esta es la API que un servidor real expone, enumerada por el propio cliente.

### Otros hallazgos

- **Spawn placement es data-driven**: 248k `.dynamicslice` incluyen spawner
  graphs por subworld (`slices/catacombs/gameplay/spawners/`,
  `slices/dungeon/raid_*/spawners/`), POI kits por zona, encounters de world
  events, y los encuentros de raid con layout explícito.
- **250+ NPCs individuales** con sus máquinas de diálogo
  (`npcdata_npc_*`, `conversationstatedata_npc_*`).
- **122 páginas de wiki cacheadas** (mecánicas, actualizaciones del juego,
  expediciones, temporadas, eventos) en `raw-wiki-1/2.json`.
- ** facet families por sistema** mapeadas 1:1 con el roadmap
  (`facet-map.json`): war_siege 23 familias, ai_encounters 32, economy 27,
  meta 24, dungeon 21, pvp 19…

---

## 2. Roadmap v3: 15 grupos, 135 puntos, en inglés

Estructura por dependencias (A → O), cada punto con `id`, `dependsOn`,
evidencia citada (client/pak/wiki/steam) y esfuerzo S/M/L/XL:

- **A · Protocol core** (9) — incluye el nuevo A9: cargar las datasheets
- **B · Character body, movement, physics** (7) — la vía crítica
- **C · Persistence & account layer** (7)
- **D · Combat rules** (8) — data-driven desde A9
- **E · World: regions, settlements, travel** (9)
- **F · NPCs & AI** (9)
- **G · Progression & trade skills** (10)
- **H · Items & economy** (10)
- **I · Social & grouping** (8)
- **J · Territory ownership & war** (8) — el flagship
- **K · Instanced content** (27) — expediciones, mutaciones, Catacombs
  (K21), raid Isle of Night (K22), Nighthaven (K23), Duel formal (K24),
  19 quests instanciadas (K25), Sandworm (K26), First Light dungeon (K27)
- **L · Housing & personal world** (4)
- **M · Events, seasons & live ops** (7)
- **N · Web platform** (6)
- **O · Scale & production** (6) — Rust gateway → Rust world → capacidad

Servido en `roadmap.json`, la página lo lee en vivo cada 60 s.
Regla intacta: el roadmap NO es el tracker de trabajo (STATUS.md manda).

---

## 3. Web bilingüe EN/ES

- **`/` = español, `/en/` = inglés**, con botón ES/EN en la nav.
- Todo el chrome de la UI traducido (nav, hero, live, timeline, roadmap
  chrome, stack, verificación, ritmo, versiones, ayudar, footer).
- **El contenido del roadmap se queda en inglés** (como se pidió).
- Sistema i18n: `src/data/i18n.ts` + datos localizados en
  `src/data/project.ts` (labels/roles/details/bullets bilingües).
- Badge en vivo, servicios y textos de estado localizados vía
  `LiveStrings.astro` (data-attributes que el JS del badge consume).
- **Nueva sección "Lo que dice la investigación" / "What the research says"**
  (`Research.astro`): las 4 cifras de fuentes y los 3 descubrimientos clave
  de esta noche, enlazando a los docs del blueprint.
- Verificado: ambas rutas 200, título correcto por idioma, 0 restos de
  español en la página EN, móvil 390px sin desbordes
  (scrollW=390 exacto).

---

## 4. Estado final de la web

- `http://127.0.0.1:8090` (ES) y `/en/` (EN) — `python ef.py web`.
- Hero limpio con tarjeta de captura real del juego (Windsward, sesión del
  7 oct) — sin fondos a pantalla completa.
- Timeline: 28 entregables con scroll horizontal, AHORA centrado al 65%.
- Roadmap: 135 puntos en vivo, filtros TODO/HECHO/EN CURSO/PLANIFICADO/
  RESEARCH, alineación de columnas corregida.
- Ritmo: commits reales de git, tick 50→60 Hz objetivo, 44 submundos.
- `live.json` conectado al ciclo de vida de `ef.py dev`/`ef.py web`.

---

## 5. Documentos generados esta noche

| Doc | Contenido |
|---|---|
| `research/docs/sim-blueprint/BLUEPRINT.md` | Referencia maestra: capas del servidor, prioridades, apéndice con la superficie RPC exacta |
| `research/docs/sim-blueprint/DATASHEETS.md` | Catálogo de las 2.250 tablas + spawn slices + territory bounds |
| `research/docs/sim-blueprint/GAMEMODES.md` | Los 53 modos definitivos con correcciones al roadmap |
| `research/docs/sim-blueprint/MASTER-FACTS.json` | Resumen consolidado de fuentes |
| `research/docs/sim-blueprint/wiki-facts.json` | Hechos extraídos de la wiki (22 sistemas) |
| `research/docs/sim-blueprint/datasheet-samples.json` | 25 tablas decodificadas con columnas y filas muestra |
| `research/docs/sim-blueprint/facet-map.json` | Familias de facetas por sistema |
| `research/docs/sim-blueprint/all-server-facets.json` | Los 390 componentes × 702 métodos servidor |
| `research/docs/sim-blueprint/server-facet-methods.json` | Métodos por componente de interés |
| `research/docs/sim-blueprint/expedition-bosses.json` | Resúmenes y jefes de 9 expediciones |
| `research/docs/sim-blueprint/steam-final-state.json` | Comunicados oficiales del fin del juego |
| `research/docs/sim-blueprint/raw-wiki-1/2.json` | 122 páginas de wiki crudas |

---

## 6. Próximos pasos sugeridos (al despertar)

1. **Decodificador de `.datasheet` a escala**: script que extraiga las ~30
   tablas clave a JSON versionado en el repo (`research/atlas/game-data/`).
2. **A5 fragment codecs** sigue siendo la vía crítica — el blueprint le da
   el mapa de qué tipos replicar primero (PhysicsTrait → character sheet).
3. **C1 base de datos**: el esquema puede derivarse de las tablas
   `javelindata_*` + componentes `Persistent*`.
4. Considerar **First Light** como territorio extra (los bounds existen).
5. La sección Research de la web puede enlazar a los nuevos docs cuando haya
   hosting público.
