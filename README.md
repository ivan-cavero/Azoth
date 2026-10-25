# Everfall

Everfall is a private New World server. It runs a local lab against a copy of
the installed client: gateway, world, and the routing that lets that client
connect.

The game's resource is still called Azoth. This project is not that word, and
it is not affiliated with Amazon Games.

## Start here

- [Current step](STATUS.md)
- [What each server message means](research/atlas/meanings.md)
- [How the real server is rebuilt](docs/PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Docs](docs/INDEX.md)

## Run locally

From the repository root, after the toolchain exists:

```powershell
python ef.py dev
python ef.py game
python ef.py status
python ef.py stop
```

On a new Windows machine, install the pinned interpreter once:

```powershell
.\az.ps1 setup
```

`az.ps1` is that installer. It is not a second command language. After setup,
use `python ef.py`. `python ef.py migrate` moves an older per-user workspace
into this checkout. The Steam install stays read-only. The private client
lands in `private-client/`. Tools and logs land in `.azoth/`.

`python ef.py dev` starts Caddy, the gateway, and the world in the background.
`python ef.py mode private` switches host routing and needs an elevated
shell. Switch back when you are done. `python ef.py re list` lists client
analysis workflows. `python ef.py probe list` lists live probes.

## Project map

| Path | Owns |
| --- | --- |
| `ef.py` | The command |
| `az.ps1` | Windows installer for the pinned Python |
| `services/gateway` | HTTP before the client joins a world |
| `services/world` | DTLS lab |
| `services/launcher` | Private client launch |
| `platform/web` | Public site |
| `research/atlas` | Facts and the meaning inventory |
| `reverse/` | Static analysis and probes |
| `deploy/` | Caddy and local certificates |
| `scripts/` | Helpers behind `python ef.py run` |
| `docs/` | Current guidance. History is in `docs/archive/` |

There is no `server/` tree. The Rust workspace was removed on purpose. The
rule for bringing it back is in `docs/PLAN.md`.
