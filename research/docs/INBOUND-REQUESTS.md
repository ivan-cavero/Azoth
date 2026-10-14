# Inbound requests — what the client asks, what we answer, and how we decide

Companion to [SERVER-CONTRACT.md](SERVER-CONTRACT.md). That file answers "is each phase
implemented?"; this one answers the two directions of the **in-world typed-message contract**:

* **inbound** — which typed requests the client sends, and what kind of thing each is;
* **outbound** — which captured responses we may send back, and the rule that decides it.

Build: `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e`.

Reproduce the inbound table:

```powershell
python scripts/inbound-inventory.py .azoth/logs/world.log --session last --json research/derived/inbound-requests.json
python scripts/inbound-inventory.py --check     # names + classification self-test
```

## 1. Inbound inventory (measured 2026-10-14, one session)

8909 datagrams parsed, 0 unparsed. Records by channel: **0 → 543**, **1 → 8412**,
**3 → 8891**. The client sent **37 distinct client→server types**:

| kind | count | meaning |
| --- | --- | --- |
| `input-stream` | 1 | the ALC input stream (wire 1589), ~20/s |
| `transport` | 8 | Carrier/system records and `PingMsg`; answered by the transport layer |
| `v3-registration` | 1 | the client's `RegistrationRequestV3Msg` (wire 19) |
| `request` | 19 | a `*ComponentServerFacet_<Method>` typed call |
| `unknown` | 8 | typed, but not named by any available registry |

Channel 1 is **only** the input stream: all 8412 records are wire 1589. Channel 3 is the
Carrier/system channel and is not Javelin-typed.

### The 19 requests

| wire | count | name |
| --- | --- | --- |
| 2709 (`0x0a95`) | 15 | `ObjectivesComponentServerFacet_SetObjectiveAutoPinning` |
| 5463 (`0x1557`) | 3 | `GroupsComponentServerFacet_RequestRemoveRaidMember` |
| 1458 (`0x05b2`) | 3 | `ObjectivesComponentServerFacet_UpdateTrackedObjectives` |
| 2556 (`0x09fc`) | 2 | `ContractsComponentServerFacet_LookupContractsByParticipant` |
| 387 (`0x0183`) | 2 | `GlobalStorageComponentServerFacet_SetReplicateStorage` |
| 4248 (`0x1098`) | 1 | `TimeComponentServerFacet_SyncToClient` |
| 2515 (`0x09d3`) | 1 | `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` |
| 4272 (`0x10b0`) | 1 | `TraversalComponentServerFacet_SyncIsAutoTraversalEnabled` |
| 4122 (`0x101a`) | 1 | `SpectatedPlayerComponentServerFacet_SetIsPublic` |
| 6268 (`0x187c`) | 1 | `MountComponentServerFacet_OnMountDashToggleChanged` |
| 6271 (`0x187f`) | 1 | `MountComponentServerFacet_OnMountSlowWalkChanged` |
| 1643 (`0x066b`) | 1 | `VoiceChatComponentServerFacet_RegisterVoiceChatService` |
| 998 (`0x03e6`) | 1 | `ActionListComponentServerFacet_SetInputsThrottled` |
| 2776 (`0x0ad8`) | 1 | `TwitchComponentServerFacet_RequestJoinableSubArmies` |
| 3970 (`0x0f82`) | 1 | `PlayerComponentServerFacet_RequestSetIsLookingThroughLoadout` |
| 3092 (`0x0c14`) | 1 | `MetaAchievementComponentServerFacet_ServerRequestMetaAchievementsSummary` |
| 2297 (`0x08f9`) | 1 | `TerritoryDetectorComponentServerFacet_AttemptTerritoryUnlock` |
| 2617 (`0x0a39`) | 1 | `ObjectivesComponentServerFacet_NotifyOpenUiScreen` |
| 843 (`0x034b`) | 1 | `MetaAchievementComponentServerFacet_ServerRequestGetPendingMetaAchievements` |

