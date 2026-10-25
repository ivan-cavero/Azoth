# Architecture

Everfall is a private New World server. Today the running programs are the
Python lab. The Rust server was removed until each message it would send has
named fields in `research/atlas/meanings.md`.

```text
New World client
    |  HTTPS
    v
  Caddy  ----  Python gateway     channel document, login, world list
    |
    |  DTLS
    v
  Python world                    measuring lab, captured ladder allowed
```

| Path | Owns |
| --- | --- |
| `services/gateway` | HTTP the client needs before it opens the world |
| `services/world` | DTLS lab and the current entry ladder |
| `services/launcher` | Private client copy and launch |
| `platform/web` | Public site. GitHub Pages builds this directory |
| `platform/launcher` | Future player launcher. Not the way we start the game today |
| `research/atlas` | Facts, including `meanings.md` |
| `reverse/` | Decompilation tools, probes, per-build corpora |
| `deploy/` | Caddy, local certificates, host routing |
| `docs/PLAN.md` | How the real server is allowed to grow |
| `docs/archive/` | Older plans, including the Rust workspace design |

The world process, when it exists again, owns the simulation and the socket.
It does not own accounts. The gateway does not own positions. Encoders do not
own game rules. A capture transformer, when we need one, is a separate crate
and is the only place an unnamed byte may live.
