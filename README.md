# Azoth (working title — rename pending)

Unofficial private New World server for play after Amazon takes official
servers offline on **2027-01-31**. Not affiliated with Amazon Games. The name
“Azoth” collides with another community project; see
[`docs/adr/0005-project-rename.md`](docs/adr/0005-project-rename.md) and
[`docs/LEGAL.md`](docs/LEGAL.md).

This repository prepares an ignored local copy
of the installed client and provides the gateway, world server, and local
routing needed to connect it.

## Start here

- [Current status](STATUS.md) — short frontier only (diaries in `docs/journal/`).
- [Contributor loop](docs/runbooks/contributor-loop.md) — setup, doctor, **native `az.dev`**.
- [Architecture](docs/ARCHITECTURE.md) — what owns what on disk.
- [Master platform plan](docs/PLAN-master-platform.md) — north star.
- [Boot-naming campaign](docs/runbooks/agentic-boot-campaign.md) — next agentic RE.
- [Legal](docs/LEGAL.md) — preservation + funding.
- [Docs index](docs/INDEX.md).

```text
.\az.ps1 setup                 # core: Python + Caddy
python az.py doctor
python az.py dev               # daily loop (ADR 0009) — NOT compose
python az.py test e2e entry
# Linux/CI only:
# docker compose -f deploy/local/compose.yml up --build
```


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
| `az.ps1`, `az.py` | Bootstrap + local supervisor (`dev`, `re`, `run`, `doctor`) |
| `server/` | **Authoritative** runtime: `channeld` / `regiond` / `worldd` + crates |
| `services/` | Python **prototype** play path until R7 parity (`services/README.md`) |
| `platform/` | Launcher + web product skeletons |
| `research/atlas/` | Durable facts + ontology |
| `reverse/` | RE tools (`az.py re`), probes, per-SHA corpora (gitignored builds) |
| `scripts/<kind>/` | Operator helpers (`az.py run list`) |
| `deploy/` | Caddy, certs, Compose (Linux/CI only — ADR 0009) |
| `site/` | Public landing / roadmap v2 |
| `private-client/`, `.azoth/` | Gitignored runtime + tool state |
| `docs/` | Plans, ADRs, runbooks (frontier = `STATUS.md`) |

Knowledge reorg is done; playable authoritative path is **not**. See `STATUS.md`.
Durable facts → atlas/ontology. Pseudocode corpora stay local under `reverse/builds/`.
