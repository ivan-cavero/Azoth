# Gateway

The gateway is one HTTP process on `127.0.0.1:8080`; Caddy terminates client
TLS on `:443`. It uses Python's standard-library server and has no runtime
dependency beyond Python.

Start, stop, restart, and inspect through `python az.py gateway start|stop|restart|status`.
`python az.py dev` starts Caddy, gateway, and world in the background; service
output is stored under `.azoth/logs/`.

## Code map

- `services/gateway/src/azoth_gateway/app.py` — HTTP request lifecycle and
  route dispatch.
- `routes/` — route families; keep wire quirks close to their handler.
- `data/` — checked-in gateway seed data.
- `research/atlas/` — durable wire schemas and observed endpoint families.

## Captures

The gateway appends request/response summaries to
`services/gateway/traffic.jsonl`; exact bodies are stored in ignored
`traffic-payloads/` sidecars. Do not edit those files while the gateway is
running. After a play session, `python az.py doc` refreshes
`research/atlas/openapi.json` from the captured endpoint families.

Unknown paths are logged and return 404. A newly requested endpoint is a
research item: capture its shape, confirm it against the client or traffic, add
the durable schema to the atlas, then implement the route.
