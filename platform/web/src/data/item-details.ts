// Per-item deep content for the roadmap + deliverables timeline.
// Loaded by the roadmap detail modal (Roadmap.astro) and the gantt detail
// modal (Gantt.astro). English content; the modal chrome is localized.

export interface ItemDetail {
  /** what this item actually means, technically (2-6 sentences) */
  what: string;
  /** how it was / will be approached concretely */
  how?: string;
  /** for done items: what happened, what was learned, with evidence links */
  completion?: {
    /** date the item landed (ISO) */
    date: string;
    /** narrative summary of how it was completed */
    notes: string[];
    /** evidence references (files, measurements) */
    evidence: string[];
    /** optional authentic, item-specific screenshots served from /evidence/ */
    images?: { src: string; caption: string }[];
  };
  /** for active items: a partial result that must not read as completed */
  progress?: {
    date: string;
    notes: string[];
    evidence: string[];
    images?: { src: string; caption: string }[];
  };
  /** wiki / docs links shown in the modal */
  links?: { label: string; href: string }[];
}

export const itemDetails: Record<string, ItemDetail> = {
  // ============================================================ bootstrap milestones
  "G0.1": {
    what: "Establish one supported command entry point for setup, local lifecycle, status, and project tooling. Keep caches, runtimes, and generated analysis under repository-local ignored paths so a fresh checkout has a documented operating path.",
    how: "Use az.py and its PowerShell launcher to route setup and development commands; keep the root README and operator docs aligned with those commands.",
    completion: {
      date: "2026-09-12",
      notes: ["The project bootstrap, az.py command surface, and documented local toolchain are in place."],
      evidence: ["README.md", "az.py", "az.ps1"],
    },
  },
  "G0.2": {
    what: "Create a reproducible evidence base from the official client's session traffic and Game.log. These captures establish observed requests and state transitions; raw payloads and secrets remain local and are not public artifacts.",
    how: "Use the repository capture tools and private-client runbook, then curate protocol facts into the atlas instead of treating raw files as documentation.",
    completion: {
      date: "2026-09-20",
      notes: ["Session-capture tooling and Game.log ingestion support repeatable protocol analysis."],
      evidence: ["research/tools/capture/", "research/docs/PRIVATE-CLIENT-RUNBOOK.md", "research/atlas/"],
    },
  },
  "G0.3": {
    what: "Serve the pre-world HTTP contract used by the client, including login, hub discovery, and certificate responses. Passing this layer gets the client to the world connection path; it does not prove world transport or in-game connection health.",
    how: "Implement the routes in the Python gateway and compare their status, headers, and response shapes with observed client traffic.",
    completion: {
      date: "2026-09-24",
      notes: ["The local HTTP gateway handles the documented pre-world routes and certificate flow."],
      evidence: ["services/gateway/", "services/gateway/traffic.jsonl", "research/atlas/openapi.json"],
    },
  },
  "G0.4": {
    what: "Bring up the private world endpoint over DTLS and run an authoritative server tick independently of inbound packet frequency. This is the protocol runtime foundation; client-visible ALC health and player movement are separate acceptance gates.",
    how: "Use the world service and supported az.py lifecycle commands; keep network parsing, session state, and periodic emitters observable in logs and measurements.",
    completion: {
      date: "2026-10-01",
      notes: ["The Python world server accepts the private-client DTLS path and runs its own tick loop."],
      evidence: ["services/world/", "STATUS.md — authoritative tick and transport measurements"],
    },
  },
  "G0.5": {
    what: "Reproduce the private-client launch and the verified entry gates through world rendering and local-player possession. This closes the entry path only; the red ALC/HUD warning, the separate return-to-menu path, and controllable movement remain open.",
    how: "Follow the private-client runbook on a fresh process and record the build, gate transitions, Game.log boundary, and visible result.",
    completion: {
      date: "2026-10-06",
      notes: ["The client enters the world and possesses the local player on a clean run; this does not establish active physics or movement."],
      evidence: ["research/docs/PRIVATE-CLIENT-RUNBOOK.md", "research/sessions/gate6_possession_20261007/"],
    },
  },
  "G0.6": {
    what: "Decode and document the Javelin typed-message registry, varint framing, and the 0x08 StateBundle record/fragment container. The container and message inventory are protocol findings; application dispatch and the movement path remain separate work.",
    how: "Cross-check captured fixtures with client reflection and live reader probes, then preserve the verified schemas and round-trip results in the atlas and codecs.",
    completion: {
      date: "2026-10-09",
      notes: ["The registry contains 144 typed messages; the bundle parser and movement-family schema have independent client and fixture evidence."],
      evidence: ["research/atlas/javelin-messages.json", "services/world/src/azoth_world/javelin/bundle.py", "research/atlas/client-functions.json"],
    },
  },
  "G0.7": {
    what: "Measure how long REP transport stays alive under a sustained private-client run. The 2 h 06 min result had no transportError or REP disconnect, while the red ALC/HUD warning remained; the client-visible connection is therefore still open.",
    how: "Run a fresh client against the local stack, retain time-correlated server and client evidence, and check transport counters separately from ALC/HUD state and the return-to-menu timer.",
    completion: {
      date: "2026-10-10",
      notes: ["REP transport lasted 2 h 06 min with transportError 0 and disconnected-from-REP 0.", "The warning stayed red and a separate ~20-minute return-to-menu path remains unresolved."],
      evidence: ["research/docs/PROGRESS-REVIEW-2026-10-11.md", "research/atlas/client-functions.json — ALC/HUD measurements", "research/sessions/2026-10-10/"],
    },
  },

  // ============================================================ A
  A1: {
    what: "The client connects to the world server over DTLS (UDP with TLS 1.2, cookie exchange, ticket-based resumption) and then speaks the REP protocol: length-prefixed Javelin frames multiplexed over channels. Session setup involves ClientHello with a pinned server certificate, a login token from the gateway, and Carrier chunk replay of the world state snapshot.",
    how: "services/world implements the DTLS handshake with pyOpenSSL, replicates the exact channel framing the official server used (captured in research/sessions), and replays Carrier chunks from the redacted capture fixture at a configurable pace (AZOTH_CHUNK_GAP_MS).",
    completion: {
      date: "2026-10-10",
      notes: [
        "A measured run kept REP transport alive for 2 h 06 min with transportError 0 and disconnected-from-REP 0. This proves transport uptime only: the client still shows a red ALC/HUD warning and cannot move.",
        "Heartbeat/input-response scheduling and 16-bit sequence wrapping fixed earlier transport failures; they did not establish the client-visible ALC conversation.",
      ],
      evidence: [
        "research/atlas/client-functions.json — hud_cable_icon_is_not_the_log_20261010",
        "research/atlas/client-functions.json — alc_pointer_never_opens_live_20261011",
        "research/sessions/2026-10-10/ — transport-soak captures",
      ],
    },
    links: [
      { label: "JAVELIN-PROTOCOL.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/JAVELIN-PROTOCOL.md" },
      { label: "PRIVATE-CLIENT-RUNBOOK.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/PRIVATE-CLIENT-RUNBOOK.md" },
    ],
  },
  A2: {
    what: "Javelin is the session/hub protocol layer above REP. Every typed message has a GUID and a wire-type number. The server must be able to emit and parse the subset the client understands: session lifecycle, hub routing, movement family, and the state bundle container.",
    how: "The registry was derived twice from independent signals (string tables + reflection metadata, then live type-resolution hooks on FUN_1461acfe0), cross-checked to 144 types. Varint and framing codecs are test-verified: 137 of 138 captured message types round-trip byte-exact.",
    completion: {
      date: "2026-10-09",
      notes: [
        "Container-level decode: prefix varint for every typed message and bundle field (javelin/varint.py).",
        "The 12 movement wire types reproduce from two independent derivations — the first time a family was closed end-to-end.",
        "Message table published as research/atlas/javelin-messages.json with GUID + wire type per entry.",
      ],
      evidence: [
        "research/atlas/javelin-messages.json (144 types)",
        "javelin/wire.py, javelin/varint.py, javelin/frame.py with tests",
      ],
    },
    links: [
      { label: "javelin-messages.json", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/atlas/javelin-messages.json" },
    ],
  },
  A3: {
    what: "The 0x08 StateBundle body is a sequence of records: [u8 record_id][u8 fragment_count][fragments...]. Each fragment is [varint key][varint type_index][type-specific payload] — exactly two header varints, no length field; the payload length is implied by the type. record_id selects a handler at state + 0x608 + record_id*0x10 in the client.",
    how: "Initially modeled as one-record-one-fragment, which passed every 'consumes exactly' check — but 'consumes exactly' is necessary, not sufficient. The discriminating evidence came from a live Frida probe on FUN_146af20d0/FUN_146af2340 counting bytes and nested reader calls per record: fragment_count == nested-call count in 90/90 records.",
    completion: {
      date: "2026-10-10",
      notes: [
        "Probe measurement: fragment_count byte equals the client's nested-call count in all 90 distinct records sampled (01 30→48, 02 03→3, 0d 06→6, 1d 13→19).",
        "78 of 79 captured bundles round-trip byte-exact through the new parser (javelin/bundle.py).",
        "Fragment grammar verified: first two varints at offsets 0 and 1 in 300/300 fragments; 48 distinct keys, 47 distinct types, 1:1 key→type binding.",
        "A hand-built bundle was accepted by the live client with no error — independent proof the container layout is right.",
      ],
      evidence: [
        "STATUS.md — 'The state bundle is a RECORD SEQUENCE — corrected and verified (2026-10-10)'",
        "services/world/src/azoth_world/javelin/bundle.py",
      ],
    },
    links: [
      { label: "bundle.py", href: "https://github.com/ivan-cavero/Azoth/blob/main/services/world/src/azoth_world/javelin/bundle.py" },
    ],
  },
  A4: {
    what: "Every periodic emitter originally ran from on_app_data — once per inbound datagram — so server output scaled with client input: measured Pearson(inbound, outbound) = 0.995, amplification 3.4:1. An authoritative server must emit on its own clock.",
    how: "PeerSession.tick() now runs from the UDP loop at TICK_HZ (50, target 60) whether or not a datagram arrived. A regression test (TestAuthoritativeTick) fails if any periodic emitter is ever called from on_app_data again.",
    completion: {
      date: "2026-10-10",
      notes: [
        "After the rework: Pearson 0.180, amplification 0.96:1, peak 99 datagrams/s (was 286), v3-registered 8 → 1.",
        "16-bit sequence fields wrap via _u16(); tick-error logs a traceback so a repeating error names its function.",
      ],
      evidence: ["STATUS.md — 'The server now emits on its own clock'"],
    },
    links: [],
  },
  A5: {
    what: "The remaining long tail of replication: one codec per replicated component type (the type_index in each fragment). PhysicsTrait comes first because it gives the player a body; then character sheet, inventory, vitals. Each codec must encode/decode the component's wire payload exactly as the client's reader consumes it.",
    how: "For each type: find the reader the client installs for that fragment type (Ghidra), read its field order, write the codec, verify against a live probe and captured bundles. The process that closed the movement family, repeated per type.",
    links: [
      { label: "BLUEPRINT.md — priority order", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/BLUEPRINT.md" },
    ],
  },
  A6: {
    what: "The client registers 82 AOI traits with 2,276 trait/message pairs. The registry closes the inventory of names and pairings; it does not mean those server behaviors are implemented. Remaining work is to classify traits against supported features and emulate only the required state paths.",
    how: "Generate the layout-independent map with scan-trait-registry.py, preserve the raw symbol-derived evidence in the atlas, and classify each trait as required now, later, or client-only.",
    completion: {
      date: "2026-10-10",
      notes: ["The build-scoped AOI registry records 82 traits and 2,276 pairs from layout-independent client symbol names.", "This completes the inventory only; per-feature server support remains open."],
      evidence: ["research/atlas/aoi-trait-registry.json", "research/atlas/client-functions.json — aoi_trait_registry_20261010", "reverse/tools/scan-trait-registry.py"],
    },
    links: [
      { label: "aoi-trait-registry.json", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/atlas/aoi-trait-registry.json" },
    ],
  },
  A7: {
    what: "ActorQueryMsg and RoutingUnsubscribeMsg are the two Javelin wire types without a verified derivation. Everything else in the registry round-trips.",
    how: "Same method as the movement family: locate the writer in the client (Ghidra), derive field order, verify with a live probe that the client accepts a synthesized message.",
  },
  A8: {
    what: "The live warning 'RMIDispatch: The facet target ID couldn't be found' (25 per session) is the server calling facet methods the client doesn't have. A real server sends a precise whitelist. The client registers 390 components with server facets and 702 named methods — that set is the exact legal surface.",
    how: "Build the whitelist from capture + the client's registry (all-server-facets.json), then gate every RMI the server emits against it.",
    links: [
      { label: "all-server-facets.json", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/all-server-facets.json" },
    ],
  },
  A9: {
    what: "The client PAK ships 2,250 javelindata_*.datasheet files — the game's actual server-side design data: the XP curve (70 rows × 51 cols incl. per-level health and gear-score caps), 5,237 loot tables, per-PvP-mode balance (war, OPR, arena, CTF, duels, FFA, openworld), 161 territory definitions, 62 mounts, mutation ranks, invasion definitions, all 16 trade-skill tables, season tracks 1-10. The datasheet binary format is already decoded (reverse/tools/datasheet.py, verified).",
    how: "Build a batch extractor that converts the ~30 key tables to versioned JSON committed under research/atlas/game-data/, and a loader the world server imports at startup. Game numbers stop being hand-designed and become data.",
    links: [
      { label: "DATASHEETS.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" },
      { label: "datasheet.py", href: "https://github.com/ivan-cavero/Azoth/blob/main/reverse/tools/datasheet.py" },
    ],
  },
  A10: {
    what: "REP has survived a measured 2 h 06 min run without a transport error, but the client still shows its red ALC/HUD warning. ALC field +0xAA0 never opens and the +0xAA8 input stamp stops refreshing; input-response messages and StartMovementCommunicationMsg did not fix that. A separate 20-minute return-to-menu path also remains open.",
    how: "Trace the client-side producer/consumer and the server contract that opens the ALC door and refreshes the stamp. Change one supported message at a time in a fresh process. Acceptance is the real HUD warning clearing, no transport disconnect, and remaining in-world beyond the 20-minute threshold; then repeat for a 2-hour soak.",
    links: [
      { label: "STATUS.md — current blockers", href: "https://github.com/ivan-cavero/Azoth/blob/main/STATUS.md" },
      { label: "client-functions.json — measured ALC/HUD findings", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/atlas/client-functions.json" },
    ],
  },

  // ============================================================ B
  B1: {
    what: "The client asks for a spawn with PlayerSpawnPointRequestTrait::RequestPlayerSpawnPointMsg; the server answers ReceivePlayerSpawnPointSuccessMsg; the manager runs ProcessSpawnQueueMsg; the body is created through PrefabSpawnRequestTrait::RequestSpawnPrefabMsg. Four steps, and the capture only ever contained the first.",
    how: "Implemented in the Python prototype against the captured traffic; the world renders and the player is possessed with a full HUD.",
    completion: {
      date: "2026-10-06",
      notes: [
        "World entry and possession pass on a clean run after CA trust, DTLS, ClientContext predicate, and local-player identity gates. The ALC/HUD warning and movement checks remain open.",
        "The runbook documents world entry and possession. Its older claim that AZOTH_REPLAY_INPUT_RESPONSE clears the red HUD warning is superseded by the ALC measurements; transport uptime, HUD state, and movement are separate gates.",
      ],
      evidence: ["research/docs/PRIVATE-CLIENT-RUNBOOK.md", "research/sessions/gate6_possession_20261007/"],
    },
    links: [
      { label: "PRIVATE-CLIENT-RUNBOOK.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/PRIVATE-CLIENT-RUNBOOK.md" },
    ],
  },
  B2: {
    what: "The old 'no physics component' conclusion used a GUID list shifted by one entry and was wrong. A corrected live dump of the 126-component player entity found both CharacterPhysicsComponent and GameRigidBodyComponent; the client's own lookup finds both. This confirms presence, not that the body/controller is active or moving.",
    how: "Use the corrected brace-wrapped GUID registry and the early-attach player probe. Treat the result as a component-presence fact; measure activation and transform movement separately.",
    completion: {
      date: "2026-10-10",
      notes: ["The corrected early player-entity dump found both physics component types among 126 components and verified each type through the client's lookup.", "The finding retracts the earlier missing-component diagnosis; body activation and movement are still unmeasured."],
      evidence: ["research/atlas/client-functions.json — local_player_components_step0_20261010", "reverse/probes/client/frida-player-components.py", "research/atlas/az-type-registry.json"],
    },
    links: [
      { label: "az-type-registry.json", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/atlas/az-type-registry.json" },
    ],
  },
  B3: {
    what: "The player has physics component types, but holding W still produces no movement-family message and the scene does not translate. The open question is whether the body/controller is active and which client input/ALC path consumes type 0x635. The older claim that the player entity lacks physics is retracted.",
    how: "On a fresh run, attach before world entry and measure the player's transform, body/controller state, and input consumer while pressing and releasing W. Do not assume generic PhysicsTrait replication is the missing fix.",
    links: [
      { label: "STATUS.md — movement blocker analysis", href: "https://github.com/ivan-cavero/Azoth/blob/main/STATUS.md" },
    ],
  },
  B4: {
    what: "The 12 movement wire types are registered, but W currently produces no movement-family messages. A reliable ReceivePlayerPositionClientMsg (4216) reaches the reader, then fails RMI dispatch because targetLocalId has no facet target. Both the input path and this receiver binding must be understood before calling movement implemented.",
    how: "Trace the channel-1 type 0x635 consumer and the correct IPositionReceiver/facet target. Prove success by measuring local transform delta while holding/releasing W, then route and validate the resulting movement through the authoritative tick.",
  },
  B5: {
    what: "Server-side anti-cheat baseline for movement: clamp per-tick position deltas to max velocity, reject collisions client-side but verify server-side, flag teleports. The client is the renderer; the server is the referee.",
    how: "Authority hooks in the tick loop; thresholds configurable through the params service (C7).",
    dependsNote: "Build after B4 proves the wire path.",
  },
  B6: {
    what: "The client ships RockNRoll::CharacterSupportInfo ({824E1E63-...}) — a capsule character controller — alongside the rigid-body path. Dodge/block combat feels controller-driven. Decision: start with the capsule controller (cheaper, matches the game's feel), keep rigid body for siege weapons and physics objects.",
    how: "Prototype both paths against B3's replication and compare client behavior in a live session.",
  },
  B7: {
    what: "Death has a two-phase design: at Death's Door the player is revive-able, all status effects cleared, can be finished by enemies, or presses E to give up. Then corpse + respawn at inn/house/camp with the corresponding cooldowns.",
    how: "Wire ReviveFromDeathsDoor, PlayerComponentServerFacet_RequestRespawn and RespawnTypeEnum through the replication layer; state machine server-side.",
    links: [
      { label: "wiki: Death's Door", href: "https://newworld.fandom.com/wiki/Death%27s_Door" },
    ],
  },

  // ============================================================ C
  C1: {
    what: "Every durable fact of the game world needs a server-owned database: characters, inventories, world state, companies, territories, market orders. The client's Persistent*ServerData components are the schema cheat-sheet — each one names exactly what a real server saves: PersistentVitalsServerData, PersistentCurrencyData, PersistentTerritoryGovernanceData, PersistentSiegeWarfareServerData, PersistentEntitlementData, PersistentItemSkinningData…",
    how: "SQLite first (zero-dep, matches the stdlib philosophy), with a thin repository layer so Postgres is a config swap later. Schema generated from the Persistent* component set + the javelindata tables (A9).",
    links: [
      { label: "BLUEPRINT.md — persistence layer", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/BLUEPRINT.md" },
    ],
  },
  C2: {
    what: "Session end must snapshot the character and session start must restore it. The client explicitly supports this flow: EntityRestoreInfo, RestoreCustomizedDataMessage, RestoredCustomizedDataMessage.",
    how: "Serialize the replicated component set (post-A5) to the C1 database keyed by character UUID; restore re-feeds the same records the client would get on a fresh spawn, then applies deltas.",
  },
  C3: {
    what: "The current prototype replays a captured character. A real server serves a real characterId — which unblocks the client's character-select screens (present in the decompilation campaign's server-select targets) and makes multi-character accounts possible.",
    how: "Issue UUIDs from C1, wire RequestGetPlayer (the empty-characterId warning disappears), feed character-specific inventory/appearance data.",
  },
  C4: {
    what: "Character creation: the client ships CharacterCreationDatabase and an ftue_v2_cc level in the PAK — the creation UI and pipeline exist client-side. Appearance components (PersistentPlayerAppearanceData, FaceMarkSkinToneData) define what the server must store.",
    how: "Serve the creation flow's typed messages, persist the appearance payload, spawn new characters at the beach intro.",
  },
  C5: {
    what: "One account system for web + game: the web mints a token, the gateway validates it, the world session inherits it. The gateway has served the client's pre-world account APIs since September — this adds our own accounts to the same path.",
    how: "JWT-style token with character bindings; the gateway already has the HTTP surface.",
  },
  C6: {
    what: "Character slots per account with per-character world state. The client's character-select screens handle the UI; the server needs slot storage and selection flow.",
    how: "Extend C3's storage model; enforce slot limits per account tier.",
  },
  C7: {
    what: "The server-params service the user asked for by name: vanilla-style editable configuration (XP rates, drop rates, taxes, gear score, schedules) with live hot-reload for all connected players. The client has explicit debug hooks (GameModeComponentServerFacet_DebugRequestSetScriptState, CombatDebugSettings).",
    how: "JSON config + watch; changes push through the tick loop so every connected player picks them up without relogin. Per-mode overrides come free from pvpbalance_* tables (A9).",
    links: [
      { label: "pvpbalance tables (DATASHEETS.md)", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" },
    ],
  },

  // ============================================================ D
  D1: {
    what: "Five base attributes (Strength, Dexterity, Intelligence, Focus, Constitution) with diminishing returns per point — the wiki documents the curve and every combat formula keys off it. javelindata_xpamountsbylevel ships AttributePoints per level (5/level, the literal data).",
    how: "Load the attribute table (A9), implement the derived-stat formulas from the damage tables, expose through AttributeComponentServerFacet.",
    links: [{ label: "wiki: Attributes", href: "https://newworld.fandom.com/wiki/Attributes" }],
  },
  D2: {
    what: "Health, mana and stamina with regen buckets. The XP table ships per-level Health (50 HP at level 1 → +50/level); stamina costs and mana costs have their own tables (javelindata_staminacosts_player, javelindata_manacosts_player).",
    how: "PersistentVitalsServerData defines the server snapshot shape; regen buckets tick in the authoritative loop.",
  },
  D3: {
    what: "The full damage pipeline: hit → damage table lookup → mitigation (per-type defenses ship in the XP table: DefStandard/Slash/Strike/Magic/Fire/Lightning/Corruption, ResFrost/Poison/Bleed/Disease/Curse) → event with flags (HealthChangeFlags).",
    how: "javelindata_damagetable_* has 450+ tables (one per enemy/variant); javelindata_damagetypes enumerates the types. Implement the pipeline generically and feed it from data.",
    links: [{ label: "DATASHEETS.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" }],
  },
  D4: {
    what: "Abilities with cooldowns, instances (AbilityInstanceTrackingComponent), and hot-swapping (ExecuteSwapWeapon). Each weapon's skill table ships as javelindata_spelltable_<weapon> (16 weapons + AI + gamemode variants).",
    how: "Ability server state machine keyed off the spelltables; swap weapon = swap active spelltable + animation state.",
  },
  D5: {
    what: "Status effects system: 328-column javelindata_statuseffects master table plus per-weapon/per-perk/per-AI variants, buckets (BuffBucketsProviderComponent), area effects (AreaStatusEffectComponent), persistence across sessions.",
    how: "Generic effect engine reading the status-effect tables; areas tick spatially in the AOI system.",
  },
  D6: {
    what: "The 16 weapons with mastery trees: sword/shield, rapier, hatchet, flail, spear, great axe, greatsword, war hammer, bow, musket, blunderbuss, fire staff, life staff, ice gauntlet, void gauntlet, daggers (Season 10). javelindata_weaponmastery (20 rows) + javelindata_spelltable_<weapon> ship the trees.",
    how: "Load mastery data (A9); respec costs Azoth (wiki-documented); each tree = passive nodes + ability unlocks.",
    links: [{ label: "wiki: Weapons", href: "https://newworld.fandom.com/wiki/Weapons" }],
  },
  D7: {
    what: "Gear system: equipment slots, perk rolls (javelindata_perks, 659 rows), gem socketing (javelindata_socketables, cut gemstones), gear score bands. EquipmentData/EquipmentSaveData define the client contract.",
    how: "Item generation service reading the perk buckets + socketables; gear score from the XP table's per-level caps.",
  },
  D8: {
    what: "The High Watermark system: drops roll gear score by zone level, per-slot watermark ratchets up, Gypsum casts and Umbral shards (javelindata_umbralcurrency, javelindata_umbralgsupgrades) provide deterministic bumps. Expertise gates mutated content.",
    how: "Watermark per slot in C1; drop rolls consult zone level + current watermark per the High Watermark tables.",
    links: [{ label: "wiki: High Watermark System", href: "https://newworld.fandom.com/wiki/High_Watermark_System" }],
  },

  // ============================================================ E
  E1: {
    what: "The main world (Aeternum, internally newworld_vitaeeterna) ships as 29,980 files in the client PAK, and the replay already streams it — the world renders with full geography, settlements, and interiors.",
    completion: {
      date: "2026-09-24",
      notes: [
        "World streaming works from the replay: the client renders the island end to end.",
        "POI composition is data-driven per grid region (24 r_+XX_+YY_pois slices) — territories_master.dynamicslice holds the bounds.",
      ],
      evidence: ["pak: sharedassets/coatlicue/newworld_vitaeeterna (29,980 files)"],
    },
  },
  E2: {
    what: "The 14 playable territories: Monarch's Bluffs, Windsward, Brightwood, Cutlass Keys, Ebonscale Reach, Mourningdale, Reekwater, Restless Shore, Weaver's Fen, Brimstone Sands, Edengrove, Great Cleave, Shattered Mountain, Elysian Wilds. javelindata_territorydefinitions (161 rows) has the canonical data, and territories_master.dynamicslice has the actual map bounds — including cut zones (First Light, Morrowtide, Queensport) whose geometry still ships.",
    how: "Load territory definitions + bounds; implement zone awareness in the AOI system (which territory a coordinate belongs to).",
    links: [
      { label: "wiki: Territories", href: "https://newworld.fandom.com/wiki/Territories" },
      { label: "GAMEMODES.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/GAMEMODES.md" },
    ],
  },
  E3: {
    what: "Settlements with per-tier crafting stations: Outfitting, Forge, Workshop, Kitchen, Stonecutting, Tannery, Woodshop, Smelter, Loom. Stations visually upgrade with tier and gate crafting max tiers. Station upgrades are town-project driven (G4).",
    how: "Station entities per settlement with tier state from the territory progression tables; crafting availability checks station tier + player trade-skill rank.",
  },
  E4: {
    what: "Each region's fort is a PvP control point granting territory + global rewards; influence towers/watches (3 per territory) feed war declaration. javelindata_factioncontrol_towerdefinitions and _buffs ship the data.",
    how: "Fort/tower entities with ownership state; capture flow feeds J3 (wars).",
  },
  E5: {
    what: "Fast travel: spirit shrines (unlock by visiting), inn recall (free, 60-min cooldown), house recall (2-4 h), Azoth cost by distance + encumbrance (javelindata_encumbrancelimits, 11 rows), faction bonuses reduce cost. The client's fast-travel facets are already mapped.",
    how: "Travel service computing cost from the encumbrance + distance tables; shrine/inn/house discovery persisted per character.",
    links: [{ label: "wiki: Fast Travel", href: "https://newworld.fandom.com/wiki/Fast_Travel" }],
  },
  E6: {
    what: "Weather system (WeatherConfiguration + WeatherSpawner) and day/night cycle. Cosmetic first; area status effects (D5) hook in later.",
    how: "Server-driven weather state broadcast; time-of-day from the timeofday zone XMLs that ship per level.",
  },
  E7: {
    what: "Resource nodes: javelindata_gatherables (1,779 rows × 49 cols) defines every gatherable; GatherableControllerComponent handles the client interaction. Nodes deplete on harvest and respawn on a server clock.",
    how: "Node registry from the gatherables table; respawn timers configurable via C7; per-node state in the world DB.",
  },
  E8: {
    what: "Player camps, tier 1-5 with skins: CampingComponentServerFacet (RequestSetCampSkinId, RequestDemolishCamp, bind cooldown). CampTierData ships tiers; the XP table shows camp blueprints (CampT1) and regen effects per level.",
    how: "Camp entity with tier + skin persisted; respawn point binding per the wiki rules.",
  },
  E9: {
    what: "Mounts: 62 rows in javelindata_mounts (horses, dire wolves, lions + variants), Riding trade skill (javelindata_tradeskillriding), mount stamina/dash/dye (javelindata_itemdefinitions_mountdye, mountitemappearances). Unlock via the 'My Kingdom For a Horse' quest.",
    how: "Mount entity attached to the player; movement speed modifiers; the client's 65 mount component types handle the rest.",
    links: [{ label: "wiki: Mounts", href: "https://newworld.fandom.com/wiki/Mounts" }],
  },

  // ============================================================ F
  F1: {
    what: "Six enemy families, each with distinct attack sets scaling by level: The Corrupted, The Lost, The Ancients, The Angry Earth, Beasts, The Varangian Knights. The damage tables ship per-enemy (450+ named tables incl. every boss and variant).",
    how: "Family definitions from the damage tables + bestiary pages; attack sets from the AI spelltables.",
    links: [{ label: "DATASHEETS.md — combat tables", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" }],
  },
  F2: {
    what: "Spawn system: AreaSpawnerComponent + AISpawnPositionTrackingComponent + the 248k dynamicslice files that place everything (spawner graphs per subworld, POI kits per zone, world-event encounters).",
    how: "Slice reader (new tool) → spawn registry per region; spawners tick on the server clock with respawn timers.",
    links: [{ label: "DATASHEETS.md — spawn placement", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" }],
  },
  F3: {
    what: "AI behavior trees (111 Behavior* types), orders (AIAssignOrder), and the AI manager/objective components. The client-side AI runs locally for its own entities; the server owns decisions and sync.",
    how: "Behavior definitions load from the AI datasheets; server issues orders, clients simulate locally within the trust boundary.",
  },
  F4: {
    what: "Navmesh navigation: NavigationAction/Link/AreaCost, NavigationObstacleMeshComponent. The level PAKs ship the navmesh per subworld.",
    how: "Load navmesh per level; pathfinding server-side for authoritative NPC movement.",
  },
  F5: {
    what: "Minion vitals + boss phases: MinionVitalsProviderComponent, BossPhaseComponent with HealthThresholdBossPhaseConfig and WaveEndedBossPhaseConfig. Every boss's damage table ships (450+ tables incl. worldboss variants).",
    how: "Phase state machine per boss from its damage/config table; vitals sync via the replication layer.",
  },
  F6: {
    what: "Loot: 5,237 loot tables (javelindata_loottables × 113 cols), loot buckets (javelindata_lootbuckets), luck system (trophies, buffs), InstancedLootComponent for per-player instanced drops, loot limits and diversion.",
    how: "Loot service rolling against the shipped tables with luck modifiers; instanced loot per player via the AOI system.",
    links: [{ label: "DATASHEETS.md — loot", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/DATASHEETS.md" }],
  },
  F7: {
    what: "Elite zones + chest runs: elite supply chests, ancient chests, provisions caches with daily lockouts (EntityLootLockEvent). The wiki's Elite Chest Runs guide documents the routes.",
    how: "Chest entities with per-player lockout state; keys/requirements from the tuning data.",
    links: [{ label: "wiki: Elite Chest Runs", href: "https://newworld.fandom.com/wiki/Elite_Chest_Runs_(Guide)" }],
  },
  F8: {
    what: "The three classic Arena Trials — Spire of Melpomene, The Eternal Pool (Reekwater), Zygoramet's Grove (Edengrove) — single-elite encounters gated by Tuning Orbs (crafted at Stonecutting). PAK subworlds nw_arena01/nw_arena02.",
    how: "Instanced encounters via K1; orb consumption on entry; loot rolls from the elite tables.",
    links: [{ label: "wiki: Arena Trials", href: "https://newworld.fandom.com/wiki/Arena_Trials" }],
  },
  F9: {
    what: "NPC waypoints and patrols: NPCWaypointSet*, PersistentWaypointsData. 250+ individual NPC data blocks ship in the PAK (npcdata_npc_*).",
    how: "Patrol routes from the waypoint sets; schedules from javelindata_npc_votimelines.",
  },

  // ============================================================ G
  G1: {
    what: "XP and levels 1-65: the literal curve ships in javelindata_xpamountsbylevel (XPToLevel per level, 70 rows). Level unlocks hotspots (HotspotUnlocksPerLevel) and gates content.",
    how: "Load the XP table; award XP from kills/gather/craft events (XpEvent); level-up notification via OnPlayerLeveledUp.",
    dependsNote: "Needs C2 (persistence) so progress survives sessions.",
  },
  G2: {
    what: "The mission system: StaticMissionData, MissionGoalTypeData, MissionOptionData, MissionDestinationData — plus every quest's objective tree ships as objectives_quest_* / objectivetasks_quest_* datasheets. 19 named quests are formal gamemodes (QuestIsabella, QuestLiang…).",
    how: "Quest engine loading the objective trees; state machine per character per quest; the 19 instanced quests route through K1.",
    links: [{ label: "GAMEMODES.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/GAMEMODES.md" }],
  },
  G3: {
    what: "Faction missions (PvE + PvP variants): faction boards, token rewards (owg_progression_* per faction), faction rank with achievements. PvP missions drop flags.",
    how: "Mission engine with faction flavor; token currency per faction; rank progression via CategoricalProgression.",
  },
  G4: {
    what: "Town projects + territory standing: town boards drive settlement upgrades (stations, forts, storage); personal Territory Standing grants choice-based perks (housing cost, station fees, travel cost). javelindata_territoryprogression (50 rows) + territory_standing ship the data.",
    how: "Board missions feed settlement upgrade pools; standing awards per activity type via CategoricalProgression.",
  },
  G5: {
    what: "Gathering: logging, mining, harvesting, tracking & skinning — with per-tool tiers and the variations_gatherables_* families (trees, minerals, bushes, essences, holiday…). 1,779 gatherables ship.",
    how: "Gathering flow from E7's node registry + per-skill XP (javelindata_tradeskilllogging/mining/harvesting/skinning).",
  },
  G6: {
    what: "Refining: smelting, woodworking, leatherworking, weaving, stonecutting. Refining recipes ship (javelindata_refiningrecipes); station tiers gate output tiers.",
    how: "Recipe engine + station tier checks; byproduct rolls from the crafting tables.",
  },
  G7: {
    what: "Crafting: weaponsmithing, armoring, engineering, jewelcrafting, arcana, cooking, furnishing — each with its own table (javelindata_crafting_<station>), Azoth-enhanced rolls, craft mods, cooldowns on named items. Crafting max tiers gate by station tier (E3).",
    how: "Craft service with roll generation (perks from javelindata_perks buckets), Azoth consumption, and named-item cooldowns.",
    links: [{ label: "wiki: Crafting", href: "https://newworld.fandom.com/wiki/Crafting" }],
  },
  G8: {
    what: "CategoricalProgression is the unified standing system: faction rank, territory standing, weapon mastery, trade-skill ranks all flow through one component (CategoricalProgressionComponentServerFacet, 10 debug methods expose the shape).",
    how: "One progression service with categories; everything else (G1-G7) feeds it.",
  },
  G9: {
    what: "Seasons + reward tracks: full data for all 10 seasons ships (chapterdata, rewarddata, seasonpassdata, seasonsrewards* per season). The final live game (Nighthaven) ran its season until shutdown — our cadence is operator-controlled.",
    how: "Season scheduler (C7) loading the season tables; reward track state per character.",
    links: [{ label: "wiki: Seasons", href: "https://newworld.fandom.com/wiki/Seasons" }],
  },
  G10: {
    what: "Achievements via the NPA model: AchievementComponentServerFacet (11 methods) with DebugRequestForceEvaluateAllNPAs — achievements are evaluated as Named Point Assertions over player state.",
    how: "NPA evaluator over C1 state; the meta-achievement tables ship (javelindata_metaachievements*).",
  },

  // ============================================================ H
  H1: {
    what: "The inventory service speaks transactions: Javelin::InventoryService::TransactWriteItemsRequest — the client expects atomic multi-slot writes with a pending-request group. InventoryRegistry, InventoryChange, InventoryKey define the shapes.",
    how: "Transactional inventory service mirroring the TransactWriteItems shape; all item mutations flow through it.",
  },
  H2: {
    what: "Equipment slots and the paperdoll: EquipmentData/EquipmentSaveData, slot conditions (ActionConditionIfItemInSlot*, broken items, sheathed state).",
    how: "Equipment model over H1; slot validation against item classes.",
  },
  H3: {
    what: "Weight and encumbrance: javelindata_encumbrancelimits (11 rows × 52 cols) defines the bands; weight affects movement and fast-travel cost (E5).",
    how: "Weight rollup from inventory; hook into movement modifiers and travel pricing.",
  },
  H4: {
    what: "Coin, fees and taxes: PersistentCurrencyData, TaxOrFeeTypeData; trading fees by posting settlement, transaction taxes by purchasing settlement, weekly housing property tax (L1), territory upkeep (J1). CurrencyConversionComponent handles exchange.",
    how: "Currency ledger in C1; fee/tax rates from territory governance (J1) — operator-overridable via C7.",
  },
  H5: {
    what: "Trading Post, global across settlements: buy/sell orders, cap of 100 active contracts per character, 14-day max order life, expiry returns items to the posting settlement's storage, fees defined by the posting settlement. TradingPostComponentServerFacet handles the client surface.",
    how: "Market service over C1 with order matching, expiry jobs, and settlement-linked storage; UI via the existing client facets.",
    links: [{ label: "wiki: Trading Post", href: "https://newworld.fandom.com/wiki/Trading_Post" }],
  },
  H6: {
    what: "Direct P2P trade with the full client flow: offer lock-in (OnLockInOfferResponse), mutual confirm, coin offers (UpdateOfferedCoin), overflow handling (OnItemsOverflowed).",
    how: "Trade session state machine between two characters; atomic swap via H1.",
  },
  H7: {
    what: "Storage: settlement storage sheds (GlobalStorageComponentServerFacet with search) + house storage chests with capacity bonuses (HousingItemBehaviorStorage).",
    how: "Storage model over C1; chest bonuses from the housing tables; search server-side.",
  },
  H8: {
    what: "Salvage and repair: repair parts + gold cost, salvage by class (CraftingComponentServerFacet_SalvageItemsInInventory, InitiateSalvageByClass), AutoRepairComponent. Salvage loot tables ship.",
    how: "Repair/salvage flows consuming the salvage loot tables; repair parts as a currency.",
  },
  H9: {
    what: "Cosmetics: transmog (TransmogComponentServerFacet), dyes with refund slots (DyeData, DyeRefund, javelindata_dyecolors), item skins (ItemSkinningComponent, javelindata_itemskins).",
    how: "Appearance service over C1; the client handles rendering.",
  },
  H10: {
    what: "Store and entitlements: GameStoreTabData, StoreSlot, store products per month (mtx_2023-01 … 2025-03 tables), EntitlementComponent with grant/lock/exchange. Needed for cosmetics and any monetization.",
    how: "Store catalog from the shipped tables; entitlement service with operator-controlled pricing.",
  },

  // ============================================================ I
  I1: {
    what: "The target social layer includes proximity, group, company, and world chat plus system messages. The prototype currently routes only a subset of channels; company and whisper delivery, durable history, membership checks, and permissions are not complete.",
    how: "Channel service in the tick loop; proximity chat resolved via AOI.",
    progress: {
      date: "2026-10-10",
      notes: [
        "The prototype routes local, group, and world chat through the session.",
        "Company and whisper channels, membership enforcement, and persistence remain open.",
      ],
      evidence: ["services/world — chat routing in rep.py"],
    },
  },
  I2: {
    what: "Voice chat: VoiceChatComponentServerFacet + VoiceChatServerData define the client transport hooks. Spatial (proximity) or channel-based; needs a media relay outside the game protocol.",
    how: "WebRTC or UDP media relay coordinated by the server; the game client's voice facets handle capture/playback.",
  },
  I3: {
    what: "Groups of 5 with raid conversion (AutoGroupConvertToRaid); group conditions permeate the action-condition system (loot rules, quest credit).",
    how: "Group service with leader/loot rules; raid conversion for 10+ (Isle of Night, K22).",
  },
  I4: {
    what: "Friends: FriendsData, FriendRequestTypesEnum, SocialComponentServerFacet_RequestFriendStatusChangeFromClient — add/remove/block with presence.",
    how: "Social graph in C1; presence from session state.",
  },
  I5: {
    what: "Companies (guilds): the war/territory actor. GuildCrest, GuildMemberData, GuildInviteData, DetailedGuildView — ranks, invites, roster, crest customization. 28 client types.",
    how: "Company service over C1; ranks + permissions; crest data; the war system (J) hangs off company ownership.",
    links: [{ label: "wiki: Company", href: "https://newworld.fandom.com/wiki/Company" }],
  },
  I6: {
    what: "The three factions — Covenant, Marauders, Syndicate: join flow, rank progression (FactionComponentServerFacet, 39 types), faction vendors with token currencies (owg_progression_covenanttokens/marauderstokens/syndicatetokens).",
    how: "Faction service over CategoricalProgression; vendor catalogs from the faction item tables.",
    links: [{ label: "wiki: Factions", href: "https://newworld.fandom.com/wiki/Factions" }],
  },
  I7: {
    what: "Emotes (43 types) and musical performances: 5 instruments (guitar, mandolin, upright bass, drums, Azoth Flute), solo/group performances grant buffs for a fee (javelindata_musicalperformancerewards, songbook + sheets).",
    how: "Emote routing; performance minigame state machine with buff rewards.",
    links: [{ label: "wiki: Music", href: "https://newworld.fandom.com/wiki/Music" }],
  },
  I8: {
    what: "Map pings, user markers, compass: MarkerComponent/UiMarkerComponent, WaypointsComponent.",
    how: "Marker broadcast within the AOI radius; client renders.",
  },

  // ============================================================ J
  J1: {
    what: "Company-owned territories with governance: the Governor's Desk (Town Hall, 2nd floor) sets taxes and upkeep; the Territory Planning Board manages upgrades; upkeep is due every 7 days or stations degrade. PersistentTerritoryGovernanceData is the persistence shape; javelindata_territorygovernance (46 rows) ships the config.",
    how: "Governance service over C1 tied to company ownership (I5); tax rates flow into H4; upkeep jobs on the server clock.",
    links: [{ label: "wiki: Territory Governance", href: "https://newworld.fandom.com/wiki/Territory_Governance" }],
  },
  J2: {
    what: "Territory upgrades: crafting station tiers (E3), fort gates/turrets, storage expansion, and the territory status-effect map (PersistentTerritoryStatusEffectsMap) that applies owned-territory buffs.",
    how: "Upgrade tree per territory consuming town-project contributions (G4); effects broadcast to residents.",
  },
  J3: {
    what: "Influence race: scheduled open-world PvP (3/day live game) — factions fight over the fort + 3 influence towers/watches for 45 minutes; highest influence declares war. Season 3 rework made wars guaranteed so defenders can lose the race but still fight.",
    how: "Scheduled event (from javelindata_schedules); influence scoring in the war board aggregates; feeds J4.",
    links: [{ label: "wiki: War — Influence Race", href: "https://newworld.fandom.com/wiki/War" }],
  },
  J4: {
    what: "War declaration + signup: Conflict tab scheduling, War Board in town (next to the town hall), remote signup from the map, 50-player roster selection by the declaring company. GameMasterComponentClientFacet_OnWarDataReceived and ResetDailyWarCount* show the war data path.",
    how: "War scheduler consuming J3 influence results; roster management; war instance scheduling on K1.",
  },
  J5: {
    what: "War gameplay 50v50: siege weapons, destructible doors (javelindata_destructiblewalls), oil vats, repeater turrets (TurretComponent), rally points, 3 lanes of attack/defense. DestroyOnSiegeWarfareComponent + ClearContainerOnSiegeWarfareComponent handle war cleanup.",
    how: "War instance mode on K1 with the siege component set; scoring via javelindata_warboardaggregates; balance from pvpbalance_war.",
    links: [{ label: "wiki: War", href: "https://newworld.fandom.com/wiki/War" }],
  },
  J6: {
    what: "War hosting: wars run as instanced shells (WarDungeonMasterSpawnResponseHandler exists in the client) — the instance framework K1 hosts them with matchmaking integration for roster fill.",
    how: "War gamemode on the K1 framework; the 50v50 instance spins up per scheduled war.",
  },
  J7: {
    what: "Corrupted invasion: PvE fort defense — waves of Corrupted scale with settlement growth; failure degrades crafting stations/gates; cadence ~every 4 days if breaches stay open. InvasionComponent + InvasionLaneProvider + InvasionWaveObjective; javelindata_invasiondefinitions + darkness tables.",
    how: "Invasion scheduler + wave director in the war instance framework; corruption damage tables drive the enemies.",
    links: [{ label: "wiki: Corrupted Invasion", href: "https://newworld.fandom.com/wiki/Corrupted_Invasion" }],
  },
  J8: {
    what: "Corrupted breaches: open-world events; closing them delays the invasion cadence. WorldEventCoordinatorTrait runs the event loop; javelindata_worldevent* ships the rules.",
    how: "World event scheduler from the shipped rules; breach entities with close interactions.",
  },

  // ============================================================ K
  K1: {
    what: "The instance framework: spawn a private subworld shell per group (BotComponentServerFacet_CreateOrJoinDungeon, DungeonCreatedInfo, DungeonPersistentData). The client already knows how to travel to shells — 44 subworlds ship in the PAK and the gamemode table names every mode.",
    how: "Instance manager: per-group shell process/world, travel routing on join, teardown on exit. This single piece unlocks every mode in K.",
    links: [{ label: "GAMEMODES.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/GAMEMODES.md" }],
  },
  K2: {
    what: "Dungeon queues + matchmaking: JoinDungeonQueue, GameModeQueueData, QueueLevelBuckets, QueueReadyThreshold, backfill, role selection phases (GameModeParticipantComponent, 25 server methods).",
    how: "Matchmaking service over the gamemode table's queue parameters; role selection flow; party fill.",
  },
  K3: {
    what: "Amrine Excavation (lvl 25, Windsward) — the first expedition: Simon Grey's dig site, Starstone-era mummies, boss behind the waterfall chest.",
    how: "Expedition shell on K1 with its spawn slices + damage tables; mutatable (K13).",
    links: [{ label: "wiki: Amrine Excavation", href: "https://newworld.fandom.com/wiki/Amrine_Excavation" }],
  },
  K4: {
    what: "Starstone Barrows (lvl 35, Everfall) — ancient mages, jumping/ducking puzzles.",
    how: "Shell on K1 with the everfall dungeon slices.",
  },
  K5: {
    what: "The Depths (lvl 45, Restless Shore) — Captain Thorpe, Master of the Tempest, Corrupted army in the storm-tower ruins.",
    how: "Shell on K1.",
    links: [{ label: "wiki: The Depths", href: "https://newworld.fandom.com/wiki/The_Depths" }],
  },
  K6: {
    what: "Dynasty Shipyard (lvl 55, Ebonscale Reach) — the Empress's warfleet: saboteur/story beats, shipyard bosses.",
    how: "Shell on K1.",
  },
  K7: {
    what: "Lazarus Instrumentality (lvl 60, Reekwater) — the behemoth Chardis; Legatus Fulvius's secret site.",
    how: "Shell on K1.",
  },
  K8: {
    what: "Garden of Genesis (lvl 60, Edengrove) — where the Angry Earth are born, infected by the Blight.",
    how: "Shell on K1.",
  },
  K9: {
    what: "Tempest's Heart (lvl 60, Shattered Mountain) — the MSQ finale vs Isabella (The Heart of the Tempest).",
    how: "Shell on K1; damagetable_isabella_lair_phase1/2 ship the fight phases.",
  },
  K10: {
    what: "Barnacles and Black Powder (lvl 60, Cutlass Keys) — Admiral Blackpowder and crew.",
    how: "Shell on K1.",
  },
  K11: {
    what: "The Ennead (lvl 60, Brimstone Sands) — ancient guardians of the Ennead.",
    how: "Shell on K1.",
  },
  K12: {
    what: "Great Cleave expeditions (lvl 60-65): Empyrean Forge, Savage Divide (Beast Lords in the Elysian Wilds caverns), The Glacial Tarn.",
    how: "Shells on K1.",
  },
  K13: {
    what: "Mutated expeditions: 3 expeditions rotate weekly (reset Tuesday 5:00), M1/M2/M3 difficulty, bronze/silver/gold score ranks, Umbral shard rewards. javelindata_mutationdifficulty (3 rows), mutationrankdata, cursemutations, elementalmutations.",
    how: "Mutation scheduler (C7 cadence) + score system + Umbral currency from the shipped tables.",
    links: [{ label: "wiki: Mutators", href: "https://newworld.fandom.com/wiki/Mutators" }],
  },
  K14: {
    what: "Seasonal trials: nw_trial_dw_dracula, nw_trial_season_02/_04 (+_daichidojo, _deviceroam), TrialSeason01/04 + Q-variants in the gamemode table.",
    how: "Shells on K1 per season schedule (G9).",
  },
  K15: {
    what: "Outpost Rush 20v20: 3 outposts (Astra/Sol/Luna) with upgradable gates, wards, repeater turrets, oil vats, cannons; Baroness Hains kill freezes enemy score; azoth essence offering at the Corrupted Portal. Level 60+, solo or 5-stack. PAK: nw_opr_004_trench, nw_opr_005_vertical.",
    how: "OPR gamemode on K1 with pvpbalance_outpostrush; war-board scoring (orwarboardaggregates); baroness encounter (upyrbaroness damage table).",
    links: [{ label: "wiki: Outpost Rush", href: "https://newworld.fandom.com/wiki/Outpost_Rush" }],
  },
  K16: {
    what: "Arena 3v3 ranked: nw_arena_3v3_04, matchmaking with role selection, pvpbalance_arena, pvp rank ladder (javelindata_pvp_rank).",
    how: "Arena gamemode on K2's matchmaking; ladder from pvp_rank.",
  },
  K17: {
    what: "Battle royale: nw_battleroyale_01/_02 with dedicated loot buckets (lootbuckets_battleroyale) and item tables (itemdefinitions_master_battleroyale). A complete mode shipped in the client.",
    how: "BR gamemode on K1; investigate the mode rules from the gamemode row + item restrictions.",
  },
  K18: {
    what: "Capture the flag: nw_ctf_002_wide, nw_ctf_003_long, pvpbalance_capturetheflag, ctfwarboardaggregates, statuseffects_ctf.",
    how: "CTF gamemode on K1; flag state machine; scoring from the war-board aggregates.",
  },
  K19: {
    what: "World raids: RaidCutlassKeys00, RaidMonarchsBluffs00 (+ Isle of Night, K22) — large-group open-world raid shells with explicit encounter layouts in the slices (raid_monarchbluff encounter1_jester, encounter2_heiressandpg).",
    how: "Raid shells on K1 with the encounter slices; contribution scoring (javelindata_contribution_*).",
  },
  K20: {
    what: "Catacomb subworld (nw_catacomb_00) with its own currencies (crowns, cursed crowns, cursedsilvers, silvers) and shop (javelindata_catacombsshop).",
    how: "Shell on K1; currency + shop from the catacombs tables.",
  },
  K21: {
    what: "Catacombs roguelite mode (Season 10): 1-3 players, tile-based procedural generation (javelindata_dungeonclusters/grammars/rooms/tiles), escalating difficulty per boss, in-run power-ups, time-limited extraction — fail to exit and lose most of the loot, but one player exiting safely saves the run. Rewards: Sterlings (everywhere) and Cursed Crowns (bosses).",
    how: "The best first instanced mode: self-contained loop, generation data ships, rewards shop included. Dungeon grammar generator + extraction timer + power-up system.",
    links: [{ label: "steam: Season 10 release notes", href: "https://store.steampowered.com/news/app/1063730" }],
  },
  K22: {
    what: "Isle of Night 10-player raid (Season 10): the game's first true raid — multi-boss, phases, raid-wide mechanics, set in the fallen kingdom (isleofnight tables ship throughout).",
    how: "Raid shell on K1 after J5 proves 50-player instances work; 10-player roster via I3 raids.",
  },
  K23: {
    what: "Nighthaven zone (Season 10): dark castles, catacombs, vertical structures, exploration-driven (quest tracker deliberately vague). A 15th territory if we follow the final state.",
    how: "Territory definition + POI loading like E2, using the isleofnight/nighthaven assets that ship.",
  },
  K24: {
    what: "Duel as a formal gamemode (a gamemode row + pvpbalance_duels exist — not just a facet condition). 1v1 with its own ruleset; no rewards from duels (documented since the 2021-07-30 beta patch).",
    how: "Duel gamemode on K1; challenge flow; the balance table drives rules.",
  },
  K25: {
    what: "19 named instanced story quests are formal gamemodes: QuestIsabella, QuestLiang, QuestMedusa, QuestNihilo, QuestGawain, QuestDracula, QuestMorgaine, QuestSeraphim, QuestVarlaam, QuestApophis, QuestCaerDun, QuestEmpressZhou, QuestMammoth, QuestMotherwell, QuestMedea, QuestYonas, QuestHeartforge, QuestWolf, QuestAdiana. The nw_ori_* PAK worlds map to these.",
    how: "Each quest = a K1 shell with its objective trees (G2); the gamemode rows already define their rules.",
    links: [{ label: "GAMEMODES.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/research/docs/sim-blueprint/GAMEMODES.md" }],
  },
  K26: {
    what: "Brimstone Sandworm world-boss trial: TrialBrimstoneSandworm gamemode + damagetable_sandworm + babysandworm — multi-phase open-world boss with scorpion adds (scorpion_slinger_sandworm).",
    how: "World-boss encounter on F5's phase system; trial gating like F8.",
  },
  K27: {
    what: "First Light dungeon: DungeonFirstLight01 gamemode row + nw_dungeon_firstlight_01 subworld exist even though First Light left the live map — the content ships.",
    how: "Investigate the gamemode row's parameters; shell on K1 if the mode is complete.",
  },

  // ============================================================ L
  L1: {
    what: "Housing: max 3 houses per player gated by Territory Standing, purchase cost by plot tier, weekly property tax (rate set by the governing company, reduced by standing perks). Unpaid tax freezes decoration changes. PlayerHousingComponentServerFacet (14 methods) + javelindata_housetypes (5 rows).",
    how: "Housing service over C1: plots, ownership, tax ledger; fast-travel recall hooks into E5.",
    links: [{ label: "wiki: Housing", href: "https://newworld.fandom.com/wiki/Housing" }],
  },
  L2: {
    what: "Decoration: HousingDecorationComponent, HousingItemComponent with behaviors (storage, interaction animation). The recognizable tables: javelindata_housingitems + housingitems_mtx (store decorations).",
    how: "Placement service with the item behaviors; storage chests hook into H7.",
  },
  L3: {
    what: "Trophies grant passive bonuses (loot luck, crafting, trade skills); slots per house tier ship in the XP table (HouseTrophySlots: 2 at low levels). DebugReloadBuffItems shows the buff pipeline.",
    how: "Trophy buff application into D5's status-effect engine.",
  },
  L4: {
    what: "Visiting other players' houses: RequestTerritoryResidentData, visitor permissions.",
    how: "Visitor flow with per-house permission lists.",
  },

  // ============================================================ M
  M1: {
    what: "Event coordinator: the game's own event system ships (javelindata_gameevents, worldeventcategories, worldeventrules, schedules) — WorldEventCoordinatorTrait runs it. Our operator surface: a JSON/config list to toggle any event with custom dates.",
    how: "Event scheduler reading the shipped rules with operator overrides (C7); the 'activate Halloween whenever you want' feature.",
  },
  M2: {
    what: "Seasonal events: Nightveil Hallow (Halloween), Winter Convergence, Summer Medleyfaire, Turkulon — each with progression tables (javelindata_progression_halloweenevent/springevent/summerevent), special loot and town decorations.",
    how: "Event content packs loaded on the M1 scheduler with operator-chosen windows.",
    links: [{ label: "wiki: Winter Convergence", href: "https://newworld.fandom.com/wiki/Winter_Convergence" }],
  },
  M3: {
    what: "Game master tools — every GM capability ships as a facet: GiveGoldToPlayer, TeleportPlayerToMeByCharacterId, TeleportToPlayerByCharacterId, ResetClaimOwnership, ResetDailyWarCountForAllPlayers/ForPlayer. Auth-gated operator surface.",
    how: "GM console (web or in-game chat commands) calling the facets with role checks from C5.",
  },
  M4: {
    what: "Leaderboards: LeaderboardComponentClientFacet with entitlement reward ranks; javelindata_leaderboard, leaderboardrewards, leaderboardstats define the tracked stats.",
    how: "Leaderboard service reading the shipped stat definitions; seasonal snapshots.",
  },
  M5: {
    what: "Titles from wars, invasions, achievements and seasons (javelindata_playertitles + categories).",
    how: "Title registry; award hooks in J/G/M systems.",
  },
  M6: {
    what: "Twitch integration: TwitchComponent + TwitchSubarmyNotificationBusHandler; the drops tables ship (javelindata_twitchdrops, twitchtags).",
    how: "Drop-campaign integration for streamers; optional and operator-enabled.",
  },
  M7: {
    what: "Seasonal cadence control: the final live game kept Nighthaven running until shutdown — our M1 scheduler plus the full season tables (chapters/rewards/journeys 1-10) mean any season can run forever with operator-chosen timing.",
    how: "Season runner on G9 with M1 overrides.",
  },

  // ============================================================ N
  N1: {
    what: "This landing page: live stack status, deliverables timeline, the full roadmap, verification matrix, pace charts. Static Astro build served by GitHub Pages; live.json polled from the az.py lifecycle.",
    completion: {
      date: "2026-10-10",
      notes: [
        "Live status connected to the real stack: gateway/world/caddy PIDs checked via tasklist, refreshed every 30 s.",
        "Timeline with horizontal scroll, ranges (7 days/month/all) and a NOW marker.",
      ],
      evidence: ["site/ — this repository's landing"],
    },
  },
  N2: {
    what: "The landing interface is available at / and /en/ with a language switcher, and its navigation and service labels are localized. Roadmap content remains English, so this is partial interface localization rather than a fully bilingual site.",
    progress: {
      date: "2026-10-11",
      notes: [
        "Landing UI chrome, live badge, and service labels use the localization tables and locale props.",
        "Roadmap titles, descriptions, and evidence remain English.",
      ],
      evidence: ["site/src/data/i18n.ts", "site/src/pages/en/index.astro"],
    },
  },
  N3: {
    what: "Account registration + login on the web: accounts mint tokens the gateway accepts (C5).",
    how: "Web auth flows (register/login/session) against C1; token issuance; the gateway validates.",
    dependsNote: "Blocked on C1 + C5.",
  },
  N4: {
    what: "Player panel: characters, inventory, progression, season track — read-only views over the server DB.",
    how: "Web views over C1's schema; no game client needed.",
  },
  N5: {
    what: "Server dashboard: uptime, players online, tick health, datagram rates — the gateway /metrics endpoint already exposes the internals.",
    how: "Status page polling /metrics; historical charts.",
  },
  N6: {
    what: "Cosmetic store (optional): web-side grants using H10's entitlement system.",
    how: "Store catalog + purchase flow that grants client entitlements.",
  },

  // ============================================================ O
  O1: {
    what: "Rust gateway: port the full HTTP surface (login, hub, discovery, certificates) once its behavior is stable. Parity is proven at the wire boundary with shared fixtures — same requests in, same responses out.",
    how: "Workspace scaffolding when A8 lands; fixture corpus from the gateway's traffic captures; per-route parity tests.",
  },
  O2: {
    what: "Rust world runtime: DTLS, authoritative tick, replication codecs. Only ported per behavior once A5 coverage is measurable; Python is removed per behavior, not wholesale.",
    how: "Codec-by-codec porting with the same fixture discipline; the tick loop and AOI last.",
  },
  O3: {
    what: "Load harness: scriptable client instances as load generators — the client ships BotComponent* (dungeon queues, debug scripts) precisely for this.",
    how: "Headless client fleet driven through the bot facets; scenario scripts (login → travel → combat → craft).",
  },
  O4: {
    what: "Measure 2,500 concurrent players: hardware, tick deadlines, bandwidth, CPU, memory, reconnect storms — the full measurement list from ARCHITECTURE.md. No capacity claim without a sustained representative run.",
    how: "O3 fleet at target scale; instrumentation from the gateway /metrics + world tick stats.",
    links: [{ label: "ARCHITECTURE.md", href: "https://github.com/ivan-cavero/Azoth/blob/main/docs/ARCHITECTURE.md" }],
  },
  O5: {
    what: "Deploy story: Caddy serving the site + gateway routing on a single host first; process supervision via az.py exists.",
    how: "Public host setup; TLS; the Pages site stays the marketing face.",
  },
  O6: {
    what: "Scale toward 10,000 players per server — only after O4 proves 2,500 with sustained representative runs.",
    how: "Sharding/load distribution informed by the O4 measurements.",
  },
};

// Gantt deliverable codes -> roadmap item ids (the timeline predates the
// A-O roadmap codes; G0.x = phase-0 items, the rest match directly).
export const ganttCodeToItemId: Record<string, string> = {
  "G0.1": "A1",
  "G0.2": "A1",
  "G0.3": "A1",
  "G0.4": "A1",
  "G0.5": "B1",
  "G0.6": "A2",
  "G0.7": "A1",
  N1: "N1",
  A5: "A5",
  A10: "A10",
  B3: "B3",
  B4: "B4",
  C3: "C3",
  C5: "C5",
  C1: "C1",
  E2: "E2",
  E3: "E3",
  F2: "F2",
  G2: "G2",
  H5: "H5",
  I1: "I1",
  J5: "J5",
  K15: "K15",
  K1: "K1",
  L1: "L1",
  M2: "M2",
  O1: "O1",
  O2: "O2",
  O4: "O4",
};

export default itemDetails;
