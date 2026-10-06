# Operator tools

Use `python az.py ...` for setup, services, the private client, and tools used
repeatedly. A focused helper without its own command runs as
`python az.py run <script.py> [args]`.

## Common commands

- `python az.py setup` — install the locked local toolchain and dependencies.
- `python az.py migrate` — move existing per-user game and research state into
  ignored paths in this checkout; active game/decompiler files are deferred.
- `python az.py dev [start|stop|restart|status]` — manage Caddy, gateway, and
  world as background processes.
- `python az.py game [start|stop|restart|status]` — manage the private game.
- `python az.py shape <body.json>` — run one login response fixture against the
  live client. The harness restores the old override and counts only requests
  from that run.
- `python az.py doc` — refresh OpenAPI from captured gateway traffic.
- `python az.py shot`, `click`, `key`, `post` — screenshot or send UI input.

## Focused helpers

| Task | Helper |
| --- | --- |
| Capture and summarize a world attempt | `capture-world-run.py`, `ack-window.py`, `ack-coverage.py`, `trace-session.py` |
| Decode client channel-0 traffic | `decode-ch0.py` |
| Send one test message to a running private world | `world-inject.py` |
| Start a fresh instrumented client attempt | `run-instrumented-attempt.py` |
| Compare two game captures | `bmp-diff.py` |
| Hold a key or verify game focus | `hold-key.py`, `focus-window.py` |
| Send text or a raw virtual key | `send-input.py`, `post-input.py` |
| Shrink a screenshot for inspection | `shrink-image.py` |
| Apply a build-bound manual patch | `patch-actor-guard.py`, `patch-dtls-disk.py`, `patch-portray-predicate.py`, `patch-teardown-guard.py` |

The login harness uses `ocr-image.ps1` internally. Do not use the removed
`ocr-window.py` capture chain; `capture-window.py` no longer exists. Client
Frida probes have their own catalog at `python az.py probe list`, and startup
patch helpers live in `services/launcher/runtime-tools/`.

Keep a helper only while it has a caller, a measured operator use, or unique
reproduction value. Put reusable workflows behind `az.py`; do not add wrappers
for one-off experiments.
