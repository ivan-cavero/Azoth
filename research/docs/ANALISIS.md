# New World Private Server — Análisis técnico

Este documento vive en el submódulo **research** (Azoth). Contrato: `../../docs/ARQUITECTURA.md`. Índice: [INDEX.md](INDEX.md).

Fecha: 2026-09-06  
Cliente analizado: instalación Steam en `C:\Program Files (x86)\Steam\steamapps\common\New World`  
Build: `[RETAIL].Javelin.1.400.6031.6004151` (compilado 21 Mar 2026)  
Steam App ID: `1063730`

Este documento es el mapa del terreno. No es un servidor todavía. Resume cómo está hecho el juego, cómo entra un jugador, qué hay que sustituir para un backend propio, y un plan por fases.

---

## 0. Contexto

Amazon delistó New World: Aeternum el 15 de enero de 2026. Los servidores oficiales cierran el **31 de enero de 2027**. No hay contenido nuevo; solo mantenimiento. Quedan ~5 meses de tráfico vivo. Ese tráfico es irrecuperable el día que apaguen.

Hoy, en esta máquina, el cliente **sí entra** a los servidores oficiales. `Game.log` de las 14:41–14:47 (hora local) muestra login Steam → Omni → cola → REP → spawn → `InGame`.

| Campo | Valor de la sesión de hoy |
| --- | --- |
| Personaje | `xNozus` |
| Character ID | `07631b31-78f5-419d-8be8-ddca69eecbc9` |
| Persona Omni | `amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c` |
| Cluster | `fra-prod` (EU Central) |
| Mundo | `live-1-12-2` / `86ae8332-ed32-420e-985c-61011022847a` |
| REP | `35.71.153.244:58257` (rango AWS Global Accelerator) |
| Tipo de cuenta AGS | `Shadow` |
| Ownership | `permanent` |

Eso cambia el plan: no hace falta “adivinar” el login. Hay que **capturar** esta sesión completa (HTTPS + UDP/DTLS) mientras Amazon sigue encendido, y al mismo tiempo construir el mock que sustituye esos endpoints.

---

## 1. Qué es realmente el cliente

### Motor

- **Amazon Lumberyard 1.12.0.1** (fork de CryEngine), no O3DE.
- DLL de juego: `Javelin` (`bootstrap.cfg`: `sys_dll_game = Javelin`).
- Renderer: Direct3D 12 (`RenderD3D12`).
- UI: gem **LyShine**.
- Combate: **Slayer Script** (C++ nativo, hot-loadable).
- Datos: gem **NewWorldDataSheet**.
- Terreno/mundo: **Coatlicue** (`CGame::InitCoatlicueTerrain`, PAK `CoatlicueStrm.pak`).
- Voz: Vivox.
- Anti-cheat: Easy Anti-Cheat EOS (`productid b0855340e2ed491096135339f6fc94b7`).
- Plataforma: Steam (`steam_api64.dll`).

Los “módulos” de `assets/Config/Game.xml` **no existen como DLLs sueltas**. Están linkados dentro de `Bin64/NewWorld.exe` (~179 MB, ~133 MB de `.text`). El exe es un monolito x64 con ASLR + DEP.

Módulos internos relevantes:

- `EngineClient`, `EngineClientServerShared`
- `JavelinComponentsClient`, `JavelinComponentsCharacterClient`, `JavelinComponentsAIClient`
- `Gem.LyShine`, `Gem.SlayerScriptClient`, `Gem.NewWorldDataSheet`

`typeindex.json` (generado 2025-10-22) lista **7052** UUIDs de tipos AZ. Es el registro de reflexión de Lumberyard: componentes, slices, assets.

### Layout de la instalación