A **wider session** (the 43-type measurement of 2026-10-13) also carried, one per session:
`VoiceChatComponentServerFacet_GenerateLoginAccessToken` (2077),
`PlayerComponentServerFacet_OnCullLimitPctChangeRequest` (3967),
`PaperdollComponentServerFacet_ServerCycleWeapon` (440),
`ChatComponentServerFacet_AddSubscription` (85),
`DamageReceiverComponentServerFacet_DebugHandleDamage` (20). They appear only when the
matching UI path is exercised, which is why a short session sees 37 and not 43.

**No request produces a client-side complaint today**, which is why the gap stayed invisible
for so long. That is not evidence that none is needed: the client's timeout and "missing data"
paths are narrow, and a request answered by replicated state has no typed reply to miss.

### The 8 types with no name

All three registries (`wire-type-names.json`, the Javelin registry, the AZ type registry) fail
to name them. Their GUIDs are **not present in the executable at all** (checked as dashed text
and as raw bytes), which means they are registered at runtime rather than declared in `.rdata`;
`typeindex.json` was itself produced by a runtime probe on 2025-10-22. Naming them needs a live
probe that reads the client's send-side class name, not a static scan.

| wire | count | channel | GUID | shape |
| --- | --- | --- | --- | --- |
| 3639 (`0xe37`) | 41 | 0 | `754d385a-8bc0-46fb-a69e-2ddc56f3f162` | 77 B, carries the local-player key |
| 1094 (`0x446`) | 14 | 0 | `93131d71-ac39-45d1-8bcc-c73e4968013d` | 48 B |
| 6745 (`0x1a59`) | 3 | 0 | `b42b3e49-b674-405c-a6ad-0cc5a8e368ba` | 45 B |
| 4143 (`0x102f`) | 2 | 0 | `81ead9f2-4838-490c-bd12-e9d78b98075f` | 44 B, phasing family (see below) |
| 4142 (`0x102e`) | 1 | 0 | `5d87aa99-1815-4d49-845b-bb29d1607887` | 46 B, phasing family |
| 6444 (`0x192c`) | 1 | 0 | `9ff57f0b-9ae9-4a69-9ebf-1bab649ee271` | 54 B, phasing family |
| 4126 (`0x101e`) | 1 | 0 | `c244a8ba-60e1-405e-af25-1eb4148ffed1` | 48 B, phasing family |
| 4854 (`0x12f6`) | 1 | 0 | `6e2a29b1-af9e-441c-8a71-67c409fdeebc` | 299 B |

One earlier name is recovered: wire **19** is `RegistrationRequestV3Msg`
(`0b826b33-89f5-49e0-b8cb-fe4433427778`), the client's V3 re-registration — the 1115-byte
`0x13` blobs are not a game request.

## 2. Outbound: the request → response map

The replay is **another client's capture**, so it contains the server's answers to requests our
client never makes. Which captured typed responses are answerable is therefore a
request-correlation question. The pairs below are derived two ways, and the derivation is
recorded so it can be re-checked:

* **ordering** — in the capture the response follows its request. Walk it with
  `ReplayStore.messages`; the sequence numbers below are from that walk.
* **naming** — `XComponentServerFacet_<M>` ↔ `XComponentClientFacet_<On><M>` in the same
  component family (regenerate names with `reverse/tools/scan-wire-names.py`).

| response | request(s) that justify it | how the pair was measured |
| --- | --- | --- |
| `0x08E6` Contracts `OnLookupContractsByParticipant` | `0x09FC` `LookupContractsByParticipant` | capture seq 59 → 67 |
| `0x1067` VoiceChat `OnVoiceChatServiceRegistered` | `0x066B` `RegisterVoiceChatService` | capture seq 100 → 101 |
| `0x1096` Time `SyncTimeChange` | `0x1098` `SyncToClient`, `0x0635` input stream | capture seq 110-114 → 117/118 (the ALC reply) |
| `0x1097` Time `SyncDayPhase` | `0x1098`, `0x0635` | same |
| `0x1033` GridTracking `UpdatePhasing` | `0x101D`, `0x101E`, `0x102E`, `0x102F`, `0x192C` | capture seq 94-97 → 98 |
| `0x1B88` GlobalStorage `ReceiveStorageSearchItems` | `0x1B7F` `RequestReplicateStorageSearchResults` | naming; 23 copies answer one request |
| `0x136A` GameModeParticipant `OnLeftQueueForGameModeMsg` | `0x0CED` `RequestLeaveGameMode` | naming |
| `0x16A0` Inventories `OnQueryInventories` | `0x169D` `QueryInventories` | naming |
| `0x0CA4` EventNotification `SyncNotifications` | *(none — unsolicited)* | no request precedes it in the capture |

