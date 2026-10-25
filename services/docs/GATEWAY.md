# Gateway

The gateway is one HTTP process on `127.0.0.1:8080`; Caddy terminates client
TLS on `:443`. It uses Python's standard-library server and has no runtime
dependency beyond Python.

Start, stop, restart, and inspect through `python ef.py gateway start|stop|restart|status`.
`python ef.py dev` starts Caddy, gateway, and world in the background; service
output is stored under `.azoth/logs/`.

## Code map

- `services/gateway/src/azoth_gateway/app.py` — HTTP request lifecycle and
  route dispatch.
- `routes/` — route families; keep wire quirks close to their handler.
- `data/` — checked-in gateway seed data.
- `research/atlas/` — durable wire schemas and observed endpoint families.

## Local overrides

Most routes serve `<discovery_dir>/<name>.json` verbatim when that file exists,
before any code default: `tokens.json`, `characters.json`,
`characters_validator.json`, `entitlements.json`, `entitlements_sync.json`,
`getlogininfo.json`, `privacy.json`, `queue.json`, `worlds_list.json`. Two more
work one level up: `worlds.json` replaces the registry that several responses
are built from, and `placeholder.dds` replaces the served image. The default
directory is the gitignored `services/gateway/mock_discovery/`, so a leftover
override changes what the client sees between sessions while the repo looks
unchanged. When a run behaves differently from the code you just read, check
that directory first.

One override decides a visible dialog: `account.type` in `tokens.json`.
The code default is `"full"`, which keeps the client out of the Amazon
account-link flow; `"shadow"` is the unlinked Steam persona and makes the
client show that dialog. A leftover `tokens.json` override can therefore flip
the dialog back on while the repo looks unchanged. The link code itself is
stubbed at `/auth/platform/user/code`.

A second, independent switch for the same dialog rides the S3 remote-config
document: `javelin.enable-agid-account-linking` is served as `false` in
`routes/s3.py::JAVELIN`, which is the check the landing screen reads before it
shows the modal.

## Captures

The gateway appends request/response summaries to
`services/gateway/traffic.jsonl`; exact bodies are stored in ignored
`traffic-payloads/` sidecars. Do not edit those files while the gateway is
running. After a play session, `python ef.py doc` refreshes
`research/atlas/openapi.json` from the captured endpoint families.

Unknown paths are logged and return 404. A newly requested endpoint is a
research item: capture its shape, confirm it against the client or traffic, add
the durable schema to the atlas, then implement the route.
