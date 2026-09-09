# Azoth — estado (2026-09-09 noche)

## 🏆 HITO: LOGIN OMNI ACEPTADO (result 0) → pantalla ELEGIR PERSONAJE

Después de semanas atascados en `CreateSession result: 203`, hoy se rompió el
bloqueo. Cadena completa verificada en vivo:

```
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
  --restore-window` reenvía. `orca computer get-app-state --app NewWorld`
  da screenshot PNG (ver documentación en `docs/INDEX.md`).
- Tests gateway: `python emulator/apps/gateway/tests/test_gateway.py` → 9/9 OK
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
```

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
