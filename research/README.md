# Research

Use the [research index](docs/INDEX.md) to find a method or protocol reference.
The atlas is the durable store for confirmed endpoint, wire, and client
function facts.

| Path | Contents |
| --- | --- |
| `atlas/` | Curated protocol facts, observed endpoint data, client functions |
| `docs/` | Decompilation, protocol, capture, and world investigation references |
| `tools/capture/` | Official-session capture tools and ingestion |
| `fixtures/` | Small reproducible inputs; redact account/session data |
| `schemas/live/` | Captured client JSON responses |
| `derived/` | Small catalogs and candidate summaries; large decompilation output is under `reverse/builds/` |
| `sessions/` | Local raw captures and logs; ignored by Git |

The client function registry lives at `atlas/client-functions.json`. The
Ghidra project, per-function output, corpus, and caches live in the ignored
`reverse/builds/<client-sha256>/` workspace. See [the reverse engineering
guide](docs/DECOMPILATION.md). Do not describe generated pseudocode as verified
source.
