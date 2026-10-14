# 2026-10-14T13:54Z — "give the setters an authoritative effect": the answer is that none of them can have one yet

This session set out to give the five state-carrying requests an authoritative effect. The result
is a **measured negative with a redirect**, and it is worth more than the feature would have been:
the client does not consume what these requests report, and the server's authority channel is not
the typed reply at all.

## What was measured

### 1. Every state-carrying request's real shape (from the wire)

`inbound-request-shape` gives the target and parameter length of each. Decoded further:

| wire | name | target (this session) | params | shape |
| --- | --- | --- | --- | --- |
| `0x9d3` | `PlayerSettingsComponentServerFacet_ReceiveSettingsFromClient` | `d1a94ccc870660b0…` | 4 B | `000097c9`; not a float, not a plausible int |
| `0x5b2` | `ObjectivesComponentServerFacet_UpdateTrackedObjectives` | `180f8d4e573697c6…` | 1 B **or 49 B** | `00` (empty) or 3 × 16-byte ids + `01` |
| `0xa95` | `ObjectivesComponentServerFacet_SetObjectiveAutoPinning` | `180f8d4e573697c6…` | 37 B | `24` + 36 bytes of `00`/`01` — a 36-flag bitfield (the `24` = 36 is the remaining count) |
| `0x183` | `GlobalStorageComponentServerFacet_SetReplicateStorage` | `e2640b7ce5408036…` | 16 B | `2bb560aa58eb8881` + 8 zero bytes |
| `0x1098` | `TimeComponentServerFacet_SyncToClient` | `93a3e477cb5fd51e…` | 0 B | no payload; the request IS the message |

The three ids inside `0x5b2` are **session-scoped player objective ids**, not types: they appear
neither as raw bytes nor as dashed strings anywhere in `NewWorld.exe`, so they cannot be resolved
statically. Same for the `0x183` id.

**A naming caveat found here and worth carrying forward.** The wire-name registry lists
`ObjectivesComponentServerFacet_UpdateTrackedObjectives` for BOTH `0x5b2` and `0xa4d`. Reading the
`.rdata` around those two GUIDs shows why: the descriptor region is
`<name>\0<pad>\0<GUID1>\0<GUID2>`, i.e. **one name followed by two GUIDs**, and the adjacency scan
attributed the same name to both. The name belongs to the FIRST GUID (`0xa4d`); wire **`0x5b2`'s
real method name is therefore UNVERIFIED** and is treated as such here. The family is certain (it
sits among `ObjectivesComponentServerFacet_*`), the method is not.

### 2. Two of them are retry loops, which is a real finding

| wire | sends in one session | distinct param values |
| --- | --- | --- |
| `0xa95` SetObjectiveAutoPinning | **17**, all inside 2 s, up to **8 of them in a SINGLE datagram** | **1** |
| `0x446` (unnamed, Player-family) | **15**, all inside 2 s | **1** |
| `0x5b2` UpdateTrackedObjectives | 3, inside one second | 2 (`00` then the 3-id list) |
| `0x9d3` ReceiveSettings | 2 | 1 |
| `0x183` SetReplicateStorage | 2 | 1 |

Byte-identical repeats are not repeat state changes; they are the client re-sending. But it is
**not** evidence that a reply is missing, and that was checked: `PlayerSettingsComponent` has **no
client-facet message at all** in the registry, and `TimeComponent`'s only client-facet replies are
the two we already send. So the protocol provides no answer for these requests — they are
fire-and-forget reports, and the repeats are the client's own queueing. The 8-in-one-datagram case
is worth noting on its own: the client's queue flushes duplicates together, which is why counting
messages would badly overstate how many distinct things the client is reporting.

### 3. The request → facet topology is per-facet and stable

Mapping every channel-0 request's 16-byte target to the request types that use it:

| target | request types addressed to it |
| --- | --- |
| `42ffae59ff63091b…` | `0xe37` only (46 sends) |
| `180f8d4e573697c6…` | `0xa95`, `0xa39`, `0x5b2` — all three Objectives ServerFacets |
| `9e921a154971f6b7…` | `0xf82`, `0x446`, `0x12f6` — Player-family |
| `ce81136a2b7ad33e…` | `0x102f`, `0x102e`, `0x192c` — the phasing family |
| `16009918b041c1f9…` | `0x187c`, `0x187f` — both Mount ServerFacets |

