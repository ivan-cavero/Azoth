# World / REP

**Python + pyOpenSSL** DTLS 1.2 (stdlib ssl has no DTLS; rustls does not speak
DTLS either). The Rust plan is retired — pyOpenSSL ships a prebuilt OpenSSL,
nothing compiles, and this service is login/campfire-tick only, not the world
hot path. Implementation: `services/world/` (see its README).

Tick **30 Hz**, single sim thread, **no GC**, per-cell AOI. Density contract: [PERFORMANCE.md](PERFORMANCE.md). Server authority: the client sends input, the server integrates and replicates. The map is not sent: `LevelInfoChanged` + `Cmd_NewProxy`.

## Frozen spawn (MVP)

1. ~~UDP bind~~ done
2. DTLS handshake (requires the client verify-bypass patch — `scripts/frida-trust-patch.py`) done
3. Carrier `CONNECT_REQUEST` → `CONNECT_ACK`
4. V3 registration (consumes ticket, `UPDATE … WHERE consumed_at IS NULL`) — answered today
5. `LevelInfoChanged`
6. `Cmd_NewProxy` for the player → Game.log `player spawn succeeds, in game`

Character standing still. Combat/AI/inventory later, one system at a time, against captures.

Wire reference: `research/docs/REP-PROTOCOL.md`.
