# Azoth — estado (2026-09-11 mañana)

## 🏆 HITO: LOGIN OMNI ACEPTADO (result 0) → pantalla ELEGIR PERSONAJE

Después de semanas atascados en `CreateSession result: 203`, se rompió el
bloqueo. Cadena completa verificada en vivo:

```text
Stub Steam v3 → AuthManager → OmniSDK 1.6.7
  → POST /games/new-world/tokens        → 200 mock → CreateSession result 0
  → "Get persona id result: OK" / "account type: Shadow"
  → GET  /prod/credentials/omni         → 200 mock → credenciales AWS OK
  → "CGame::OnCampfireLoginComplete, login successful. ownership=permanent"
  → título "PULSA CUALQUIER BOTÓN" → Enter → PANEL "ELEGIR PERSONAJE"
  → (nuevo frontera) reintenta GET /prod/game/getlogininfo/jwt/omni cada 10s
```

## La clave del 203 (leer antes de tocar nada)

**203 NO es un código semántico: es `0xcb` = "JSON parse error" del SDK.**
Todos los shapes "razonables" (result/id, JWTs sueltos, STS-shaped…) daban 203
porque al SDK le faltaba una clave o tenía otro tipo. Cómo se sacó (método
para futuras sesiones):

1. **Oráculo**: el gateway sirve lo que haya en
   `apps/gateway/mock_discovery/tokens.json` (override sin reiniciar). El juego
   reintenta y loguea el result en Game.log → bucle de feedback de segundos.
2. **Errores con nombre**: `{"errorCode":"INVALID_PLATFORM_AUTH"}` → result 303,
   `INVALID_AGS_AUTH_TOKEN` → 302, `INVALID_GAME` → 102, `AGS_IDENTITY_REQUIRED`
   → 203, `INVALID_AGS_IDENTITY` → 331. Con la tabla se identificó el 203.