```
New World/
  NewWorldLauncher.exe          # launcher + EAC bootstrap
  Bin64/NewWorld.exe            # cliente real
  EasyAntiCheat/                # EAC EOS
  assets/
    Config/Game.xml
    Engine.pak                  # cvars, engine assets
    GameData.pak                # materiales, VFX (~648 MB, ZIP)
    DataStrm*.pak               # streaming: meshes CGF, UI LyShine, anims
    SharedDataStrm*.pak         # dynamicslices, animaciones CAF, datasheets
    CoatlicueStrm.pak           # terreno
    VegetationStrm*.pak
    levels/newworld_vitaeeterna/level.pak   # mundo abierto
    levels/nw_dungeon_*         # expediciones
    levels/nw_raid_* / nw_trial_* / nw_opr_* / nw_arena_*
    levels/frontend* / nw_frontend_nighthaven
  bootstrap.cfg
  engine.json                   # LumberyardVersion 1.12.0.1
```

Los PAK son **ZIP** (`PK\x03\x04`). Se pueden listar y extraer con cualquier herramienta ZIP. Eso es la vía de contenido custom, no parchear el exe.

Datos de usuario:

- Logs: `%LOCALAPPDATA%\AGS\New World\Game.log` (muy verboso, oro para RE)
- Settings: `%APPDATA%\AGS\New World\`

### Autoridad

El juego es **server-authoritative**. El cliente manda inputs; el servidor simula física, reglas y AI; el cliente pinta el resultado. Un private server no puede ser un “relay tonto”: tiene que simular.

Arquitectura oficial de un mundo (AWS re:Invent 2021, Werner Vogels):

- 4 **REP** (Remote Entry Points) públicos — routers de conexión
- 7 **Hubs** EC2, cada uno dueño de celdas del mapa (grids no contiguos)
- Instance pool para expediciones/arenas (sesiones)
- Hubs “stateless” con estado en DynamoDB (~800k writes / 30s a escala de lanzamiento)
- Microservicios Lambda/API Gateway para login, personajes, trading, compañías
- Tope de diseño: ~2500 jugadores + ~7000 AI + cientos de miles de objetos por mundo

Eso es el techo de Amazon. Un private server arranca con **un proceso de simulación + un gateway HTTP**. Escalar a grids/hubs viene después, cuando el protocolo y la simulación funcionen.

---

## 2. El login no se “salta”: se sustituye

El cliente no tiene un modo offline. El arranque **siempre** habla con Amazon. El private server no crackea Steam ni Omni: **se hace pasar por los endpoints de Amazon** y, al final, le entrega al cliente la IP:puerto de *nuestro* REP.

### 2.1 Mapa de servicios (vivos hoy)

El cliente empieza pidiendo:

```
GET https://d2c74t4zimux3r.cloudfront.net/STEAM_APP_ID.1063730.json
```

Ese JSON (guardado en `_re/channel_config.json`) es el directorio de regiones. Lo tenemos entero. Por cada cluster:

| Cluster | Región | Auth stack | Login gateway | Javelin Gateway CF |
| --- | --- | --- | --- | --- |
| `fra-prod` | EU Central | `2mfrik7h83.execute-api.us-east-1.amazonaws.com` | `u433g9r00c.execute-api.eu-central-1.amazonaws.com` | `d1w0bfy6smo4d1.cloudfront.net` |
| `gru-prod` | SA East | `kqqt5twsi7.execute-api.us-east-1.amazonaws.com` | `j4n6whncmi.execute-api.sa-east-1.amazonaws.com` | `d1cjlmzk0xrm0z.cloudfront.net` |
| `iad-prod` | US East | `eudbjx6mig.execute-api.us-east-1.amazonaws.com` | `0prplal5u1.execute-api.us-east-1.amazonaws.com` | `d2oeuvxi3kfsrw.cloudfront.net` |
| `pdx-prod` | US West | `q8hqllbg6k.execute-api.us-east-1.amazonaws.com` | `v7irlu1nrl.execute-api.us-west-2.amazonaws.com` | `d3bj4csovi1fe8.cloudfront.net` |
| `syd-prod` | AP Southeast | `hhf8nn71vb.execute-api.us-east-1.amazonaws.com` | `ep1m9qoir8.execute-api.ap-southeast-2.amazonaws.com` | `de4mfzk9wkelz.cloudfront.net` |

Metadata Omni:

```json
"OMNI.STEAM_APP_ID.1063730": {
  "omniTokenUrl": "https://tokenservice.amazongames.com",
  "nwTokenUrl": "https://prod.newworld.com/",
  "omniStage": "prod",
  "omniGameAlias": "new-world"
}
```

Otros hosts que el log de hoy tocó:

- `ags-javelin-remote-config` (S3, configs por ProductId / RegionId / CognitoId / WorldId)
- `d1hkbwzm1bktgo.cloudfront.net` (CMS: news, marketing tiles, MOTD worlds)
- `client.content-service.amazongames.com` (imágenes CMS)
- `client.entitlementservice.amazongames.com` (ownership)
- Vivox `nwxp0euc1.vivox.com` (voz 3D, se puede stubear o ignorar al principio)

### 2.2 Secuencia real (de *este* Game.log, 2026-09-06)

```
t+0      NewWorld.exe [AZ_RETAIL_CONFIG]  FileVersion 1.400.6031.6004151
t+65s    Channel service URI
         Cluster fra-prod elegido