### The rule the server now applies

`rep.py::_deferred_decision`, one decision per held response:

1. **known request** → send once the client has sent it; hold up to
   `AZOTH_REPLAY_DEFER_TIMEOUT_S` (default 20 s), then drop with
   `event: replay-response-suppressed`, `reason: request-not-seen`.
2. **no known request, facet measured absent** → drop, `reason: facet-absent`. This is the only
   remaining static drop and it is exactly one type (`0x0CA4`).
3. **otherwise** → send (an unsolicited push whose target exists).

The levers are `AZOTH_REPLAY_REQUEST_GATING` (default **1**; set 0 for the older
send-everything-at-drain behaviour, so the two can be A/B'd),
`AZOTH_REPLAY_DROP_UNRECEIVABLE`, `AZOTH_REPLAY_DEFER_CLIENT_FACETS`.

### What changed against the previous policy, and why

The old tables dropped `0x1B88`, `0x0CA4` and `0x1067` because a survey of the live player
entity found their facets absent. That survey was true but it was the wrong instrument:

| type | old action | new action | why |
| --- | --- | --- | --- |
| `0x1B88` GlobalStorage | drop | **drop** | same outcome, better reason: the client never sends `0x1B7F` |
| `0x0CA4` EventNotification | drop | **drop** | unsolicited and the facet is absent; the only static drop left |
| `0x1067` VoiceChat | drop | **send** | the client *does* send `0x066B`, so the answer has a requester |
| `0x16A0` Inventories | *(sent immediately)* | **drop** | the client never sends `0x169D`, so it was an unrequested response |

`0x16A0` is the one that had been going out unasked the whole time, and `0x1067` is the one
whose answer was being thrown away although the client had asked for it. Both are consequences
of replacing a facet survey with request correlation.

### Coverage, logged per session

When the held set is fully decided the server logs `event: inbound-request-coverage` with the
client's inbound types split into `answerable_by_replay` and `no_replay_response`. That is the
inbound half of the contract made visible: a request in `no_replay_response` is one the client
is waiting on and the server currently ignores. It is a **report, not a verdict** — many
`*ServerFacet_*` messages are setters answered by replicated state rather than a typed reply.

## 3. The gap that remains

There is still **no inbound typed dispatcher**: every request above is acknowledged at the
transport level and then ignored. The next concrete step is to answer the requests a playable
world needs, in this order (each is a setter whose effect is visible in the client):

1. `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` (2515)
2. `ObjectivesComponentServerFacet_UpdateTrackedObjectives` (1458) /
   `SetObjectiveAutoPinning` (2709)
3. `ContractsComponentServerFacet_LookupContractsByParticipant` (2556) — the capture contains
   the matching `0x08E6` response, so this one is answerable from the replay
4. `GlobalStorageComponentServerFacet_SetReplicateStorage` (387)
5. `TimeComponentServerFacet_SyncToClient` (4248)

## Evidence

* Inventory tool + classification: `scripts/inbound-inventory.py --check`.
* Per-session request log: `event: inbound-typed` (`rep.py::_note_inbound_typed`).
* Scheduling decisions: `event: replay-response-scheduling`, `replay-defer-start`,
  `replay-response-suppressed`, `replay-deferred-sent`, `inbound-request-coverage`.
* Capture ordering: `services/world/replay/messages-redacted.txt` via
  `azoth_world.javelin.replay_store.ReplayStore`.
* Names: `research/derived/wire-type-names.json`, `research/atlas/javelin-messages.json`,
  `research/atlas/az-type-registry.json`.
