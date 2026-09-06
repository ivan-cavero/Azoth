# Roadmap — Azoth

Detalle: [ARQUITECTURA.md](ARQUITECTURA.md). Captura official **en paralelo** mientras Amazon viva.

## Hecho

- [x] Nombre **Azoth**, mundo `azoth-1`
- [x] Árbol `research` / `emulator` / `launcher` (sin `capture`+`captures`)
- [x] Docs de análisis, captura, contrato, sesiones, protocolo, launcher
- [ ] Git paraguas + submódulos commiteados
- [ ] Spike skip-EAC: `launcher/src/Start-NwPrivate.ps1`

## Fase 0 — Research official (hasta 2027-01-31)

Steam + EAC + `research/tools/capture`. Combate, inventario, territorio, expedición.

## Fase A-private — Cliente sin EAC / sin Steam

`Start-NwPrivate.ps1` → si el 1.400 llega a frontend, copia + parche URL/pin. Play del launcher Azoth.

## Fase 1 — Gateway

Channel + CMS (ETag) + Omni + S3 + personajes + cola. Señal: `StartREPConnection` a localhost.

## Fase 2 — World stub

DTLS openssl + Carrier + V3 + spawn congelado.

## Fase 3–6

Movimiento → N jugadores → sistemas de juego → contenido custom + updater del launcher.
