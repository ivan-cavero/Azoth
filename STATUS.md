# Live status

## 2026-10-20 — the "move a body that renders" re-scope was tried, and its premise was wrong

The re-scope written yesterday was "move an EXISTING captured actor instead of creating one".
It was tried with two live arms and a real code bug was found and fixed on the way. **The premise
did not survive: neither character record is a body that renders.**

### A real bug, fixed: the move was gated on the source seq

`_send_replay_message` read `if move_to is not None and msg.seq == MOVE_ACTOR_SEQ`, so the rewrite
only ran on the bundle whose seq equals the configured source. But an entity is **created** by the
first bundle that carries it and only **updated** by the rest, and the component maps are
first-write-wins — so patching only the stream's copy leaves the body at the capture's position.
That is the same defect the structure experiment already paid for.

Measured, not inferred: record 29's position pair `(9345.4609, 2781.2595)` is carried by **two**
bundles, `0x77` (below the stream floor `0x94`, so the **replay** sends it once) and `0xa1` (the
stream). Gating on seq never touched the creation bundle. The rewrite is now applied **by value to
every body** that carries the pair; `MOVE_ACTOR_SEQ` only resolves the anchor. Live: `actor-moved`
fires on `0x77` **and** `0xa1` in one session. A test pins both halves. **375 world tests OK.**

### Arm 1 — record 29 (`0xa1`), the character 5.8 u from the player

Accepted with **0** `Failed to unmarshal`, **0** `ValidationError`, **0** `more than one root`, and
the 26 Transform warnings that are this build's fixed baseline. **No body appears** 5.8 u away. That
is consistent with the existing record that record 29 never rendered: it was never a candidate.

### Arm 2 — Saradnax (`0x97`, record 94)

Its slice instance at payload **291** declares its actor (`8e4972ff…`) and then **`18b03301040001a0`**
where record 29 has a real f32 pair (payload 684). **The slice declares no transform**, and the only
plausible pair in the 575-byte payload is at offset 216 — **84.3 u** from the player, which is not
where a slice position lives. Rewriting it changed nothing visible, as the layout predicted.

### The census, run for the first time (2026-10-20, later)

The roadmap named the actor/entity census as the next instrument. It now exists
(`reverse/probes/client/frida-actor-transform.py`, read-only, native `Memory.scan`,
player id as positive control) and it changes the picture:

| actor id | in client memory |
| --- | --- |
| local player (rid 1) | **yes**, 30–39 hits — the control |
| rid 29, 30, 60 | **yes**, 1 hit each |
| rid 87 | 1 hit, then **0** in the next scan 23 s later |
| rid 79, 88, 89, 90, 91, 92, 93, 94 | **absent** |

So the bodies the capture names — Saradnax (rid 94), Marrlord (rid 88), Vinicent (rid 89),
Nuna (rid 91) — are **not held under their declared actor id**. The re-scope assumed the
opposite. Two more negatives from the same run: **no** actor id has an adjacent world-position
pair in either endianness, and the same wildcard search cannot find **the player's own position**
as an adjacent f32 pair anywhere in 3 GB (an f64 search finds nothing either) — the accessor
derives it rather than storing it as a plain pair.

**The way forward is not a scan.** `frida-entity-table.py` shows the entity manager at
`this+0x110` **is populated** (four non-empty bucket cells, counts 2/2/1/1), so entities exist as
objects in a hash table. Walk that table, read each entity's actor id and transform, and find
which entity is a body that renders.

**Caveat, stated so it is not overread:** the budget is 3 GB over ~35 000 ranges, so *absent*
means *not in the scanned region*. The control makes the present-hits trustworthy; the absences
are strong but not absolute.

### Walking the entities worked, and the render does not follow the transform (2026-10-20, last)

Two failed instruments before the one that worked, and both failures are worth keeping:

- **Guessing the hash table failed.** Walking `this+0x110` by assuming a bucket/chain layout followed
  arbitrary pointers into code memory (`comps=112` at a `.text` address). That layout is not
  documented, so a guess produces garbage that looks like data.
- **A JS byte loop over 13 patterns × 3 GB did not finish** in 7 minutes; the native `Memory.scan`
  does the same work in 23 s.
- **What worked** is the client's own lookup `FUN_1413fb700` as the anchor: `args[0]` is an entity and
  the component count is `(entity+0x18 - entity+0x10)/8`. Attached at **character select**, so the
  load is covered — the atlas already recorded that the player entity is only observable during it.

**Result:** with a 40-component floor, exactly **15** entities survive — two of **126** (the live local
player, 1884 hits) and **twelve of exactly 61**. Twelve is the number of actor-bearing records the
capture declares, so **the remote actors are now addressable** for the first time.

**And then the decisive negative.** Only one of the twelve carries a plausible world position in its
Transform: two consecutive 12-byte little-endian `(x, y, z)` triples at `+0xE48`, **including the
height**, which never travels on the wire. Writing that triple:

| check | result |
| --- | --- |
| the client keeps the written value | **yes**, read back 3× unchanged — the Transform is a source |
| the render follows | **no**: four arms 6 u around the player, all **0.12–0.13x** motion |
| the other eleven entities | **no triple anywhere** in 16 KB — there is no common layout |

So the actors are addressable, their transforms are writable and stay written, and the **body still
does not move**. The next hypothesis is a separate render-side component — the player's own component
list already includes `AsyncRenderTransformComponent` (index 18) — not another transform offset.

### The thirteen entities ARE the remote players — and their position is nowhere in a transform (2026-10-20, last)

The walk was extended to resolve a second component and to name every component of the entities it
finds, and that answers what they are:

| | remote shape (13 × 61 components) | local player (126) |
| --- | --- | --- |
| `CharacterComponent`, `PlayerAppearanceComponent`, `SkinnedMeshComponent`, `PlayerSaveData`, `PlayerPositionTrackingComponent`, `AsyncRenderTransformComponent`, `Transform` | **yes** | yes |
| `PlayerAOIComponent`, `HUDComponent`, `CameraLockComponent`, `InventoriesComponent`, `AttributeComponent`, `CombatStatusComponent`, `PlayerInputFiltersComponent`, `PlayerSettingsComponent` | **no** | yes |

All 61 resolve with **zero** errors, and the split is exactly *remote proxy* versus *the player you
drive*. **Thirteen of them exist against the twelve actor-bearing records the capture declares** — the
remote player entities are addressable objects for the first time.

**Then the position hunt, and it is a negative with a control.** Three windows over the `Transform`
and the `AsyncRenderTransformComponent`:

| window | what it showed |
| --- | --- |
| 0x400 B | nothing — a **window bug**, the position is at `+0xE48` in one entity |
| 0x8000 B | in-band triples, but at **wildly different offsets** per entity (2904 … 31332) |
| current+previous must be **close** | offsets still inconsistent; 8 of 13 report nothing |

Inconsistent offsets across instances of the same component type mean those hits are **neighbouring
heap objects read past the end of the component**, not the entity's own transform. And the decisive
control: **the live local player — which certainly renders — has no in-band triple at all**, in either
component, at any window up to 0x8000. So the render path does not read a world position out of these
components, and *"find the offset"* is the wrong question.

**Where the position actually lives:** the client's own accessor `FUN_140fddfa0(&holder)` reports it at
`holder+0x14c/+0x15c/+0x16c` — a **different structure** from the Transform component. The next
instrument is to identify what that holder *is* and how an entity reaches it.

### The position layout, finally: stride 0x10 — and the server DOES own the spawn position (2026-10-20)

A session of failed position hunts is explained by one number. **The world position is three floats at
`Transform +0x14c (x)`, `+0x15c (y)`, `+0x16c (z)` — stride `0x10`, not a packed 12-byte triple.**
Every scan in this project looked for a packed triple, which is why none of them ever found it,
including the one that reported "no position in any entity's Transform".

Established two independent ways:

1. **Decompiled** `FUN_140fddfa0` (the accessor behind `nw_getPlayerPosition`) and its handler
   `0x141015b30`, which reads exactly `obj+0x14c / +0x15c / +0x16c`. A runtime probe then read that
   object's **vtable slot 0**, which answers the AZ type id **`484AE67D-…` = Transform**. The holder
   *is* a Transform component.
2. **Reading those offsets** on the twelve remote entities reproduces the capture's declared positions
   **0.5–2.3 u** apart for all twelve, and on the local player reproduces exactly the accessor's value.

**A method trap worth keeping:** calling that accessor from a Frida interval thread returns an all-zero
structure. It must be called **from inside a hook**, i.e. on the game's own thread.

### What that unlocked, and where it stops

| measurement | result |
| --- | --- |
| server sets rid29 to `(9352.0, 2786.0)` | client's entity comes up at **(9351.80, 2786.53)** — the server's value, not the capture's |
| changing the file mid-session | **no effect**: 1 `actor-moved` write (the `0x77` creation bundle) vs **264** stream sends of `0xa1` |
| writing the entity Transform directly | the write **lands**, the client **restores** it in ~2 s, and the render does not move (0.08x vs a 0.11x do-nothing control) |

So the server **owns the spawn position of a captured actor** — the by-value fix is what made that
work — and the **client re-imposes** that position, which is why writing the transform cannot move a
remote body. The mid-session wall is the same one already documented for the local player, now
confirmed **from the client's side** instead of inferred from the wire.

### The gap I left open, closed: the position works and nothing is drawn (2026-10-20, last)

The previous entry claimed the server owned a captured actor's position but admitted it had measured
**memory, not pixels**. That is now measured properly, and the answer is the opposite of a position bug.

- **Aim, from the client's own data:** the camera yaw is stable at **−154.04°** over 1 897 229 channel-1
  samples, so forward is `(−sin, cos)` and a body 3 u ahead of the player at `(9341.441, 2790.11)`
  belongs at `(9342.754, 2787.413)`.
- **Placed before the session started**, so the replay's creation bundle `0x77` carries it.
- **Result:** the client's entity for that record — **61 components, the remote-player shape** — sits at
  **(9342.5566, 2787.938)**, 0.56 u from what the server asked. The screenshot from the player's own
  viewpoint shows **no body**. Client otherwise clean: 0 unmarshal, 0 validation.

**So the position half works end to end and the missing body is a RENDER problem.** It is the same 26
`Couldn't get Transform component on the slice` warnings this build emits every session: the
remote-player slice is never placed. Items 1 and 2 are blocked by **one** thing, not two, and it is not
reachable from the position or the record.

### What that means

The bodies that render are **not** the actor records this project has been rewriting, so "move one"
needs the actor identified from the client first — the actor/entity census the roadmap already names
(`FUN_146801040`, manager at `this+0x110`, `frida-entity-table.py` / `frida-actor-presence.py`), not
another payload guess. Two screenshot A/Bs were taken at a fixed viewpoint and diffed with a masked
scene diff (HUD chrome excluded): 0.067 and 0.063–0.071, i.e. camera micro-motion, no entity.

**Also measured:** the launcher's Frida `DTLS verify bypass` crashes the client during startup
mapping (`frida-agent.dll_unloaded`, `0xc0000005`, offset `0x9c7e0`) — reproduced **twice today**.
Use `scripts/patch-dtls-disk.py apply` plus `scripts/private-run.py`, which is probe-free and reached
`InGame … player possessed` on every arm.

## 2026-10-19 (cont. 2) — item 1 is REFUTED, and the reason is a fixed property of this build

The roadmap's own step 1 for item 1 was "replicate a captured entity record under a new identity;
acceptance: two bodies render where one did". It was tested twice, the second time as strongly as it can
be tested, and it is **refuted**. Items 1 and 2 cannot be closed by the server in this build.

### The strongest test, and it failed cleanly

The first attempt used record 29 (19 fragments, 5.8 u from the player). Two real bugs were found and
fixed on the way (a record slot that was already allocated, and a replication counter below the client's
high-water), the record then reached the dispatcher, the slot was created and stable - and no body
appeared.

So the second attempt used the record that **provably produces a visible body**: the **48-fragment SPAWN
record**, the one that creates the local player. Composed and verified offline first: all **48 fragments
byte-identical** (every undecoded payload preserved), `record_id` 95 (a slot the client's own table
reports NULL), the position pair at payload offset 38332 rewritten to 3.5 u from the player, and the
actor id at offset 29731 rewritten to a new one. The server sent it (91 replay chunks) and the client
**accepted everything**: 0 `Failed to unmarshal`, 0 `ValidationError`, 0 `more than one root`, 0
transport errors. **No second body appeared.**

That controls for every variable the project has been guessing at - record content, fragment count,
actor id, position, slot, replication counter - and rules them all out. **The player renders because the
client binds it as the LOCAL player, not because of anything in that record.** A remote body needs the
`remoteplayer.dynamicslice` path instead.

### The real blocker, measured, and it is structural

`remoteplayer.dynamicslice` never receives a `GameTransformComponent` in this build:

| measurement | value |
| --- | --- |
| `Slice: Couldn't get Transform` warnings | **26, in every session since 2026-10-10** |
| the Transform gate `FUN_141763b70` | runs **30 times** per session |
| the registration `FUN_141582430` | runs **0 times** |
| the slice job's QueryInterface | accepts `{ED75FE05-…}` and `{B18D903B-…}` (= `ReflectContext`), returns **null** for `{83482F97-…}` - the one the gate asks for |

The 26 warnings are invariant across twelve retained logs including one from a different day, and do not
depend on anything the server sends. That is why every record-shape attempt failed identically.

**Both ways of supplying the missing Transform from outside the client were measured, and both break
it:** handing a default-constructed component back from the lookup gave 26 warnings -> 0 but **26
`The slice has more than one root` errors plus an APPCRASH** (`NewWorld.exe`, `0x3f00ce4`); answering the
QueryInterface gave `qi=2 answered=2` and an **APPCRASH** (`0x149923d`) before the world loaded.

### What this means for the roadmap

Items 1 and 2 are **re-scoped, not abandoned**: the remaining honest options are (a) provide a real
client-side implementation of that interface - client modification, out of scope for a server-faithful
implementation - or (b) re-scope both to what the server can actually own. `docs/ROADMAP.md` carries
this in both item 1 and item 2.

**Also corrected in this session:** the roadmap's claim that entity records carry "component GUIDs, not
actor ids" was wrong (a record DOES declare its actor id, and only 12 of 36 record ids do), and its
"long tail" note is refuted - replication gets the bytes accepted and is not enough to get a body.

**Validation:** 368 world tests OK. Atlas: 285 records.

## 2026-10-19 (cont.) — three real bugs fixed; the created entity still does not render

Worked the roadmap in the order requested (4, 1, 2, 3). Three defects were found and fixed, two of them
in code this session wrote, and one of them broke the operator's own machine. **The entity-creation
acceptance criterion is NOT met and is not claimed.**

### A real operational bug: the world log was filling the disk

`OUTBOUND_PAYLOAD_LOG` hex-dumps every outbound datagram. A live world sends ~200 datagrams/s of ~1 KB,
so `world.log` grew at **~1 MB/s**: one 84-minute session produced a **4 GB** file and one afternoon of
experiments left `.azoth/logs/` at **7.3 GB** on a disk at 78%. The visible symptom was the game becoming
unresponsive and the client being killed — reported by the operator, reproduced, and **not** the client's
fault. Fixed: the verbose hex form is now **opt-in** (`AZOTH_LOG_OUTBOUND_PAYLOADS=1`); every structured
event (`state-stream`, `replay`, `reply`, `heartbeat`, `movement-*`, `npc-*`) stays on, so no existing
measurement is lost. The 7.3 GB of stale rotated logs were deleted; `.azoth/logs/` is back to <1 GB and a
fresh session writes ~3 MB where it used to write 1 MB/s.

### Entity creation, bug 1: the "free" record slot was occupied

`entities.CAPTURED_RECORD_IDS` was derived by reading only the **first** record of each captured
payload — but a payload is a **sequence** of records (`[u8 id][u8 frags][fragments…]`, repeated) that
cannot be walked because a fragment carries no length field. So that set was a **lower bound**, not the
occupied set, and the slot chosen from it (**3**) was allocated. Measured the authoritative answer from
the client itself (`state + 0x608 + record_id*0x10`, probe
`reverse/probes/client/frida-record-slots.py`): **ids 1..94 occupied, 95..255 NULL**. Consequence,
measured rather than inferred: the dispatcher reported `slotEmpty: false` for slot 3 on every send, so
the message was an **UPDATE**, which the first-write-wins component maps discard
(`component_map_is_first_write_wins_20261018`). Fixed: `MEASURED_USED_SLOTS`, `free_record_ids()` starts
at **95**, `AZOTH_NPC_DUPLICATE=auto` resolves to it, and an allocated id is refused at load with a log
line. Atlas: `client_slot_table_measured_1_to_94_occupied_20261019`.

### Entity creation, bug 2: the replication gate dropped the bundle

`duplicate_entity` re-encodes the **payload** but not the bundle **prologue**, so the duplicated record
kept the source record's replication counter (`0x26` = 38). The client's gate drops any unreliable
replication whose counter is not strictly greater than `port[+0x78]`, and on a live session that
high-water was **1216** — so **every** NPC bundle was discarded before the dispatcher. Proved, not
assumed: of 81 distinct record ids reaching `FUN_141717fc0`, **95 was absent**, while the server logged a
send every second. Fixed: the NPC body now goes through `with_replication_seq` on the **same monotone
counter the state stream uses**; the wire shows it advancing (1806/1811/1817) and **record 95 reaches the
dispatcher**. Atlas: `npc_bundle_was_dropped_by_the_replication_gate_until_its_seq_advanced_20261019`.

### THE ROOT CAUSE, and it is bigger than the created entity

`Game.log` logs `[WARNING] Slice: Couldn't get Transform component on the slice!` **26 times, all for
`slices/remoteplayer.dynamicslice` (asset `A660EEEB-EBC7-5CB7-BE6B-AB11EB831731:64`)**, 5 s after spawn,
**in a session with the NPC feature DISABLED**. That slice is the one whose instance carries every
entity's actor id - the GUID embedded in record 29 at payload offset 642 is exactly
`a660eeebebc75cb7be6bab11eb831731`. The committed replay declares **46 such slice instances across 13
record ids** (1, 29, 30, 60, 79, 87, 88, 89, 90, 91, 92, 93, 94) - the remote players and creatures.

The static chain already on record (`gametransform_entity_attach`) says the class map the slice clone
uses **never receives `GameTransformComponent` from any function that runs at startup**: `FUN_141582430`
is the only inserter and its only caller `FUN_141763b70` has no static callers. So the cloned remote
entities have a **null Transform slot**, and a slice instance without a Transform has no world matrix
and cannot be placed in the scene.

**This is why the created entity has a slot but no body**, and it is a PRE-EXISTING condition, not
something this session broke - the same warning was in every earlier session. It also means the
**second-player item is blocked by the same thing**, because a remote player IS one of these instances.
Stated as a consequence, not as proof: the discriminating experiment is the one already designed in
`gametransform_attach_ab` - hook the lookup's return and, for entities whose slice path contains
`remoteplayer` and whose `entity+0x60 == 0`, call the GameTransform factory `FUN_14169a210` then
`FUN_1413789c0` (AddComponent), **with a hard cap** (that A/B measured 12488 attaches and stalled the
game thread when uncapped). Atlas: `the_client_cannot_bind_a_transform_to_remoteplayer_slices_20261019`.

### What the creation mechanism now has, and what it still lacks

Established, each measured: the actor id is a real addressable field **inside** the record — 16 bytes at
payload offset **662** in record 29, in the shape `<remoteplayer.dynamicslice GUID><00 00 00 02><actor
id>`, and the **same shape carries the local player's id at offset 29731** of the 48-fragment spawn
record, which is the independent confirmation that the field is the actor id; rewriting it changes
**exactly 16 bytes**; `ClientAddEntryMsg` is composed byte-exactly as `[00 01][a4][16-byte id]`; the
record now passes the replication gate and is dispatched; and the slot is **created and stable** with a
single send (1 distinct pointer in 9 samples) whereas re-sending it once per second made the pointer
**churn on every dispatch** — so the churn was caused by the server re-sending, not by the client
rejecting, and `AZOTH_NPC_MAX_SENDS` makes that a one-variable lever.

**Not established: a visible second body.** A figure appeared in the with-NPC run and looked like the
created entity; the same viewpoint was then reproduced with `AZOTH_NPC_DUPLICATE=0` and **the identical
figure is in the control**, so it is a pre-existing world NPC. That is the false-positive class this
project has already been burned by (`retracted_movement_claim_20261011`), caught here by taking the
control arm. Atlas: `the_created_entity_does_not_render_and_the_ab_refuted_the_candidate_body_20261019`.
**Next instrument, and it is not another payload shape:** the actor/entity table (`FUN_146801040`,
manager at `this+0x110`) counted before and after, plus a hook on the creation apply `FUN_14178db00`.

### Duration: the teardown is NOT deterministic

A probe-free session ran **1 h 24 min 06 s** from spawn to the last client line with `Disconnected from
REP` 0, `is timeout` 0, `transportError` 0, `exiting to main menu` 0, `ActorContainerDisconnect` 0 and
`Cleanup()` 0 — **1053 s (17.5 min) past** the 1 h 06 min 33 s ending recorded on 2026-10-14, same build,
same server code. So the long-session teardown is **not a fixed timer**, and the duration item must be
re-scoped from "find the 1 h 06 m timer" to "find what occasionally arms it". Caveat stated because it
would otherwise be misread: that session was ended by the probe's own deliberate `device.kill`, not by
the client. Also measured: the four teardown anchors (`FUN_146420610`, `FUN_146444b10`, `FUN_141004100`,
`FUN_146460240`) recorded **zero hits** in 24 minutes of a clean session, and `FUN_14643e4a0` is **not**
the disconnect consumer — it was called 893 times in 60 s with the watchdog returning non-zero on all of
them and the session stayed up, which corrects the earlier reading of that pair. Atlas:
`session_passed_1h24m_probe_free_the_teardown_is_not_deterministic_20261019`,
`duration_anchors_do_not_fire_in_a_clean_84_minute_session_20261019`.

### Also measured: the ntdll crash is not this session's change

The client still dies with `APPCRASH` / `ntdll.dll` / `c0000005` / offset **`0xc3ab6`** — a **new**
offset, and it reproduces with the NPC feature **disabled**, so it is the long-session instability already
on record, not a side effect of the entity work.

**Validation:** 368 world tests OK (32 in `test_entities.py`, 12 new).

## 2026-10-19 — the server owns the inventory, and a real gating bug was suppressing it

**The client renders an inventory the server composed.** TAB opens it and it is populated: armour,
weapons, rewards, jewellery, reagents, pelts, weight `90/91.90`, gold `2.492` — the **428 entries**
the server sent.

### The response, decoded

`InventoriesComponentClientFacet_OnQueryInventories` (wire `0x16a0`) has two captured bodies: **153 B**
(empty, no entries) and **99 819 B** (**428 entries**). Each entry is anchored by the marker
`00 01 82 5a` **68 bytes in**, and carries a NUL-padded container name (`w-world|`), a varint length,
the item type (`SkinCollection`), a GUID, flags, the literal `isCollected`, a count, a `0x02` tag, and
the item id as **decimal ASCII**.

**The trap: an entry is `223 + id_length` bytes** — 233 for a 10-digit id (338 entries), 232 for 9 (79),
231 for 8 (10). A fixed-stride parser reads 19 of 428 and then walks into padding, which is what the
first attempt did. The walk must anchor on the marker.

**Re-rendering the parsed entries is byte-identical to the capture** (99 819 → 99 819), which is what
makes it safe to change one id and send the result.

### A real bug in the existing gating, found while wiring it

`RESPONSE_REQUESTS[0x16A0]` was `(0x169D,)`, so `_deferred_decision` held both inventory responses and
then **dropped them as `request-not-seen`**. But the client **never sends `0x169D`** — 0 of 39 client
messages in the capture, 0 `inbound-typed` events in any live session — while the **real server sent
`0x16a0` at seq 0x28 and 0x29 unsolicited** and the client accepted both. The rule required a request
that cannot arrive and suppressed a legitimate push. Corrected to `()`, with a test that asserts the
capture has no such request.