t+124s   AuthManager → SteamAuth → OmniSDK 1.6
         Steam session ticket (handle 2)
         Omni CreateSession OK → persona amzn1.developerPersonaId.…
         GET/POST …/prod/credentials/omni
         STS-shaped AWS creds (gateway + persona), refresh ~55 min
         CGame::OnCampfireLoginComplete  ownership=permanent
t+152s   StackConfig S3 layers (public + publicGameplay)
         GameConnection ConfigureLogin MODE_GATEWAY
t+226s   CMS news/MOTD
t+226s   ActorContainerConnect
         playerName = xNozus
         Disconnected → QueryGameUpdateCheck → QueueGameLogin → WaitingForQueuedLogin
         character 07631b31-…
         login ticket 86ae8332-…_7978b8a9-…
         World live-1-12-2
         REP Address 35.71.153.244:58257
t+231s   remote config WorldId
         ObtainREPRequirements → StartREPConnection → WaitingForREPConnection
t+231.3s REP socket connection established
t+231.4s registration response from REP
         Server version [RETAIL].Javelin.1.365.6031.6017213
         WaitingForActorGameConnection
t+231.5s actor game connection succeeds
         WaitingForSpawnPoint → spawn point found → WaitingForPlayerSpawn
         LevelInfoChanged
         load NewWorld_VitaeEterna  (unload NW_Frontend_NightHaven)
t+233.6s player spawn succeeds, in game
         state InGame
         JavelinGame::OnConnectionSucceed
         Vivox login
```

Máquina de estados del cliente (nombres del propio log):

```
Disconnected
  → QueryGameUpdateCheck
  → QueueGameLogin
  → WaitingForQueuedLogin          # HTTP login/queue/v2, ticket + RepAddress
  → QueryForRemoteConfigClass
  → WaitingForRemoteConfigClass
  → ObtainREPRequirements
  → StartREPConnection
  → WaitingForREPConnection        # DTLS + V3 Registration
  → WaitingForActorGameConnection
  → WaitingForSpawnPoint
  → WaitingForPlayerSpawn          # LevelInfoChanged, load map
  → InGame
