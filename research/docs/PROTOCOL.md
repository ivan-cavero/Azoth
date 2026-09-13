# Game protocol (Javelin / GridMate)

Javelin is a fork of **Lumberyard GridMate**, not O3DE AzNetworking. MIT reference code: `aws/lumberyard` `Code/Framework/GridMate/`.

## Layers

```
UDP
  DTLS 1.2  ECDHE-RSA-AES256-GCM-SHA384
    Carrier datagram
      [u16 BE seq] [records…]
      optional compression hint (0x00 / LZ4)
      4 channels; channel 3 = system (connect, acks, clock)
    Application
      Handshake / V3 Registration (ticket + character/world)
      Replicas: Cmd_Greetings, Cmd_NewProxy, Cmd_DestroyProxy,
                Cmd_NewOwner, Cmd_Heartbeat, updates per ReplicaId
      RPC in chunks (*ComponentClientFacet / *Messages)
```

Details:

- Endianness **big-endian**.
- Acks as `SM_CT_ACKS` on channel 3, not in every packet.
- After DTLS: `SM_CONNECT_REQUEST` (unreliable, retry) → `SM_CONNECT_ACK` (reliable). The login ticket goes there.
- `ReplicaChunkClassId = CRC32(name)`. Facet (state) + Messages (RPC) × Client/Server.
- VLQ sizes (not protobuf). Bools to a **bit**.
- Custom AOI (grids). The server **does not send the map**: `LevelInfoChanged` + replicas. The client loads the `level.pak`.

## Spawn MVP (estimated)

1. V3 RegistrationResponse accepted
2. `PlayerManagerSelfIdentification`
3. `LevelInfoChanged` (e.g. `NewWorld_VitaeEterna` or `FTUE_V2`)
4. `Cmd_NewProxy` of the player's actor → `InGame`

The `Cmd_*` names come from GridMate + analysis; the official pcap is ciphertext. Server version seen: `[RETAIL].Javelin.1.365.6031.6017213` (client is `1.400.6031.6004151`). The stub may echo `1.365…`.

## RMIs seen live (names, not payloads)

- `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`
- `GatherableControllerComponentClientFacet_GatheringInterrupted`
- `EventNotificationComponentClientFacet_SyncNotifications`
- `GridTrackingComponentClientFacet_UpdatePhasing`
- `GameModeParticipantComponentClientFacet_OnLeftQueueForGameModeMsg`

They appear as `[ERROR] RMIDispatch: facet target ID couldn't be found` **during map unload** — the server sent the RMI before the client had the facet. Useful as a name catalog, not as a real crash.
