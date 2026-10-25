# Local routing and TLS

`deploy/` contains the Caddy configuration, host allowlist, and private/official
route switch. `python ef.py caddy` starts Caddy; `python ef.py mode status` is
read-only. Changing host routing requires elevation. Read
[`docs/ADMIN.md`](../docs/ADMIN.md) before any elevated operation.

## Local files

- `Caddyfile.json` — local TLS proxy configuration.
- `hosts-allowlist.json` — approved names redirected in private mode.
- `switch-mode.ps1` — applies `private`/`official` routing or checks status.

`python ef.py dev` runs Caddy on loopback with the gateway and world server.
Its CA, certificates, and state live in ignored `.azoth/caddy/`; the binary is
installed by `python ef.py setup`.

## Linux compose (server path)

```bash
docker compose -f deploy/local/compose.yml up --build
```

See [`local/README.md`](local/README.md) and Dockerfiles under `docker/`.
Public binary names inside images: `world`, `region`, `channel` (ADR 0006).