Live confirmation: **0 `0x16a0` suppressed** in the run (was 2 per session), both bodies sent
(seq 40 = 153 B, seq 41 = **99 819 B in 91 chunks**), `server-inventory-composed` logged **428 entries,
3 changed**, and the client reported 0 `Failed to unmarshal`, 0 `ValidationError`, 0 `transportError`.

### And the false negative that hid it

The first attempt at opening the UI failed, and I nearly recorded "the UI does not open".
`scripts/send-input.py` sent a **VK without `KEYEVENTF_SCANCODE`**, while `hold-key.py` sends a real
**scan code** — and `hold-key.py`'s own docstring already says *“New World reads Raw Input; only
SendInput with a real scan code reaches it”*. The same session proved input was arriving (W moved the
player 7 u), so the honest reading was “this path does not deliver that key”.

TAB is scan code **`0x0F`**, and with that the inventory opens. **`send-input.py` now sends scan codes
by default** (`key <SCAN>`), keeping `vk <VK>` for paths that want one.

**Validation:** 346 world tests OK (23 new), 24 gateway OK. Atlas: 263 records.

## 2026-10-18 (cont. 18) — the server ENFORCES movement authority, verified live

The correction side, implemented and measured. **The server now follows a real player and corrects
when it should — and a legitimate walk produces zero corrections.**

### The architecture, from the client's own cvars

The CLIENT owns its locomotion and corrects its own desync; the SERVER validates and reacts. So a
correction is the server **refusing or limiting what it accepts**, not pushing a position — this build
has no working position-push channel (`IPositionReceiver`'s apply is `ret 0`, measured).

Three layers, deliberately separate so each is testable without a running game:

| layer | what it does |
| --- | --- |
| `alc.read_live_position` | the client's live position (movement buffer, validated **600/600**) |
| `MovementSimulator` / `YawAwareSimulator` | the server's **own** position and prediction |
| `CorrectionPolicy` | what the server **does** about a divergence |

### The escalation

| action | when | lever |
| --- | --- | --- |
| **ACCEPT** | claim plausible | adopt it |
| **HOLD** | claim rejected | keep the server's position; divergence recorded |
| **FREEZE** | past `freeze_after` violations | **stop refreshing the player state stream** — measured 2026-10-13 to freeze the client's simulation and make W do nothing |
| **DISCONNECT** | past `disconnect_after` | drop a client that will not converge |

And it **recovers**: `recover_after` clean samples resume the stream.

### Verified live (run 22:00)

| measure | value |
| --- | --- |
| server's own position | **(9352.11, 2769.72)** — tracked a real **23.02 u** walk from (9341.44, 2790.11) |
| adopted / violations | **3317 / 0** |
| mean prediction error | **0.0027 u** |
| decisions | **3, all ACCEPT** |
| client errors | 0 `Failed to unmarshal`, 0 `ValidationError`, 0 `transportError`, 0 connection warnings |

**A legitimate walk produces zero corrections** — the correct behaviour, and exactly what a naive
authoritative server gets wrong by rubber-banding an honest player.

### Two bugs found while wiring it

1. **`set_offset` was called every sample**, and it clears the tracker's streak (correctly — a new
   frame invalidates a streak built in the old one), so the streak reset forever and the desync
   **never fired**. Now called once.
2. **`movement-simulation-held` logged once per sample** because it shared a dedup flag with the
   validator, whose reference resets after a rejection and then reports the next sample as its own
   first sample. It has its own flag now.

**Validation:** 312 world tests OK, 24 gateway OK. Atlas: 259 records.

## 2026-10-18 (cont. 17) — the yaw was 90° off, and the feed now reads correctly

With the live feed working, the simulator produced numbers — and they were **the opposite of the
truth**: a player walking straight forward reported `forward_speed 0.00 / lateral +3.83 u/s`.

**The yaw is measured from +Y, not from +X.** Over **79 displacements** during a real walk,
`(movement heading − yaw)` is **+90.0°** in **77** of them (+90..+105 in the other 2). A constant
90° offset is a different angle origin, not noise.

Cross-check: the measured yaw was **−154.04°**; `(−sin, cos)` of that is **(0.438, −0.899)**, and the
player's actual displacement over the walk was `(10.1, −20.7)` normalized = **(0.439, −0.899)**.
Exact.

**After the fix, on 133 real walking samples:**

| measure | value |
| --- | --- |
| forward_speed | **+3.83 u/s** median |
| lateral_speed | **0.00** |
| mean prediction error | **0.1265 u** |
| violations | **0** |
| disagreements | **0** |

That is the first set of movement numbers in this project measured against a real walk with a real
feed — the earlier ones (4.0311 u constant, 0.0419 u prediction error) were taken against the anchor
and meant nothing.

**Validation:** 302 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 16) — SOLVED: the channel carries the live position in a BUFFER

The correction in cont. 15 was itself incomplete, and the missing piece is the answer the whole
project was looking for.

**The channel-1 body has TWO forms, and I had only ever looked at one:**

| form | payload | positions | what they are |
| --- | --- | --- | --- |
| **idle** | 311 B | **1** | the spawn anchor — does **not** follow the player |
| **moving** | **403–412 B** | **5** | a **sliding buffer of the last five movement samples**, newest first, 20 Hz |

**Every analysis in this project filtered for `len(payload) == 311`.** That is why the anchor was all
it ever saw, and why “the channel carries no live position” looked true. It does.

### Validation — the strongest in this project

The client's own accessor polled at **20 Hz** while the player walked **23.00 u**, matched against
every buffer entry:

| check | result |
| --- | --- |
| entries per moving message | **5 / 5** in all 120 messages |
| entries landing on the accessor's trajectory (< 0.5 u) | **600 / 600 (100%)** |
| entry timestamps | a clean **0.051 s** ladder |

### The layout

Anchored on the same `3d 4c cc cd` marker the idle form uses: first entry at **marker+12**, then
~63 bytes per further entry. Each entry is `[f32be x][f32be y]` followed by a trailer whose last byte
before the next entry is a **descending input sequence number**.

One trap the reader handles: the stride is **64** for the first entry and **63** after, so an
index-based walk drifts. The reader searches a window after each entry instead.

### The frame offset

`wire = accessor + (−2.2002, +3.3777)`, constant to **0.000 u** — the same offset the anchor has,
which is how the two forms were tied together. It is a **frame difference** between two quantities the
client computes, not noise.

The server stays in the **wire frame** (anchor, buffer and the state it writes back are all in it).
The constant exists only to compare against the accessor. The simulator's seed was moved to the wire
frame for exactly this reason — seeding with the accessor value while feeding wire values would have
put a permanent 4.03 u error in its own state.

### What this changes

**Step 1 of the authority loop is now genuinely solved.** The server has a live feed to simulate from,
and `alc.read_live_position` is wired into `_observe_movement_claim`.

**Validation:** 303 world tests OK (8 new), 24 gateway OK.

## 2026-10-18 (cont. 15) — CORRECTION: the channel-1 position is a spawn anchor, not a feed

This is the most consequential correction of the session, and it came from using the decisive
instrument instead of the wire.

**The measurement.** `frida-player-position` — which calls the client's OWN accessor exactly as
`nw_getPlayerPosition` does — polled at 20 Hz while the player walked, correlated against the
channel-1 claim in the same window.

| source | what it showed |
| --- | --- |
| client accessor, 20 Hz | a **real 23.00 u walk**: (9343.642, 2786.733) → (9353.72, 2766.06) in ~5 s, ≈4.6 u/s |
| channel-1 claim, same minute | **1050 samples, 0 position changes** |
| channel-1 claim, whole hour | **2 distinct values, 1 change** — a **243 u respawn jump** |

**So the `x,y` in the channel-1 body is a spawn/reference ANCHOR.** It updates on teleport and
respawn, not by locomotion. It sits 4.03 u from the accessor at spawn (the “instrument offset”) and
stays there while the player walks away.

**What this invalidates — plainly:**

1. “Step 1: LEER the client's position from channel 1” was reading an anchor. The field is real and
   readable; **it is not the live position**.
2. The desync detection compared that anchor against a constant server position — **two constants**.
   That is why the error was **exactly 4.0311 u in all 2562 samples** and calibrated to a residual of
   **0.0000**. “In sync” was trivially true and meant nothing.
3. The “3.342 u real divergence detected while walking” was **the anchor drifting**, not the player
   diverging.
4. The predictive simulator's **0.0419 u** mean error was measured on input that never moves — it
   measured arithmetic on a constant.

**What survives:** the client does stream state at 20 Hz on channel 1 (213k records measured); the
camera yaw and pitch in that body are held state that changes when the player turns the camera; and
the client's true position **is** readable through its own accessor — but that is a client-side
instrument, not a wire feed.

**What it means for authority:** the server cannot learn the player's live position from the wire as
currently understood. Either another message carries it, or the authoritative position must be
derived from **input plus physics**. That is a larger piece of work than “read the claim and compare”.

The code carries the caveat in its own docstrings so nobody trusts the numbers wrongly.

## 2026-10-18 (cont. 14) — the walk worked, and the position is NOT continuous

Captured a live session with continuous movement: **W held 24 s** (six holds of 4 s). The player
moved from `(9341.44, 2790.11)` to `(9251.20, 3015.70)` — **over 240 u** — so the walk was real and
the input stream recorded it.

**But the reported position is not continuous.** Over **5128 samples there are only 3 position
changes**, and they are **jumps**: 42.866 u, 157.105 u, 128.797 u. Between them the position is
byte-identical for hundreds of samples.

| transition | from | to | distance |
| --- | --- | --- | --- |
| #280 | (9341.44, 2790.11) | (9356.83, 2750.10) | **42.866 u** |
| #420 | (9356.83, 2750.10) | (9295.86, 2894.90) | **157.105 u** |
| #448 | (9295.86, 2894.90) | (9251.20, 3015.70) | **128.797 u** |

**So the channel-1 position is not a per-frame sample of a walking player.** It updates in bursts.
That kills the intent-correlation plan as written — there is no per-sample displacement to correlate
against — and it explains why every earlier attempt measured “2 pairs of movement”: the movement
never appears as small steps.

**What was learned anyway:** the movement block's `x,y` **does** change on each of the three jumps, so
the block is genuinely the position and it travels with the update. The byte ranges that differ across
a jump are consistent: `0..3` (container CRC), `53..54`, `71/73`, `78..79`, `86..87` (a small
counter), the movement block `123..140`, and four 2-byte counters at `150/191/232/273`.

**Consequence for the server:** prediction between claims has to come from the **camera orientation**
and the validator, not from an interpolated position history — which is what `YawAwareSimulator`
already does. Note the caveat: the measured prediction error (0.0419 u) was computed on a session
where the position never changed, so it measures the **quiet** case, not a walk.

**Next, if intent is wanted:** it needs the per-frame state, which the channel-1 stream alone does not
carry — either a client-side probe reading the position accessor at 20 Hz, or a different message the
client sends while moving.

## 2026-10-18 (cont. 13) — movement INTENT: blocked on data, not on analysis

I went looking for the intent (which keys are held) in the rest of the 311-byte body. **The answer is
that the existing captures cannot answer it**, and no amount of further static work will change
that.

**What the body offers:** only **34 of 283 body bytes ever vary**. Ranges: body `17..51` (before the
movement block), the block itself (`96..112`), and four 2-byte counters at `122/163/204/245`. Two
bytes are binary and were the obvious intent candidates — body **17** (`0` in 5427, `1` in 573) and
body **58** (`1` in 5164, `0` in 836).

**Why it cannot be decided.** Correlating them with movement needs samples where the client actually
moves. Scanning all **172 575** channel-1 samples for consecutive-sample displacement:

| threshold | pairs |
| --- | --- |
| > 0.01 u | **2** |
| > 0.05 u | **2** |
| > 0.10 u | **2** |
| > 0.30 u | **0** |
| > 1.00 u | **0** |

Two pairs is not a sample.

**And a trap I have to flag:** an earlier pass grouped by *distinct position* and looked like movement
(355 distinct positions in one session). That is the client **drifting while standing**, not
locomotion — per-sample displacement is essentially zero. A first correlation attempt then reported
“no difference” between flag=0 and flag=1; **that is not evidence either way**, because both groups
were almost entirely stationary (mean speed 0.001 u/sample). Reporting it as a negative would have
been wrong.

**What is needed:** a session where the player **walks continuously** for tens of seconds while the
traffic log captures channel 1. Nothing else will unblock it.

**What does not depend on this:** the server already has its own position, its own prediction (mean
error 0.0419 u on 4001 real samples), a rejection criterion that holds against an insisting client,
and the player's frame from yaw + pitch. Intent would let it **originate** a movement; everything else
is already there.

**Validation:** 295 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 12) — `b` is the camera pitch: the block is (pitch, yaw, x, y)

The last field decoded, by the same method that established the yaw — and it corrected the entry I
wrote one step earlier saying `b` was unknown.

**Evidence, in the same shape as the yaw's:**

| property | `b` (pitch) | `a` (yaw) |
| --- | --- | --- |
| distinct values | 637 | 610 |
| **changes in 197 810 samples** | **770** | **729** |
| mean run length | 256 | 271 |
| range | **−30.3° … +26.1°** | −179.5° … +179.9° |

`b` changes **770 times in 197 810 samples** — held camera state, exactly like the yaw. Its range is
a pitch range. And **691 of the 808 angle changes are simultaneous in `a` and `b`** (turning the mouse
diagonally), with 38 yaw-only and 79 pitch-only (looking up or down). Correlations against speed,
forward speed and lateral speed are all **below 0.10**, which is what an independent camera angle
looks like.

**The block is `(pitch, yaw, x, y)`** — the client's camera orientation and its world position in one
sample.

The pitch is recorded but **deliberately not used** in the velocity decomposition: the wire carries a
2D position (z is derived by the client), so movement is planar and a pitch cannot contribute.
Inventing a vertical component would be exactly the inference this project keeps paying for.

**Measured on 4001 real captured samples with both angles:** 29 violations, 8 prediction
disagreements, **mean prediction error 0.0419 u**, orientation captured on 3971 of them.

**Still not: prediction from INTENT.** The block gives orientation and position, not which keys are
held — so the server can *interpret* a movement but cannot yet *originate* one.

**Validation:** 295 world tests OK (11 new), 24 gateway OK.

## 2026-10-18 (cont. 11) — `a` is the camera yaw; `b` stays unknown

Decoded over **1008 measured displacements** in six sessions, and my first hypothesis was refuted by
the measurement.

**`a` is the CAMERA YAW** (radians, wrapped to ±π). Established by classifying every displacement by
`(movement heading − a)`:

| relative angle | share | what it is |
| --- | --- | --- |
| **+90°** | **47.8%** | strafe left |
| **+180°** | **24.4%** | walking back |
| **−90°** | **11.8%** | strafe right |
| 0° | 5.4% | forward |

That is the signature of WASD movement against a camera. I tried “direction of travel” first; it fits
**5.4%** and the histogram killed it.

**`b` stays UNKNOWN** and is exposed raw. It correlates with **position** rather than with speed or
heading (`corr(speed, b) = −0.0095`), stays inside `[−0.53, +0.46]`, and has 637 distinct values — so
it is not speed, not a heading, and not a small angle.

So **`a` is usable and `b` is not**: a server can turn a camera yaw plus a movement intent into a
world direction, and cannot do that with `b`.

### `YawAwareSimulator`

The velocity is now expressed in the **player's own frame**: forward along the yaw, lateral across
it. That is what lets the server say *how* the player is moving, not just how fast — and it is the
frame a correction would have to be expressed in.

**Measured on 3001 real captured samples:** 10 violations, 4 prediction disagreements, **mean
prediction error 0.0334 u**, yaw captured on 2990 of them.

**Not yet: prediction from intent.** That needs which keys are held, and the input stream has not
been shown to carry it. Yaw plus a finite-difference velocity is the precondition, not the answer.

**Validation:** 293 world tests OK (9 new), 24 gateway OK.

## 2026-10-18 (cont. 10) — the input stream is decoded, and the server predicts

Two things: the client's **movement block** is now decoded from its own input stream, and the server
now **predicts** rather than only adopting.

### The movement block, decoded from the client

Immediately after the `3d 4c cc cd` marker (the float 0.05), the channel-1 body carries a run of
big-endian float32:

| offset (payload / body) | field | measured range |
| --- | --- | --- |
| 119 / 91 | marker 0.05 | — |
| +4 / +4 | `a` | −2.93 … +0.33 — **meaning not established** |
| +8 / +8 | `b` | −0.01 … +0.18 — **meaning not established** |
| **+12 / +12** | **x** | world x |
| **+16 / +16** | **y** | world y |
| +20 | — | 0 while walking (not z: the wire is 2D) |

**Verified: x and y here equal the pair the position claim reports, 34 of 34 distinct positions, to
within 0.01 u** — and a second pass through the reader over **201 samples** gave 0 mismatches. The
client reports its position twice in the same body.

Offsets are measured on the **payload** (119); the reader works on the **body**, which starts 28
bytes later, so the marker is at body **91**. Both constants are recorded and a test pins them,
because mixing them is an easy mistake.

`a` and `b` vary with movement and are the natural velocity/heading candidates — but nothing has
established that, so they are exposed **raw**. The project has paid for unverified inferences too
many times to guess here.

### The server predicts, then checks

`PredictiveSimulator`: it estimates velocity from consecutive **server-held** positions, predicts the
next position, and records how far the client's claim was from that prediction — while still adopting
the claim when plausible.

| scenario | result |
| --- | --- |
| 3 s walk at 5 u/s, 0.05 u noise | 60 samples, 0 violations, 0 disagreements, **mean prediction error 0.0654 u**, velocity 4.617 u/s |
| 900 u teleport in one sample | **refused**: “teleport from the server's position: 884.993 u”, server keeps its own position |
| 2001 real captured claims | 0 violations, 0 prediction error — that dump is a session where the player never moved |

The distinction that matters: the client stays authoritative over its locomotion (what the cvar
names say the original does), but the server now has an **independent expectation**, so it can say
*“that step does not follow from what you reported”* rather than only *“that step was too fast”*.

**Validation:** 284 world tests OK (11 new), 24 gateway OK.

## 2026-10-18 (cont. 9) — the server has its OWN position now (not a replay)

Three things, and the first is the one that changes the shape of the project.

### 1. The original design, recovered — and it is not what I was looking for

The client's own cvar names settle how the original handled movement authority:

| side | cvars |
| --- | --- |
| **client** | `javelin.alc-correct-position-desync-during-attack-slow-down`, `javelin.alc-correct-lateral-desyncs-…` |
| **server** | `javelin-server.alc-speed-hack-fix-v2-enabled` / `-wipe-inputs` / `-max-buffered-inputs`, `javelin-server.player-teleport-2d-distance-metrics-threshold`, `javelin.alc-validate-sector-bounds`, `javelin.num-inputs-to-wait-for`, `javelin-server.ALC-max-input-to-combine`, `javelin-server.alc-request-input-throttle-server-override-delay-ms` |

**The client is authoritative over its own locomotion; the server validates and reacts.** Every
correction cvar is client-side; every server-side one is validation or input control. So **there is
no server→client position-push message to find** — a “correction” is the server refusing, throttling
or wiping inputs, after which the client reconciles.

That invalidates the search I spent this session on, and it is the third time I had to correct a
conclusion. The difference now is that this one comes from the vendor's own vocabulary rather than
from my reading of a decompiled branch.

### 2. `SetInputsThrottled` (0x3e6) is client→server, not a correction channel

Wire **998**, GUID `6e9b47da-ba7f-4253-8042-46580b9d7be0`, channel 0, once per session. It appears in
the **inbound** request inventory, and there is **no `ActionListComponentClientFacet_SetInputsThrottled`**
anywhere in the 7052-entry registry — the full 31-type ActionListComponent surface has only
ServerFacet throttle variants. It is the client telling the server its inputs are throttled.

Not present in our traffic dumps (0 occurrences), so its payload is a recorded **known-unknown**
rather than a guess.

### 3. The server now holds its own position

`movement.MovementSimulator` — the server's OWN authoritative position, seeded at spawn (where the
server genuinely decides) and folded forward from the client's validated claims. `Authority` records
whether the client or the server decided the current value on each sample.

**A real design defect was found by its own test:** the step must be measured against **the server's
position**, not the client's previous claim. `MovementValidator` resets its reference on a rejected
teleport, so measuring there would refuse a teleport **once** and then accept the teleported position
— an insisting client would win after a single refusal. Fixed, and the test pins it.

`AZOTH_STATE_POSITION=sim` publishes the simulated position into the state the server sends, so the
position it reports is **computed** rather than replayed. Default off, so nothing changes by accident.

**Validation:** 273 world tests OK (10 new), 24 gateway OK.

## 2026-10-18 (cont. 8) — `IPositionReceiver` CANNOT be unblocked: its apply method is a stub

I went to unblock the position-correction channel with pure RE, no live runs. **The channel is dead
by construction, and it is not a binding problem.**

**What the delivery does** (`FUN_143f97bf0`, decompiled):

```c
target = FUN_1416bcba0();
if (target) {
    qi = target->vtable[0x20](target, IPositionReceiver_guid);   // QueryInterface
    if (qi) {
        read 4 u32 at msg+0x30 and a u64 at msg+0x40;
        qi->vtable[0x40](qi, that_u64, &those_floats);            // THE APPLY
        return 1;
    }
}
```

**The apply is `vtable[+0x40]`, and that slot is `ret 0`.** The interface vtable is `0x1482eb160`;
its `+0x40 = 0x140294860`, which disassembles to exactly `c2 00 00` — `ret 0`. Slots `+0x48`, `+0x50`,
`+0x58` are the same stub. Neighbouring slots **are** implemented (`+0x30` = `jmp 0x143fa8520`,
`+0x38` = a real function with a prologue), so the interface is live but **this method is not**.

**No other vtable carries the QI.** Searching all of `.rdata` for the QI pointer `0x143fadd00` gives
exactly **2 occurrences, both inside `0x1482eb160`** (its `+0x20` and `+0x28`). There is **no static
concrete-class vtable** with the QI at `+0x20` and a real function at `+0x40`.

**And the client never builds one at runtime:** the measured session found `installer=0` and
`register=0` across a whole login + world entry + 18 minutes.

**Two earlier measurements are explained by this.** The “delivery succeeded 260/260 non-null” result
was measuring **this stub** — the delivery returns 1 once QI succeeds, whether or not anything was
applied. And “no registered target answers the interface” is consistent with there being nothing to
bind.

**Conclusion:** server authority over the local player's *ongoing* position is not reachable through
any channel measured in this project — not replicated state (spawn-only, first-write-wins) and not
this RMI (stub). Unblocking it would require a runtime-built implementation the shipped client never
creates.

**Validation:** 263 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 7) — CLOSED: the position is spawn-only in replicated state

The question this whole line was chasing — can the server own the player's position *over time* by
sending replicated state — is now answered **structurally**, from the committed replay, with no new
experiment. **The answer is no, by design.**

**`record_id 1` has two variants, and only one carries the position:**

| variant | bundles | fragments | payload | carries x/y |
| --- | --- | --- | --- | --- |
| SPAWN | 24 (seq `0x2a..0x6c`) | **48** | 46 393 B | **yes, all 24** |
| ongoing player state | 5 (seq `0x98/0x9a/0x9c/0x9e`) | **9** | 7 154 B | **no, none of them** |

Both carry fragment `key=16 type=11` with the **same vtable** (`0x7ff60a93f900`) — same component
type — but with **different payload sizes**: 85 B in the spawn (position at payload offset 20) vs
**49 B in the player record, with no position at all**. The component has optional fields and the
position is one of them.

**That explains every measurement at once:**

* the 2026-10-14 spawn override moved the client with **0.0000 u** error — the spawn variant does
  carry the pair;
* re-sending the spawn record cannot update it later — the component map is **first-write-wins**;
* the 4 Hz stream cannot update it either — **the ongoing variant does not carry the position**;
* the player moves freely anyway — the client **predicts locally**.

