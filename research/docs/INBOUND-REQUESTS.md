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

## 3. The state-carrying requests: measured, and why none can have an effect yet

This section replaces the earlier "answer the five requests in this order" plan, which turned out
to be wrong for a reason worth recording: **the protocol has no reply for them, and the client does
not consume what they report.** Measured 2026-10-14 over four fresh sessions
(`research/sessions/session-20261014T1354Z-authoritative-effect-negative/`).

### Their real shapes

| wire | name | params | shape |
| --- | --- | --- | --- |
| `0x9d3` | `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` | 4 B | `000097c9` — not a float, not a plausible int |
| `0x5b2` | *name unverified, see below* | 1 B or 49 B | `00`, or three 16-byte ids + `01` |
| `0xa95` | `ObjectivesComponentServerFacet_SetObjectiveAutoPinning` | 37 B | `24` + 36 `00`/`01` bytes — a 36-flag bitfield |
| `0x183` | `GlobalStorageComponentServerFacet_SetReplicateStorage` | 16 B | an 8-byte session id + 8 zero bytes |
| `0x1098` | `TimeComponentServerFacet_SyncToClient` | 0 B | the request IS the message |

The ids inside `0x5b2` and `0x183` are **session-scoped player/objective ids**: they appear neither
as raw bytes nor as dashed strings in `NewWorld.exe`, so they cannot be resolved statically.

### Why no reply can be built

1. **No client-facet message exists for them.** `PlayerSettingsComponent` has exactly ONE message
   in the whole registry — the ServerFacet request. `ObjectivesComponent`'s only client facets are
   `OnObjectiveWarning`, `OnMilestoneCorrection`, `SetObjectiveInstanceDisabled` and a debug one;
   none is a "here is your state" reply. `GlobalStorage`'s client facets are all storage-search
   results behind `0x1b7f`, which the client never sends.
2. **The one family with a real reply is ignored by the client.** `TimeComponent` answers with
   `0x1096`/`0x1097`, and the client does not take its clock or day phase from them. Measured with
   the client's own `lc_getTime` command across four conditions:

   | condition | game seconds per wall second | `DayPhase` shown |
   | --- | --- | --- |
   | baseline, time sync sent | **12.2×** | `day` |
   | time sync NOT sent at all | **12.2×** | `day` |
   | `0x1097` payload forced to `0` | **12.2×** | `day` |
   | `0x1097` payload forced to `3` | **12.2×** | `day` |

   The forced value was confirmed on the wire (`…00000003` outbound, 241 logged override events), so
   the client received it and still showed `day`. Both the clock and the day phase are computed
   locally at a fixed 12.2×.

3. **Byte-identical repeats are not a request for an answer.** `0xa95` is sent 17 times inside two
   seconds (up to **8 copies in a single datagram**), `0x446` 15 times, always with identical
   parameters. That is the client's queue flushing duplicates, not a retry loop: the registry has
   no reply for either, so there is nothing for a reply to satisfy.

### The redirect: the authority channel is replicated state

The one thing ever measured to make the client **apply** server data is **replicated state**: the
player moves while the record-1 `0x08` bundles flow and stops when they do not. Every typed reply
we have tried either has no target, no consumer, or no effect.

So an authoritative effect must be expressed as **replicated state**, and the first one to build is
a change to what the `0x08` bundles carry — not another typed message. This is also what makes
`docs/ROADMAP.md` item 4's Rust trigger concrete: the first **state bundle the server composes
itself**, instead of forwarding a captured one.

### A naming caveat that this work exposed

The wire-name registry lists `ObjectivesComponentServerFacet_UpdateTrackedObjectives` for **both**
`0x5b2` and `0xa4d`. The `.rdata` region explains why:

```
0x8252a50  "ObjectivesComponentServerFacet_UpdateTrackedObjectives\0"
0x8252a88  55a7d1e9-9511-4eca-8f10-ea7d79f43f43      <- the name belongs to THIS one (0xa4d)
0x8252ab0  298436a9-06d0-4bda-8dd9-0708b36e7374      <- 0x5b2, unnamed
```

The descriptor form is `<Name>\0<pad>\0<GUID1>\0<GUID2>` for some types — one name followed by
two GUIDs — so an adjacency scan gives both GUIDs the same name. `scan-wire-names.py` now lets a
name be claimed by **one** GUID only; 146 wire types lost a borrowed name as a result (2201 → 2055
named) and the eight hand-verified anchors still reproduce. Wire `0x5b2` is therefore reported as
unnamed, and the server's own name table marks it `(name unverified)`.

## Evidence

* Inventory tool + classification: `scripts/inbound-inventory.py --check`.
* Per-session request log: `event: inbound-typed` (`rep.py::_note_inbound_typed`).
* Per-session request SHAPE (target + params): `event: inbound-request-shape` (`_dispatch_inbound`).
* Scheduling decisions: `event: replay-response-scheduling`, `replay-defer-start`,
  `replay-response-suppressed`, `replay-deferred-sent`, `inbound-request-coverage`.
* The dispatcher's answers: `event: inbound-answer`, `inbound-time-target-learned`,
  `inbound-dispatcher-owned`.
* The client's own in-game time and day phase: `reverse/probes/client/frida-game-time.py`
  (`python ef.py probe frida-game-time`), which runs the client's own `lc_getTime` command and
  reads its printed values.
* The negative result and the four-condition table:
  `research/sessions/session-20261014T1354Z-authoritative-effect-negative/` (`REPORT.md`,
  `clock-samples.jsonl`).
* Capture ordering: `services/world/replay/messages-redacted.txt` via
  `azoth_world.javelin.replay_store.ReplayStore`.
* Names: `research/derived/wire-type-names.json`, `research/atlas/javelin-messages.json`,
  `research/atlas/az-type-registry.json`. Regenerate the first with
  `reverse/tools/scan-wire-names.py --check`, which now refuses to give one name to two GUIDs.
