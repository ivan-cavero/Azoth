# Azoth research

**Capture, reverse engineering and decompilation** lab for the New World client, part of the **Azoth** monorepo.

Sessions go in `sessions/` (raw dumps gitignored). Docs, atlas and commits are in English.

```
research/
  atlas/           RE memory: endpoints, models, errors, levers
  docs/            analysis, kit, EAC, contract, decompilation, sessions, protocol
  derived/         decompilation output — regenerable, gitignored
  fixtures/        redacted extracts
  schemas/live/    channel + CMS (plaintext)
  sessions/        raw dumps — gitignored (tickets, pcap)
  notes/           local channel_config
  tools/capture/   Start-NwCapture.bat — record an official session
  tools/reversing/ disk, strings, pcap, endpoints
```

## Capture (official profile)

Steam + New World as always. Admin: `tools\capture\Start-NwCapture.bat`. Play 5–15 min. ENTER. Start with `sessions/<session>/REPORT.md`.

Docs: [docs/INDEX.md](docs/INDEX.md).

Docs and commits are written in English.