**So no amount of streaming, and no payload composition, can move the player through `record-1`.**
The ongoing position is client-authoritative, and server correction must travel on the dedicated
channel: `ReceivePlayerPositionClientMsg` (4216) → `IPositionReceiver` — which this build **never
instantiates** (installer 0, register 0, 0 of 225 vtables over 37,063 targets, measured 2026-10-12).

That is also exactly the vendor's own description of the design: the client predicts, the server is
authoritative and sends the outcome back. Which requires a working correction channel, not a
replicated field.

**Validation:** 263 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 6) — RUNTIME: the answer, and it refutes my own static reading

A new read-only probe (`frida-fragment-vtable`) hooked `FUN_141717fc0` and walked the fragment
vector it receives, reporting each fragment's key, object and **vtable**. 400 records captured,
including **25 spawn records (48 fragments)** and **63 local-player records (9 fragments)** — both
`record_id 1`, told apart by count.

**FINDING 1 — the `+0x60` slot is not a filter, and my static reading was WRONG.** The slot is
identical for **every fragment of every record**; disassembled it is **`xor al, al; ret`** — it
returns 0 unconditionally, so `if (cVar5 == '\0')` is always taken and every fragment is processed.
There is **no per-fragment predicate**. The previous entry claiming one is corrected in the atlas.

**FINDING 2 — the component maps are FIRST-WRITE-WINS.** Both `FUN_1415e5140` (called per fragment
with the fragment key) and `FUN_1415e68b0` hash on the key and then:

```c
if (*param_3 == (int)puVar9[2]) { *(undefined1 *)(param_2 + 1) = 0; return existing; }
```

An **already-present key is not replaced** — the caller gets the existing entry and the new
fragment is discarded.

**FINDING 3 — key 16 is a distinct component type:** same vtable in both records, but a different
`+0x90` reader than every other fragment (`0x142a436b0` vs `0x1417b4110`).

**This explains every measurement in this session.** The spawn record is sent when the keys are
**absent**, so every fragment is inserted — which is why the 2026-10-14 spawn override worked with
0.0000 u error. Every later correction re-sends key 16, which is **already present**, so it is
discarded and the client keeps the spawn value: accepted, zero errors, character visible, position
unchanged. Exactly what four payload shapes did.

**Consequence:** re-sending a key cannot work by construction. A correction must first **remove** the
component (the AOI registry already has `replica_portrayal_remove`) or use a delta/update message.

**Validation:** 263 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 5) — STATIC: the answer to why a correction is ignored

Decompiled `FUN_141717fc0` in full, plus `FUN_1415e68b0`, to answer the one question the four
refuted shapes left open: **why is a record the client parses not applied?**

**The dispatcher has two apply paths and they are structurally different.**

