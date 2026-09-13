# World / REP

Proceso **Rust** + **openssl** DTLS 1.2 (rustls **no** habla DTLS). Cipher `ECDHE-RSA-AES256-GCM-SHA384` hay que habilitarlo explícito.

Tick **30 Hz**, sim thread único, **sin GC**, AOI por celda. Contrato de densidad: [PERFORMANCE.md](PERFORMANCE.md). Server authority: el cliente manda input, el server integra y replica. El mapa no se envía: `LevelInfoChanged` + `Cmd_NewProxy`.

## Spawn congelado (MVP)

1. UDP bind  
2. Handshake DTLS (pin: informe DER/PE en capture, o parche en copia private)  
3. Carrier `CONNECT_REQUEST` → `CONNECT_ACK`  
4. V3 registration (consume ticket, `UPDATE … WHERE consumed_at IS NULL`)  
5. `LevelInfoChanged`  
6. `Cmd_NewProxy` del player → Game.log `player spawn succeeds, in game`

Personaje quieto. Combate/AI/inventario después, un sistema por vez, contra capturas.

## Módulos internos

`dtls`, `carrier`, `registration`, `replicas`, `levels`, `tickets`. `libs/protocol` es Rust **solo de este proceso**. El gateway no interpreta Carrier.
