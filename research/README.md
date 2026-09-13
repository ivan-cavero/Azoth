# Azoth research

Laboratorio de **captura, ingeniería inversa y decompilación** del cliente New World. Submódulo de **Azoth**.

No hay carpeta `capture/captures`: el repo se llama `research/`, las sesiones van en `sessions/`.

```
research/
  docs/            análisis, kit, EAC, contrato, sesiones, protocolo
  tools/capture/   Start-NwCapture.bat — grabar una sesión official
  tools/re/        disk, strings, pcap, endpoints
  tools/decomp/    Ghidra / parches de la copia private
  schemas/live/    channel + CMS (plaintext)
  fixtures/        extractos redactados
  sessions/        dumps crudos — gitignored (tickets, pcap)
  _re/             channel_config local
```

## Capturar (perfil official)

Steam + New World como siempre. Admin: `tools\capture\Start-NwCapture.bat`. Juega 5–15 min. ENTER. Empieza por `sessions/<sesión>/REPORT.md`.

Docs: [docs/INDEX.md](docs/INDEX.md).
