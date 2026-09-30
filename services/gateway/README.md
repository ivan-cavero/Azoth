# gateway minimo

Python **stdlib only** (`127.0.0.1:8080`), detrás de Caddy en private. Sirve lo que el
cliente 1.400 necesita para salir del frontend: **channel + CMS con ETag**. Lo demás
(Omni → queue → REP) cae a `discovery` (404 + dump) para fijar el siguiente schema.

## Run (sin pip)

```powershell
powershell -File apps\gateway\Start-Gateway.ps1 --port 8080
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/STEAM_APP_ID.1063730.json
```

Detrás de Caddy `:443` (SNI) según `deploy/hosts-allowlist.json`. Sin Caddy el cliente
sigue yendo a CloudFront oficial: el gateway solo sirve tráfico redirigido.

## Qué responde

| Ruta | Respuesta |
| --- | --- |
| `GET /healthz`, `/metrics` | ok + contadores (`unknown_paths`, `cms_missing_etag=0`) |
| `GET /*STEAM_APP_ID*.json` | `data/channel-azoth.json` (un cluster `azoth-1`, tolera el garbage `BRANCH.<rand>`) |
| `GET .../newsstories/.../metadata.json` | `research/schemas/live/cms_news.json` + ETag |
| `GET .../marketingtiles/.../metadata.json` | `cms_tiles.json` + ETag |
| `GET .../motd/...json` | `cms_motd.json` + ETag (el cliente lo repide ~60 s) |
| resto | 404 `unknown-path` + dump en `mock_discovery/` (gitignored, máx 200) |

`If-None-Match` → `304`. Sin ETag el cliente crashea: aquí **siempre** se envía.

## Perf (honesto)

Login-only, fuera del hot path del world. Cuerpos + ETags precargados una vez;
por request solo routing + comparar cabeceras. `ThreadingHTTPServer` con threads
daemon. Los dumps de discovery son best-effort y acotados.

## Layout

- `src/azoth_gateway/app.py` — dispatch + server
- `src/azoth_gateway/config.py` — args/env
- `src/azoth_gateway/routes/{channel,cms,discovery,health}.py` — una concern por módulo
- `src/azoth_gateway/data/channel-azoth.json` — un cluster `azoth-1` (endpoints = allowlist, el hosts/Caddy decide el destino)
- `tests/test_gateway.py` — `python tests/test_gateway.py` (stdlib unittest)

Criterio Fase 1: `Game.log` dice `StartREPConnection` con `RepAddress` localhost.
Quedarse en `WaitingForREPConnection` sin world **es éxito** de esta pieza.
