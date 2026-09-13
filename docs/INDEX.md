# Documentación — índice

**Azoth** — servidor privado de New World. El análisis y la memoria RE viven en **research/**; el contrato del server en **services/docs/**; el cliente propio en **services/launcher/**. Este `docs/` es el pegamento.

## Sistema

| Doc | Contenido |
| --- | --- |
| [NOMBRE.md](NOMBRE.md) | Por qué Azoth |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Contrato del **día 1 / MVP**: 2 procesos, skip-EAC |
| [ARQUITECTURA-FLOTAS.md](ARQUITECTURA-FLOTAS.md) | Contrato de **topología de producción**: Auth global, regiones, mundos, instancias. El MVP crece hacia aquí. |
| [ROADMAP.md](ROADMAP.md) | Fases + **qué capturar ahora** |
| [ADMIN.md](ADMIN.md) | **Permisos admin: pedir el UAC al operador ANTES de empezar** |
| [sessions/](sessions/) | Sesiones históricas (`2026-09-13_pre-monorepo-STATUS.md` = todo el pre-monorepo) |
| [../services/docs/PERFORMANCE.md](../services/docs/PERFORMANCE.md) | Densidad / tick / AOI |

## Research (`research/docs/`)

| Doc | Contenido |
| --- | --- |
| [ANALISIS.md](../research/docs/ANALISIS.md) | Motor, login, GridMate, PAKs |
| [CAPTURA.md](../research/docs/CAPTURA.md) | Kit pasivo |
| [EAC.md](../research/docs/EAC.md) | EAC EOS, sin RPM en official |
| [CONTRATO_CLIENTE.md](../research/docs/CONTRATO_CLIENTE.md) | JSON/hosts que espera el cliente |
| [SESIONES.md](../research/docs/SESIONES.md) | Live 2026-09-06 |
| [PROTOCOLO.md](../research/docs/PROTOCOLO.md) | DTLS, Carrier, RMI |
| [DECOMPILATION.md](../research/docs/DECOMPILATION.md) | Método de decompilación |

**Atlas (memoria RE viva):** [`research/atlas/`](../research/atlas/README.md) — endpoints, modelos wire, errores, palancas de debug.
Schemas live: `research/schemas/live/`. Fixtures: `research/fixtures/`.

## Services (`services/docs/`)

| Doc | Contenido |
| --- | --- |
| [GATEWAY.md](../services/docs/GATEWAY.md) | HTTPS :8080 |
| [WORLD.md](../services/docs/WORLD.md) | REP / spawn |
| [DATA.md](../services/docs/DATA.md) | Persistencia (nota: hoy sin DB, mocks) |

## Launcher (`services/launcher/docs/`)

| Doc | Contenido |
|---|---|
| [LAUNCHER.md](../services/launcher/docs/LAUNCHER.md) | Updater, Play, sin Steam |
