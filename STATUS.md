# Azoth — estado (2026-09-08 noche)

## Dónde estamos

El juego **arranca sin Steam, sin EAC y sin crashear**, llega al frontend y
pasa `CreateSession` con **`result: 0`** (la barrera 203 cayó hoy). La frontera
actual es `GET /prod/credentials/omni`: el juego la construye ("Calling Http
API") pero casi nunca la envía (2 envíos observados en ~12 intentos).

```
Stub Steam v2+ → frontend NightHaven → AuthManager → OmniSDK 1.6
  → ticket 0xA5 → POST /games/new-world/tokens (nuestro)
  → 200 mock → CreateSession result 0 → GET /prod/credentials/omni
  → (a veces no se envía) → STS mock → sin reacción visible aún.
```

## Avances del 2026-09-08

- **Schema de tokens sacado del binario** (pefile+capstone sobre NewWorld.exe,
  sin debugger): el SDK exige `accessToken`, `fallbackToken`,
  `platformAccount{identityType,identityId,personaId,ageGroup}`,
  `account{identityId,personaId,type,ageGroup[,isNewAccount]}`;
  cualquier clave requerida ausente → `result 203` (`mov [rbp+0x310],0xcb`).
  Opcionales: `errorCode`, `penalties`, `region{region}`, `limitedUseToken`.
  Override rápido sin reiniciar: `emulator/apps/gateway/mock_discovery/tokens.json`.
- **Mock de credenciales** (`routes/credentials.py`, GET+POST): STS con
  `AccessKeyId`/`SecretKey`/`SessionToken`/`Expiration` (+`type/accountType`
  `Full`, `ownership` `permanent`). OJO: la clave es `SecretKey`, NO
  `SecretAccessKey` (cadena literal en el binario). Tests 9/9 en verde.
- **Mock S3 remoteCfg** (`routes/s3.py`): JSON válido acolchado al tamaño
  capturado por key (190…5887 B). Listo para cuando caigan credenciales.
- **Stub: reintentos arreglados**: el juego pide ticket en CADA intento pero
  solo registraba el callback 168 una vez → 2º intento atascado en "Getting
  steam auth session ticket". Fix: flag pending por cada
  `GetAuthTicketForWebApi` + re-arme en `RegisterCallback`
  (`launcher/steam_stub/src/stub.c`). Recompilado con **clang**
  (MSVC no tiene Windows SDK: `windows.h` ausente) → `steam_api64.dll`
  77824 B, 22 exports verificados. Los reintentos ya fluyen (2 intentos/10s).
- **Infra rehecha**: Caddy 2.11.4 instalado (winget) en `deploy/bin/`
  (antes vivía en `F:\Azoth`, que ya no existe); CA propia en
  `CurrentUser\Root` + leaf con 13 SANs; `Caddyfile.json` con rutas locales
  + `logs:{}` (todo el TLS queda en `%TEMP%\azoth-caddy.err.log`);
  `hosts` en private (marcadores nuevos); gateway + Caddy verificados E2E.
- **Log real del stub**: `%TEMP%\azoth_stub.log` (el de `Bin64\` es viejo,
  del 06/09). Game.log: `%LOCALAPPDATA%\AGS\New World\Game.log`.
- Rarezas: el editor Zed del operador hace `GET /v1/models` a `127.0.0.1:8080`
  (ensucia discovery/metrics; se filtra por User-Agent).

## Qué falta (siguiente sesión)

1. **Envío de credentials**: sale 2 de ~12 veces. Sin handshake TLS en Caddy
   cuando falla = el juego no lo emite (probado con netstat en caliente).
   NO depende de: contenido de tokens.json (V14 idéntico envía o no),
   tecla temprana/tardía, stub MSVC/MinGW, gateway/Caddy reiniciados.
   Candidatos: race en el worker HTTP de SteamAuth, estado del AuthStack.
2. **Persona vacía**: `Get persona id result: Not OK`, `id:` vacío,
   `account type: Shadow, error 301` (nuestro `type: Full` no lo lee de
   donde espera). Sin persona, el flujo no avanza tras credenciales.
3. Cuando entren credenciales: S3 remoteCfg (mock listo) → characters →
   `login/queue/v2` → world REP/DTLS.
4. `switch-mode official` para volver a Amazon (ver PC abajo).

## Estado del PC (IMPORTANTE al volver)

- `hosts` en modo **private**. Para official:
  `powershell -File emulator\deploy\switch-mode.ps1 official` (admin).
  OJO: el script actual NO limpia bloques viejos (`# >>> AZOTH >>>` sin
  `PRIVATE`) y su guardián <3 líneas se niega si el hosts quedó solo con el
  bloque (pasó hoy: restaurado desde `hosts.azoth.bak` del 28/08).
- Gateway corriendo (`python -m azoth_gateway`, :8080, código nuevo con
  override). Caddy corriendo (`caddy run`, :443, con log). Juego cerrado.
- Cambios sin commitear (a propósito): `emulator` (omni.py override,
  app.py, credentials.py, s3.py, Caddyfile.json, tests), `launcher`
  (stub.c + dll MinGW). `mock_discovery/` tiene los dumps del día
  (gitignored).
- `python -m pytest` no instalado: tests con `unittest` de stdlib:
  `python emulator/apps/gateway/tests/test_gateway.py`.

```
Stub Steam v2 → frontend NightHaven → AuthManager → OmniSDK 1.6
  → ticket 0xA5 aceptado localmente → POST /games/new-world/tokens (nuestro)
  → 200 mock → CreateSession result 203 → retry con backoff. Sin crash.
```

## Probado hoy (evidencia en Game.log + stub log + capturas)

- Stub v2 mínimo (22 exports): 6+ lanzamientos, 0 crashes, 0 EAC. Causas reales
  encontradas con `tools/azoth_dbg.py`: vtable de Apps corta, slot-2 de User
  desreferenciado como `CSteamID*` (`NewWorld+0x5a7f7ae`), callbacks sin dispatch.
- Intercept TLS completo: hosts → Caddy `:443` (CA local + leaf con 13 SAN) →
  gateway `:8080`. El cliente lee `Channel name: Azoth`, `ClusterId: azoth-1`.
- Gateway sirve channel + CMS con ETag (el routing channel-earns-cms se cazó y
  tiene test de regresión). Tests: stub OK, gateway 7/7 OK.
- Descubierto y capturado: `POST tokenservice…/games/new-world/tokens`
  (`platformIdentityType: steam`, ticket en hex, `attributionData`) en
  `emulator/apps/gateway/mock_discovery/`… (ojo: ver nota abajo).

## Qué falta (siguiente sesión)

1. `CreateSession 203`: iterar el mock de `routes/omni.py` (el juego responde a
   cada cambio: 201→202→203). Candidatos: forma exacta del `id`/sesión que Omni
   espera antes de llamar a `/prod/credentials/omni`.
2. `GET/POST /prod/credentials/omni` (gateway-CF): mock STS cuando Omni lo pida
   (caerá en discovery con el body).
3. `login/queue/v2` → ticket + `RepAddress` localhost, luego world (REP/DTLS).
4. `switch-mode official` para volver a jugar en Amazon (ver PC abajo).

## Estado del PC (IMPORTANTE al volver)

- `hosts` queda en modo **official** (restaurado). Para seguir con Azoth:
  `powershell -File emulator\deploy\switch-mode.ps1 private` (admin).
- Caddy detenido; gateway detenido; juego cerrado. Para arrancar:
  `Start-Gateway.ps1` (o el job), `caddy run --config deploy\Caddyfile.json`
  (admin por el `:443`), `src\Start-NwPrivate.ps1`.
- `AZOTH_STUB_LOG=1` → `%TEMP%\azoth_stub.log` (traza de llamadas Steam).
- Binarios locales NO commiteados: `deploy/bin/caddy.exe`, `deploy/certs/`,
  `mock_discovery/` (ver nota).

## Notas / trampas conocidas

- `mock_discovery/` vive en `emulator/apps/gateway/` (no en `emulator/`);
  `config.py:GATEWAY_ROOT` ya apunta ahí. El README del gateway decía otra ruta.
- No fiarse del puerto 8080 sin comprobar el PID dueño: hubo una sesión con
  **dos gateways** (código viejo + nuevo) y métricas engañosas.
- `switch-mode.ps1` nunca debe dejar `hosts` vacío: se niega si el contenido
  superviviente tiene <3 líneas (lección del 2026-09-07: hubo que restaurar
  desde `hosts.azoth-bak-*`).
- `python -m pytest` no instalado: tests con `unittest` de stdlib.
