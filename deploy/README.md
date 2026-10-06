# Local routing and TLS

`deploy/` contains the Caddy configuration, host allowlist, and private/official
route switch. `python az.py caddy` starts Caddy; `python az.py mode status` is
read-only. Changing host routing requires elevation. Read
[`docs/ADMIN.md`](../docs/ADMIN.md) before any elevated operation.

## Local files

- `Caddyfile.json` — local TLS proxy configuration.
- `hosts-allowlist.json` — approved names redirected in private mode.
- `switch-mode.ps1` — applies `private`/`official` routing or checks status.

`python az.py dev` runs Caddy on loopback with the gateway and world server.
Its CA, certificates, and state live in ignored `.azoth/caddy/`; the binary is
installed by `python az.py setup`. There is no Docker Compose stack.
