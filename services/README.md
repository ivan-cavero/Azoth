# Python services (transitional)

Authoritative runtime is `server/` (Rust). These trees are the **prototype /
parity** path until R7 (kill Python play path).

| Path | Role today | Rust owner |
| --- | --- | --- |
| `gateway/` | HTTPS bootstrap (Omni, CMS, getlogininfo, queue, …) | `apps/regiond` + `apps/channeld` |
| `world/` | DTLS + REP + ladder (replay-era heritage) | `apps/worldd` + `azoth-dtls` / `azoth-wire` / `azoth-session` |
| `launcher/` | Private client launch / patches | `platform/launcher` (skeleton) + `scripts/session` / `scripts/patch` |

## Rules

- Do not add long-term features only in Python when Rust already owns the plane.
- Preserve fixtures and measured behaviours for parity tests.
- When a Rust acceptance gate is green for a feature, mark the Python module
  for deletion here and in STATUS — do not leave twin sources of truth.
- Nested notes: [`AGENTS.md`](AGENTS.md).

## Daily loop

Still started via `python az.py dev` (gateway + world + Caddy). Compose is
Linux/CI only (ADR 0009).