```

Eso es el contrato. Un backend propio tiene que empujar al cliente por esos estados, en ese orden, con los JSON y los paquetes que cada transición espera.

### 2.3 Cómo redirigir el cliente a nuestro server

Hay **dos capas**, y hay que tener las dos.

**Capa A — HTTPS (auth, personajes, cola, config)**

1. Hosts file (o DNS local) apunta los hostnames de Amazon a `127.0.0.1`.
2. Un HTTPS server en `:443` con un CA local instalado en Windows.
3. Ese server responde:
   - Channel config (podemos devolver el JSON real, o uno que liste un solo cluster nuestro)
   - `tokenservice.amazongames.com` (Omni tokens)
   - `/prod/credentials/omni` (credenciales con forma de STS: AccessKeyId 20 chars `ASIA…`, secret 40, sessionToken, expiration RFC3339)
   - entitlements
   - `/prod/game/getlogininfo/...` (mundos + personajes)
   - create/validate character
   - `/prod/game/login/queue/v2/...` con `RepAddress: <nuestra_ip>:<nuestro_puerto>`
   - S3 remote-config `{}` o overrides mínimos
   - CMS vacío con **ETag siempre presente** (sin ETag el cliente crashea)

El cliente **sigue pidiendo un Steam ticket**. Steam tiene que estar abierto. No hace falta que Amazon valide ese ticket: nuestro mock no habla con Amazon. El cliente usa el ticket como input de Omni; Omni embebido habla con `tokenservice.amazongames.com`, que ya es nuestro.

Cuenta `Shadow` vs `Full`: hoy Omni devolvió `ags account type: Shadow` y un link code `REYSKJDE`. El mock debe devolver `type: "full"` para no empujar al usuario al flujo de vincular cuenta Amazon.

**Capa B — REP (el juego de verdad)**

El ticket de cola contiene `RepAddress`. El cliente abre un socket a esa dirección. En la sesión de hoy fue `35.71.153.244:58257`. El puerto **cambia por mundo/sesión** (no es fijo 24083). El mock elige el puerto.

Sobre ese socket:

1. DTLS 1.2, cipher `ECDHE-RSA-AES256-GCM-SHA384`
2. El cliente trae un certificado embebido / pin. Un cert self-signed “cualquiera” falla con `unknown ca` / `@mm_csdkerr_transport_security_error`.
3. Tras DTLS: handshake Carrier (GridMate) `SM_CONNECT_REQUEST` → `SM_CONNECT_ACK`
4. Luego **V3 Registration** (login ticket + character/world ids)
5. Luego réplicas: `Cmd_Greetings`, `Cmd_NewProxy` del actor, `LevelInfoChanged`, spawn

Hasta que esas cinco cosas ocurran en orden, el cliente se queda en `WaitingForREPConnection` y a los ~30 s tira la sesión.

### 2.4 EAC

El launcher (`NewWorldLauncher.exe`) instala y arranca Easy Anti-Cheat EOS. El binario live de Steam **no se deja instrumentar** (Frida, DLL inject, memory patch) con EAC activo.

Implicaciones:

- Un private server que pretenda el cliente **sin parchear el disco** tiene que hablar el protocolo tal cual. Eso es lo correcto.
- Capturas de tráfico: mitm HTTPS (hosts + CA) no toca el proceso. Captura UDP/DTLS en el NIC (Wireshark) tampoco. Eso sí se puede hacer **hoy**, con EAC puesto, jugando en oficial.
- Parches en memoria / Frida: solo con un build lanzado saltándose el launcher, y EAC se quejará o no arrancará. No es el camino del MVP.

No hay que “saltar EAC” para un emulador. Hay que **hablarle al cliente en su idioma**.

### 2.5 Qué no hacer

- No atacar los API Gateway / REP de Amazon.
- No reenviar tickets Steam a Amazon desde un server pirateado.
- No publicar un crack del exe.
- El objetivo es un **emulador** al que el cliente que ya posees se conecta, igual que TrinityCore con WoW.

---

## 3. Protocolo de juego (Javelin)

Javelin es un fork/rebrand de **Lumberyard GridMate**, no de O3DE AzNetworking. El wire format se puede leer en el código MIT de GridMate (`aws/lumberyard`, `Code/Framework/GridMate/`).

Capas, de abajo arriba:

```
UDP
  DTLS 1.2  (ECDHE-RSA-AES256-GCM-SHA384)
    Carrier datagram
      [u16 BE seq] [message records…]
      opcional: hint de compresión (0x00 / LZ4)
      4 canales; canal 3 = sistema (connect, acks, clock)
    Mensajes de aplicación
      Handshake / V3 Registration
      Replica stream:
        Cmd_Greetings, Cmd_NewProxy, Cmd_DestroyProxy,
        Cmd_NewOwner, Cmd_Heartbeat, updates por ReplicaId
      RPCs en chunks (*ComponentClientFacet / *Messages)
