# Azoth

Azoth is a private New World server project. It prepares an ignored local copy
of the installed client and provides the gateway, world server, and local
routing needed to connect it.

## Start here

- [Current status](STATUS.md) — the active blocker and the next useful step.
- [Roadmap](docs/ROADMAP.md) — the order of work and the repository cleanup plan.
- [Architecture](docs/ARCHITECTURE.md) — Rust, content, decompilation, and capacity boundaries.
- [Agent rules](AGENTS.md) — evidence, runtime, code, and documentation rules.
- [Docs index](docs/INDEX.md) — operating, service, and research references.

## Run locally

From PowerShell at the repository root:

```powershell
.\az.ps1 setup
.\az.ps1 mode status
# In an elevated PowerShell session, when you want the private route:
.\az.ps1 mode private
.\az.ps1 dev
.\az.ps1 game
```

On an existing machine, run `python az.py migrate` after closing NewWorld and
any Ghidra job using the old per-user workspace. It moves existing profiles,
the private runtime, and local analysis/tool state into ignored paths in this
checkout. New checkouts skip migration and use project-local paths directly.

Check the current route first. Switch to `private` only when you intend to
launch the Azoth client. The original game must be installed through Steam;
the launcher discovers its library or accepts `AZOTH_GAME_INSTALL`.
`.\az.ps1 setup` installs checksum-verified CPython, the pinned toolchain, and
Python dependencies under ignored project-local paths. `.\az.ps1 dev`
starts Caddy, gateway, and world in the background; logs go to `.azoth/logs/`
and no service terminal is opened. `.\az.ps1 dev stop` stops those three
processes. `.\az.ps1 game restart` replaces the private game process.
`.\az.ps1 status` reports all managed processes, and `.\az.ps1 stop`
stops the whole stack including the game. Switch routes with
`.\az.ps1 mode <mode>`. Use `.\az.ps1 re list` for maintained client
analysis workflows and `.\az.ps1 probe list` for focused live probes. Existing
Python installations can invoke the same interface through `python az.py`.

## Project map

| Path | Owns |
| --- | --- |
| `az.ps1`, `az.py` | Bootstrap entry point and local command supervisor |
| `services/gateway/` | HTTP APIs the client needs before joining a world |
| `services/world/` | Javelin/REP protocol and DTLS server |
| `services/launcher/` | Separate private game runtime and launch flow |
| `private-client/` | Ignored runtime copy, private profile, patched executable, and game log |
| `.azoth/` | Ignored tool installs, venv, process state, and operator logs |
| `deploy/` | Caddy, local certificates, and host routing |
| `research/atlas/` | Curated protocol facts and confirmed client function map |
| `research/tools/capture/` | Game log and official-session capture tools |
| `reverse/tools/` | Static analysis, Ghidra, PAK, and format tools |
| `reverse/probes/client/` | Named, on-demand live client probes |
| `reverse/builds/` | Ignored local Ghidra projects and pseudocode, one client build per SHA-256 |
| `scripts/` | Local operator commands and focused runtime experiments |
| `docs/` | Current project guidance and historical archives |

Durable facts belong in the atlas or the relevant service/protocol reference.
Generated decompilation workspaces and raw session captures stay local. The
future Rust and content boundaries are recorded in the [roadmap](docs/ROADMAP.md).
