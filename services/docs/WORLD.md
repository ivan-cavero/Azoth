# World / REP

**Rust** process + **openssl** DTLS 1.2 (rustls does **not** speak DTLS). Cipher `ECDHE-RSA-AES256-GCM-SHA384` must be enabled explicitly.

Tick **30 Hz**, single sim thread, **no GC**, per-cell AOI. Density contract: [PERFORMANCE.md](PERFORMANCE.md). Server authority: the client sends input, the server integrates and replicates. The map is not sent: `LevelInfoChanged` + `Cmd_NewProxy`.

## Frozen spawn (MVP)

1. UDP bind  
2. DTLS handshake (pin: DER/PE report in capture, or patch on the private copy)  
3. Carrier `CONNECT_REQUEST` → `CONNECT_ACK`  
4. V3 registration (consumes ticket, `UPDATE … WHERE consumed_at IS NULL`)  
5. `LevelInfoChanged`  
6. `Cmd_NewProxy` for the player → Game.log `player spawn succeeds, in game`

Character standing still. Combat/AI/inventory later, one system at a time, against captures.

## Internal modules

`dtls`, `carrier`, `registration`, `replicas`, `levels`, `tickets`. `libs/protocol` is Rust **for this process only**. The gateway does not interpret Carrier.
