# Data capture — what, why, and what not to touch

The official servers shut down on January 31, 2027. Every session you play **now** is protocol that later does not exist. This kit records that session without putting hands on the game process.

## What we will NOT do (ban)

Easy Anti-Cheat EOS is active on the live client. These things are exactly what EAC detects and reports to Amazon/Epic:

| Action | Risk |
| --- | --- |
| `ReadProcessMemory` / RAM dump | Ban |
| Frida, DLL inject, API hook | Ban |
| Debugger (x64dbg, Cheat Engine, ReClass) over `NewWorld.exe` | Ban |
| Patching the exe on disk and launching it | Ban / EAC won't start |
| Drivers to "hide" from EAC | Ban + worse |

There is no reliable "undetected" mode against EAC while the client talks to Amazon. We are not building one. An emulator does not need it: the client **already writes** the login map to `Game.log`, and network traffic is visible at the NIC.

Once we have **our** REP and the client no longer talks to Amazon, protocol reverse engineering is done against our own packets and static analysis of the exe (file). That is another moment.

## What the kit DOES capture (passive)

| Source | What you get | Does EAC see it? |
| --- | --- | --- |
| `%LOCALAPPDATA%\AGS\New World\Game.log` | The whole state machine, URLs, Omni, REP IP:port, spawn | No. The game itself writes it |
| `pktmon` at the NIC (`--comp nics`) | Encrypted UDP/DTLS + TCP 443. IPs, ports, sizes, handshake timing | It does not inject into the process. It is Windows' packet monitor |
| `netstat -ano` filtered by PID | Launcher/client connections | An OS query, does not open the process with `VM_READ` |
| DNS cache | CloudFront / API Gateway / Vivox resolution | Same |
| Files on disk | channel config, local EAC logs, settings, Steam `runprocess_log` | File reads |
| Strings of `NewWorld.exe` **as a file** | Embedded URLs and Javelin names | Not process memory |

The REP's UDP is encrypted (DTLS). The pcap does **not** give you the protocol in the clear. It gives you:

- the REP's real IP and port (changes per session)
- how many packets, of what size, in what order
- how long the handshake takes

The **clear** part of auth is in `Game.log` (the client prints it). That is worth more than an HTTPS MITM against Amazon, and it does not break the official login.

## How to use it

1. Close weird overlays (not the Steam overlay; that one is already in). Do not have Cheat Engine open "just in case".
2. **Double-click** `tools\capture\Start-NwCapture.bat` and accept the UAC (pktmon needs admin).
3. Two windows open: orchestrator (press **Q** to finish) and watcher (live events).
4. Open Steam, launch New World **as always**, log in, enter the world.
5. Play **5–15 minutes** for real: walk, hit a mob, open inventory, swap weapon, talk if you can. The more systems you touch, the more RMI names show up in the log.
6. Back at the orchestrator, press **Q**. Wait for `REPORT.md`.

Output:

```
sessions/YYYYMMDD_HHMMSS/
  REPORT.md                      ← start here
  logs/Game.log.raw              ← do NOT upload (Steam tickets)
  logs/Game.log.redacted
  logs/events.jsonl              ← structured sequence
  network/pktmon.pcapng
  network/connections.jsonl
  extracted/identities.json      ← player, world, REP
  extracted/urls.txt
  extracted/state_machine.jsonl
  static/                        ← exe strings (if you didn't use -SkipStatic)
```

## What to record in each session (priority)

While Amazon lives, the order of value is:

1. **Full login up to InGame** (you already did it once; repeating it with the kit gives pcap + aligned events).
2. **Movement + one combat** (`ActorMover` RMI, abilities).
3. **Inventory / storage** (today the log already fired `GlobalStorageComponentClientFacet_*`).
4. **Territory change / fast travel**.
5. **Entering an expedition** (another `level.pak`, another REP or instance).
6. **War / crafting / trading** — once 1–5 are in the box.

Four hours are not needed. **System coverage** is needed: short, well-labeled sessions.

Rename the folder if you want: `sessions/20260906_ingame_combate`.

## Flags

```text
Start-NwCapture.ps1
  -SkipPktmon     logs only (if you can't get admin)
  -SkipStatic     don't extract exe strings (saves CPU at startup)
  -HashExe        SHA-256 of NewWorld.exe (slow, ~179 MB)
  -SessionName X  fixed folder name
```

## After the capture

`REPORT.md` has a checklist: Steam → Omni → Campfire → queue → REP → V3 → InGame. If a box is missing, that session is no good for that layer.

With one good InGame session you can start the HTTP gateway (Phase 1) without touching memory or the community project: the schemas come out of `events.jsonl` and your `Game.log`.
