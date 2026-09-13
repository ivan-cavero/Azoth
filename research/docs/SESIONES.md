# Sesiones capturadas

Todas en este PC, 2026-09-06, cluster `fra-prod`, mundo `live-1-12-2` / `86ae8332-ed32-420e-985c-61011022847a`, persona Omni `amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c`. Raw (`Game.log.raw`, pcap) **no se versiona**.

## `live_20260906_155045` — personaje existente

- ~291 s, InGame True, player **xNozus**, character `07631b31-78f5-419d-8be8-ddca69eecbc9`
- REP `35.71.153.244:23771` (o `58257` en un log previo del mismo día)
- pcap ~24k paquetes (pktmon frames no-Ethernet; el analizador ya decodifica SNAP/IPv4)
- Escalera completa hasta InGame

## `live_20260906_160330` — create + FTUE + switch

- ~725 s, 1266 líneas de Game.log, 429 eventos, 58195 paquetes
- **Dos entradas en la misma sesión** (identities.json solo guardó la última; la timeline está en fixtures):

| | Nuevo | Viejo |
| --- | --- | --- |
| Nombre | Nozusss | xNozus |
| Character | `abdbd9e8-50f8-4c05-a41b-3f17e9b0407e` | `07631b31-78f5-419d-8be8-ddca69eecbc9` |
| REP | `52.223.18.203:48274` | `52.223.18.203:33000` |
| InGame | 14:07:03 | 14:14:16 |

Mapas: `NW_Frontend_NightHaven` → `FTUE_V2_CC` (creador) → `FTUE_V2` (tutorial SoleSurvivor) → `NewWorld_VitaeEterna` → frontend → otra vez Aeternum con xNozus.

`WaitingForPlayerSpawn` **no era un hang**: es el estado al cambiar de mapa (`InGame → WaitingForPlayerSpawn` ~4 s) y el `from` de STATUS.txt de la última transición (`to: InGame`).

CMS 62 eventos, Vivox 91. RMI vistos: GlobalStorage, Gatherable Interrupted, EventNotification, GridTracking phasing, GameMode queue.

## `live_20260906_173554` — combate / gather / muerte (xNozus)

- ~881 s, 1363 líneas, 635 eventos, **118643** paquetes, InGame True, `current_state InGame`
- Mismo toon `xNozus` / `07631b31-…`, mismo mundo, REP nuevo `35.71.153.244:38811`
- Un solo `WaitingForPlayerSpawn → InGame` al entrar (15:37:29). **Morir y respawnear no cambia GameConnection** (sigue InGame).
- Combate (log): `CameraLockComponentClientFacet` ×6 (lock de target, 15:39–15:40); `SlayerScriptComponent` CRC de entidad desconocida (15:44:46, skills).
- Gather: `GatheringInterrupted` ×9, **7 nodos** distintos (15:44:53–15:48:59). Completar gather no se loguea; solo el interrupt cuando el nodo desaparece.
- Inventario/equip: **cero líneas**. Va por DTLS (pcap ~69k records / 20 MB al REP).
- Otros jugadores: `slices/remoteplayer.dynamicslice` (AOI). `SocialComponentClientFacet::RequestGetPlayer` con `characterId` vacío (15:43:14) — UI de grupo/expedición sin gente.
- Dungeon: no hay `LevelInfoChanged` a `nw_dungeon_*`, no hay segundo REP. `OnLeftQueueForGameModeMsg` es basura de spawn, no una cola real.
- Muerte: avisos `entity was destroyed` + física `DetectableComponent` rigid body; **no hay string Death/Respawn**.
- Vivox 406 eventos (grids 3D al andar). Ruido, no protocolo de combate.

## Lo que el kit aún no ve

Bodies HTTPS (TLS official) y plaintext DTLS. Combate/inventario/muerte **viven en DTLS**, no en Game.log. El mock los verá cuando el cliente hable con Azoth. Dungeon sigue pendiente (hace falta grupo o una instancia solo).