3. **RE del parser** (capstone sobre NewWorld.exe, offsets de fichero):
   - `ags_fed_acc_token.cpp` (parser de la respuesta de tokens), claves en
     orden: `region`, `limitedUseToken`, `platformAccount`, `account`,
     `isNewAccount`, `conflictingAccount`, `accessToken`, `expiresIn`,
     `fallbackToken`. Falta clave/typo mal → `0xcb` (203).
   - `platform_persona_account.cpp`: `{ageGroup:int, identityType:str,
     platform:str?, identityId:str, personaId:str}`.
   - `ags_persona_account.cpp`: `{type:"shadow"|"full", ageGroup:int,
     identityId:str, personaId:str}`; sin `account` → 307.
   - `identityType` string→enum con tabla hash (FNV) interna: "ags",
     "intermediate", "shadow", plataformas consola. En la respuesta a Steam el
     `account.type` válido que se aceptó fue **"shadow"**.
   - JWTs: `jwt_reader` exige 2 puntos; `alg:"none"` con firma vacía vale
     (validación local). `iat`/`exp` en **milisegundos** ("AGS Auth token iat
     %lldms").
4. Respuesta final servida (ahora es el default en `routes/omni.py`):
   `accessToken/expiresIn/fallbackToken/limitedUseToken/isNewAccount/region/
   platformAccount{ageGroup,identityType:"steam",platform:"steam",
   identityId:<steamid64>,personaId}/account{type:"shadow",ageGroup,
   identityId,personaId}` — persona = `amzn1.developerPersonaId.fc906c07-…`.

## El crash tras credentials (y su fix)

Con credenciales STS-shaped (`AccessKeyId`, `Expiration` ISO) el juego hizo
**crash** (`0xc0000005` en `+0x7465476`) tras "Calling Http API". RE: el parser
de credenciales busca claves **camelCase** con un lookup que devuelve NULL si
falta la clave y el caller desreferencia:
`accessKeyId`, `secretAccessKey`, `sessionToken`, `expiration` (**double con
época unix, no ISO**), `region`. `routes/credentials.py` ya sirve exactamente
eso (más copias planas legacy para herramientas) → ya no crashea y el login
completa.

## Frontera ACTUAL (siguiente sesión)

### Sesión 2026-09-11 (tarde): worlds/list + veto del override de config

**Hallazgo 1 — la ruta que faltaba para la lista de mundos.**
Tabla de paths del exe en `.rdata` @`0x84ff388`. Operaciones REST del
`JavelinGatewayService` (nombre de operación → path):

| Operación | Path |
| --- | --- |
| `GetLoginInfo` | `/prod/game/getlogininfo/jwt/omni` |
| **`ListWorlds`** | **`/prod/game/worlds/list/jwt/omni`** ← faltaba y el cliente la pedía |
| `PostGameWorldsWorldIdCharacters` | `/prod/game/worlds/%s/characters/jwt/omni` |
| `PatchCharacter` | `/prod/game/characters/%s/jwt/omni` |
| `QueueLogin` / `RefreshQueuedLogin` | `/prod/game/login/queue/v2/jwt/omni` (+ `/%s`) |
| `ValidateCharacter` | `/prod/game/worlds/%s/characters/validator/jwt/omni` |
| `LinkIdentity` / `UnlinkIdentity` | `/prod/game/linkIdentity`, `/game/unlinkIdentity` |

`ListWorlds` llena `Game.GetWorldList` (la lista visible); `getlogininfo`
(`GetLoginInfo` → `LoginInfoList`) es otra cosa. Ya implementado en
`routes/worlds_list.py` desde el registro. El cliente ya la consume (3 hits)
pero la lista sigue sin pintarse: falta el valor exacto del enum
`WorldType`/`WorldStatus` (aws-sdk ignora claves que no matchean, sin error).

**Hallazgo 2 — `ClientOverride.json` NO sirve en build de PAK (spike cerrado).**
El juego busca `@assets@/ClientOverride.json` y loguea `Client config override
file not found`. Se probó el archivo en 5 ubicaciones (install root, install
`Assets`, game root, game `Assets`, `Bin64`) + `stack.override.json` en ambos
roots, con formato anidado y plano-con-puntos: **en ninguna lo lee**. La config
vive dentro de los PAK y se resuelve por el VFS interno, no por el sistema de
archivos. Conclusión: redirigir endpoints por archivo suelto requiere repackear
un PAK. Los archivos de prueba se borraron (install limpio).

**Hallazgo 3 — la palanca de redirección es el CHANNEL (nuestro).**
El log ecoa la config activa y esos valores salen del channel que servimos:

```text
ClusterId          <- clave del channel ("azoth-1")
Gateway Signing Host <- channel.publicApis[loginGateway].apiEndpoint
Gateway Address      <- channel.publicApis[JavelinGatewayService-CF].apiEndpoint
HTTP Gateway Address <- "https://" + (esa) + "/prod"   <- esquema HARDCODEADO
Gateway Mode         <- "gateway"
```

O sea: para mover el gateway se edita NUESTRO channel JSON; pero el esquema es
`https://` fijo ⇒ **hosts + Caddy :443 se quedan**. Esto cierra la pregunta
abierta de ARQUITECTURA.md (“URL parcheada vs hosts+CA”): hosts+CA, sin parche.

**Superficie de config completa** (solo alcanzable por PAK, pero documentada en
caso de repack futuro): `client-connection.client-gateway.{mode,endpoint,
http-endpoint,region,signing-host}`, `client-connection.authorization.{mode,
backend,auth-endpoint,cluster,cognito-pool-id,product-id,token-version}`,
`client-connection.enable-local-dev` / `.enable-remote`,
`client-connection.transport-options.{rep-default-port,tick-frequency-ms,
transport-type}`, `client-connection.auth-testing.*` (inyección de fallos),
`client-connection.warnings.*`.

**Modo local-dev del propio juego**: `client-connection.enable-local-dev` levanta
servicios stub in-process que persisten a `_persistence/{achievements,
leaderboards,agsPrivacySettings}.json`. Servicios stub existentes: Gateway,
Character, Guild, Inventory, GroupFinder, Matchmaking, Notification, Achievement,
Leaderboard, FCS (entitlements/catálogo/transacciones), Privacy. Sirve para saber
qué NO hace falta implementar todavía (si se logra repack).

### Sesión 2026-09-11: post-login mocks + RE de ListWorlds (NO CERRADO)

Avance: el juego llegó al panel ELEGIR PERSONAJE → VER MUNDOS. Acepta Términos
(los acepta solos, se puede RE-ear el endpoint para persistirlo en la futura
DB). Cuelga imagenes CMS (`nw_maintenance__modal`, `newstile2.dds` — placeholder
DDS servido por `routes/images.py`). UI muestra `@mm_azoth_1` y lista de
mundos VACÍA.

**Lo que se implementó y probó esta sesión (todo commiteado + pushed):**

- `routes/getlogininfo.py`: shape RE'd del exe. En `.rdata` (offset ~0x8702000)
  está la tabla del modelo aws-sdk `ListWorldsResponseBody`: `Worlds`,
  `LoginInfoList`, `RecommendedWorlds`, `PendingWorldMerges`, `AccountIsLocked`,
  y por mundo `PublicName/PublicStatusCode/WorldName/WorldStatus/WorldType/
  WorldVersion/QueueWaitTimeSec/WorldAgeDays/WorldPopulationStatus/IsFull/
  IsRecommended/MaxConnectionCount/TransferToRegion`. En 0x83bf000 está el
  descriptor UI (`UiLoginScreenRequestBus`, `GetLoginInfoLists`): claves
  camelCase (`publicName`, `queueSize`, `worldPopulationStatus`,
  `maxAccountCharacters`, `worldSet`, `isFull`...) y enums
  `eWorldType_FTUE/OpenWorld/Unknown`. Ambos casings se sirven.
- getlogininfo se sirve con `Content-Type: application/x-amz-json-1.1` (lo que
  el cliente aws-sdk-cpp manda y espera).
- `routes/queue.py`, `routes/characters.py`, `routes/entitlements.py`
  (x-amz-json-1.1), `routes/images.py` (DDS placeholder válido 145B).
- `research/schemas/live/cms_motd.json` reescrito: 1 mundo
  (`00000000-0000-4000-8000-000000000001`) + worldSet `azoth-1`→"Azoth".
- channel-azoth.json: `localizedName`/`displayName` = "Azoth-1" (fuera @mm).
- `config.py`: DEFAULT_SCHEMAS ahora relativo al repo (antes F:\Azoth duro).
- Caddyfile.json: certs a rutas del repo. Caddy corriendo elevado en :443.
- Tests gateway: 13/13 OK (unittest stdlib).

**Por qué la lista de mundos sigue vacía (frontera exacta):**

- El juego pide `GET /prod/game/getlogininfo/jwt/omni?channelId=…&includeNames=true&isTrialOwner=false` cada 60s, recibe 200 con el shape RE'd, pero NO pinta el mundo ni deja de pollear.
- El motd `worlds_STEAM_APP_ID.1063730.json` (CMS, cada 60s también) ya sirve el mundo con el MISMO worldId. El Game.log no muestra errores de parseo (aws-sdk traga y no loguea).
- **Siguiente paso**: RE del deserializador real de ListWorlds en el exe
  (capstone, buscar xrefs al offset de la tabla 0x87023d0 y mapear los offsets
  de cada clave para reconstruir el orden/tipos EXACTOS que espera). Alternativa: iterar el override `mock_discovery/getlogininfo.json` con variantes de shape (p. ej. `JwtClaims` como objeto, `WorldStatus` con otros valores, worlds anidado por región).
- Tras el primer mundo pintado: click en el mundo → `POST /prod/game/login/queue/v2/jwt/omni` (ticket `worldId_uuid`, `RepAddress 127.0.0.1:9000`) → world server DTLS (no existe todavía, `emulator/apps/world` vacío).

### Deuda menor detectada esta sesión

- Aceptar-términos: RE-ear el endpoint para persistir el consentimiento (futura DB).
- `Game.log` está en `%LOCALAPPDATA%/AGS/New World/Game.log` (no en el runtime dir).
- launcher stub steam: sin errores; `@mm_azoth_1` del dropdown se cachea al arrancar → con el channel arreglado, al REINICIAR el juego el dropdown mostrará "Azoth-1".

### Frontera previa (2026-09-09)

El panel "ELEGir PERSONAJE" pide (vía gateway-CF, con SigV4 de NUESTRAS
credenciales + `X-Nw-Auth: <accessToken JWT>`):

1. **`GET /prod/game/getlogininfo/jwt/omni?channelId=STEAM_APP_ID.1063730&…`**
   (reintento cada 10s). Es el "login token" de mundo. No conocemos el shape
   de la respuesta; probar override `getlogininfo.json` igual que tokens
   (añadir ruta al gateway). Tras validar, pedirá world/queue.
2. `GET /players/<persona>/games/new-world/platforms/steam/entitlements` y
   `/sync` (entitlements). Servir lista vacía razonable.
3. Después: selección de mundo → `login/queue/v2` → world REP/DTLS.

## Entorno de esta sesión (qué queda montado y cómo reproducirlo)

- **Admin sin UAC**: tarea programada `AzothAdminProxy` (ver
  `docs/ADMIN.md`): escribes comando en
  `%LOCALAPPDATA%\Azoth\admin\cmd.txt`, `Start-ScheduledTask`, lees
  `out.txt`. La usamos para `hosts` y para lanzar Caddy elevado.
- `hosts` en modo **private** (`switch-mode.ps1 private`, ya aplicado).
- Gateway: ventana PowerShell (job) en `:8080` (`Start-Gateway.ps1`).
- Caddy elevado oculto en `:443` (logs en `%TEMP%\azoth-caddy.{out,err}.log`).
  OJO: `deploy/Caddyfile.json` tenía rutas absolutas viejas de otro equipo;
  ya corregidas a `F:\Azoth\emulator\deploy\certs\*`.
- Juego: `launcher\src\Start-NwPrivate.ps1` (o directo al exe del runtime).
  El juego **auto-intenta el login** ~18s tras abrir; si falla y muestra
  diálogo, `orca computer press-key --app NewWorld --key Return
  --restore-window` reenvía. `orca computer get-app-state --app NewWorld
  --restore-window --json` da screenshot PNG (path en `result.screenshot.path`).
- Tests gateway: `python emulator/apps/gateway/tests/test_gateway.py` → 13/13 OK
  (unittest stdlib; pytest NO instalado).

## Comandos útiles

```powershell
# gateway (ventana nueva)
Start-Process powershell -ArgumentList '-NoProfile','-NoExit','-Command','& F:\Azoth\emulator\apps\gateway\Start-Gateway.ps1'
# Caddy elevado (una línea en cmd.txt del proxy):
Start-Process -FilePath F:\Azoth\emulator\deploy\bin\caddy.exe -ArgumentList 'run','--config','F:\Azoth\emulator\deploy\Caddyfile.json' -WindowStyle Hidden -RedirectStandardOutput $env:TEMP\azoth-caddy.out.log -RedirectStandardError $env:TEMP\azoth-caddy.err.log
# pantalla del juego
orca computer get-app-state --app NewWorld --json
# pulsar tecla (foco del juego)
orca computer press-key --app NewWorld --key Return --restore-window --json
```text

## Deuda técnica / refactor pendiente (siguiente sesión)

1. Pasar el override `tokens.json` del discovery a un fixture commiteado y
   que el default del gateway sea determinista (persona/steamid fijos).
2. Mock nuevo: `getlogininfo` (+ override file) y `entitlements`/`sync`.
3. Mover a `research/docs/` el método RE (capstone snippets, offsets
   `ags_fed_acc_token.cpp`, fórmula lea rip: `tgt = insn+7+0xA00+disp`,
   `.rdata`: `vaddr = fileoff + 0x1800`, `.text`: `vaddr = fileoff + 0xA00`).
4. Mundos: el channel-azoth.json apunta a los endpoints reales de fra-prod
   (hosts redirigidos). Cuando el logininfo valide, responder con
   `RepAddress` apuntando a nuestro world.