* **PATH A — CREATION** (the record's slot `*(state + 0x608 + record_id*0x10)` was **empty**): it
  builds a value and calls `FUN_14178db00(state, *slot + 0x860, &value)` — **one apply for the whole
  record, no per-fragment filter**.
* **PATH B — UPDATE** (the slot already exists): it loops the fragment vector and for **each**
  fragment calls a **virtual predicate** at `fragment->vtable + 0x60`; only when that predicate
  returns **0** does the fragment enter the component map (`FUN_1415e68b0`, decompiled: a hash-map
  insert/lookup keyed on the fragment key — the *map*, not the applier). Fragments that fail the
  predicate are **skipped**. It then applies through `vtable + 0x10` on the handler object's `+0x18`.

**That is the answer.** A correction is an **update** — the spawn already created the slot — so it
must pass a **per-fragment predicate the server does not control**. “Accepted, zero errors, no
effect” is exactly what a fragment that fails that predicate looks like. And it explains why the
spawn record works: it arrives when the slot is **empty**, so it takes PATH A and bypasses the
filter entirely.

It also explains why the previous session's reasoning could not have worked: the filter is **not
about the bytes we send**. No composition and no flag can satisfy it.

**Not claimed:** what the predicate at `vtable + 0x60` tests, or whether the position fragment can
satisfy it. **I tried to identify that vtable and FAILED** — recorded as
`fragment_object_vtable_identification_FAILED_20261018` so it is not repeated. The vtable I found by
pattern-matching `.rdata` for the slot value is a **serializer** (`+0x60` = `read(n)`, which returns
a previous cursor position, not a bool — so it cannot be the `char` the dispatcher tests). The right
method is to take the vtable at runtime from the object `FUN_146af2340` builds, not to match slot
values in the file.

What survives independent of that: the two apply paths, the per-fragment gate, and that
`FUN_1415e68b0` is a hash map keyed on the fragment key rather than the applier.

**Validation:** 263 world tests OK, 24 gateway OK.

## 2026-10-18 (cont. 4) — correction refuted in three shapes; a real server crash bug fixed

**Correction does not work in any shape tried, and that is now a measured conclusion rather than a
missing experiment.**

| shape | size | flags | client errors | character | applied |
| --- | --- | --- | --- | --- | --- |
| full spawn record, looped | 46 408 B | 0x21 | 0 | **invisible** | no |
| position fragment alone | 102 B | 0x21 | 0 | visible | no |
| record the client applies + position | 7 255 B | 0x21 | 0 | visible | no |
| **same, unreliable** | **7 255 B** | **0x20** | **0** | **visible** | **no** |

The last one was the one-variable test the static analysis called for: `FUN_14643e7b0` shows the
Carrier flag byte selecting between a path that does **not** advance `port[0x78]` (reliable) and one
that does (unreliable), and every captured bundle the client applies arrived through the second.
Sending 0x20 changed nothing: the error grew to **11.861 u and kept rising**, with 0
`Failed to unmarshal`, 0 `ValidationError`, 0 `transportError`.

So **neither composition nor the flag byte is the obstacle.**

**A real pre-existing bug was found and fixed, and it was killing sessions.** Three consecutive runs
failed to reach the world: the server armed the replay and went silent, and its log ended with
`UnboundLocalError: cannot access local variable 'traceback'`. The cause was a **local
`import traceback`** inside the feed-error handler, which makes the name local for the whole
function scope, so the **tick-error** handler raised instead of logging. That turned “one bad
datagram” into “the world process dies” — the exact failure both handlers exist to prevent, and a
plausible contributor to the intermittent `transportError 4` sessions recorded earlier in this
project. Fixed; the server then survived a full session.

**A bug of mine was caught by the new tests:** `_send_replay_message` had its body reading `flags`
while its signature still said `(self, server, msg)` — every replay send raised
`NameError: name 'flags' is not defined` (104 tick errors, 46 re-registrations, never reached the
world). The source-string test passed throughout; the fix is a test that inspects the parameter
list.

**Validation:** 263 world tests OK, 24 gateway OK. `AZOTH_MOVEMENT_CORRECT` still defaults to 0.

## 2026-10-18 (cont. 3) — STATIC: the record dispatcher, and why the 1-fragment bundle is ignored

Decompiled `FUN_141717fc0` (the record dispatcher) and its caller `FUN_14175ccc0` to explain the
live negative above. Build `8654f01d…`.

**The call site, confirmed in the decompiled body:** `FUN_14175ccc0` loops over the bundle's
records, calls `FUN_146af20d0(&reader, &out_record_id, &fragment_vector)` per record, then calls
`FUN_141717fc0(state, record_id, &fragment_vector, *FUN_1406d97b0(msg), byte[msg+8], success,
FUN_1406c10a0(msg))` — record id, fragment vector, message seq, a **flag byte at `msg+8`**, the
reader's success value, and the `clientContextInstanceId`.

**The apply gate:** `if ((param_5 == '\0') || (uVar11 == 0))` where `uVar11` is the record's
existing handler slot at `state + 0x608 + record_id*0x10`. An update applies only when the flag
byte is zero **or** the slot was empty; otherwise it is silently skipped — no error, no effect,
which is exactly the shape of the measured failure.

**The first fragment selects the path.** Immediately after the slot lookup the dispatcher makes a
virtual call derived from the **first element of the fragment vector** and branches on its result;
the `cVar5 != 0` branch contains an explicit `record_id == 1` special case. So a record is **not an
unordered bag of fragments**. A 1-fragment record whose only fragment is the position does not take
the same path as the 48-fragment spawn record (whose first fragment is key 71 type 4878).

**A wrong atlas record was corrected.** `spawn_record_fragments_do_not_carry_the_local_player_position_20261012`
claimed the position appears “NOWHERE in the whole replay”. It searched for the 12-byte **triple**
and z is not on the wire; the 8-byte **pair** is at payload offset 38332, re-verified with the
repo's own `decode_bundle`. The 2026-10-14 result stands.

**Also verified:** `key=16 type=11` appears in BOTH records with different payload sizes (85 vs 49
bytes) and only the large variant carries the position — the component has variable-length encoding.

**The next experiment is built and tested offline** (not wired, not run):
`rep.player_body_with_position_fragment` takes the 7154-byte record-1 bundle — the one the client
**demonstrably applies** at 4 Hz — and appends the position fragment, producing a **7256-byte**
record with `record_id=1, fragment_count=10` that carries the new position. That is the difference
the failed attempt lacked: it keeps the record composition the client already takes the right path
for, instead of sending the fragment alone.

**Not claimed:** which virtual function `vtable+0x60` is, or what `byte[msg+8]` carries. Both need a
targeted follow-up.

**Validation:** 255 world tests OK (4 new), 24 gateway OK.

## 2026-10-18 (cont. 2) — the position fragment is located; sending it alone does not move the player

**Two results, one durable and one a clean negative.** Session
`research/sessions/session-20261018T1135Z-minimal-position-bundle-negative`.

**LOCATED.** The 46393-byte spawn payload is 48 fragments whose boundaries are not derivable from
the bytes (no length field; the length is implied by the type; the first fragment is type 4878,
outside the nine types the 7154-byte record gave us). They were read from the client instead:
`python az.py probe frida-fragment-grammar --min-fragments 20` captured the same 48 offsets **25
times, byte-identical**. **The position is fragment #35**, payload offset `38310..38397`, header
`10 0b` (**key=16, type=11**) — the same key/type as fragment #6 of the player record. All **24**
captured copies of the spawn record carry a byte-identical fragment #35. That composes a
**101-byte** record-1 bundle (`record_id=1, fragment_count=1`), **451x smaller** than the 46 KB
spawn record.

**AND IT DOES NOT WORK.** With that bundle wired to the correction path: the player walked, error
reached 3.186 u, `movement-desync` fired, the **102-byte** correction was sent, the client reported
**0** `Failed to unmarshal` / **0** `ValidationError` / **0** `transportError`, the character stayed
**visible** (the full-spawn-record attempt had made it invisible) — and the error then **grew to
16.5 u and stayed there**. A record-1 bundle with one fragment is not a repositioning message. The
client appears to need the record's full fragment set, which is consistent with the full spawn
record having moved the player *at spawn* (0.0000 u, 2026-10-14).

So the position is **locatable but not addressable** as a standalone message with today's
knowledge. The remaining question — does the client treat the record as an atomic unit — is a
decompilation question, not a protocol-shape one. `AZOTH_MOVEMENT_CORRECT` defaults to **0**.

**A probe defect was found and fixed.** `frida-fragment-grammar` read the record's `out_u16` in the
record reader's `onLeave` and attached it to each fragment event, but fragments are emitted in the
fragment reader's `onLeave`, which runs *before* the record's — so **all 300** previously captured
fragment events carried `recordId: null` and the docstring's claim was false. It now emits at
record leave and filters by fragment count, required anyway because the spawn record and the player
metadata record are **both `record_id 1`** (48 vs 9 fragments).

**Two defects of mine, each caught only by a live run:** the correction body was a
`SimpleNamespace` while `_send_state_bundle` calls `dataclasses.replace()` — a `TypeError` the UDP
loop swallowed, killing the session with `transportError 4`; and the cap check logged on every
sample, hundreds of lines a second. Both fixed, both with tests.

**Validation:** 251 world tests OK, 24 gateway OK.

## 2026-10-18 (cont.) — desync detection verified LIVE, and the first design was refuted by it

**Two live runs, one code change between them.** Session
`research/sessions/session-20261018T0924Z-desync-verified`.

**Run 1 confirmed the reader and the load gate.** `movement-ready` fired at **t+13.115 s** with
**1,342** channel-1 records — inside the 8–14 s band predicted from the captured corpus, against a 60 s
timer that cannot see the difference.

**Run 1 also refuted the design I had just written.** `DesyncTracker` compared the raw wire claim with
the server's position, arguing that no offset was needed because they were "the same quantity". Reading
all **2,562** claims over two minutes gave an error of **exactly 4.0311 u in every sample**, with a
**single distinct position** — the player never moved. A perfectly in-sync player sat permanently above
the 2.0 u floor. That 4.0311 u is the instrument offset, matching the independently probe-measured
`(-2.200, +3.378)`.

**The correction, now measured.** The offset is calibrated per session with **no probe** — at spawn the
client is where the server put it, so the constant difference over the first samples *is* the offset.
Run 2 logged `movement-calibrated` `(-2.2002, +3.3777)`, magnitude **4.0311 u**, residual **0.0000**,
20 samples — reproducing the probe measurement to four decimals from a different data path — and then
**no** desync. A calibration whose samples are not tightly clustered is **rejected, not averaged**
(a wrong offset hides real divergence), and the tracker **fails open while uncalibrated**.

**The positive half is also confirmed.** With the offset fixed, `W` held 3 s produced
`movement-desync` **error 3.342 u**, claim `(9342.902, 2787.105)` vs truth `(9343.642, 2786.733)` — a
real divergence, because the server's truth stays frozen at spawn. That is the honest shape of the
system today: **it detects that it has lost track of the player and cannot yet correct it.**

**Gate 6 re-confirmed the hard way.** The first launch reached `InGame` but never streamed: 0 `Slice`
lines, black screen, no channel-1 record, `OnLocalNetworkConnectionWarning` 1→4. Cause:
`az.py dev` was started without `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`, whose default is the
failing value. A fresh `NewWorld.exe` was required.

**Validation:** 229 world tests OK (47 new), 24 gateway OK.

## 2026-10-18 — the client's own position is now READ, and the desync offset was the wrong problem

**Three measured results, one negative result, and a correction to an older record.** The reader and the
policy are now wired into the world loop as a read-only observer (`AZOTH_MOVEMENT_OBSERVE`, default on);
nothing corrects yet, and no live run has exercised it.

**1. The channel-1 stream DOES carry the player's position — the older record was measuring the pre-spawn
body.** `javelin/alc.py` reads it: container `[crc32][len][target16][00 01][varint type][body]`, type
**`0x635` = 1589** (`b5 18` is a *prefix* varint; reading it as LEB128 gives `0xC35` and rejects every
record — a test caught that, not inspection), body at payload offset 28, then two `f32` big-endian located
by the marker `3d 4c cc cd` (`0.05`) at `marker + 12`. Over **213,202** captured channel-1 records:
**197,810** carry a position, **15,392** do not (pre-load), **0** are ambiguous. The block *moves* — body
offset 91 in the dominant form, 93 on 11,144 records, also 92/101/112 — so a hard-coded offset of 103 reads
the wrong bytes on those 11,144. `scripts/alc-position.py` reproduces all of it.

**2. The real "load finished" signal, and it is 8–14 s, not 60.** The input body grows
`93 → 108 → 123 → 138 → 153 → 154` and only carries a position once it crosses ~280 bytes. The first
position-bearing record arrived at **t+8…14 s** after the first channel-1 record in 10 of 11 sessions; the
eleventh (18:50:56Z) never grew and produced **no** position in 400 records — a failed load, which a timer
cannot distinguish from a slow one. `movement.LoadGate` keys on the marker instead.

**3. The 2–4 u reference offset is an INSTRUMENT property, and treating it as desync is the bug.** Paired
sample-by-sample against the client's own `nw_getPlayerPosition` accessor with the player standing still,
the wire claim sits **2.0–4.0 u** away and the offset is **per session** (`(-2.196,+3.370) |d|=4.022`,
`(-1.183,+1.847) |d|=2.193`, `(-2.200,+3.378) |d|=4.031`, `(-2.260,+3.202) |d|=3.919`, `(-0.313,-0.475)
|d|=0.569`, `(+0.502,-3.991) |d|=4.023`). Within a session it is **constant**: residual **0.0000 u** in two
and under 0.26 u in three more. So the reader is precise and the offset is a constant of the session. The
consequence is the design: **calibrating the offset is not how you tighten the threshold — it is how you
stop the threshold from being wrong.** `DesyncTracker` compares the claim against the **server's own**
position (same quantity, same frame, no offset), and `ReferenceOffset` is only for validating the instrument
from probe pairs.

**Negative result.** The client's exact accessor bytes appear in **0 of 213,202** channel-1 payloads in any
encoding tried (f32/f64 both endians, scaled i16/i32/i64 at ×1/×10/×100/×1000/×1024). The wire value is a
different point in the client's pipeline, not a rounded copy of the rendered position — which is exactly why
it cannot be used as if it were one.

**What is NOT done.** Steps 1–3 of the authority loop now exist as code with 42 new tests (224 world tests
OK, 24 gateway OK), and `_observe_movement_claim` reads every channel-1 record in a live session and logs
`movement-ready` / `movement-desync` / `movement-reject` on transitions only — but **no live run has
exercised it yet**, so the runtime numbers are still the capture-derived ones. Correction is still where it
was: available as **replicated state** (the 2026-10-14 result, 0.0000 u) and unavailable as an RMI, because
`IPositionReceiver` is never instantiated. The position is still applied **at spawn only**, so there is
still no authority over the position *over time*. Next: a probe-free live run to confirm `movement-ready`
lands at 8–14 s, then make the position stream continuous.

**Not in this checkout:** the 2026-10-17 work (`javelin/alc.py` under that name, `MovementValidator`,
`DesyncTracker`) does not exist here — no branch, no commit, no blob, and no file on disk. It was done on a
different checkout or machine. This session re-derived the reader independently, and it disagrees with that
note on one point worth checking when the two meet: the raw residual while standing still is **2–4 u**, not
0.54 u. Either that note's figure was measured after some calibration, or it was reading a different field.

**Validation:** 224 world tests OK (42 new: `test_alc.py`, `test_movement.py`), 24 gateway OK,
`scripts/alc-position.py` reproduces the corpus numbers. Atlas:
`client_channel_one_carries_the_players_position_20261018`,
`reference_offset_is_an_instrument_property_20261018`,
`load_signal_is_the_input_body_growing_20261018`.

## 2026-10-14 (cont. 8) — **THE SERVER OWNS THE PLAYER'S POSITION** (measured, 0.0000 u error)

**The server wrote a position into the state it sends and the client's own accessor reported exactly
that position.** This is the first authoritative *effect* in the project: not "we composed bytes the
client accepted", but "we decided where the player is and it went there".

**Where the position actually lived, and why it never moved.** It is NOT in the 7154-byte record-1
bundles the state stream sends. It is in the **46393-byte** record-1 bundles — the spawn record, 48
fragments, replay seq `0x2a..0x6c` — which sit **below the stream's `MIN_SEQ` floor of `0x94`**, so
the replay sends them once and the stream never does. That is the entire reason the position stayed
anchored at the capture's value for the whole history of this project.

Found **by value, not by a guessed offset**: x `9343.6416015625` and y `2786.732666015625` sit at
payload offsets 38332/38336 as big-endian float32, byte-exact against the position the client's own
accessor had always reported. **z is not in the payload at all** (searched f32/f64 both endians and
scaled i16/i32/i64 at x1/x10/x100/x1000/x1024): the wire carries a **2D** position.

**The measurement.** `AZOTH_STATE_POSITION=9353.7227,2766.0681` — a point the client itself had
reported after walking, ~23 u from the capture's spawn:

| measure | value |
| --- | --- |
| server side | **24 `state-position-override` events, each `replacements: 1`**, on seq `0x2a/0x2b/0x2e/0x2f/0x30/0x33`… — exactly the spawn bundles, nothing else |
| client's reported position | **(9353.72265625, 2766.068115234375, 87.5379638671875)** |
| distance to what the server wrote | **0.0000 u** |
| distance to what the capture carried | **22.9925 u** |

The override is anchored on the **measured capture value**, so it fires only in a body that actually
carries the position and cannot corrupt one that does not.

**The z question is now answered.** The earlier session could not tell whether the client derives the
height or keeps the capture's. It derives it: z varies across the 199 samples (87.432 → 87.611) while
x and y sit exactly on our values. So the server decides where in the plane the player is and the
client puts it on the ground.

**And it is a starting point, not a freeze:** with W held 5 s from there the player moved **14.005 u**
and stopped again after release (net 0.000 u over 120 samples).

**Nothing regressed:** 1 `RMIDispatch` error (the known spawn−3 ms GridTracking artifact), 0
connection warnings, 0 `Failed to unmarshal` / `ValidationError`, 0 transportError/timeouts/REP
disconnects, world rendered with 26 slice lines.

**Not claimed:** one session and one injected value; the override writes x and y only (the client owns
the height); and the position is applied **at spawn** from a record the replay sends once, so this is
authority over the starting point, not yet over the position over time. `AZOTH_STATE_POSITION`
defaults to empty.

**Launcher defect found and fixed on the way.** The first attempt failed with `FAIL: window never
appeared`, and it was not the client: **Windows PowerShell 5.1 on this machine loads
`Microsoft.PowerShell.Utility` but does not expose `Get-FileHash`**, which `Start-NwPrivate.ps1` calls
to record the client's source hash. The launcher died with `The term 'Get-FileHash' is not
recognized` — a launcher failure that reads as a client failure. `pwsh` 7 is installed and the runbook
already records that it, not 5.1, is the shell this script needs; `az.py` and `scripts/private-run.py`
now prefer `pwsh` and fall back, so a machine without it behaves as before.

**Validation:** 182 world tests OK (6 new for the position override, 16 new across this work), 24
gateway OK, all three tool self-checks OK. Evidence:
`research/sessions/session-20261014T1746Z-server-owns-the-position/`. Atlas:
`server_owns_the_player_position_measured_20261014`.

## 2026-10-14 (cont. 7) — the server composes the player's own state bundle, and the client applies it

**This is the first place the server OWNS the bytes instead of forwarding them, and it is the
direction the previous negative result pointed at.** Two runs, one question each.

**The fragment grammar is now derived FROM THE CLIENT.** `frida-fragment-grammar.py` hooks the
record reader (`FUN_146af20d0`), the fragment reader (`FUN_146af2340`) and the shared prefix-varint
reader (`FUN_14087b5c0`), and logs each fragment's offset from the record start plus every varint
read inside it. That settles the open question in `bundle.py`'s own docstring: a fragment is
`[varint key][varint type_index][payload]` with **no length field** (the payload length is implied
by the type). The same probe run reproduced the local-player record's nine boundaries **21 times**,
and the (key, type) pair it reported per fragment matches an independent byte-level parse of the
payload — two methods, same answer. Recorded as `research/derived/state-bundle-fragments.json`.

**Run A — recomposition is byte-exact.** With the authoritative path on and no override: **487
recompositions, all 487 `identical: true`, 0 failures.** The identity is asserted on every send, so
turning the path on cannot change behaviour by accident, and a layout that stopped matching the
build would log `state-authoritative-failed` rather than send something wrong.

**Run B — the client accepts state the server wrote.** With
`AZOTH_STATE_OVERRIDE=key=16,off=8,hex=010203`: **672 sends, all `override_applied`**, the logged
transition `0975bf` → `010203`, **0 failures, 0 `Failed to unmarshal`, 0 `ValidationError`**, 1
client error (the known spawn−3 ms GridTracking artifact) and the world rendering normally. So the
client parses and applies a bundle whose bytes we composed.

**`key=16` is the right first target because the capture proves it is live:** across the four
captured copies the payloads differ in **exactly three bytes**, at offsets 5345-5347, and both
values differ per copy (`0975bf` vs `0aa7c2`). A test asserts that is still true, so the constant
cannot drift silently.

**Regressions clear in run A:** movement **0.000 u** baseline → **27.142 u** under W held 5 s (path
27.142, straight) → **0.000 u** after release; cable readout **67 / 330 / 433 ms**; 0
transportError, 0 timeouts, 0 REP disconnects.

**Not claimed:** the overridden field's **meaning** is not decoded. The run establishes that we can
write it and the client accepts it, not what it does — nothing observable changed between run A and
run B under `010203`, so it is either cosmetic state or that value is inert. And the path composes
**one** record from one record's fragments; everything else in the stream is still forwarded
verbatim. `AZOTH_STATE_AUTHORITATIVE` defaults to 0: proven, not yet adopted.

**The next step this opens:** now that a bundle can be composed from named fields, the same method
applies to the field whose effect IS measurable — the player's position, which the client reads
back with its own accessor. That turns "the server composed a bundle" into "the server moved the
player".

**Validation:** 176 world tests OK (10 new), 24 gateway OK, all three tool self-checks OK. Evidence:
`research/sessions/session-20261014T1549Z-authoritative-state/`. Atlas:
`state_bundle_can_be_composed_from_fragments_and_the_client_accepts_it_20261014`,
`state_bundle_fragment_grammar_derived_from_the_client_20261014`.

## 2026-10-14 (cont. 6) — the setters cannot have an authoritative effect yet, and the reason redirects the work

**I set out to give the five state-carrying requests an authoritative effect. The answer is a
measured negative, and it is worth more than the feature would have been: the client does not consume
what they report, and the server's authority channel is not the typed reply at all.**

**1. No client-facet reply exists for them.** Checked per family in the wire-name registry:
`PlayerSettingsComponent` has exactly ONE message (the ServerFacet request). `ObjectivesComponent`'s
only client facets are `OnObjectiveWarning`, `OnMilestoneCorrection`, `SetObjectiveInstanceDisabled`
and a debug one — none is a "here is your state" reply. `GlobalStorage`'s client facets are all
storage-search results behind `0x1b7f`, which the client never sends. So there is no reply message to
build, and inventing one is exactly what this repository forbids.

**2. The one family that HAS a reply is ignored by the client.** I built an instrument for this —
`reverse/probes/client/frida-game-time.py` runs the client's own `lc_getTime` console command and
reads the values it prints (`Current Container Time: h:m:s; t = …; CryTime: h:m; DayPhase: …`),
through the same printer `nw_getPlayerPosition` uses. The handler addresses are derived from the
console-command registration shape and calibrated against the hand-verified
`nw_getPlayerPosition` → `0x141015b30` (`lc_getTime` → `0x141015E80`, `lc_requestTime` → `0x141018E10`).
Four fresh sessions:

| condition | game seconds per wall second | `DayPhase` shown |
| --- | --- | --- |
| baseline, time sync sent | **12.2x** | `day` |
| time sync NOT sent at all | **12.2x** | `day` |
| `0x1097` payload forced to `0` | **12.2x** | `day` |
| `0x1097` payload forced to `3` | **12.2x** | `day` |

The forced value was confirmed ON THE WIRE before drawing the conclusion (`…00000003` outbound, 241
logged override events), so the client received it and still displayed `day`. **The client's clock and
day phase are computed locally at a fixed 12.2x and do not come from `0x1096`/`0x1097`** — they
neither freeze the clock nor set it.

**3. Byte-identical repeats are not a request for an answer.** `0xa95` is sent **17 times inside two
seconds, up to 8 copies in a single datagram**, always with identical parameters; `0x446` 15 times.
That is the client's queue flushing duplicates, not a retry loop, and the registry confirms no reply
exists for either.

**The redirect, which is the actual result.** The one thing ever measured to make the client APPLY
server data is **replicated state**: the player moves while the record-1 `0x08` bundles flow and stops
when they do not. Every typed reply tried so far has no target, no consumer, or no effect. So an
authoritative effect must be expressed as **replicated state**, and the first one to build is a change
to what the `0x08` bundles carry — not another typed message. That also makes ROADMAP item 4's Rust
trigger concrete: the first **state bundle the server composes itself** instead of forwarding a
captured one.

**Two side findings, both acted on.** (a) The request→facet topology is **per-facet and stable**:
every Objectives request carries the same 16-byte target, every Mount request the same one, and so on
— which is why the dispatcher's target-learning is general rather than a special case. (b) The
wire-name registry was giving **one name to two GUIDs**: the `.rdata` descriptor is
`<Name>\0<pad>\0<GUID1>\0<GUID2>` for some types, so the adjacency scan named both. That is how
`ObjectivesComponentServerFacet_UpdateTrackedObjectives` ended up on both `0x5b2` and `0xa4d`.
`scan-wire-names.py` now lets a name be claimed by one GUID only; **146 wire types lost a borrowed
name** (2201 → 2055 named), the eight hand-verified anchors still reproduce, and `0x5b2` is honestly
unnamed with the server's table marking it `(name unverified)`.

**Nothing was left in the runtime.** The day-phase override lever, its helper and its three unit tests
were deleted once the experiment came back negative — `rep.py` is byte-identical to its committed
state, per the repository's rule that a failed alternative does not stay in the code. The negative
lives in the atlas, `research/docs/INBOUND-REQUESTS.md` §3 and the session report.

**Validation:** 166 world tests OK, 24 gateway OK, all three tool self-checks OK,
`scan-wire-names.py --check` OK. Evidence:
`research/sessions/session-20261014T1354Z-authoritative-effect-negative/` (REPORT.md,
clock-samples.jsonl). Atlas:
`state_carrying_requests_have_no_reply_and_the_client_ignores_the_time_sync_20261014`,
`wire_name_registry_gave_one_name_to_two_guids_20261014`.

## 2026-10-14 (cont. 5) — the server answers the client now: the inbound dispatcher exists

**The server had NO inbound typed dispatcher. It has one, verified live, and it learns addresses
from the client instead of guessing them.**

**Why it was needed.** Every typed request the client made was acknowledged at the transport level
and then ignored, with nothing in any log saying so — measured 19 requests in a short session, 29 in
one that exercises more UI.

**The request shape is now measured, not guessed.** Every client->server typed request is
`[u32 crc32][u32 len][16-byte facet target][00 01][varint type][params]`, so after the type marker
the **first 16 bytes are the target facet's local id** — which is exactly the address a reply needs.
The server logged the real shape of all six known requests (`inbound-request-shape`), including
targets and parameter lengths, so the wire layout of a request is now in the record next to its name.

**Two things the dispatcher does that the replay could not:**

| act | evidence |
| --- | --- |
| **Learns the time facet's address from the client itself** | `0x1098` carried `93a3e477cb5fd51ebf85314bbc4a951a`, and the captured `0x1096` body carries the same value as its own target. All **151** `input-response` events report `target_source: client-request` — no longer the capture, and no longer a Frida probe publishing an id to a file. |
| **Answers the contracts request once per ask** | the client asked at `12:08:30` and `12:08:38`; **both** got the captured `0x08E6` (42 B, `inbound-answer n: 1` and `n: 2`). Before, the replay sent each body **once, ever**, so the second ask went unanswered. |

`0x08E6` therefore moved out of the replay's one-shot set into `DISPATCHER_OWNED_RESPONSES`
(`inbound-dispatcher-owned`), and the held set fell from 32 to **31** — the dispatcher owns exactly
the one body it took over.

**Client side, unchanged and clean:** 1 `RMIDispatch` error (the spawn−3 ms `GridTracking` artifact),
0 `OnLocalNetworkConnectionWarning`, 26 slice lines, player possessed. The count is unchanged across
all four sessions since the deferral fix — the four `TimeComponentClientFacet` errors were removed by
that fix two commits ago, **not** by the dispatcher, and saying otherwise would overclaim.

**Regressions checked in the same session:** movement 0.000 u baseline → **22.998 u** under W (path
23.028, straight) → 0.000 u after release; cable readout **498 / 265 / 266 ms** on three samples ~9 s
apart; ACK window still correct (widest 6637, 0 at/over the limit).

**What it deliberately does NOT do:** the five state-carrying requests (`0x9d3` PlayerSettings,
`0x5b2`/`0xa95` Objectives, `0x183` GlobalStorage) are decoded, counted and shape-logged but have **no
authoritative effect** yet. They remain in the coverage line's `no_replay_response`. Inventing a
reply for a setter without evidence is what this repository forbids, so the next step is decoding each
one's params and deciding per request what an authoritative effect requires.

**Validation:** 166 world tests OK (8 new for the dispatcher), 24 gateway OK, all three tool
self-checks OK. `AZOTH_INBOUND_DISPATCH` (default on) and `AZOTH_INBOUND_ANSWER_INTERVAL_S` (0.25)
are both readable from the session's own `config` event. Evidence:
`research/sessions/session-20261014T1208Z-inbound-dispatcher/`. Atlas:
`inbound_dispatcher_answers_requests_and_learns_facet_addresses_20261014`.

## 2026-10-14 (cont. 4) — `az.py doc` is not a clean "what the client requested" source, and the traffic log has lost records

**Found while regenerating the atlas after this session, and the regeneration was REVERTED rather than
committed.** `research/atlas/observed-endpoints.json` claims to be "every endpoint family the New World
client actually requested", and its pipeline is `services/gateway/traffic.jsonl` -> `az.py doc`. Both
halves are currently untrustworthy:

**1. The log contains requests that are not the game client.** Regenerating ADDED two families with an
EMPTY example payload: `/v1/models` (2 hits, 2026-09-26) and `/images` (1 hit, 2026-10-09). Neither is
something the New World client calls; they are local probes that reached the gateway while the log was
recording. The log also holds **274 records for `azoth-1`**, a test world id, not the real world.

**2. The log has LOST real client records.** Regenerating DROPPED
`/prod/game/login/queue/v2/enqueue` and the WorldId config-set variants, which HEAD's atlas recorded -
i.e. a genuine client endpoint disappeared from the tracked file. The log's own `n` counter is
**non-increasing 82 times** (e.g. `n 1481 -> 1`, and the last line is `n 34` after 15 898 lines), so the
file has been rebuilt/truncated and is not one coherent history. Its `/ping` total fell from the
recorded 16 146 to 7 063 for a span whose *first* record is EARLIER, which is only possible if middle
records were removed.

**3. Consequence for the counts.** Every regenerated per-endpoint `hits` figure is lower than the
tracked one and the tracked figures cannot be reproduced from the log that exists now. Rewriting them
would silently discard recorded history while making the file look freshly verified.

**What was done:** both generated files (`observed-endpoints.json`, `openapi.json`) were reverted, so
the tracked atlas keeps its last reproducible state, and this is recorded instead. **What is needed
before the next `az.py doc`:** either keep the client's traffic separate from local health/smoke probes
(the gateway knows the normalised path, so a small allowlist or a source tag at the logger is enough),
or accept that the log is not append-only-across-runs and stop deriving cumulative totals from it. Until
then `az.py doc` output must not be committed blindly.

## 2026-10-14 (cont. 3) — the ACK-window session ended at **1 h 06 min 33 s**, by the documented client-initiated REP disconnect

**The session that validated the ACK fix ran 1 h 06 min 33 s (spawn 09:39:07 → disconnect 10:45:40),
still live when closed by hand, and it ended by the known client-side path — not by a crash and not by
our code.**

**It was a GRACEFUL CLIENT-INITIATED disconnect, read from the bytes.** The client's final datagram
carries a system record `SM_DISCONNECT` (id 3): `[ch3 flags 0x21 size 2 sys 3][ch3 flags 0x18 CT_ACKS]`.
The client then logged `CGame::ActorContainerDisconnect` → `Disconnected from REP` → `Update state
InGame to new state Disconnected`. The server was emitting normally through that exact second
(40 heartbeats/min, 192 state-stream/min, 272 replay/unreliable per min) and correctly dropped the
peer; no server-side event precedes the disconnect by way of a cause.

**It matches the documented REP-disconnect ending, including its signature markers:**
`exiting to main menu` **0**, `Cleanup()` **0**, `Disconnected from REP` **1**. That is the same
signature the runbook records for `AZOTH_CHUNK_GAP_MS=4` — where the 20-minute return-to-menu arm
does **not** fire and the session "ended 26:33 by a REP disconnect". **Our run is that same ending at
1 h 06 min 33 s, i.e. ~2.5x later**, and with zero connection warnings against 682 in the pre-fix arm.
The teardown delegate's first statement still tears the connection down even though
`patch-exit-to-menu.py` successfully skipped the call that would leave the world, which is why the
world stays rendered: the client keeps the **last frame** after tearing REP down.

**What the user sees, and it is exactly explained by this:** the world still rendered at the spawn
point with the ALC readout reporting `Time since last response: 11 m 28 s` (10:57:08 minus the
10:45:40 disconnect) — far past the ~15 s red threshold, hence the red cable — and no movement,
because there is no REP session left to carry the local player's own state. Same mechanism as every
earlier cable/movement failure; only the trigger is different.

**Nothing else looked wrong:** 0 `OnLocalNetworkConnectionWarning` in the whole hour, 0
`transportError`, `[ERROR]` 2 (the spawn−3 ms `GridTracking` artifact plus one client-content
`CameraLock…Combat Profile is invalid`), and every HTTP call succeeded (credential refresh every 5
min, last before the disconnect at `10:42:09`, 200).

**Recovery, and it is not optional:** the client does not rebuild its `ClientContext`, so a new
attempt needs a fresh `NewWorld.exe` — `python az.py world restart` then click Play.

**The next blocker is now precise and it is client-side:** what arms the teardown. The runbook's own
conclusion stands — "to keep a session past 20 minutes the **arm** must be prevented" — and this run
shows the arm now fires at ~1 h instead. That, plus the still-open inbound dispatcher, are the two
remaining items.

## 2026-10-14 (cont. 2) — the end-of-session storm had a server cause: our ACK range grew past half the 16-bit space

**The client's retransmit storm is fixed, and it was our bug — an addressing window, not load.**

**The defect.** The Carrier CT_ACKS is a CONTINUOUS range `[ack_first, ack_last]` carried in two
**16-bit** fields. `ack_first` was pinned to the session's first inbound envelope sequence, so the
acknowledged range grew by exactly one per datagram for the entire session. Once the range passes
**half the 16-bit space (32768)** a wrap-aware reader can no longer tell how wide it is — and the
client's response to that is not an error, it **retransmits**.

**The onset is exact, to the second, measured in the 34-minute pre-fix session:**

| event | value |
| --- | --- |
| last inbound envelope seq below the boundary | `32767` at `08:42:44` |
| first at/above | `32768` at `08:42:44` (ACK range width `32766`) |
| first retransmitted client record | reliable seq `1836` at `08:42:45` — records 1-1835 had each been sent **exactly once** |

From there the client re-sent every reliable record it produced: **140 174 inbound channel-0
records in 10 minutes carrying only 660 distinct sequences — a 212x retransmit factor**, against
**1.2x** earlier in the same session. The same storm caught wire 3639 (3 133 records, 202 distinct,
15.5x), which corrects my earlier reading of it as a mysteriously sustained request: it was a
victim, not a separate phenomenon.

**It is not load, transport, or our reliable stream — three quantities measured constant across the
onset:** the server's outbound rate (2 626/min), its ACK send rate (665/min), and its own outbound
reliable-sequence stream (no gap; two reordered pairs, no missing value).

**The fix.** `rep.py::ack_window_first` returns a **sliding** window instead of a pinned one:
`ack_last - (min(datagrams_seen, ACK_WINDOW) - 1)`, computed in 16-bit wrap space from a
**monotonic datagram count** so it also survives the 65536 wrap a pinned range could not.
`ACK_WINDOW` defaults to **16384** — half the safe maximum, and still ~13 minutes of history at the
measured ~21 inbound datagrams/s. New lever `AZOTH_ACK_WINDOW`.

**Verified live as a one-variable A/B, both arms the same build, env and machine, probe-free:**

| | pre-fix (spawn 08:16:51) | fixed (spawn 09:39:07) |
| --- | --- | --- |
| crossed 32768 at | `08:42:44` | `10:05:05` |
| widest CT_ACKS range | **56210** | **16383** |
| CT_ACKS at/over 32768 | **7496** | **0** |
| wire 349 retransmit factor | **64x** (142 088 records / 2 212 distinct) | **1.0x** (1 727 / 1 724) |
| wire 3639 retransmit factor | **15.5x** | **1.0x** |
| `OnLocalNetworkConnectionWarning` at ~29 min elapsed | ~100, climbing 0.8/s | **0** |
| client `[ERROR]` lines | 6 | 2 (the spawn−3 ms GridTracking artifact + one client-content CameraLock) |

`transportError` 0, `State(InGame) is timeout` 0, `Disconnected from REP` 0, and the world server's
emitter rates unchanged. The client logged **zero connection warnings in 31+ minutes**, where the
pre-fix run had ~100 by the same point.

**New tool:** `scripts/ack-audit.py` (`--check`) reports the widest CT_ACKS range, whether any
reached 32768, the envelope crossing, and the per-type retransmit factor. It **exits 1 on the
pre-fix log** (7 496 ACK ranges at/over the limit, first at `08:42:44` with `first=2 last=32770`)
and 0 on the fixed one, so the defect and its absence are both reproducible from a log alone.

**Validation:** 157 world tests OK (6 new in `TestAckWindow`, including the exact boundary that
broke the client and the 16-bit wrap), 24 gateway OK, `ack-audit.py --check` OK,
`inbound-inventory.py --check` OK, `request-response-map.py --check` OK. Evidence:
`research/sessions/session-20261014T0939Z-ack-window/` (NOTES.md, ack-audit.txt,
server-events.jsonl, Game.log). Atlas:
`ack_range_pinned_to_session_start_breaks_the_client_at_32768_20261014`.

**Not claimed:** that sessions no longer crash. The fix removes a measured storm, and the run above
lasted **1 h 3 min 7 s** against a 34 min 10 s best for the pre-fix arm — but that duration figure is
**one run**, and the crash history has at least three distinct signatures. Duration stays open until
a 2-hour soak.

## 2026-10-14 (cont.) — the response direction is now request-correlated, and the inbound inventory is complete

**The two directions of the typed contract are now measured by tools that fail loudly, not by
hand-checked tables.**

**Inbound: every client→server type is named, counted and classified.** `scripts/inbound-inventory.py`
now resolves names from three registries (the build's type table, the Javelin registry, the AZ
registry), classifies each type (`request` / `notification` / `transport` / `input-stream` /
`v3-registration` / `unknown`) and self-checks with `--check`. One session: 8909 datagrams,
**37 distinct client→server types** — 19 requests, 8 transport, 1 input stream, 1 V3
re-registration, **8 typed-but-unnamed**. Artifact `research/derived/inbound-requests.json`;
full tables in the new `research/docs/INBOUND-REQUESTS.md`.

**The 8 unnamed types are runtime-registered.** Their GUIDs are absent from the executable as
dashed text *and* as raw bytes (checked), so no static scan can name them; `typeindex.json` was
itself produced by a runtime probe. Wire **19** is recovered as `RegistrationRequestV3Msg` — the
1115-byte `0x13` blobs are the client's V3 re-registration, not a game request. Naming the rest
needs a live send-side class-name probe.

**Outbound: the drop table is gone, replaced by request correlation.** The old policy decided by
whether the client *had the facet*; the measurement that actually supports the decision is
whether the client *sent the request*. The replay is another client's capture, so it answers
questions ours never asks. `rep.py::_deferred_decision` now holds each captured typed response
until the client's object graph exists, then sends it only if the client sent the request it
answers (`RESPONSE_REQUESTS`, pairs derived from the capture's ordering and the family naming).
It is wrong in both directions and both are fixed:

| response | old | new | why |
| --- | --- | --- | --- |
| `0x1067` VoiceChat `OnVoiceChatServiceRegistered` | dropped | **sent** | the client *does* send `0x066B` |
| `0x16A0` Inventories `OnQueryInventories` | sent unasked | **dropped** | the client never sends `0x169D` |
| `0x1B88` GlobalStorage `ReceiveStorageSearchItems` | dropped (facet absent) | **dropped** (request never sent) | same outcome, honest reason |
| `0x0CA4` EventNotification `SyncNotifications` | dropped | **dropped** | the only static drop left: unsolicited + absent facet |

New lever `AZOTH_REPLAY_REQUEST_GATING` (default 1) for the A/B, plus
`AZOTH_REPLAY_DEFER_TIMEOUT_S` (default 20). New self-verifying tool
`scripts/request-response-map.py --check` re-derives the pairs from the capture and fails on a
contradiction. The server now logs `replay-defer-start`, `replay-response-suppressed` (with its
reason) and one `inbound-request-coverage` line per session that splits the client's inbound
types into `answerable_by_replay` and `no_replay_response`.

**A naming discrepancy recorded, not silently resolved.** The client reports
`GridTrackingComponentClientFacet_UpdatePhasing` for the response we send as wire `0x1033`, but
the wire-name registry pairs that *name* with wire **930**, which the capture does not contain.
The client's own error is the authority for what it received, so the table keeps `0x1033` and
the mismatch is documented.

**VERIFIED LIVE, twice (2026-10-14).** Two clean sessions, the second probe-free against the
final code. `replay-response-scheduling` held **32** responses both times, and the gate decided
them **identically** in both runs:

| outcome | wire | count | reason |
| --- | --- | --- | --- |
| **sent** | `0x08E6` Contracts `OnLookupContractsByParticipant` | 1 | client sent `0x09FC` |
| **sent** | `0x1033` GridTracking `UpdatePhasing` | 1 | client sent `0x101E`/`0x102E`/`0x102F`/`0x192C` |
| **sent** | `0x1067` VoiceChat `OnVoiceChatServiceRegistered` | 1 | client sent `0x066B` |
| **sent** | `0x1096` / `0x1097` Time `Sync{TimeChange,DayPhase}` | 2 | client sent `0x0635`/`0x1098` |
| suppressed | `0x1B88` GlobalStorage `ReceiveStorageSearchItems` | 23 | `request-not-seen` (`0x1B7F` never sent) |
| suppressed | `0x16A0` Inventories `OnQueryInventories` | 2 | `request-not-seen` (`0x169D` never sent) |
| suppressed | `0x136A` GameModeParticipant `OnLeftQueueForGameModeMsg` | 1 | `request-not-seen` (`0x0CED` never sent) |
| suppressed | `0x0CA4` EventNotification `SyncNotifications` | 1 | `facet-absent` (unsolicited) |

**The client end: exactly 1 `RMIDispatch` error both times**, `GridTracking` at spawn−3 ms — the
known client-side artifact, unchanged in kind. The two decisive facts are absences:
**no `VoiceChatComponentClientFacet_*` error although `0x1067` is now sent** (the old policy
discarded it; the client accepts it) and **no error for `0x16A0` although it is now suppressed**
(it had been going out unasked and was never needed). After the spawn line: `[ERROR]` 0,
`transportError` 0, `State(InGame) is timeout` 0, `Disconnected from REP` 0.

**Regressions checked and clear in the same sessions.** Movement: baseline **0.000 u**, W held 5 s
**23.270 u** with path 23.303 u (straight), **0.000 u** after release. Cable: the client's own
`Time since last response` read **717 / 431 / 98 ms** on three samples ~10 s apart, far under the
~2 s amber threshold. World rendered both times (26 slice lines).

The new `inbound-request-coverage` line, measured: `inbound_types 50, request_types 29,
answerable_by_replay 7, no_replay_response 22` — and the 22 are all channel-0 requests, the
Carrier noise gone (the first live line had listed 13 channel-3 records as waiting on us, which
is why `_counts_as_request` was added).

**Two honest corrections and one new observation from this session.** (1) `measure-cable.py`
reported `absent/other` on the first session, but **its crop landed on wooden beams, not the HUD**,
so its verdict is unusable for that frame; the ALC readout above is the real instrument. (2) The
first session died at **11 min 46 s** with WER `BEX64`, `P4: frida-agent.dll_unloaded`, `P7: 0x9c7e0`,
`P9: 8` — the documented execute-after-unload race, **caused by my own position probe**, which still
ended with a bare `session.detach()` 8 min 48 s earlier. `frida-player-position.py` now ends through
`_paths.safe_shutdown()` (`kill` by default, `--keep-process` for the orderly path). Most probes
under `reverse/probes/client/` still call `session.detach()` directly; that systemic cleanup is
recorded here, not done silently in this change.

**(3) The probe-free run lasted 34 min 10 s — the longest session measured on this build.**
Spawn `08:16:51`, last client log line `08:51:01`, with `transportError` 0, `State(InGame) is
timeout` 0, `Disconnected from REP` 0, and the world server emitting a steady ~59 heartbeats /
~285 state-stream / ~59 input-response per minute throughout. That exceeds the ~12–22 min range
`STATUS.md` previously recorded, so the response-gating change did not shorten a session. It is
**one** session, so it is not a 2-hour soak and does not overturn the crash history.

**New open observation, measured and not diagnosed.** `OnLocalNetworkConnectionWarning
countReceived` climbs from spawn+1s at ~1 per 16 s, then at **spawn + 27 min 14 s** accelerates
about **24×** to ~0.7–0.85 s per warning (1→101 took 1633 s; 101→201 took 69 s; 401→682 took
0.78 s each). It is **not a transport failure**, and that was checked: the client's own derived
flag is **`Client.ConnectionWarning: 0` in all 19 occurrences** and it keeps re-asserting 0, there
are 0 timeouts and 0 REP disconnects, the server keeps emitting normally, and the state stream's
`wire_seq` is monotone with **0 decreases** (128 → 9644, no wrap). So a cumulative counter
accelerates at ~27 min while the client's own warning flag stays clear. Recorded as an open
question with one suggested experiment (raise `AZOTH_REPLAY_STATE_STREAM_PLAYER_PERIOD_S` from
0.25 to ~1.0 and see whether the onset moves), not as a finding.

**The other 5 client errors are not ours:** 2× `SlayerScriptComponent: Attempted to reference an
unknown entity` and 3× `CameraLockComponentClientFacet: Camera Target Lock Combat Profile is
invalid` — client content/GDE data, neither in the response-gating path.

**Validation:** 151 world tests OK (6 new cases for the gate: rule coverage, hold-until-request,
drop-without-request, unsolicited-absent-facet, channel-0-only coverage, and the honest gating-off
A/B), 24 gateway OK, `inbound-inventory.py --check` OK, `request-response-map.py --check` OK.
Evidence: `research/sessions/session-20261014T0758Z-response-gating-e2e/` (NOTES.md,
server-events.jsonl, Game.log, position-samples.log, alc-response-strip.jpg) and
`research/sessions/session-20261014T0815Z-response-gating-probe-free/` (NOTES.md, server-events.jsonl,
Game.log). Atlas:
`inbound_request_inventory_is_complete_and_classified_20261014`,
`response_scheduling_is_request_correlated_not_facet_correlated_20261014`.

**The gap that remains is unchanged and now visible in every session:** there is still no
inbound typed dispatcher, so all of them are ignored. Measured per session: **19 requests** in a
short session, **29** in one that exercises more UI. Next: answer the five a playable world
needs, starting with `ContractsComponentServerFacet_LookupContractsByParticipant` (2556), whose
matching `0x08E6` response the capture already contains.

## 2026-10-14 — completeness audit: the client asks 43 things and we answer none; the replay used to answer questions nobody asked

**Both directions of the client/server contract were broken, and one of them was invisible.**

**Inbound: 43 request types, 0 answered.** Measured with a new tool (`scripts/inbound-inventory.py`)
over a live session: the client sends **43 distinct typed request types** and the server has **no
inbound typed-message dispatcher at all** (`grep -c dispatch_inbound` → 0), so every request is
acknowledged at the transport level and then ignored, with nothing in any log saying so. By channel:
channel 1 = 13 894 records, **all** of them the ALC input stream (wire 1589); channel 0 = 832, of
which 703 are `PingMsg`; channel 3 = 14 670 system records. None of the 43 currently produces a
client-side complaint, which is exactly why the gap stayed invisible. **Visibility fixed:** the server
now logs each distinct `(channel, type)` once per session (`event: inbound-typed`), so every future
session carries its own request inventory.

**Outbound: we were answering questions the client never asked.** The replay is *another client's*
capture, so it contains the server's answers to requests our client never makes. A clean session
logged **29** `RMIDispatch: facet target ID couldn't be found` errors, all in a single millisecond,
**1 ms before `player spawn succeeds`**, while the replay drains **8 s after** it. Which fix is right
depends on whether the client has the facet at all (measured against the live entity's 107 bound
facets): **absent → drop** (GlobalStorage, EventNotification, VoiceChat), **present but not built yet
→ defer until the replay drains** (TimeComponent, GameModeParticipant, GridTracking, Contracts).
Dropping loses nothing — the request behind the 23 storage-search replies is wire 7039, which is not
among the client's 43.

| dispatch errors per session | |
| --- | --- |
| before | **29** |
| after dropping the 25 unreceivable | **3** |
| after the input-response waits for the client's object graph | **1** |

That last fix is a real distinction the code had wrong: the **heartbeat** is a *transport* ping and
must not wait for the replay (the client's watchdog is ~27 s), but the **input-response** is a
*client-facet RMI* and the facet does not exist until the client is in the world. They shared one
readiness predicate, which sent the first input-response 1 s before spawn.

**The one remaining error is not ours.** `GridTrackingComponentClientFacet_UpdatePhasing` fails at
spawn−1 ms while the message we send arrives **8 s after** the error, and the same single error appears
in every session measured — including one with the state stream off. It is a client-side artifact of
its own spawn sequence, bounded at one per session.

**`SERVER-CONTRACT.md` was materially wrong and is corrected.** It listed movement authority and entity
replication as **missing**, and attributed the HUD cable to the input-response lever. Both are wrong:
movement and the cable are the *same* record (record_id 1, the local player's own state), and the
`0x1096`/`0x1097` pair is delivered 828 times per session without clearing the cable. The file now
carries the measured tables, the inbound-request section and the response-scheduling rules.

**Also hardened:** `scan-wire-names.py` was returning printable noise as type names (`F)@`, `p<WF`) and
now requires an identifier shape with a lowercase run, plus a fallback to the AZ registry — coverage
went from 1833 (with noise) to **2201** clean names, and it recovered the important
`7048 = GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`.

**Validation:** 145 world tests OK (7 new cases), 24 gateway OK, all four registry scanners self-check
clean. Evidence: `client_asks_43_request_types_and_the_server_answers_none_20261013`,
`unrequested_client_facet_responses_were_dropped_or_deferred_20261013`.

## 2026-10-13 (cont. 5) — **WASD VERIFIED: all four directions, correct geometry, stops on release**

Position sampled at 0.2 s with the client's own accessor, each sample wall-clock stamped and each key
phase bounded by a recorded marker. Keys sent as real scan codes. Env: **the mandatory three only** —
the state stream is ON by default and needs no variables.

| phase | samples | net move | path | delta (dx, dy, dz) |
| --- | --- | --- | --- | --- |
| baseline (no input) | 28 | **0.000 u** | 0.000 | (0, 0, 0) |
| **W** held 5 s | 27 | **22.998 u** | 23.039 | (+10.079, −20.672, +0.013) |
| **S** held 5 s | 37 | **18.975 u** | 18.980 | (−8.341, +17.043, +0.003) |
| **A** held 5 s | 37 | **4.515 u** | 5.412 | (+4.018, +2.060, +0.158) |
| **D** held 5 s | 38 | **9.359 u** | 9.793 | (−8.212, −4.488, −0.131) |
| after release | 10 | **0.003 u** | 0.003 | ~0 |

```
angle W vs S = 179.9 deg   (opposite)        angle W vs A = 91.2 deg   (perpendicular)
angle A vs D = 178.5 deg   (opposite)        angle W vs D = 87.3 deg   (perpendicular)
vertical drift over ~23 u of horizontal travel: within 0.16 u
```

Four independent properties say this is real movement and not a canned or random displacement:
the opposing keys are near-exactly anti-parallel; the perpendicular pair is near-exactly orthogonal
to forward; **path ≈ net in every phase** (23.039 vs 22.998) so the motion is straight with no jitter
or rubber-banding; and the player is **still with no input and stops again within 2 s of release**.
Same session, no probe attached: **cable absent, red 0.0 %**. Evidence:
`WASD_verified_all_four_directions_20261013`, `research/sessions/session-20261013T2205Z-WASD-verified/`.

**The config is now three variables:**

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'
python az.py dev
```

**Still outstanding, and it is only duration:** movement is verified over 5 s windows inside a session
that ran ~22 min. No 30-minute proof and no 2-hour soak yet. Soak runs must be **probe-free** — the
last client crash was `frida-agent.dll` at `0x9c7f4`, caused by a measurement probe.

## 2026-10-13 (cont. 4) — **BOTH GATES MET: the player MOVES and the red cable is GONE**

**The player moves, and one missing record explains both symptoms.** For the whole history of this
project the local position was frozen at exactly `(9343.6416, 2786.7327, 87.538)` and W did nothing —
667/667 identical samples in the most thorough earlier measurement. It moves now.

**Movement, measured three times (position via the client's own accessor, 0.2 s sampling):**

| run | no input | W held | result |
| --- | --- | --- | --- |
| movement (21:20Z) | frozen, net 0.0 u | **92 distinct positions, net 83.026 u** | moves |
| **repro (21:47Z)** | 2 samples, net **0.0 u — STILL** | **55 samples, 53 distinct, net 20.784 u** | **moves** |
| **A/B, stream OFF (21:55Z)** | — | **5 samples, 1 distinct position** = the old frozen constant | **does not move** |

The two moving runs displace in **different world directions** (`(-10.3, +82.4)` vs `(+9.3, -18.6)`),
which is what WASD-relative forward looks like when the character faces a different way — evidence the
motion is the player's own movement, not one canned offset.

**The A/B is one variable and it settles causation:**

| | `state_stream=ON` | `state_stream=OFF` |
| --- | --- | --- |
| W held 10 s | **moves 20.8 u** | **frozen at `(9343.6416, 2786.7327, 87.538)`** |
| HUD cable | **icon absent** | **RED (3.7% red)** |
| ALC stamp | refreshing (225 changes / 140 s, age ≤ 100 ms) | frozen, age grows |

**Mechanism.** The client only simulates the local player while it is receiving the player's own AOI
state. Our server replayed the capture once and then stopped. Resuming it was not enough either,
because with the old floor of `0xA0` the stream re-sent only **other** entities' records
(`0xA0..0xB0` carry ids 22, 29, 10, 30, 60, 79, 87, 44, 88, 58, 89, 72, 90, 35, 91, 92, 70) and never
**record id 1 — the local player**. The floor is now `0x94`, which includes the four record-1 bundles
(seq `0x98/0x9A/0x9C/0x9E`), and they are additionally re-sent at **4 Hz** so the ALC stamp stays
younger than its ~2 s amber threshold. **The same missing record explains both symptoms.**

**The state stream is now the correct default, not an experiment.** It was OFF by default because a
2026-10-04 version broke REP at +23 s; that was the counter rewrite writing **one raw byte**, which
widens a one-byte varint into two and shifts every fragment. The rewrite now re-encodes through the
verified parser, and it defaults ON. A silent bug was found and fixed while doing this:
`AZOTH_REPLAY_STATE_STREAM_ONLY_RECORD` was an **equality against its own sentinel**, so the default
`-1` matched **no** bundle — the stream armed with `count: 0` while the config event still said
`state_stream: True`. Fixed, tested, and the arming event now logs `count`/`seqs`/`player_bundles` so an
empty arm is visible.

**Config that works (the state stream needs no variables at all now):**

```powershell
$env:AZOTH_REPLAY_LOCAL_PLAYER_UUID = 'character'
$env:AZOTH_REPLAY_INPUT_RESPONSE    = '1'
$env:AZOTH_RESEND_INTERVAL_S        = '1.0'
python az.py dev
```

**Not yet proven, and next:** movement was measured over 10-12 s windows inside sessions that lived
~22 min; there is no 2-hour soak yet, and the session still dies on a client crash (the last one was
`frida-agent.dll` at `0x9c7f4`, caused by **my own probe** — the movement the user observed was in a
clean session with no probe attached). Evidence:
`MOVEMENT_WORKS_state_stream_enables_player_simulation_20261013`,
`state_stream_defaults_are_the_fix_not_an_experiment_20261013`, and bundles
`research/sessions/session-20261013T2120Z-MOVEMENT-and-cable-fixed/`,
`.../session-20261013T2155Z-AB-state-stream-off/`.

## 2026-10-13 (cont. 3) — **THE RED CABLE IS FIXED**, and the position is no longer frozen

**The red cable is fixed, and it was one record id.** The cable is a pure client-side age of the ALC
local client's `+0xAA8` stamp (`age = clock() - *(alc+0xAA8)`; amber ~2 s, red ~15 s). A new probe
(`frida-alc-stamp.py`) learned the ALC object and logged every change of that stamp:

| what the server sent | stamp changes in ~140 s | max age seen | cable |
| --- | --- | --- | --- |
| replay + input-response (the old default) | **1** | **262 000 ms** | RED |
| + state stream from seq `0xA0` | **1** | 250 000 ms | RED |
| + state stream from seq `0x94` | 12 | ~100 ms | YELLOW |
| **+ stream = ONLY record id 1, 4/s** | **225** | **100 ms** | **icon GONE** |

**What refreshes it is the local player's own state record.** In the capture that is `record_id 1`
and it appears only in the four 7154-byte bundles at replay seq **0x98/0x9A/0x9C/0x9E** — all *below*
the stream's old default floor of `0xA0`, so the stream was re-sending **everybody else's** state and
never the player's. The fixed run's own arming event proves it:
`{"count": 4, "seqs": ["0x98","0x9a","0x9c","0x9e"], "only_record": 1, "period_s": 0.25, "loop": true}`.

Config that fixes it (on top of the mandatory `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`,
`AZOTH_REPLAY_INPUT_RESPONSE=1`, `AZOTH_RESEND_INTERVAL_S=1.0`):

```
AZOTH_REPLAY_STATE_STREAM=1
AZOTH_REPLAY_STATE_STREAM_SEQ=1
AZOTH_REPLAY_STATE_STREAM_MIN_SEQ=0x94
AZOTH_REPLAY_STATE_STREAM_ONLY_RECORD=1     # NEW lever (rep.py)
AZOTH_REPLAY_STATE_STREAM_PERIOD_S=0.25
```

**Also, for the first time, server-sent data changed the player's position.** Every previous session
had the position frozen at exactly `(9343.6416, 2786.7327, 87.538)`. With the record-1 stream active
it reads `(9354.0039, …)` and drifts through **50 distinct values** before settling. **But movement is
NOT solved:** the honest control in the same run gave `[0.0,0.0,0.0]` with no input over 10 s **and**
`[0.0,0.0,0.0]` with **W held for 10 s**. The drift was a one-time convergence onto the state we send;
the player is then static and W still does nothing. What is new is that the client now **applies** the
local player's replicated state — which is the mechanism the server would use to move the player.

**Next experiment (now possible):** take a record-1 bundle, modify its position field, send it, and see
whether the player goes there. If it does, the server becomes authoritative over the position.
Evidence: `RED_CABLE_FIXED_record1_state_stream_refreshes_the_alc_stamp_20261013`,
`local_player_position_is_no_longer_frozen_once_record1_state_is_streamed_20261013`, bundle
`research/sessions/session-20261013T2039Z-cable-fixed/`.

## 2026-10-13 (cont. 2) — the runner was calling HUNG LOADING SCREENS "player possessed"; baseline red cable measured properly

**I spent most of a session measuring a hung client, and the reason is an instrument defect worth more
than any result here.** `scripts/private-run.py` printed `verdict: InGame reached, player possessed` on
the strength of the state machine, and a client **hung on a loading screen** satisfies that: it logs
`player spawn succeeds` and `Update state WaitingForPlayerSpawn to new state InGame` and then sits
there. Measured, two sessions on this build:

| session | post-spawn non-boilerplate lines | `[WARNING] Slice:` | what it really was |
| --- | --- | --- | --- |
| ch1 server-container (17:44Z) | 5 | **0** | loading screen, window said "(Not Responding)" |
| baseline (19:11Z) | 35 | **26** | **world rendered** — character, village, full HUD |

One of those hung sessions was the "~60 minutes alive" I reported: the **network stack and the server
kept running normally while the client was frozen**, and Game.log accumulated nothing but connection
warnings. That is why it looked like a long stable session and was not one.

**Fixed in the runner:** it now waits up to `--render-timeout` (default 90 s) after the spawn marker
for the first `[WARNING] Slice:` line, reports the count in the verdict, and **exits 1** with a loud
verdict when the state machine says InGame but no slice lines were seen. From now on the mechanical
"did it render" signal is the slice count, never `InGame`. Evidence:
`in_game_state_machine_does_not_mean_the_world_rendered_20261013`.

**Baseline red cable, measured on a session that really rendered** (26 slice lines, state machine to
InGame, **0 timeouts**): **RED (disconnected)**, red 3.66%, yellow 1.77%, screenshot kept. Two
measurement traps recorded because both gave false readings first: a desktop capture must be cropped to
the game window's client rect before the documented indicator box is applied (otherwise it reads
`absent/other`), and a loading screen does not draw the cable at all. Evidence:
`red_cable_reproduced_on_a_rendered_session_20261013`.

**Channel-1 container A/B, executed and attributed.** Answering the client's channel-1 input stream on
**channel 1**: with the **capture's server container** the client reaches InGame with **0 timeouts**;
with the **client's own `[crc32][len][target]` container** it stalls at `WaitingForActorGameConnection`
with repeated timeouts and never spawns — and logs no unmarshal/CRC/unknown-type error, so it fails
silently. So the container was the poison, not the channel.

**Also this session:** the ALC stamp writer is still not found, and two more candidate explanations for
the red cable are now measured out (delivered input responses; the state stream). The remaining
candidate with support is that the stamp is refreshed by **`MB::ALCReplicatedState`** — whose replicated
field list includes `worldPosRel`/`worldPosAbs`, so the state that would clear the cable is also the
state that carries the position.

**Gates: still not met.** The red cable is reproduced on a properly rendered session; movement is
unmeasured this session. What improved is that the experiment stopped lying about whether a session was
alive.

## 2026-10-13 — the ALC reply IS delivered and the cable still goes red; the "wrong target" theory is refuted

**This session's result is a correction, and it removes the leading theory for the cable.**

**1. The position is INSIDE the ALC's replicated state.** The `ALCReplicatedStateAllocator` descriptor
carries its replicated field names, and they include **`worldPosRel` / `worldPosAbs`, `rotation`,
`lookDir`, `timeOffsetRel`/`Abs`, `slayerSeqTimeRel`/`Abs`, `scopeData`, `forbiddenBounds`** — so the
player's world position is a field of `MB::ALCReplicatedState`, the object `FUN_142a3b050` allocates by
name at **0x1560** bytes. The cable's clock and the position being missing are therefore the *same*
replicated state, which is why one thing is missing and not two.

**2. The ALC reply is delivered at 2/s for the whole session — and the cable still turns red.** This
is the decisive measurement:

| fact | value |
| --- | --- |
| `input-response` events the server sent | **414** (828 messages) |
| client `facet target ID couldn't be found` for `TimeComponentClientFacet_Sync*` | **4**, all in one millisecond |
| when those 4 happened | **one millisecond BEFORE `player spawn succeeds`** |
| the id in the error | `10638597947943539998` = **`0x93a3e477cb5fd51e`** |
| is that id registered in our session? | **YES** — `TimeComponentClientFacet` holds four local ids and that is one of them |

So the only failures are the pre-spawn ones, and **every later reply was dispatched without error** —
and the cable still went RED. Two conclusions: **(a) the red cable is not caused by the client failing
to receive our input response**; **(b) `0x1096`/`0x1097` are NOT what refreshes the ALC stamp.** The
lever's own docstring ("our replay sends them once, then the client HUD's *time since last response*
climbs") is measured to be wrong about the refresh — sending them 2/s changes nothing. Evidence:
`alc_reply_is_delivered_and_the_cable_still_goes_red_20261013`.

**3. The "wrong target" theory is refuted, and yesterday's label corrected.** The capture's id is
registered here, so re-addressing the reply to it is not "a target the client does not have". What
survives for the movement work is the part that matters: delivering a position to a
`TimeComponentClientFacet` still does not apply it. `position_reply_timecomponent_target_is_a_false_fix_20261012`
now carries that correction.

**4. The `+0xAA8` writer is still not found, and the reason is recorded.** Of the 42 functions writing
`[reg+0xAA8]`, the one that also calls a clock is a **constructor** where `+0xAA0`/`+0xAA8` are a
`std::string`'s capacity/size pair (`0xf`, `0`), and its clock call stores into a different field
(`+0xB18`). The `lea [reg+0xAA8]` site near the HUD is a **debug formatter** building an array of field
*addresses* to log. So the stamp's writer must be found **by class**, not by offset — `+0xAA8` is shared
by several classes and is inside a string triple in some. Evidence:
`alc_stamp_writer_not_findable_by_displacement_20261013`.

**Next step, now much better constrained.** The ALC stamp is refreshed by the **ALC replicated state**,
not by a typed message. That makes the whole problem one thing: find the record/fragment that carries
`MB::ALCReplicatedState` (its own field list includes `worldPosRel`/`worldPosAbs`) and whether the
capture contains it. The capture's steady-state tail carries record ids 22, 29, 10, 30, 60, 79, 87, 44,
88, 58, 89, 72, 90, 35, 91, 92, 70 — and **the local player's actor id appears only in the spawn
record (record 1), never in the state flood**, which is why streaming those bundles could not have
delivered the player's position (measured: the stream does not move the player, cont. 10).

**Gates: still not met.** Movement unchanged; cable still red. What changed is that the cable's cause is
now narrowed to one missing piece of replicated state, with the two most popular theories (wrong
target; needs a typed response) both measured out.

**5. The ALC state's registration and allocation are located.** `FUN_142a3d460` registers
`ALCReplicatedState` (descriptor `{0x8000, 0x1570, 0x1570, ...}` — note **`0x1570 == 0x1560 + 0x10`**,
the object size plus alignment), `FUN_142a43b30` allocates an **array** of them at `0x1570` stride, and
`FUN_142a3b050` allocates one by name. So the engine tracks **multiple** `ALCReplicatedState` instances
— one per actor — which is a concrete reason the local player's own state cannot be assumed to be "the"
ALC state. Evidence: `alc_replicated_state_registration_and_allocator_20261013`.

**A method correction, again worth more than the result.** The first search for these users was a
whole-`.text` linear Capstone sweep that reported **0** references to the `ALCReplicatedState` name —
while the function that creates the object plainly contains `142a3b117 lea rdx,[rip+0x56c3c72]`
pointing at it. A linear sweep over 132 MB desynchronises on data, and one bad byte silently swallows
every later reference, so the failure looks like a confident negative. New tool
`reverse/tools/find-rip-lea.py` matches the RIP-relative LEA *opcode pattern* instead and cannot
desync; it reproduces the by-hand result and found the complete reference sets.

**New tooling this session:** `reverse/probes/client/frida-facet-target-id.py` (reads the client's own
RMI target registry and names each target by its AZ type, so a facet's per-session local id is a lookup
instead of a guess; `--publish` writes an id to `.azoth/state/alc-target.txt` for the server), the
`AZOTH_REPLAY_INPUT_RESPONSE_TARGET` lever (`file` re-reads the id every send, so a live probe can
re-address the reply mid-session), `retarget_typed_body()` with 4 new unit tests, and
`scripts/prejoin-smoke.py`.

## 2026-10-12 (cont. 10) — the red cable is IDENTIFIED as the ALC, the ALC state is replicated state, and the state stream is ruled out

**Three results, and the first two are the strongest the cable work has had.**

**1. The red cable IS the ALC's `server-timeout-for-input`. Confirmed three ways.** (a) `FUN_140208350`
initialises a block at `0x149f20ee8` whose first field is the pointer to the string
`javelin.alc-server-timeout-for-input` (`0x147fd8ec0`), followed by
`javelin.alc-server-timeout-for-ui`. (b) The per-frame HUD function `FUN_14486c740` reads its two cable
thresholds out of the **same** block (`_DAT_149f20f90` amber, `_DAT_149f21048` red). (c) The string
`ALCLocalClient` has **exactly one xref in the whole image**, at `0x14486d833`, **inside
`FUN_14486c740`** — so that function *is* the ALC local client, and its
`age = clock() - *(u64*)(self+0xAA8)` comparison against those thresholds *is* the cable. The icon is a
pure client-side age of one timestamp, and that timestamp belongs to the ALC. Evidence:
`red_cable_is_the_alc_server_timeout_for_input_20261012`.

**2. The ALC's authoritative state is AOI REPLICATED STATE, like the position.** The image contains
`InstallRegistrationHook<MB::ALCReplicatedState>` — the same mechanism already recorded for
`VPositionInTheWorldReplicatedState` — and `FUN_142a3b050` allocates the object **by name** through the
AZ reflection registry with the `ALCReplicatedState` RTTI, size **0x1560** (5472 bytes). So the
hypothesis that now fits BOTH symptoms is: *the cable going red and the player not moving are the same
missing thing — the server never delivers the ALC/position replicated state.* That is a hypothesis with
a specific test, not a conclusion: identify the trait that owns `ALCReplicatedState` (its record id /
fragment key), the way `PhysicsTrait` owns its state type. Evidence:
`alc_state_is_replicated_state_not_a_message_20261012`.

**3. The state stream is RULED OUT, in both forms.** The lever's own comment asked for the run with the
seq rewrite on. Measured:

| run | `state-stream` sent | client errors | cable | W held |
| --- | --- | --- | --- | --- |
| rewrite OFF | 697 | `Failed to unmarshal` 0 | — | — |
| rewrite **ON** | 126 | `Failed to unmarshal` 0, `recursion` 0 | **RED** (3.23% red) | position **unchanged** |

With the rewrite off the client reported no errors and the world behaved exactly as if nothing had been
sent — which confirms that **"no errors" does not mean "applied"**. With it on, the cable stayed red and
a 10 s W hold left the position at `(9343.6416, 2786.7327, 87.538)`, the same value as every run before
it. **Honest limitation:** the new gate probe (`frida-repl-gate.py`) reported
`calls=261 accepted=261 rejected=0 distinctSeqs=1` — the field at `msg+0x28` is constant, so it is not
the per-message sequence and **per-bundle acceptance is still unmeasured**. Do not claim the stream
applied. Evidence: `state_stream_does_not_clear_the_cable_or_move_the_player_20261012`.

**The cable instrument was broken, and that invalidates earlier readings.** `watch-indicator.py` is the
only instrument for the icon, and it had **three** defects that each produced a wrong verdict silently:
(1) it classified a **stale** capture when `shot.py` failed — a 3-minute run reported `absent/other` with
0% red while a fresh capture of the same second showed the icon plainly RED, reading a file written 40
minutes earlier; (2) it did not scale its box, so a 1920x1080 capture sampled the wrong region; (3) its
red rule required `g < 110` while the icon's own pixels measure `(229,113,106)`, so the brightest half of
the cable was excluded. All three are fixed and the fix is verified against a case whose answer is known
by eye. Evidence: `hud_indicator_classifier_had_three_defects_20261012`.

**Next concrete step (bounded, static).** Identify the trait that owns `MB::ALCReplicatedState` and the
record id / fragment key that carries it, then check whether the capture contains it. That is the same
analysis that mapped `PhysicsTrait`, and it is what decides whether the ALC/position state is obtainable
from the capture at all. `reverse/tools/find-disp-writes.py` and
`reverse/tools/scan-wire-names.py` (1833 of 7052 wire types now named, 8 hand-verified anchors
reproduced) are the tools for it.

**Still not met: both gates.** Movement: unchanged through W in every session measured. Connection: the
cable goes red, now with a mechanism and a class attached to it. What this session produced is the
identification of the thing to fix, not the fix.

## 2026-10-12 (cont. 9) — the red cable, read from the code: it is a client-side age, and the field is NOT findable by offset

**The cable verdict is computed in one function, and the comparison is now exact.** `FUN_14486c740`
does:

```
now  = FUN_141413890();
age  = now - *(u64*)(hud + 0xAA8);
if (age > red_threshold)   state = 2;      // red
else                       state = (age > amber_threshold);   // 1 amber, 0 clear
FUN_1433d4660(0xc1fd05e0, &state, 1);
```

The two thresholds are client cvars read through `_DAT_149f20f90` (amber) and `_DAT_149f21048`
(red). So the icon is a **pure client-side age of one 64-bit timestamp field** — no server verdict
appears anywhere in it. That turns the earlier *observed* thresholds (amber ~2 s, red ~15 s) into a
code-level fact, and it means the reported sequence (clear → amber → red) is exactly what happens
when nothing refreshes `hud+0xAA8`: the age grows monotonically on its own. The previous live
finding that the stamp "moved once (at replay-complete-quiet) then froze" is therefore the whole
story so far — written at least once, never refreshed. Evidence:
`hud_cable_state_is_computed_in_code_with_exact_thresholds_20261012`.

**Why earlier attempts never found the writer — and this is the useful part.** `+0xAA8` is **not
unique to that class**. A displacement search over the image finds **10 functions writing a qword**
there and **68 `lea` sites** computing an address with that displacement; at least six of the writers
are the same constructor pattern (`lea rax,[rip+const]; mov qword [rdi+0xAA8], rax`) initialising a
**pointer** field in unrelated classes. Worked example of the trap, hit this session: the two most
promising candidates (`mov qword [rdi+0xAA8], rax`, i.e. "store now") turned out to be a
**profiler settings initialiser** whose neighbours are the cvars `profile_additionalsub` (stored at
`+0xA88`) and `profile_filter` (at `+0xAA8`). None of the 10 writers calls the HUD clock. So a
displacement search, or a Frida hook on the raw offset, catches unrelated classes and **cannot**
identify the ALC field. The correct next step is to identify the **class** of the HUD object from
the HUD function's two callers (`0x14485d663` calls `FUN_14486c740(param_1 - 0x160)`, so the HUD
object is a base subobject of a larger one) and hook that class's specific writer. New reusable tool:
`reverse/tools/find-disp-writes.py <disp>` (general; dedupes REX-prefix shadow decodings and groups
hits by containing `.pdata` function).

**The ALC conversation is visible in the capture, and its reply is identified.** Reconstructing the
177-message capture as one ordered timeline: the client's channel-1 input burst is **seq 110-114**
(five consecutive `0x635` = `ActionListComponentServerFacet_ReceiveInputFromClient`), and the server
answers **immediately after** with `0x8` state, then `0x1096`/`0x1097` (`SyncTimeChange`/`SyncDayPhase`),
then a continuous `0x8` state flood (seq 119-176) interleaved with `0x15d` pings. So the reply to the
client's input stream *is* the time-sync pair plus fresh state — which is why the wire names ("time
sync") and the protocol role ("the ALC reply") are both right and neither is a misnomer. Also
confirmed: `0x15d` is `PingMsg`, 10× R (12 B) then 10× W (36 B), i.e. server pings, client pongs.
And a fixture limit worth recording: **the capture does not record the datagram channel** (137/137
server bodies begin with the typed marker, and `raw` is a message body), so no claim about which
channel the real server used can be measured from it — that is an inference from our own sender.
Evidence: `capture_records_bodies_not_channels_and_the_alc_reply_pair_20261012`.

**Honest state of the two gates: still not met, and this session added no server-side fix.** Movement:
W/S still produce no position change. Connection: the cable still goes red, and the code above shows
why it will keep doing so until `hud+0xAA8` is refreshed. The one thing that would settle it is
naming the HUD object's class and finding that class's stamp writer — a bounded static task, then a
single targeted hook. No live run was made in this session; the three earlier runs already showed
that the client dies ~7 min in on an ntdll access violation, which limits what any one session can
measure.

## 2026-10-12 (cont. 8) — WHY FRIDA KILLS THE CLIENT (and the fix, with its limit); the client's own `teleport` does not move the player

**Frida: the mechanism is identified, and so is a fix — but the fix is not a session fix.**

The crash is Windows `Event Name: BEX64`, `P4: frida-agent.dll_unloaded`, `P7: 0x9c7e0`,
`P8: c0000005`, and the field that names it is **`P9: 8`** — an **execute** violation (DEP), not a
read or write. `frida-agent.dll` is on disk for every attach (`.azoth/tmp/frida-<hash>/x86_64/`,
and the hashes matched the probe times exactly). Disassembling it at `0x9c7e0` shows that is the
**first instruction of a function** (`mov rax, rsp` of a big prologue; `.pdata` gives
`0x9c7e0..0x9cbd7`). So a client thread branched to a function entry inside a module that had
already been unmapped — a plain **execute-after-unload race**: `session.detach()` unloads the agent
while hooks installed by the script are still reachable. The client logs *nothing* for it, which is
why it was misread as the 20-minute timer.

**The fix.** `reverse/probes/client/_paths.py::safe_shutdown()` now offers `kill=True` (end the
client deliberately — usually right, since every world A/B needs a fresh process anyway) and an
orderly path: `Interceptor.detachAll()` → settle → `script.unload()` → settle → `session.detach()`,
which removes hook routing *before* the module can go away. Hot-hook probes export `teardown()` and
take `--shutdown kill|detach`.

**Its limit, measured — do not overstate this.** Two orderly teardowns were followed by a live
client (checked at 19:18:19 and 19:20:38), against three same-day crashes at ~23 s with a bare
detach, so the `frida-agent` BEX64 signature did **not** recur. **The client still died ~7 minutes
after spawn (19:22:16Z) — and the WER event says it was a different failure:** `APPCRASH`,
`ntdll.dll`, `c0000005`, **`P8: 0x165497`**, `P9` empty (read/write, not execute). That is the same
family as the already-recorded `ntdll` crashes (`0x1662b7` ×3, `0xc4a0f`), at a new offset. So the
orderly teardown removes *this* crash source and is **not** a session fix; the real long-session
blocker remains the ntdll access violation. Evidence:
`frida_unload_crash_mechanism_and_the_fix_20261012`.

**The client's own `teleport` does not move the player — the first measurement past "input has no
effect".** `teleport`'s handler (`FUN_141020a40`) parses three floats via `IConsoleCmdArgs` and
calls the dispatcher `FUN_140fbf3b0(&{0x14057148c, 0}, &vec3)`, which iterates a manager list calling
`fn(obj->[5] + off, &vec3)`; `0x14057148c` is a virtual-call thunk. Reproducing that call with the
client's own arguments:

| measurement | result |
| --- | --- |
| position before / after (client's own accessor) | identical, 3 runs |
| does the dispatcher visit an entity? | **yes — `visited: 1`**, object `0x2110c932ca8`, our vec3 `[1,2,3]` |
| is that object an AZ-reflected component? | **no** — slot 0 is not the type getter (garbage GUID), vtable RVA `0x8535968` has **zero** pointers to it in the image |

So the empty-list hypothesis is refuted, and the open fork is precise: either (a) that object is not
the local player (`FUN_141029f90` has **125 callers** — an ubiquitous context, not a player manager),
so `teleport` is simply not aimed at the player and this says nothing about whether the client *can*
move it; or (b) the write lands but does not take, because it is issued from a Frida **remote
thread** instead of the client's own console/game thread. The discriminator is already in the probe
(`--probe-dispatch` dumps the object's vtable, `+0x28` target and GUID). This matters because the
project's own note calls `teleport` the command that "actually sets the player rotation correctly".
Evidence: `client_teleport_command_does_not_move_the_player_20261012`.

**Honest state of the two acceptance gates: neither is closer to passing.** Movement: W and S still
produce no position change on a session that renders (re-confirmed this session), and now even the
client's own debug write path does not move it — one more dead end ruled out, not progress toward
movement. Connection: the HUD cable was **RED** again in this session, and the session ended ~7 min
in on an ntdll crash. What this session produced is *understanding* (facet creation is not the
blocker; the replay never carries the position; Frida's failure is an unload race with a fix) and
one new, sharper question (what object `teleport` writes). Evidence bundle:
`research/sessions/session-20261012T1913Z-teleport-test/`.

## 2026-10-12 (cont. 7) — the black screen was a MISSING ENV VAR, not the client; movement re-measured on a rendering session; the Frida crash reproduced

**Three results from this session, one of them a correction of this session's own first conclusion.**

**1. The world renders. The black screen was my own omitted environment variables.**
`python az.py dev` forwards whatever `AZOTH_*` variables the calling shell has, and
`AZOTH_REPLAY_LOCAL_PLAYER_UUID` defaults to **`off`** — the documented failing value for gate 6.
A run without it logged `Initialize()` → `GDERenderManager Init()` → **five**
`Context: Exceeded max recursion for deferred actions ... The rest will be dropped`, spawned the
player, and rendered **black** (verified mechanically: the game window's client area had 0
non-black pixels while a desktop capture had content, so neither the monitor nor the GPU was at
fault). With `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character AZOTH_REPLAY_INPUT_RESPONSE=1
AZOTH_RESEND_INTERVAL_S=1.0` the world renders with the player possessed and `private-run.py`
prints `verdict: InGame reached, player possessed`:

| | with the vars | without them |
| --- | --- | --- |
| world renders | **yes**, player possessed | **no**, black frame, no player |
| `Exceeded max recursion for deferred actions` | **0** | **5** |
| `replay-local-player-uuid` spans filled | **25** | 0 |
| client channel-1 records | **1470** | **0** |

So the Gate 5 symptom set (black frame + deferred-action burst) is reproduced by a missing env var
**with the predicate patch correctly applied**, and the omission also kills the client's input
stream. `AZOTH_REPLAY_SPLIT_SEQ=0x25` was **not** needed: every session on 2026-10-10 that rendered
used `split=off`. The runbook now shows the exact exports and how to verify the effective config —
the world server logs a `config` event as the first line of every session, and reading the **last**
one of an accumulated log is required (reading the first one produced a wrong diagnosis this
session). Evidence: `runbook_env_vars_are_mandatory_and_verifiable_20261012`,
`config_event_is_the_effective_config_20261012`.

**2. W still does not move the player — now measured on a session that provably renders.**
The client's own accessor returned holder `0x20f3f50ca80` at
`(9343.6416, 2786.7327, 87.538)` — byte-identical to the previously recorded value, so the
instrument reproduces across machines. A **10 s W hold and a 5 s S control produced zero change in
every sample**, while the server received **20 channel-1 records per second** at every timestamp
bucket (wire `0x635` = `ActionListComponentServerFacet_ReceiveInputFromClient`, 5839 for the
session). The negative half of the movement criterion therefore no longer rests on a black-screen
session. The **HUD cable was RED** in this same run, on a session whose own log reported
`transportError` 0, `disconnected from REP` 0 and `OnLocalNetworkConnectionWarning` 0 — the
documented separation between the icon and the log, now with a matched screenshot and a matched
clean log. Evidence: `movement_negative_confirmed_on_a_rendering_session_20261012`.

**3. The Frida agent-unload crash is REPRODUCED — detach is not a safe way to end a probe.**
The existing record had one instance and had to be hedged as correlation. A second, unrelated probe
(`frida-facet-slots.py`, new) produced the identical signature: WER `BEX64`,
`P4: frida-agent.dll_unloaded`, `P7: 0x9c7e0`, `P8: c0000005`. The client died **silently** at
detach — Game.log simply stops at a routine CMS heartbeat, with no `Cleanup()`, no
`exiting to main menu` and no `Disconnected from REP` — which is why it first looked like the exit
timer. Read the faulting module in Application event 1001 before reading a session death as client
behaviour. Evidence: `frida_agent_unload_crash_reproduced_20261012`.

**4. The decisive facet measurement: facets ARE created — the previous blocker was a category error.**
The facet slot is `component + 0x80` (that is where the by-name factories store the facet), **not** a
member of the entity's component list. Measured on the live local-player entity (126 components, all
resolved, probe attached at character select):

| | |
| --- | --- |
| components with a bound facet object | **110 / 126** |
| distinct facet GUIDs | 108 |
| named ones, of which `*ClientFacet` | **106 / 106** |
| components with no facet | 16 — TagComponent, PlayerSaveData, Footprint/SkinnedMesh/MotionParameterSmoothing, one unnamed, **eight audio/vegetation** |
| position components among the 16 | **none** |

`PlayerPositionTrackingComponent` (index 95) **has `PlayerPositionTrackingComponentClientFacet`
(B74D06BC-…) bound at `+0x80`** — the exact class `position_facets_absent_on_the_live_entity_20261012`
recorded as absent. That entry searched the entity's **component list** for facet class names, and
`IPositionReceiver` is an **interface**, not a component; three different kinds of object were
conflated. Its conclusion "the client-side facets are not created on the local player entity" is
**false**, and it is no longer a valid reason for the movement blocker. What survives, restated: of
the position family only `PlayerPositionTrackingComponent` is a **component** of this entity
(`PositionInTheWorldComponent`, `PositionalTicketingComponent`, `CameraComponent` are not components
of it at all), and there is no `GlobalStorage` component either — so the 23 unbound
`GlobalStorageComponentClientFacet` errors are the same shape of mistake (a class absent from *this*
entity), not a broken facet mechanism. Evidence:
`client_facets_ARE_bound_on_the_live_player_entity_20261012`.

**Also confirmed offline this session (see cont. 6).** Client facets are built by per-class
by-name factories against the registry at `0x14a313ff8`; the 368 `*ComponentClientFacet` classes
are enumerated by `reverse/tools/scan-client-facets.py`. The replay provably never carries the
player position.

**Next experiment.** The movement blocker is no longer "facets are missing". Two candidate
directions, both cheap and both offline-or-light: (a) `PositionInTheWorldComponent` is not a
component of the entity although its server facet declares the replicated fields — check whether it
is *supposed* to be, by looking at a remote player's entity (which does replicate a position) and
seeing whether that component is on it; (b) the entity's `PlayerPositionTrackingComponent` has a
live client facet, so instrument what that facet does with the 20 Hz channel-1 input stream. Either
way, attach probes at character select and prefer hooks-only: a probe that hooks the hot component
lookup and then detaches has killed the client **three times** in this session. Evidence bundles:
`research/sessions/session-20261012T1818Z-render-ok/` (rendering run) and
`research/sessions/session-20261012T1938Z-entertest/` (black-screen run without the vars).

## 2026-10-12 (cont. 6) — client facets are created by per-class by-name factories; the replay provably never carries the position

**Environment warning for a fresh checkout.** The raw live captures the (cont. 2)–(cont. 5)
sections cite are **not on this machine**: `reverse/sessions/` is absent, `.azoth/night/runs/`
does not exist, and `.azoth/logs/` plus `.azoth/captures/probes/` stop at **2026-10-10 11:50**.
So `player-components-1791660475.jsonl`, `player-components-full-1791794008.jsonl`,
`physics-timeline-1791800300.jsonl` and the run directories `phys-101555`, `comp-083309`,
`rcv2-073512`, `smC0-054923` are all missing here and those measurements can only be
re-verified by new runs. Only the committed atlas/docs summaries survive. `services/world/rep_traffic.jsonl`
is 2.59 GB and is a debugging log, not state.

**What creates a client facet is now located, and it is not a message.** Every client facet is
built by a **per-class by-name factory**:
`ReflectionRegistry.CreateByName("<Class>", size, align, …)`, then the new object is stored at
`<owner> + 0x80` with `<facet> + 8 = <owner>`. The registry is the global at `0x14a313ff8` — the
same object behind the `IPositionReceiver` register-by-name (`0x143f98300`) and installer
(`0x143f983d0`). So "create the ClientFacet" and "create the `IPositionReceiver` instance" are
**one question about one registry**, not two.

The factory per class is reachable offline: each class owns a table in `.rdata` whose tail is
`[0x1406c7b30][0x1416a1340][FACTORY][0x14171a8b0][0x1417aae90]`. Scanning that signature gives
**369 tables / 368 distinct names, and 368/368 are `*ComponentClientFacet`**. New tool
`reverse/tools/scan-client-facets.py --check` (self-verifying) regenerates
`research/derived/client-facet-factories.json`. The factories are **never called directly**
(0 callers; the address exists only as the table slot), so creation is table-driven.

**The class is not missing from the build.** `PlayerPositionTrackingComponentClientFacet` →
`0x142cff160`, `PositionInTheWorldComponentClientFacet` → `0x145c209f0`,
`PositionalTicketingComponentClientFacet` → `0x142605970`. Whole-family creators exist too:
`0x142d14d50` and `0x145c94990`. And **22 of the 26 named components on the live entity have a
registered `*ComponentClientFacet` class** — so "the class does not exist" is excluded.
`IPositionReceiver` is **not** in the 368 (it is not a client facet), and there is **no
`CharacterPhysicsComponentClientFacet` in this build at all**, independently corroborating
(cont. 5). Atlas: `client_facet_creation_is_a_by_name_factory_20261012`.

**The replay provably never carries the player position.** Parsed with the repo's own
`replay_store` + `bundle` (78/79 bundles decode) and walked with the live-measured fragment sizes,
the spawn record is `record_id 1 / fragment_count 48 / payload 46393 B`, re-sent 24 times. The
measured live position `(9343.6416, 2786.7327, 87.538)` appears **nowhere** in any of the 177
messages in float32, float64, or int16/int32/int64 fixed point at x1/x10/x100/x1000/x1024/x4096.
What the spawn record *does* carry is identity: the player's 16-byte actor id
`1a954abc4b3185bfbe37c3d8592618e0` at payload offset `0x7423`, fragment `n=23 key=0 type=10`. Atlas:
`spawn_record_fragments_do_not_carry_the_local_player_position_20261012`.

**Next measurement (one number per component, no new probe design).** The facet slot is
`component + 0x80`. Extend `frida-player-components-full.py` to read `[component+0x80]` for each of
the 126 components of the live local-player entity. If it is **null for all of them**, the local
player gets **no client facets at all** and the problem is general (hook the table-driven path).
If it is non-null for most and null only for the position family, the problem is specific and the
family creator `0x142d14d50` is the thing to hook. That single reading decides which of the two
very different investigations to run.

## 2026-10-12 (cont. 5) — physics disagreement RESOLVED; the position path is replicated state, and its facets are missing

**The physics disagreement is settled, and it settles AGAINST the committed record — by that
record's own capture.** One session (run `phys-101555`, probe
`reverse/probes/client/frida-physics-timeline.py`, new) snapshotted the SAME live entity at
three instants — as soon as it was tracked (~4 s after spawn), +30 s and +120 s — while hooking
the component ADD `FUN_1413789c0` so a late addition could not be missed:

| instant | components | resolved | `CharacterPhysicsComponent` | `GameRigidBodyComponent` | controls |
| --- | --- | --- | --- | --- | --- |
| ~4 s | 126 | 126/126 | absent | absent | all present |
| +30 s | 126 | 126/126 | absent | absent | all present |
| +120 s | 126 | 126/126 | absent | absent | all present |

The ADD hook was demonstrably live: **24 adds observed**, every one on a different entity, none
on the player entity. **Root cause of the disagreement:** the 2026-10-10 capture is still on
disk (`.azoth/captures/probes/player-components-1791660475.jsonl`) and its own `top` record says
`"physics_asked": {"CharacterPhysicsComponent": "null", "GameRigidBodyComponent": "null"}` and
lists BOTH in **`lost_named`** — the bucket for components asked about and NOT found. The atlas
entry written from it (`local_player_components_step0_20261010`) read `asked_named` as if it were
the found list. That capture also read an entity with only **hits=21**, the short-lived/freed
126-component entity, not the live one. The entry is corrected and marked superseded. Evidence:
`physics_components_absent_RESOLVED_20261012`.

**Position: the authoritative path is replicated STATE, not an RMI — and the facets are missing.**
Measured on the live entity, of the whole position family only the bare component is there:
`PlayerPositionTrackingComponent` present, but `PlayerPositionTrackingComponent{Client,Server}Facet`,
`PositionInTheWorldComponent{Client,Server}Facet`, `PositionalTicketingComponent{Client,Server}Facet`,
`CameraComponent` and `IPositionReceiver` **all absent**. Static confirms why no RMI can be the
authoritative path: `PlayerPositionTrackingComponent` has only three messages and all are AI
spawn-manager **debug** (wires 357, 2780, 6635); `PositionInTheWorldComponent{Client,Server}Facet`
have **no registered messages at all**; and `PositionInTheWorldComponentServerFacet::InitializeReplicatedFields`
exists, so the position travels as **replicated state** (`MB::PositionInTheWorldReplicatedState`)
on the AOI state-record path. This is the same failure class as the 23
`GlobalStorageComponentClientFacet_ReceiveStorageSearchItems` facet errors and as the missing
`IPositionReceiver`: **the client-side facets are not created on the local player entity.**
Evidence: `position_facets_absent_on_the_live_entity_20261012` and
`position_state_may_arrive_as_replicated_state_not_rmi_20261012`. Stop looking for a message to
send.

**Next concrete step.** Find what makes the client create/bind a client-side facet for a
replicated component — most likely the server-side replicated component state arriving in a
state bundle — and identify which of the spawn record's 48 captured fragments declares the
position component's replicated fields.

## 2026-10-12 (cont. 4) — the live player entity's 126 components are now named, and the physics claim does not reproduce

**The component resolution bug is fixed and the list is complete.** Every component of the live
local-player entity is now dumped and named. The old probes rejected **126/126** components
because they checked `inCode(vtable)` — on this build a component's vtable lives in `.rdata`
(`r--`) while the function pointer inside it lives in `.text`, so the check must be on the
resolved **function pointer**, never the vtable. With that fixed, run `comp-083309` resolved
**126/126 with zero failures** (`bad: nullComp 0, badVtblPtr 0, badSlot0 0, nullType 0, exc 0`).
Probe: `reverse/probes/client/frida-player-components-full.py`. Atlas:
`player_entity_component_list_measured_20261012`.

**The position plumbing is on the entity:** `PlayerPositionTrackingComponent` (index 95, GUID
`62620B33-6F37-418B-9C4F-62AD6058D54D`), plus `CharacterComponent`, `Transform`,
`TraversalComponent`, `CameraLockComponent`, `PlayerInputFiltersComponent`,
`MotionParameterSmoothingComponent`, `PlayerAOIComponent`, `SpectatedPlayerComponent`,
`SpectatorModeComponent`, `SkinnedMeshComponent`, `FootstepComponent`, `PlayerSaveData` and
more (36 of the 126 GUIDs have no name in the atlas registry).

**`CharacterPhysicsComponent` and `GameRigidBodyComponent` do NOT reproduce on the live
entity.** At ~4 s after spawn, neither is in the 126-component list, and asking the CLIENT'S
OWN lookup `FUN_1413fb700` for both GUIDs (trying both byte orders) returned `found=False`
while the controls `Transform` and `CharacterComponent` returned `True`. That is the same
method the committed record `local_player_components_step0_20261010` used, with the opposite
result. **This is recorded as an unresolved disagreement, not a retraction:** the dump is one
instant ~4 s after spawn and the client crashed ~3 s later, so whether the client adds physics
later is unknown. The deciding experiment is to re-dump the same entity at spawn+4 s, +30 s and
+2 min in one session while logging every ADD (`FUN_1413789c0`). Atlas:
`physics_components_absent_on_the_live_player_entity_20261012`.

**Crash attribution corrected: Frida itself is a crash source.** The Windows Application log
names the faulting module, and the crash that ended `comp-083309` was in
**`frida-agent.dll_unloaded`** at offset `0x9c7e0` — i.e. the instrumentation, not the game
logic. Other recent crashes are `ntdll.dll` at `0x1662b7` (twice) and `0xc4a0f`. Rule for the
next runs: attach as late as possible (at character select, via `private-run.py --no-play`),
prefer hooks-only probes, and treat a death as an invalid attempt unless the faulting module is
`NewWorld.exe`. Atlas: `frida_agent_unload_is_a_crash_source_20261012`.

## 2026-10-12 (cont. 3) — the player position is now measured directly: W does NOT move it

**Movement is now measured with the client's own instrument, not with offsets or screenshots.**
The client ships `nw_getPlayerPosition` ("print player position to the screen"). Its handler
`0x141015b30` calls the accessor **`FUN_140fddfa0(&holder)`** and prints
`*(float*)(holder+0x14c)`, `+0x15c`, `+0x16c`. That is the local player position in the
client's own format, and the sibling command `teleport` (handler `0x141020a40`) reaches
`FUN_140fbf3b0`, so the client can also set its own position. New probes
`frida-player-position.py` and `frida-position-validate.py`; the latter **calls the client's
own command handler** and watched its printer fire (0 → 1), which confirms the accessor is
the client's own position rather than a guessed object. Atlas:
`player_position_accessor_and_console_commands_20261012`.

**Measured, run `rcv2-073512` (in-world, possessed):** the position was sampled at 0.2 s and
**667 of 667 samples were identical** — `(9343.6416, 2786.7327, 87.538)` — across a 136 s
window containing a **10 s W hold** and a 4 s S hold as a control. The instrument was live
(RMI dispatch counter 124) and the input did reach the game: the world server logged
**8184 app-data events carrying 7804 channel-1 records** in the same window. So: input
leaves the client, the position never changes, and no screenshot or byte-diff is involved.
This satisfies the negative half of the movement acceptance criterion. Atlas:
`w_does_not_move_the_player_measured_with_the_client_accessor_20261012`.

**Why, in two parts — both newly measured.**

1. **The `ActorMover` family is NOT locomotion.** Its surviving strings are a server-side
   hub-migration protocol: `Sending CommitMovement for actor`, `Destination hub timed out
   before receiving CommitMovement or AbortMovement…`, `DelayMigrationsMsg`,
   `MoveActorToHubMsg`. So `StartMovementCommunicationMsg` was the wrong lever from the
   start, consistent with it changing nothing when sent reliably on channel 0. The real
   plumbing is `PlayerPositionTrackingComponent` (GUID `62620B33-…`), `PositionInTheWorldComponent`,
   `PositionalTicketingComponent`, `CameraPositionListener`. Atlas:
   `actormover_is_hub_migration_not_locomotion_20261012`.
2. **The receiver is never created.** `frida-position-receiver` ran for a whole session
   (spawn 07:38:56, still in-world 07:57): **`installer=0` and `register=0` in every
   sample**. The installer `0x143f983d0` is the only site in the image referencing the
   interface vtable, so over a full login + world entry + 18 min in-world the client never
   creates or registers an `IPositionReceiver`. No target id can work because the object
   does not exist. Atlas: `position_receiver_never_created_in_a_full_session_20261012`.

**The 20-minute exit did not arm (replicated).** With `AZOTH_CHUNK_GAP_MS=4` the session
passed 22 min 12 s with `ActorContainerDisconnect` 0 and `exiting to main menu` 0 — a second
independent gap-4 run agreeing with `exitval2-202053` against the gap-20 run that armed at
exactly 20:00.398. Atlas: `exitA_gap4_replication_20261012`. The HUD cable was RED in every
sample; no run has yet reached the 30-minute acceptance.

**Next experiment.** Build the position work on `PlayerPositionTrackingComponent` /
`PositionInTheWorldComponent` (not `ActorMover`), and find which client object would create
the `IPositionReceiver` instance — the object graph is incomplete for several client facets,
not only this one. The accessor now makes every subsequent movement claim measurable, and
`nw_findLocalEntity` / `nw_getPlayerHealth` give the same treatment to other questions.

## 2026-10-12 (cont. 2) — the receiver is data-driven; a repeatable ntdll crash blocks the world

**The IPositionReceiver machinery is fully mapped, and it is data-driven.** The interface
vtable `0x1482eb160` is referenced by exactly **one** site in the whole image: the installer
`0x143f983d0` (`lea rax,[0x1482eb160]; mov [r8],rax`), which is reached as slot **+0x28** of
the family's base vtable `0x1482ea4e8`. That base vtable's slot **+0x20 is `0x140294860` =
`ret 0`** (returns null), which is why the delivery can never answer on a base-typed object:
`FUN_143f97bf0` does `q = target->vtable[+0x20](target, IPositionReceiver_guid)`. The
interface is registered by name by `0x143f98300`. Neither the installer nor the register
function has a direct caller, so both are invoked through the AZ reflection descriptor —
**the instance creation cannot be found by following xrefs and has to be observed.**
Atlas: `ipositionreceiver_vtable_layout_20261012`, `az_interface_decoupler_mechanism_20261012`.

**The blocker is reframed: our replay delivers to unbound client facets generally.** In
`exitval-194552` the 13041 `facet target ID couldn't be found` errors are 13012 position
replies **plus 23 `GlobalStorageComponentClientFacet_ReceiveStorageSearchItems`** (wire 7048)
plus time/phasing/notification ones. So the replay itself sends messages to client facets
that are not bound, independently of the position reply: this is "the client's local-player
object graph is incomplete", not "we picked the wrong message". Atlas:
`replay_sends_to_unbound_client_facets_20261012`.

**New instrument, verified working; the decisive count was NOT obtained.**
`reverse/probes/client/frida-position-receiver.py` hooks the installer, the register-by-name
and the delivery (control), and reads the AZ reflection registry at `0x14a313ff8`. In run
`rcv-070042` the hooks installed and fired, but **the client crashed during login before
`player spawn succeeds`** with `0xc0000005` in `ntdll.dll` at **offset `0x1662b7`** — the same
signature that ended `exitval-194552`, and different from the older Frida-startup crashes.
Both `0x1662b7` runs had a read-only Frida probe attached (correlation, not proof: `mvB`
and `mvD` also had probes and did not crash there). So the current failure mode blocking a
30-minute session includes a repeatable `ntdll+0x1662b7` access violation. Atlas:
`position_receiver_probe_and_ntdll_crash_signature_20261012`.

**Next experiment.** Run `frida-position-receiver` in a session that actually reaches the
world, and read the installer/register counters: if they stay 0 for a whole session the
client never creates the receiver and the missing piece is upstream in the object graph; if
they fire, the recorded return address names the creating code. Because the crash interferes,
run it without any other probe attached, and treat a crash before `player spawn succeeds` as
an invalid attempt rather than a result.

## 2026-10-12 (cont.) — the position reply's target was wrong, not the interface; the client's input stream is identified

**Three corrections that change how the movement work should be read.**

1. **The client's channel-1 stream is `ActionListComponentServerFacet_ReceiveInputFromClient`**
   (wire 1589 / `0x635`), not an unnamed state stream. Measured on the whole session:
   **19676/19676** channel-1 records have a valid `[crc32][len]` container, all with
   target = the full 16-byte actor id `1a954abc4b3185bfbe37c3d8592618e0` and type
   `0xC35`. So the client streams its ALC input to the server ~20×/s and the input
   direction already works. Evidence: `input_stream_is_action_list_facet_call_20261012`.
2. **The `0x1096`/`0x1097` "input response" is a misnomer**: they are
   `TimeComponentClientFacet_SyncTimeChange` / `SyncDayPhase`. So `AZOTH_REPLAY_INPUT_RESPONSE`
   replays **time sync** messages, and the recurring `2 × SyncTimeChange + 2 × SyncDayPhase`
   facet errors are those. Evidence: `wire_type_names_from_binary_20261012`.
3. **My previous "dispatch fixed" result was a false fix.** The blob that makes the
   dispatch succeed (`93a3e477cb5fd51e`) is the client's **`TimeComponentClientFacet`**
   local id — the target the capture's own time-sync messages use. Re-addressing the
   position reply there turns a loud failure into a silent wrong-object delivery: the
   dispatch succeeds (642/642, 0 facet errors) but the position goes to a time-sync
   facet, so `FUN_143f97bf0` still returns 0. Evidence:
   `position_reply_timecomponent_target_is_a_false_fix_20261012`.

**The interface is implemented; no instance is bound.** The whole chain is now located by
bytes: the delivery queries `target->vtable[0x20]` with the GUID from `FUN_143fb2b90`
(0x143f97c0a-0x143f97c4c); `FUN_143fadd00` is that QueryInterface (returns `this` on a GUID
match); the receiver's vtable is **`0x1482eb160`**, installed by the 6-byte function at
`0x143f983d0`; the interface is registered by name by `FUN_143f98300`; the RTTI descriptor
is `IPositionReceiver` at `0x1482ea920` with GUID
`{17C00FC6-074F-47EB-9640-9743D890ED6F}`. The blocker is that **no client-side RMI target
is an instance of it** (37063 targets, 225 distinct vtables, 0 positives). Evidence:
`ipositionreceiver_implementation_located_20261012`,
`message_interface_map_from_pdb_strings_20261012`.

**`StartMovementCommunicationMsg` is not the trigger — measured.** Sending it **reliably on
channel 0** (the framing fix: the earlier attempt was unreliable on channel 1, which the
client never decodes) still binds no receiver and the actor-id reply still fails: **1581**
facet errors for `ReceivePlayerPositionClientMsg`. The body was never the problem
(20 bytes, verified against the client's own reader `FUN_146a55240`). And the client never
sends `0x2D6` itself (1144 channel-0 records enumerated; absent). Evidence:
`start_movement_reliable_ch0_does_not_bind_receiver_20261012`.

**Next experiment.** Find what constructs an instance of vtable `0x1482eb160` and registers
it as a client-side RMI target, and what tells the server its local id. The client's own
outbound messages address a 16-byte target that begins with the actor id because they call
a *server* facet, so the actor id being the client's outbound target does not make it a
valid client-side target for our reply.

## 2026-10-12 — dispatch fixed by re-addressing the reply; the blocker is now the interface binding

**Movement, step 1: SOLVED and measured.** `AZOTH_REPLAY_POSITION_REPLY_TARGET` (the
re-addressing lever added last session) removes the `facet target ID couldn't be found`
failure completely. Same reply, only the target blob changed from the actor id to
`93a3e477cb5fd51ebf85314bbc4a951a`:

| run | target blob | dispatch of that id | facet errors for 4216 |
| --- | --- | --- | --- |
| `exitval-194552` | actor id | 0 / 601 | 13012 |
| `mvB-020002` | capture input-response blob | **642 / 642** | **0** |

The delivery path itself also succeeds (260/260 non-null). Evidence:
`position_reply_target_fixes_dispatch_20261011`.

**Movement, step 2: the remaining blocker is precise.** `FUN_143f97bf0` still returns 0:
the target it receives does not answer the `IPositionReceiver` interface query. A scan of
all **37063** registered targets, grouped by object vtable (**225** distinct vtables) and
queried through the client's own GUID getter `FUN_143fb2b90`, found **no registered target
that answers that interface**. So no target id can work: the interface has no bound
instance, which is the same open question as the ALC conversation. Evidence:
`position_target_scan_no_binding_20261011`.

**Movement, step 3: instrument built, position offset still unknown.** New probe
`frida-movement-state.py` resolves the live player entity's `Transform` and
`GameRigidBodyComponent` through the client's own lookup `FUN_1413fb700`. A 4 s W-hold
produced zero changed words in the transform component's first 0x100 bytes — but reading
that object shows a pointer/counter header, not floats, and no plausible position float
triple exists in it or in its first writable pointer. **That zero-change result is a
measurement of the wrong bytes and proves nothing about movement.** Next step: trace the
client's own transform accessor instead of guessing offsets. Two invalid resolution
methods are recorded so they are not repeated. Evidence:
`player_entity_transform_readable_but_position_offset_unknown_20261011`.

**Connection / session lifetime: the 20-minute exit is armed by the replay gap.**
One-variable A/B, no Frida in either run:

| run | `AZOTH_CHUNK_GAP_MS` | replay | 20-min exit |
| --- | --- | --- | --- |
| `exitA-gap20-012032` | 20 | 29 s | **fired at 20:00.398** |
| `exitval2-202053` | 4 (default) | 10 s | did not arm (session ended 26:33 by a REP disconnect) |

And the corrected patch is now **exercised**: in `exitA-gap20-012032` the delegate ran
(`CGame::ActorContainerDisconnect` logged) and the patched call at `0x14100425F` was
skipped — `exiting to main menu` 0, `Cleanup()` 0, where the pre-patch runs logged both.
**It is not a session fix:** the same delegate tears the connection down at
`0x141004230` *before* the patched call, so the client stopped sending traffic at
20:00.398 (zero server-side events after that; the world on screen at 01:54Z was a frozen
frame). To survive past 20 minutes the **arming** must be prevented, not the exit call.
Evidence: `exitA_gap20_run_outcome_20261011`,
`chunk_gap_decides_the_20minute_arm_20261011`.

**Next three experiments.**

1. Find what binds an `IPositionReceiver` (same question as the ALC conversation); no
   target id can work until something does.
2. Trace the client's own transform accessor, then re-run the W-hold measurement against
   the real position bytes.
3. Arm-side fix for the 20-minute path: hook the enqueue (`FUN_14107fb40`, the
   deferred-action queue drain) rather than patching the exit, since gap 4 merely moves
   the failure to a 25-26 minute disconnect.

## 2026-10-11 (late) — the 4216 dispatch blocker is a wrong target id; the 20-minute exit is conditional

**Movement.** The `RMIDispatch: The facet target ID couldn't be found` blocker for wire
4216 is now measured, and it is **not** a missing facet type. The client's RMI target
registry holds **37063** entries; the actor id the server's position reply carries
(`1a954abc4b3185bf`) matched **0 of 601** lookups, while the 16-byte blob the capture's
own input-response messages carry (`93a3e477cb5fd51ebf85314bbc4a951a`) matched
**136 of 136** in the same session. So the reply is addressed to a target the client
never registered. New probe `reverse/probes/client/frida-rmi-targets.py` dumps the
registry (capacity, every key, each target's object and vtable). New env lever
`AZOTH_REPLAY_POSITION_REPLY_TARGET` re-addresses the reply without a code edit.
Evidence: `rmi_target_registry_measured_20261011` and
`rmi_dispatch_facet_target_registry_20261011` in
[`client-functions.json`](research/atlas/client-functions.json).

**Connection / session lifetime.** The corrected exit call site `0x14100425F` is
byte-verified statically (`exit_delegate_call_site_verified_20261011`), but it is **not
yet validated live**, and the exit-to-menu path did not fire in **three consecutive
patched runs**: `exitfix-161219` (stopped 84 s in-world, cause unresolved),
`exitval-194552` (25 min 06 s, ended by an access violation `0xc0000005` in `ntdll.dll`
~40 s after a read-only Frida probe detached), and `exitval2-202053` (26 min 33.6 s,
ended by a **client-side REP disconnect**: `CGame::ActorContainerDisconnect` +
`Disconnected from REP` + `InGame -> Disconnected`, `transportError` 0, then the client
returned to the frontend and re-logged in). `CGame exiting to main menu` and `Cleanup()`
are absent from all three, so the delegate never reached the patched call. Earlier runs
left the world at exactly 20:00.4. So the 20-minute path is **conditional** and the
current failure mode is a **~25-27 minute client-side disconnect or crash**, not the
menu timer. Method note: `FUN_146420610` has 11 callers, so its log line marks *some*
caller, not the delegate; only its absence is decisive. Full record:
`exitval_194552_run_outcome_20261011`, `exitval2_202053_run_outcome_20261011`,
`exit_to_menu_path_not_reproduced_20261011`.

**Next experiment (one variable).** Baseline with `AZOTH_CHUNK_GAP_MS=20` and nothing
else changed: that is the best-supported difference (the runs that exited at 20:00.4
used 20 ms; both recent runs used the 4 ms default) and it decides both whether the
exit returns at 20:00 and whether the patch is exercised. Then re-address the position
reply with `AZOTH_REPLAY_POSITION_REPLY_TARGET` and measure whether the dispatch
succeeds and the local transform changes. Keep Frida attaches out of the baseline runs.

Also recorded this session: `.azoth/night/runs/exitfix-161219` (the previous run, never
analysed) stopped 84 s in-world with no exit line; its world log is preserved as
`.azoth/logs/world.log.exitfix-161219`.

## 2026-10-11 — transport survives; visible connection and movement remain open

**The player still cannot move. A previous version of this section claimed the
opposite and was WRONG** (retracted: `retracted_movement_claim_20261011` in
[`client-functions.json`](research/atlas/client-functions.json)). The claim rested
on a screenshot diff, and `scripts/bmp-diff.py` computes
`motion ratio = mad(shift 0) / best_mad(±24 px)`; a real camera translation makes
the best shift match *better* than no shift, i.e. ratio **> 1**. The W-hold pair
gave zero-shift mad 37.21 and best mad 39.46 — the best shift was *worse* than no
shift — so 0.94 means the scene changed but **did not translate**. A screenshot
diff cannot establish movement.

**What is solid (non-visual, binary):**

- **The Carrier `MF_RELIABLE` flag is required for the wire-4216 decoder path.** Unreliable
  (`flags 0x20`) the client resolved 3418 messages across 90 types with 4216
  **absent** and the reader at **0** calls. Reliable (`flags 0x21`) the same stack
  resolved index 4216 **212** times and the reader ran **212** times, 1:1.
- **The 4216 reader is reached; subsequent RMI dispatch attempts fail.**
  `Game.log` logs 103 times:
  `RMIDispatch: The facet target ID couldn't be found when trying to dispatch the
  RMI message. {"targetLocalId":1915519389091857855,"messageType":"ReceivePlayerPositionClientMsg"}`.
  That is the logged form of the static prediction that a bound
  `IPositionReceiver` is required (`FUN_143f97bf0` looks the interface up by GUID
  and returns 0). The message reader is reached, but the position is **not
  applied**. This does not establish movement.

**Next decisive measurement:** read the local player's own transform (position
vector) live while W is held — not screenshots. That is the only thing that can
settle "does the player move".

Historical snapshot: 2026-10-11 afternoon (later measurements below supersede the early 4216 interpretation).

## Historical afternoon snapshot (2026-10-11; later results below supersede it)

This snapshot is retained for experiment history. Later runs and direct probes below supersede its early interpretation of 4216 and the HUD cable. Evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json)
(`alc_pointer_never_opens_live_20261011`,
`wire4216_never_resolved_live_20261011`,
`exit_patch_0x141004230_refuted_20261011`,
`start_movement_does_not_open_alc_20261011`).

- **Item 1 — the ALC pointer never opens.** A new probe reads BOTH classes that
  keep a field at `+0xAA8` (the HUD object `FUN_14486c740` and the connection
  object `FUN_1449309b0`). `+0xAA0` stayed **0** on both for the whole session,
  and the HUD stamp moved once (at `replay-complete-quiet`) then froze. Sending
  `StartMovementCommunicationMsg` (0x2d6) did **not** open it either. So the door
  is **upstream of the ALC module**, not inside it. No tested message has opened it; the missing handshake producer remains to be identified. A server-side handshake is the leading inference, not a demonstrated implementation. The client does stream input (23 819 channel-1 records).
- **Item 2 -- reliability opens the 4216 decoder path; it does not solve movement.**
  With `flags 0x20`, 700+ replies produced **0** resolutions and reader calls.
  With `flags 0x21`, the resolver and reader ran **212 times**, but later
  `Game.log` showed 103 RMI dispatch failures because `targetLocalId` has no
  facet target. This is a decoder gate only; neither application nor movement
  is established. The earlier screenshot-based movement claim was retracted.
  See `position_reply_now_decoded_but_not_applied_20261011` and
  `retracted_movement_claim_20261011` in the atlas.
- **Item 3 — the 20-minute exit patch is REFUTED.** With the patch applied and
  byte-verified (`e8dbc34105` -> `9090909090` at `0x141004230`), the session still
  died at **20 min 0.4 s** after spawn with a clean `exiting to main menu` +
  `Cleanup()`. The five bytes were still NOPs afterwards. The timer is real; that
  call site is not the path it uses.
- **Server bug fixed (it caused an earlier transport failure before the separate menu exit).**
  `on_app_data` parsed the raw (still LZ4) body of envelope `0x81` as Carrier
  records; garbage produced channel 4 and `parse_datagram`'s guard (`channel > 4`
  while `per_seq` holds four slots) raised `IndexError`, the loop dropped the peer
  and the client logged `transportError 4` ~18.7 min in. Now `on_app_data`
  decompresses first and the guard is `channel > 3`; regression test added.
  **120 world tests pass.**

Updated: 2026-10-11 (overnight session; full report in
[`research/docs/NIGHT-REPORT-2026-10-11.md`](research/docs/NIGHT-REPORT-2026-10-11.md)).

## Overnight 2026-10-11 — what changed

- **The red HUD cable tracks stale ALC response age.** The measured color
  thresholds are amber after 2 s and red after 15 s;
  `javelin.alc-server-timeout-for-input` is one 2000 ms client cvar, not the red
  threshold itself. The HUD compares `now` with its `+0xAA8` stamp. Live probes
  found the ALC door `+0xAA0` closed and the HUD stamp stopped advancing after
  initialization/replay activity; static analysis found no recurring writer in
  this build. REP logged no transport error while the icon remained red. This is
  stale ALC response state, not a REP disconnect; the handshake producer remains
  unknown.
- **The client's record container is decoded**: every non-chunked DATA record on
  channels 0 and 1 is `[u32 BE crc32][u32 BE len][16-byte target][00 01][type][body]`
  (40 279/40 279 channel-1 records and 285/294 channel-0 records verified). The
  server uses the capture's `[vlq32 len]` form instead.
- **The client streams exactly one type**: channel 1 carries only type `0x635`
  (17 912 records in one session). Its channel-0 traffic is `0x15d` plus typed
  requests.
- **The separate ~20-minute return-to-menu path is still open.** A live trace
  observed a queued delegate and a teardown candidate at `0x141004230`
  (`exit_to_main_menu_delegate_chain`), but patching that call did not prevent
  exit: the client returned to menu at 20 min 0.4 s. The candidate is refuted as
  a fix; trace the actual delegate/caller before changing code.
- **Historical container result (superseded for channel-0 reliable).** An earlier
  A/B got zero reader calls for the tested client-container/channel variants
  (`position_reply_containers_refuted_20261011`). A later run with reliable
  flags `0x21` reached the 4216 reader 212 times, then failed RMI facet-target
  dispatch. The current blocker is application binding, not a proven container
  failure.
- **Trap fixed for future runs**: `python az.py dev` returns before the gateway
  binds :8080, and launching inside that window makes Caddy answer 502 for the CMS
  manifest; the client then stalls with `Auth manager does not exist`. `night-run.py`
  now waits for the manifest to return 200 before it launches.

Updated: 2026-10-09 (overnight session). Exact function evidence is in
[`research/atlas/client-functions.json`](research/atlas/client-functions.json);
the consolidated wire reference is
[`research/docs/JAVELIN-PROTOCOL.md`](research/docs/JAVELIN-PROTOCOL.md) and the
message table is
[`research/atlas/javelin-messages.json`](research/atlas/javelin-messages.json);
what the client expects from the server, phase by phase, is
[`research/docs/SERVER-CONTRACT.md`](research/docs/SERVER-CONTRACT.md); how to
bring up and patch a private run is
[`research/docs/PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).

## Active objective

Deliver a usable in-world session with both **visible connection health** and
**controllable player movement**. Entry, rendering, and possession reproduce;
REP transport survived a 2 h 06 min run, but the user still sees the red ALC/HUD
warning and the client has a separate 20-minute return-to-menu path. Movement is
not solved and its cause is not yet known.

## Confirmed

- **World entry and possession work (2026-10-07).** With the runbook sequence
  the world renders and the player is possessed: `Initialize()` without
  `Cleanup()`, `player spawn succeeds, in game`, and `InGame`. This does not
  establish that the player's physics/controller is active.
- **REP transport survived 2 h 06 min (2026-10-10); user-visible connection is
  still open.** The run had `transportError` 0 and `disconnected from REP` 0,
  while the red ALC/HUD warning remained visible. The ALC input stamp stops
  updating and the ALC door stays closed. A separate client return-to-menu path
  still occurs around 20 minutes. Keep these results separate in reports.
  1. **The REP watchdog heartbeat no longer waits for the replay.** This activity-warning clock is separate from the red ALC/HUD stamp. The `0x15d` heartbeat
     and the `0x1096`/`0x1097` input response both gated on the replay queue being
     empty, but the replay is ~1090 Carrier chunks and needs ~22 s at
     `AZOTH_CHUNK_GAP_MS=20` — inside the client's ~27 s watchdog. The session log
     had **zero** `heartbeat` and **zero** `input-response` events. They now run
     concurrently with the replay, which is what the capture shows the real server
     doing. The state stream still waits: it re-applies the same captured bundles,
     and double-applying state is not idempotent client-side.
  2. **16-bit wire fields now wrap.** The server's envelope sequence was unmasked,
     so once `next_out_seq` passed 65535 the keepalive raised
     `OverflowError: int too big to convert` and stayed dead for **two hours**
     (7395 consecutive tick errors). Every 16-bit field now goes through `_u16()`,
     and a `tick-error` logs a traceback so a repeating error names its function.
- **CORRECTION to the warning count above, measured 2026-10-10 on the documented
  configuration.** The `OnLocalNetworkConnectionWarning` **1** figure does not
  reproduce: two live runs on `AZOTH_CHUNK_GAP_MS=20` logged a burst of **104** and
  **116** warnings, starting ~2 s after the spawn and stopping when the replay
  drained. The server log shows why — `replay-chunk` ran 19:30:40Z..19:31:09Z (29 s),
  `replay-complete-quiet` fired at 19:31:09Z and the **first `heartbeat` was also
  at 19:31:09Z**: not one ping during the whole replay.
  `PeerSession._post_replay_started()` returned `self.greetings_after_replay`, which
  is set only when the replay queue **drains**, so the gate-8f concurrency fix was a
  silent no-op. It now returns `self.v3_responded`, and the fix is verified: **20
  heartbeats fire before the drain** (was 0). See
  `post_replay_predicate_regression_20261010` in
  [`client-functions.json`](research/atlas/client-functions.json).
  **For the Game.log activity-warning counter (not the left-edge ALC/HUD cable), the measured 2026-10-10 result is that the burst tracks REPLAY DURATION.**
  While the replay is still streaming the client has not re-stamped its REP activity
  watchdog clock, so it warns every interval until the replay finishes — the burst lasts
  exactly as long as the replay. Four paired runs, one variable at a time
  (`scripts/measure-run.py`, raw rows in `.azoth/logs/ab-runs.jsonl`):

  | `AZOTH_CHUNK_GAP_MS` | activity stream | replay | warnings | transportError |
  | --- | --- | --- | --- | --- |
  | 20 | off | 76 s | 80 | **1** + disconnect |
  | 20 | **on** | 29 s | 82 | 0 |
  | 8 | off | 15 s | **0** | 0 |
  | unset (default **4**) | off | 10 s | **0** | 0 |

  So: in this replay-duration/Game.log-warning A/B, the type-`0x1b88` activity
  stream **did not help** (80 vs 82 — hypothesis
  refuted); 32 heartbeats before the drain **did not save** the 20 ms run; and the
  runbook's `AZOTH_CHUNK_GAP_MS=20` is slower than the code's own default of 4 ms
  while sitting right on the client's ~27 s watchdog. See gate 8g in
  [`PRIVATE-CLIENT-RUNBOOK.md`](research/docs/PRIVATE-CLIENT-RUNBOOK.md).
  **Unresolved trade:** a fast replay is warning-free but one run logged a
  `Cleanup()` ~3 min in; a slow one is calmer but risks the 27 s kill. The next
  measurement is *what makes a fast replay unstable*.
- **The server now emits on its own clock.** Every periodic emitter used to be
  called from `on_app_data` (once per inbound datagram), so server output scaled
  with client input: measured `Pearson(inbound, outbound) = 0.995`, peak 286
  datagrams/s, amplification 3.4:1. `PeerSession.tick()` now runs from the UDP
  loop at `TICK_HZ` (50) whether or not a datagram arrived. After: Pearson
  **0.180**, amplification **0.96:1**, peak **99/s**, `v3-registered` 8 -> **1**.
  `TestAuthoritativeTick` fails if a periodic emitter is ever called from
  `on_app_data` again.
- **Three server defects that made the loop stall itself are fixed** (each could
  cause a REP `transportError 4`/disconnect; those do not by themselves explain
  the separate ALC/HUD cable): the event log reopened a ~90 MB file per
  event (measured 27 s of silence under a 287-record burst); every ACK was a
  separate datagram (1:1 with inbound); and the post-replay heartbeat was
  retried to its 6-try cap (1106 heartbeats produced 5437 resends, 46% of all
  outbound traffic).
- **Private-run gates 1-8b** (see the runbook). Three fail silently: Caddy CA
  trust, the DTLS pin, and the server settings below.
  - Gate 5 (black screen) = the ClientContext predicate.
  - Gate 6 (no player) = server env `AZOTH_REPLAY_LOCAL_PLAYER_UUID=character`.
  - `AZOTH_REPLAY_INPUT_RESPONSE=1` is not a fix for the measured ALC/HUD
    warning; the icon remained red with input responses active.
  - The default replay gap is 4 ms; 20 ms was slower and had worse watchdog
    results in the recorded A/B. Do not treat 20 ms as a solved gate.
  - Gate 8b (resend storm) = `AZOTH_RESEND_INTERVAL_S=1.0`.
- **The launcher was dead on PowerShell 5.1** (`$PSScriptRoot` inside a `param()`
  default), and `az.py`/`private-run.py` both use `powershell.exe`, so the whole
  documented run path was broken. Fixed 2026-10-09.
- **The protocol is now decoded at the container level** (2026-10-09), with
  tests rather than prose:
  - The **prefix varint** every typed message and bundle field starts with.
    `services/world/src/azoth_world/javelin/varint.py`; 137/138 captured message
    types round-trip.
  - The **type-0x08 StateBundle** body, byte-exact: 78 of 79 captured bundles
    consume their body exactly. `javelin/bundle.py`.
  - The **message registry**: all 144 message types with GUID and wire type,
    `research/atlas/javelin-messages.json`. All 12 movement wire types reproduce
    from two independent derivations.
  - The **replication gate**: a bundle is accepted only when its instance id
    matches and its counter exceeds the client's high-water.
- **Warnings in a clean session are few and all benign**: 26 x Slice transform
  (0-component `remoteplayer` slices), 25 x RMIDispatch facet-not-found, 1 x
  `RequestGetPlayer: empty characterId`, 1 x benign physics note, 1 x
  `XDllSingleton already instantiated`.
- Input delivery is verified: scan-code `SendInput` reaches the client, mouse
  look rotates the camera, and the UI consumes keys. Holding W produced no
  movement-family message in the sampled session. The old screenshot-diff ratios
  are not a movement measurement; read the live player transform directly.
- **The client is confirmed to consume our post-replay traffic (2026-10-10).**
  Hooking the type-resolution function `FUN_1461acfe0` on a live session shows
  the client resolving exactly three type ids in a repeating cycle, and they are
  the three messages the server sends after the replay: index 349 (`0x15d`,
  PingMsg — the heartbeat), and 4246/4247 (`0x1096`/`0x1097` — the input
  response). This proves those typed messages are resolved; it does not prove
  that the real HUD warning clears or that the ALC input stamp refreshes.
  **Historical fragment-reader doubt superseded:** later direct hooks on
  `FUN_146af20d0`/`FUN_146af2340` measured record and nested-fragment reads, and
  the record/fragment grammar is documented above. Unknown per-type payload
  codecs remain open.
- **The `inject` lever is validated end to end.** A type-0x08 StateBundle built
  from scratch by `javelin/bundle.py` was accepted by the live client with no
  error, which is independent proof that the container layout is right. A
  `StartMovementCommunicationMsg` (`0x2d6`) with an empty body was also accepted,
  proving the type and framing. **Negative result:** a bundle carrying an unknown
  fragment `type_index` is dropped *silently*, so the client log is not a usable
  signal for "does the client know this fragment type" — future codec work needs a
  Frida hook or an observable state change instead.
- Tests most recently documented: **120 world**, **24 gateway**.

### Objective: visible connection and controllable movement

Keep the immediate slice focused on two user-visible gates: clear the real ALC/HUD
warning and prove the player transform changes with W. The shared replication
mechanism matters after a measurement shows which state or message is missing; do
not assume that adding generic PhysicsTrait codecs will fix movement. The sequence
and acceptance criteria live in [`docs/ROADMAP.md`](docs/ROADMAP.md).

**The corrected component measurement is complete:** the live 126-component
player entity contains `CharacterPhysicsComponent` and `GameRigidBodyComponent`,
and the client's own lookup finds both. The older claim that the entity lacks
physics is refuted. Presence does not prove that the body/controller is active
or explain why input produces no movement.

### The HUD red cable is an ALC timeout, not a REP transport verdict

The icon the user sees is on the **left edge, vertically centred**: a network cable
with a red X and a warning triangle. Sequence described by the user: appears on
entering, goes **yellow** for a while, then stays **red**.

**`Game.log` does not record this icon at all.** `OnLocalNetworkConnectionWarning`,
`transportError`, `disconnected from REP` and `State(...) is timeout` say nothing
about it — three diagnoses in one session were wrong for exactly that reason. The
only instrument that sees it is a screenshot; `scripts/watch-indicator.py` classifies
that box as RED / YELLOW / absent.

**Measured: the icon was RED for a whole 14-minute window while REP transport was
healthy.** At the same UTC second the server logged 1243 `app-data`, 972
`outbound-app-data`, 739 `reply`, 59 `heartbeat`, 58 `keepalive` and 58
`input-response` events in the last 60 s, with the newest traffic event matching the
current clock to the second; the client logged `transportError` 0, `disconnected
from REP` 0, `OnDisconnection` 0, `is timeout` 0 and exactly one
`clientContext == nullptr` (the normal transient at the frontend→world transition).
The icon means the client's ALC input stamp is stale; it does not mean the REP
transport disconnected. Evidence:
`hud_cable_icon_is_not_the_log_20261010` in
[`client-functions.json`](research/atlas/client-functions.json).

Separate and still open: holding W produced no movement-family messages. The
older screenshot ratio is not valid proof of position; measure the live transform.

### Movement: the client never emits anything (measured 2026-10-10)

Holding W for 2 s in a stable in-world session produces **no movement message in
either direction**. Decoding every client->server record in that window gives
zero `StartMovementCommunicationMsg`, `AckMovementMsg`, `CommitMovementMsg`,
`MoveActorMsg` and `ReceivePlayerPositionClientMsg`. The channel-1 local-player
stream (119/120 B, actor `1a954abc…` at offset 8, raw payload with no typed
marker) is **byte-identical across 3038 records** taken while W was held: masking
the rolling 4-byte counter at offset 0, only two bytes ever differ (offset `0x31`
and `0x4e`). No position, no orientation, no velocity. The client's own
`teleport_player` command (T) does not move the player either.

This proves that the sampled input did not produce a movement-family message and
that the channel-1 stream did not carry a changing position. It does not prove
the entire client simulation state. The player's physics component types are
present; measure activation and the input consumer before deciding which server
message is missing.

### Movement blocker (re-measured; the earlier diagnosis is corrected)

The client broadcasts its local-player state on channel 1 (type `0x635`) and the
server answers only on channels 0 and 3. The capture contains **no movement
message in the server->client direction at all**, so the reply must be
constructed server-side.

One lead remains: `FUN_141763b70` ran exactly once at process startup, before
world entry, and `FUN_141582430` was not called during the sampled login/spawn
window (`local_body_gate_never_runs_20261003_2250`). The latest component dump
then found physics and rigid-body components on the live player entity. Therefore
the gate observation is not proof that the entity lacks a body; trace its role,
activation state, and relationship to the live transform before inferring cause.

**Correction to the earlier "the player has no physics component" conclusion —
and it was worse than a partial correction.** The GUID list in
`local_player_has_no_physics_20261004` is **shifted by one entry**, and
`physics_component_guids_corrected_20261005` fixed only four of them, so the
record still disagreed with the binary. The shift: the old list gave
`GameRigidBodyClientFacetConfig` = `{0BCAB3AC…}` (that is `GameRigidBodyConfig`),
`GameRigidBodyServerFacetConfig` = `{0E0EDECA…}` (that is
`GameRigidBodyClientFacetConfig`), `GameRigidBodyComponentBase` = `{0C1F07A3…}`
(that is `GameRigidBodyServerFacetConfig`), and `CharacterControllerConfig` =
`{824E1E63…}` (that is `RockNRoll::CharacterSupportInfo`). And
`{B1237004-14E1-4327-8774-D2C5796230E7}`, recorded as `CharacterPhysicsComponent`,
**does not exist in this build at all**. The verified registry is
`research/atlas/az-type-registry.json` (4814 names, 4818 entries, 750 in the type
table), regenerated and checked by `reverse/tools/scan-az-types.py`.

**The old "no physics component" conclusion is refuted (2026-10-10).** The live
player entity (`0x207084fca10`,
**126 components**) HAS `CharacterPhysicsComponent` and `GameRigidBodyComponent`;
the client's own lookup `FUN_1413fb700` finds both on it. The old conclusion came
from searching for ids that do not exist — `{B1237004-…}`, recorded as
`CharacterPhysicsComponent`, is `PlayerDynamics`. What remains true is only that
the player **prefab** ships no physics component. Full evidence:
`local_player_components_step0_20261010` in
[`client-functions.json`](research/atlas/client-functions.json); probe
`reverse/probes/client/frida-player-components.py`. This refutes component
absence as the explanation. It does not yet distinguish body activation, input
consumption, ALC setup, or movement dispatch. Method requirement: the player
entity is only observable **during the world load** (an idle in-world run saw only
223-478 lookups, all for entities below 20 components), so the probe must attach
before entering the world. The next question is activation and transform change,
not whether the component types are present.

**Trap for anyone re-deriving these:** a loose scan for `<name>\0…<bare-guid>`
pairs a name with unrelated neighbours. It maps `Transform` to
`{5D9958E9-…}` (the AZ math struct) when the entity-component `Transform` is
`{484AE67D-…}`. Use the brace-wrapped `{GUID}` form only.

**The bundle call chain is now verified, not guessed.** `FUN_14643e7b0` (the
handler that logs `skipping ReceiveStateBundle`) → `FUN_146455e90` →
`FUN_14175ccc0` → `FUN_146af20d0` → `FUN_146af2340`, every edge a real call. The
call site shows `FUN_146af20d0` filling a **record id** and a **vector of fragment
objects** (not raw payloads — `FUN_146af2340` creates one object per fragment),
and `FUN_141717fc0` then indexes a handler table at
`state + 0x608 + record_id*0x10`. So the record id is a **handler index**, which
is why record id 1 is the local-player metadata slot.

**Where physics actually comes from.** The server replicates entities and
components through an **area-of-interest trait** system (`Amazon::Hub::Aoi`, 185
traits), as *records* carrying *fragments* — the `0x08` bundle. `PhysicsTrait`
owns state type `{F05E34C6-AF1E-476D-9472-5FC118FC4503}` and registers
`RegisterRigidBodyMsg` and friends. The by-name component creator
(`FUN_141416740`) was measured **never to run** during world entry, and the
capture's 79 fragments all carry `type_index` 1, so the replay never delivers a
rigid body either.

### The replication architecture, mapped (2026-10-10)

There are **three** message systems, and conflating them is what made the
protocol look opaque:

1. **AOI traits** (82 traits, 2276 trait/message pairs —
   `research/atlas/aoi-trait-registry.json`): server-side authority for entity and
   component state. A trait replicates state as **records carrying fragments**,
   which is what the `0x08` bundle transports. The record id selects a handler at
   `state + 0x608 + record_id*0x10`.
2. **Client messages** (1783 RMIs): component-facet method calls named
   `<Component><Client|Server>Facet_<Method>`. This is the system behind the live
   warning `RMIDispatch: The facet target ID couldn't be found` — the server calls
   a facet method on a facet the client does not have.
3. **Javelin typed messages** (144 — `research/atlas/javelin-messages.json`):
   session, hub and movement control, carrying a wire type number.

**The spawn protocol is now readable.** The client asks with
`PlayerSpawnPointRequestTrait::RequestPlayerSpawnPointMsg`; the server answers
with `ReceivePlayerSpawnPointSuccessMsg`; the manager runs
`ProcessSpawnQueueMsg`; and the body is created through
`PrefabSpawnRequestTrait::RequestSpawnPrefabMsg`. **Physics is registered
separately**, by `PhysicsTrait::RegisterCharacterMsg` /
`RegisterCharacterWithRepulsorsMsg`. `PhysicsTrait` alone registers **76**
messages, including `RequestCharacterSetPositionMsg`,
`RequestCharacterPositionDeltaMsg` and `RequestIsCharacterReadyMsg`.

So "give the player a body" is not one message: it is a spawn-point handshake, a
spawn-queue process, a prefab spawn **and** a physics registration — and the
capture contains only the first part.

### The state bundle is a RECORD SEQUENCE — corrected and verified (2026-10-10)

The `0x08` body is `[marker][01][varint SEQ][6 invariant bytes][varint length]`
then a payload that is a **sequence of records**, each
`[u8 record_id][u8 fragment_count][fragments…]`.

This replaced the earlier "one record, one fragment" model, which was wrong in a
way that passed every check it was given: it consumed all 79 captured bodies
exactly, because it treated the whole payload as one opaque fragment payload.
**"Consumes exactly" is necessary but not sufficient** — an opaque-remainder model
always consumes exactly, so that check cannot distinguish one fragment from many.

The discriminating evidence is the client's own reads. A live Frida probe on
`FUN_146af20d0` (one record) and `FUN_146af2340` (one fragment) measured, per
record, the bytes consumed and the number of nested reader calls, and:

- the `fragment_count` byte **equals the nested-call count in all 90 distinct
  records** (`01 30`→48, `01 09`→9, `02 03`→3, `03 01`→1, `0d 06`→6, `1d 13`→19);
- byte-exact on the 78-byte bundle: payload 66 bytes = **two records of 33
  bytes** (`48 03 …`, `49 03 …`), with the client measuring `consumed=33,
  fragments=3` for each;
- `record_id` is **sequential** across a session (1…`0x2e`, then `0x48`, `0x49`,
  `0x4a`) — a handler index, matching `state + 0x608 + record_id*0x10`;
- `SEQ` spans **1..53**, exactly the high-water the client logged live.

So the spawn record's fragment count is **48**, not 1. All 78 bundles round-trip
exactly through the new parser.

**The fragment grammar is also verified.** A fragment is
`[varint KEY][varint TYPE_INDEX][type-specific payload]` — **exactly two header
varints, no length field**. A live probe logging every varint read with its offset
shows the first two varints at offsets 0 and 1 in **300 of 300 fragments**, with 48
distinct keys and 47 distinct types and a **1:1** key→type binding. The keys are
sparse (0…77), which is a component slot table with freed slots, and the spawn
record has exactly 48 fragments with exactly 48 distinct keys. The payload length
is **implied by the type** (the reader consumes it through vtable `+0x90`), which
explains the variable fragment sizes.

**The container is now fully understood down to the fragment.** What remains is
the **per-type payload encoding** — one codec per component type. That is the
remaining long tail, and it is also what physics needs, since a physics component
would arrive as one of these fragments.

## Decompilation campaign

**50** targets in the committed manifest
(`research/atlas/decomp-campaign.json`: launch 3, login 2, server-select 11,
character-select 0, world-entry 12, in-world 22). Growth through `campaign add` /
`expand` now persists to that manifest instead of only to the ignored per-build
state, so it survives the machine. The bulk corpus remains complete:
423,579 `.pdata` ranges accounted for, **423,542 `ok` / 37 `fail`** (20 timeouts,
10 mid-function fragments, 6 payload-cap, 1 address-space), and it does **not**
cover the 13,943 leaf functions in `.text` that carry no unwind info.

## Next useful step

Follow the gated plan in [`docs/ROADMAP.md`](docs/ROADMAP.md): reproduce the red
ALC state and measure `+0xAA0`/`+0xAA8` plus the 20-minute exit on a fresh client;
then read the player's transform/body-controller state while pressing and
releasing W. Trace the channel-1 `0x635` consumer and the missing facet target for
reliable 4216. Change one evidence-backed variable per fresh process. Close only
when the actual HUD clears, the client stays in-world beyond 20 minutes and then
2 hours, and the transform changes with W and stops on release. Transport logs
and screenshots alone do not pass those gates.

## Project structure

The game profile/runtime, PAK index, tools, and old logs live in ignored
project-local paths (`private-client/`, `.azoth/`, `reverse/builds/`).