So each facet has one local id and every message to that facet carries it. This is what makes the
dispatcher's target-learning general rather than a special case for the time facet.

### 4. The decisive experiment: the client ignores the time payload entirely

`reverse/probes/client/frida-game-time.py` (new) runs the client's own `lc_getTime` console command
and reads what it prints — `Current Container Time: h:m:s; t = …; CryTime: h:m; DayPhase: …` —
through the same printer `nw_getPlayerPosition` uses. Four conditions, each a fresh session:

| condition | game seconds per wall second | `DayPhase` shown |
| --- | --- | --- |
| baseline (`INPUT_RESPONSE=1`) | **12.2×** | `day` → `day` |
| `INPUT_RESPONSE=0` (no time sync sent at all) | **12.2×** | `day` → `day` |
| `AZOTH_DAY_PHASE_OVERRIDE=0` | **12.2×** | `day` → `day` |
| `AZOTH_DAY_PHASE_OVERRIDE=3` | **12.2×** | `day` → `day` |

The override was verified on the wire before drawing a conclusion — the client really received the
new value:

```
2026-10-14T13:54:00Z env=1248  00019742 93a3e477cb5fd51ebf85314bbc4a951a 00000002   <- replay
2026-10-14T13:54:00Z env=1268  00019742 93a3e477cb5fd51ebf85314bbc4a951a 00000003   <- our override
2026-10-14T13:54:01Z env=1304  00019742 93a3e477cb5fd51ebf85314bbc4a951a 00000003
```

and 241 `day_phase_override: 3` events were logged.

**Conclusion: the client's clock and day phase are computed locally at a fixed 12.2× and do not
come from `0x1096`/`0x1097`.** The captured bodies neither freeze the clock (a 2026-10-14 worry)
nor set it. The time-sync family is not a setter the server can act on.

## The redirect, which is the actual result

Putting this together with the two previous sessions:

* the state-carrying requests have **no reply message** in the protocol (checked in the registry,
  per family);
* the one family that does have a reply — Time — has a client that **ignores the payload**;
* the one thing we have ever measured the client **applying** is **replicated state**: the player
  moves because the record-1 state bundles keep flowing, and stops when they do not.

So the server's authority channel is **the state bundle**, not the typed RMI reply. An authoritative
effect has to be expressed as replicated state, and the first one to build is therefore a change to
what the `0x08` bundles carry — not another typed message.

This also sharpens the Rust trigger recorded in `docs/ROADMAP.md` item 4: "the first behaviour the
server decides rather than replays" means the first **state bundle the server composes itself**
instead of forwarding a captured one.

## What was built and kept

* **`reverse/probes/client/frida-game-time.py`** — a durable instrument. It derives the client's
  console-command registration shape (`lea rdx,<name>; lea r8,<handler>; call [rax+0x110]`),
  calibrated against the hand-verified `nw_getPlayerPosition` → `0x141015b30`, and uses it to run
  `lc_getTime` (`0x141015E80`) and `lc_requestTime` (`0x141018E10`). It reads the client's own
  in-game time and day phase as text. It ends through `_paths.safe_shutdown()`.
* **`clock-samples.jsonl`** — 41 samples across the four conditions above.

## What was built and REMOVED

The `AZOTH_DAY_PHASE_OVERRIDE` lever, its `day_phase_body()` helper and its three unit tests were
deleted once the experiment came back negative. `services/world/src/azoth_world/rep.py` is
byte-identical to its committed state: the repository's rule is that a failed alternative does not
stay in the runtime, and the negative result lives here and in the atlas instead.

## Honest limits

* The `lc_getTime` readout is the client's **container time**, and it is the value the client itself
  prints as its game time; I did not verify that this is the same clock the day/night lighting uses.
  The `DayPhase` string, however, is exactly what the day-phase message names.
* One session per condition. The signal is categorical (identical 12.2× and identical `day` in all
  four), not marginal, so this is not a threshold result — but it is not a statistical one either.
* `AZOTH_DAY_PHASE_OVERRIDE` only ever rewrote the 4-byte payload; a wrong-layout 0x1097 would have
  been passed through untouched by design, and the wire capture confirms the rewrite took effect.
