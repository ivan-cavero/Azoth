# Azoth — estado (2026-09-07 noche)

## Dónde estamos

El juego **arranca sin Steam, sin EAC y sin crashear**, llega al frontend y
avanza el login de Omni hasta `CreateSession`. La frontera actual es la
respuesta del mock de tokens: `result: 203, id: (vacío)` con retry limpio.
Progresión de hoy del `result`: `303` → `201` → `202` → **`203`**.

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
