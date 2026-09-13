# Protocolo de juego (Javelin / GridMate)

Javelin es un fork de **Lumberyard GridMate**, no O3DE AzNetworking. Código MIT de referencia: `aws/lumberyard` `Code/Framework/GridMate/`.

## Capas

```
UDP
  DTLS 1.2  ECDHE-RSA-AES256-GCM-SHA384
    Carrier datagram
      [u16 BE seq] [records…]
      hint de compresión opcional (0x00 / LZ4)
      4 canales; canal 3 = sistema (connect, acks, clock)
    Aplicación
      Handshake / V3 Registration (ticket + character/world)
      Replicas: Cmd_Greetings, Cmd_NewProxy, Cmd_DestroyProxy,
                Cmd_NewOwner, Cmd_Heartbeat, updates por ReplicaId
      RPC en chunks (*ComponentClientFacet / *Messages)
```

Detalles:

- Endianness **big-endian**.
- Acks como `SM_CT_ACKS` en canal 3, no en cada paquete.
- Tras DTLS: `SM_CONNECT_REQUEST` (unreliable, retry) → `SM_CONNECT_ACK` (reliable). Ahí va el login ticket.
- `ReplicaChunkClassId = CRC32(nombre)`. Facet (estado) + Messages (RPC) × Client/Server.
- Tamaños VLQ (no protobuf). Bools a **bit**.
- AOI custom (grids). El server **no envía el mapa**: `LevelInfoChanged` + réplicas. El cliente carga el `level.pak`.

## MVP de spawn (estimado)

1. V3 RegistrationResponse aceptada  
2. `PlayerManagerSelfIdentification`  
3. `LevelInfoChanged` (p.ej. `NewWorld_VitaeEterna` o `FTUE_V2`)  
4. `Cmd_NewProxy` del actor del jugador → `InGame`

Los nombres `Cmd_*` salen de GridMate + análisis; el pcap official es ciphertext. Versión de server vista: `[RETAIL].Javelin.1.365.6031.6017213` (el cliente es `1.400.6031.6004151`). El stub puede ecoar `1.365…`.

## RMI vistos en live (nombres, no payloads)

- `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`
- `GatherableControllerComponentClientFacet_GatheringInterrupted`
- `EventNotificationComponentClientFacet_SyncNotifications`
- `GridTrackingComponentClientFacet_UpdatePhasing`
- `GameModeParticipantComponentClientFacet_OnLeftQueueForGameModeMsg`

Aparecen como `[ERROR] RMIDispatch: facet target ID couldn't be found` **durante el unload de mapa** — el servidor mandó el RMI antes de que el cliente tuviera el facet. Útil como catálogo de nombres, no como crash real.
