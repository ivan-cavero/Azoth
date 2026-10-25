# services/

This is the measuring lab, not the game server.

| Path | What it does today |
| --- | --- |
| `gateway/` | HTTP before the client opens a world: channel document, login, world list |
| `world/` | DTLS session. It can replay a capture so the client can be watched |
| `launcher/` | Starts the private client copy |

`python ef.py dev` starts Caddy, the gateway, and the world. The replay is
allowed to emit a captured body while `research/atlas/meanings.md` still
calls that body unknown. It does not decide position, items, or currency.

Channel and region HTTP stay here until their JSON fields are named the
same way as a world message. The world process that replaces the replay
will be Rust, one named message at a time. See `docs/PLAN.md`.

Nested notes: [`AGENTS.md`](AGENTS.md).