```

Detalles que importan para implementar:

- Endianness **big-endian**.
- Header de datagrama: 2 bytes de sequence.
- Cada mensaje: flags (reliable, chunks, channel, sequential ids) + payload.
- Acks **no** van en cada paquete: van como `SM_CT_ACKS` en canal 3.
- Tras DTLS, el Carrier manda `SM_CONNECT_REQUEST` (unreliable, retry backoff). El server responde `SM_CONNECT_ACK` (reliable). Ahí es donde New World mete el login ticket.
- Replicas: `ReplicaChunkClassId = CRC32(nombre)`. New World parte cada componente en `*Facet` (estado) + `*Messages` (RPC) × Client/Server.
- Tamaños VLQ (no protobuf varint): prefijo de 1s cuenta bytes extra.
- Bools empaquetados a **bit**, no a byte.
- Interés espacial (AOI) es custom: el mundo es seamless y los hubs oficiales se parten el mapa en grids.

El cliente, en el spawn de hoy, ya disparó RMIs reales:

- `EventNotificationComponentClientFacet_SyncNotifications`
- `GridTrackingComponentClientFacet_UpdatePhasing`
- `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`
- `GameModeParticipantComponentClientFacet_OnLeftQueueForGameModeMsg`

Eso es el catálogo vivo de mensajes. `Game.log` los nombra. Una captura DTLS descifrada (o un hook posterior) los aterriza en bytes.

MVP de spawn, estimado desde la máquina de estados:

1. V3 RegistrationResponse aceptada
2. `PlayerManagerSelfIdentification` (avanza 10→11)
3. `LevelInfoChanged` (carga `NewWorld_VitaeEterna`)
4. `Cmd_NewProxy` del actor del jugador (avanza 13→14 `InGame`)

Con eso el cliente entra al mundo. Combate, AI, inventario, crafting, war, trading: todo eso son cientos de chunks más, implementados **después**, uno a uno, contra capturas.

---

## 4. Contenido: cómo está el mundo en disco

| Qué | Dónde | Formato |
| --- | --- | --- |
| Mundo abierto | `levels/newworld_vitaeeterna/level.pak` | Cry level (xml + terrain.dat + .bai) |
| Expediciones | `levels/nw_dungeon_*` | igual |
| Raids / trials / OPR / arenas | `levels/nw_raid_*`, `nw_trial_*`, `nw_opr_*`, `nw_arena_*` | igual |
| Frontend / menú | `nw_frontend_nighthaven`, `frontendv2*` | igual |
| Terreno stream | `CoatlicueStrm.pak` + `coatgen/` en SharedDataStrm | dynamicslices por chunk espacial |
| Prefabs/entidades | `*.dynamicslice` (~40k+ en SharedDataStrm, ~57k en part1) | Lumberyard slices |
| UI | `lyshineui/` en DataStrm | dds + uicanvas |
| Meshes | `.cgf` / `.cgfheap` en DataStrm | Cry geometry |
| Anims | `.caf` | Cry animation |
| Tablas de quest/NPC | `sharedassets/springboardentitites/datatables/*.datasheet` | binario DataSheet |
| Materiales/VFX | GameData.pak | mtl, xml particles |

Coatlicue parte el mapa en chunks (`props_32x32`, `128x128`, `256x256`, `1024x1024`). El cliente **ya tiene el mundo**. El servidor no tiene que “enviar el mapa”: tiene que decir “carga `NewWorld_VitaeEterna`” (`LevelInfoChanged`) y luego replicar actores.

Añadir zonas/clases **no** es un JSON en el server. Es:

1. Extraer PAK → editar / crear slices, datasheets, level.pak
2. Repack PAK (el cliente lee `PaksList.lst`)
3. Enseñar al servidor las nuevas entity defs (los mismos IDs/CRC que el cliente)
4. Spawnear esas entidades por réplica (`Cmd_NewProxy`)

Sin el editor de Lumberyard (no es público para este juego) el contenido nuevo se hace a ciegas: clonar un slice existente, cambiar IDs, datasheets. Es viable para items/stats/quests. Una zona nueva con terreno propio es un proyecto de arte aparte (Coatlicue).

Las “clases” de New World no existen como en WoW: hay weapons + skill trees. Añadir un arma nueva = datasheet de weapon + abilities Slayer Script + anims + UI icons + réplica del componente de combate. El cuello de botella es el **script de combate en el server**, no el icono.

---

## 5. Backend objetivo (moderno, sin lag, escalable)

No copiar DynamoDB + 7 hubs el día 1. Copiar el **contrato** con el cliente, y una simulación que no mienta.

### 5.1 Procesos

```
                    ┌─────────────────────────────┐
   cliente  HTTPS   │  gateway (auth/login/CMS)   │  :443
   ───────────────► │  Rust axum / Go             │
                    │  Postgres (cuentas, chars)  │
                    └────────────┬────────────────┘
                                 │ ticket + RepAddress
                                 ▼
                    ┌─────────────────────────────┐
   cliente  DTLS    │  REP / world sim            │  UDP
   ───────────────► │  Rust o C++                 │
                    │  tick 20–30 Hz              │
                    │  spatial hash / grid        │
                    │  interest management        │
                    └────────────┬────────────────┘
                                 │
                    ┌────────────┴────────────────┐
                    │ Redis (presencia, queues)   │
                    │ Postgres (persistencia)     │
                    │ instance workers (dungeons) │
                    └─────────────────────────────┘
```

### 5.2 Por qué este split

- El 90% de los endpoints de login son JSON HTTP. Fáciles, testables, no son el hot path.
- El lag se juega en el **REP**: DTLS, acks, AOI, física, combate. Eso tiene que ser un binario nativo, zero-copy, sin GC en el tick.
- Un mundo privado de 50–200 jugadores cabe en **un solo proceso** de simulación si el AOI está bien (solo replicar lo cercano).
- Expediciones: el cliente ya carga otro `level.pak`. El server spawnea un worker, mueve al jugador a otro RepAddress o a un “instance id” interno. Amazon usaba un pool de EC2; nosotros un pool de procesos.

### 5.3 Stack recomendado

| Pieza | Elección | Motivo |
| --- | --- | --- |
| Gateway HTTP | Rust (`axum` + `rustls`) | TLS propio, schemas JSON estrictos, un binario |
| REP / sim | Rust (tokio + rustls DTLS o openssl) **o** C++ | Tick determinista, sin GC |
| Persistencia | PostgreSQL | personajes, inventario, world state lento |
| Hot state | Redis o en memoria + snapshot | presencia, locks de gathering |
| Capturas | Wireshark + mitmproxy + logger propio | mientras Amazon viva |
| Tests | fixtures de paquetes capturados | cada mensaje se round-trippea |

Python sirve para el **mock de auth** y para prototipar codecs. No sirve como simulación de 200 jugadores. El gateway de auth se puede quedar en Python al principio y reescribirse cuando el esquema esté cerrado.

### 5.4 Simulación (para que no haya lag)

Reglas, no magia:

- **Server authority** de verdad: el cliente manda input (WASD, skills), el server integra y replica transform.
- Tick fijo (p.ej. 30 Hz). Inputs en cola con timestamp. No procesar “el último paquete gana” sin rewind corto.
- AOI por celda (el mapa oficial ya es un grid). Un jugador solo recibe réplicas de su celda + vecinas.
- Unreliable para movimiento; reliable para inventario, quests, combat events.
- No replicar 100k props estáticos: el cliente ya los tiene en Coatlicue. Solo actores vivos (players, AI, gatherables con estado, projectiles).
- Physics: no hace falta PhysX completo el día 1. Capsule + navmesh extraída del level + raycasts de combate.
- Persistencia async: el tick nunca espera a Postgres. Write-behind.

Cuando un solo proceso no baste: partir el mapa en N workers (como los 7 hubs), con handoff de actor al cruzar frontera. Eso es fase 4, no fase 1.

---

## 6. Plan por fases

### Fase 0 — Captura (ahora, mientras Amazon vive)

Cada día sin captura es protocolo que se pierde en enero 2027.

1. Dejar `Game.log` rotando; copiar cada sesión a `sessions/`.
2. Wireshark en la NIC: UDP hacia `35.71.0.0/16` (Global Accelerator) durante un login completo + 5 minutos in-world (andar, atacar un dummy, abrir inventario, cambiar arma).
3. Mitm HTTPS del channel/gateway **solo contra nuestro mock**, no contra Amazon, cuando empecemos a redirigir. Mientras juguemos en oficial, no interceptar: el pin/CA de Amazon es el suyo.
4. Guardar: ticket de cola, RepAddress, version strings, secuencia de estados.

Sin esta fase, el resto es arqueología a ciegas.

### Fase 1 — Auth mock (1–2 semanas de trabajo real)

Un HTTPS server local que:

- Sirve channel config
- Completa Omni + credentials
- Lista un mundo `Valhalla` ACTIVE / OpenWorld
- Lista o crea un personaje
- Devuelve login ticket con `RepAddress: 127.0.0.1:<port>`

Criterio de hecho: el cliente llega a `StartREPConnection` apuntando a localhost. Se queda ahí (no hay REP todavía) pero **ya no habla con Amazon**.

### Fase 2 — REP stub (la parte dura)

DTLS + Carrier + V3 + SelfIdent + LevelInfoChanged + NewProxy del player.

Criterio de hecho: `Game.log` dice `player spawn succeeds, in game` y el cliente carga `NewWorld_VitaeEterna`. El personaje puede estar congelado. Da igual. Eso es el MVP de todo emulador de MMO.

### Fase 3 — Un jugador se mueve

Input → transform replicado. Cámara, animación idle/walk. Sin combate.

### Fase 4 — Persistencia + N jugadores

Cuentas, personajes, inventario básico, ver a otros jugadores (AOI).

### Fase 5 — Sistemas de juego, uno a uno

Gathering, crafting, combat (Slayer), AI, quests, war, trading, dungeons. Cada uno es un proyecto. Se prioriza con capturas.

### Fase 6 — Contenido custom

Datasheets + slices + (más adelante) niveles nuevos. Solo cuando el server ya entiende entity defs vanilla.

---

## 7. Realidad sobre “hacerlo desde cero”

Existe trabajo comunitario. No es un secreto y no conviene fingir que el mapa está vacío:

- **OpenWorld / first-light** (Discord `discord.gg/5XzwZHFv`, repo histórico `nw-private-server/first-light`). Auth HTTPS mockeado. DTLS + V3 parcialmente. Bloqueados en el avance post-V3 (`WaitingForREPConnection` retry). El repo GitHub está marcado defunct; el desarrollo se movió al Discord.
- **Aeternum Legacy** (otro Discord, claims de character-select contra backend propio, sin parche de binario). Hay que tratarlo con escepticismo hasta ver proof.

Usar su documentación de protocolo (GridMate, schemas JSON, máquina de estados) no es “copiar un server”: es no repetir 8 meses de Ghidra. El server, la simulación y el contenido sí se construyen aquí.

Este repo debe ser **nuestro** backend: gateway + REP + persistencia + capturas de *esta* máquina. Las specs de wire format se verifican contra el `NewWorld.exe` y el `Game.log` locales.

---

## 8. Siguiente paso concreto

El análisis ya alcanzó el techo de “leer archivos y logs”. El siguiente trabajo útil es de ingeniería, en este orden:

1. **Pipeline de captura** en esta máquina (script que copia Game.log + pcap UDP de una sesión).
2. **Gateway HTTP** (Fase 1) con los schemas que el log ya delató, testeado con el cliente real.
3. Solo entonces DTLS/REP.

Herramientas de RE para más adelante (cuando el mock esté y el cliente apunte a localhost): Ghidra sobre `NewWorld.exe`, búsqueda de `"ECDHE-RSA-AES256-GCM-SHA384"`, `WaitingForREPConnection`, `InstallRegistrationHook`. El exe tiene 133 MB de código; no se decompila “entero”, se entra por strings del log.

---

## 9. Inventario local (hechos)

- `NewWorld.exe` 179 204 176 bytes, PE32+, timestamp UTC 2026-03-21 00:07:07
- EAC EOS product `b0855340e2ed491096135339f6fc94b7`
- Channel config live descargado: `_re/channel_config.json` (5404 bytes)
- `Game.log` de hoy: login oficial completo hasta InGame
- PAKs = ZIP; GameData 18 034 files; DataStrm 19 331; SharedDataStrm 65 491; SharedDataStrm-part1 65 199
- 7052 type UUIDs en `typeindex.json`
- Mapa principal `NewWorld_VitaeEterna`; frontend actual `NW_Frontend_NightHaven`
