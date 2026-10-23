# Feature: azoth-wire parity, and the remaining 1.460 measurements

Phase 0 closure of `docs/PLAN-backend-rust.md`. Two halves:

* **Code** — the first crate of the Rust workspace, `azoth-wire`, ported from the
  Python codecs and proven byte-for-byte against them over the captured corpus.
* **Measurement** — the three 1.460 rows that Phase 0 left open (entity
  transform, sprint ceiling, buffer slot order) plus continued decoding.

Build in scope: `1.460.6033.6024067` /
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1.** "1. La paridad de azoth-wire" — the codecs are ported to Rust and their
  output is byte-identical to the Python encoders over the whole captured corpus.
- **S2.** "Arreglar el probe de transform" — the entity transform measurement
  works, or its unavailability is demonstrated with a concrete reason.
- **S3.** "Re-medir con sprint" — the sprint speed ceiling is measured, and the
  five-position buffer's slot order is resolved.
- **S4.** "luego continua toda la noche investigando cosas, haciendo decoding,
  con frida, etc lo que necesites" — continue the decoding work beyond the named
  items, within the repository's evidence rules.
- **S5.** "ves monitoreando el disco importante no pasarte" — check free disk
  before and after every disk-heavy step; compress raw logs rather than keep them
  raw; never let a log grow unbounded.
- **S6.** "cuando acabes todo pushea commitea y apaga el ordenador" — at the end:
  commit, push, then shut the machine down. Nothing is left running.
- **S7.** "consiguiendo tener todo para la 1.460" — every fact recorded is
  build-scoped to the SHA-256 above; a fact from another build is not evidence.
- **S8.** Repository rules: no EAC, no memory reads while its state is uncertain,
  Steam install read-only, no raw captures committed, docs and code in English.
- **S9.** The plan's own rules: a crate owns a distinct reason to change; no file
  over ~400 lines; no `unsafe` outside `azoth-wire` and `azoth-dtls`; no
  environment variables outside a `config` module.

## Tasks

| ID | Specs | Route | State |
| --- | --- | --- | --- |
| T1 | S9 | inline | in progress — branch `feat/azoth-wire-parity`, workspace skeleton |
| T2 | S1, S9 | inline | pending — codecs |
| T3 | S1 | inline | pending — differential harness, 0 mismatches |
| T4 | S2 | inline + live client | pending — transform probe |
| T5 | S3 | inline + live client | pending — sprint |
| T6 | S4 | inline | pending — decoding |
| T7 | S5, S6 | inline | pending — disk check, commit, push, shutdown |

## Log

### L1 — the user's request, verbatim

> Vale peus a ver yo me voy a ir a dormri quiero que estes toda la noche de forma
> autonoma, consiguiendo tener todo paral la 1.460 y asi mañana empezsa el
> servidor de rust ,1. La paridad de azoth-wire, Arreglar el probe de transform y
> Re-medir con sprin y leugo conctinua toda la noche investigando cosas, haciendo
> decoding, con frida, etc lo que necesites y ves monitoreando el disco importante
> no pasarte, cuando acabes todo pushea commitea y apaga el ordenador

### L2 — slice boundaries, and why the first commit is large

`c5754f2` is 4,533 authored lines in one commit, past the ~400-line review slice.
That is deliberate and recorded here rather than split artificially:

* **It is documentation and measurement, not behaviour.** The bulk is
  `docs/PLAN-backend-rust.md` (1,950 lines, written before this session) and
  `odd/tasks/remeasure-1460.md` (491 lines). Splitting a single coherent evidence
  document across commits would make it harder to review, not easier: the plan's
  §0.2 status table only makes sense next to the measurement log that produced it.
* **It is the specification the later code commits are reviewed against.** Landing
  it first means the crate commit can cite it instead of restating it.

The code commits that follow are kept inside the slice limit: the `azoth-wire`
crate and its parity fixtures land as their own commit, and the live-client
measurements as another.

Delivery strategy: `feature-branch-chain` on `feat/azoth-wire-parity`. No push or
merge is implied by a commit; both remain the user's decision, and the user asked
for a push at the end of the session (S6).

### L3 — T4: the transform probe works now, and the answer is not an offset

**The fix, and the measurement that caused it.** The probe ran 13 patterns over ~1,059 memory
ranges, i.e. **13,767 `Memory.scan` calls** and ~39 GB of scanning, with a `setImmediate`
round-trip between each. That does not finish in 15 minutes on this machine, which is why two
earlier runs reported `TIMED OUT - no summary`. The cost is `patterns x budget`, and nothing in
the probe said so.

Two changes, both in `reverse/probes/client/frida-actor-transform.py`:

* `--only <label>` scans ONE captured id. The positive control alone is 1/13 of the work.
* `--budget-mb` makes the budget explicit, and the probe now **prints
  `N pattern(s) x M MB = N*M MB of scanning`** before it starts, so a long run is explained
  rather than mysterious.

**Result: the positive control passes.** One pattern, 3,000 MB, **6 min 21 s**, and the local
player's actor id `1a954abc4b3185bfbe37c3d8592618e0` was found **4 times**.

**And `withPair = 0` on all four hits — the transform is not next to the actor id.** Dumping a
±64/+128 byte window around each hit shows what they actually are: the actor id inside **wire
buffers**, not inside an entity object. The fourth hit is unambiguous:

```text
... c4 8f dd cc | 02 62 04 00 | ed e8 bb cd 3b 4b 00 90 | 31 79 c5 76 00 00 00 92 |
    1a954abc4b3185bfbe37c3d8592618e0 | 00 01 b5 18 | fb de 4b 9a 60 0d 42 8f ...
    <-- 16-byte target actor id -->   <-- 0x635 -->  <-- channel-1 body -->
```

That is the client's own channel-1 container: `crc32`, `len`, target actor id, `00 01`, type
varint `0x635`, body. So the scan found the **input record being assembled**, not the entity.

**This is a real result, and it agrees with what the repository already recorded**: the rendered
bodies are *not* held under their declared actor id (`STATUS.md` 2026-10-20: "the rendered bodies
are not held under their declared actor id, which is the opposite of what this re-scope
assumed"). Searching by actor id cannot find a transform, because the id is not stored with it.

**Therefore the transform offsets stay measured-but-not-re-verified**, and the honest statement
is narrower than the plan's original row: `+0x14c/+0x15c/+0x16c` (stride `0x10`) was established
on 1.400 by decompiling `FUN_140fddfa0` and reading the holder's vtable slot 0 (type
`484AE67D-…` = `Transform`) — a **method** that does not depend on the actor id and would work on
1.460. What has *not* been done is running that method on this build. That is a follow-up with a
known technique, not an open question, and it does not block Phase 1–3.

**An operational mistake worth recording.** After the probe, a throwaway script of mine attached
to the client to dump the hit windows and exited **without detaching**. The client process was
gone shortly after. This is the `frida-agent.dll_unloaded` execute-after-unload crash the probe's
own docstring warns about, and the shared probes avoid it deliberately (`_paths.safe_shutdown()`).
An ad-hoc Frida script is not exempt from that rule. The session it killed was the one that had
not yet run the sprint measurement, so the sprint needs its own run.

### L4 — T5: the buffer slot order is answered; sprint is not

**The five-position buffer's slot order — ANSWERED: NEWEST FIRST.**

The 1.400 note said "a sliding buffer of the last five movement samples, newest first at
20 Hz" and never proved the order. The earlier attempt in this campaign tested the wrong pair
and came out "inconclusive"; the correct test is `buffer(n+1)[1] == buffer(n)[0]` (if the newest
sample is first, the next record's second entry is this record's first), and its complement
`buffer(n+1)[4] == buffer(n)[0]` for oldest-first.

Measured over **343 records** carrying exactly five plausible position pairs (payload sizes 401
and 351, from a live walk):

| Test | mean distance | pairs within 0.6 u |
| --- | --- | --- |
| `buffer(n+1)[1] ~ buffer(n)[0]` (newest-first) | **0.0073 u** | **341 / 342** |
| `buffer(n+1)[4] ~ buffer(n)[0]` (oldest-first) | 0.1847 u | — |

0.0073 u is 25x tighter than the alternative, and 341 of 342 transitions agree. **The buffer is
newest-first**, so `marker + 12` is the CURRENT position and not the oldest of five — which is
what makes the existing locator correct rather than accidentally close.

**The earlier "inconclusive" was an interpretation error, not a measurement error.** It compared
`buffer(n+1)[0]` against both `buffer(n)[0]` and `buffer(n)[1]` and concluded newest-first was
wrong because the first was closer. Under newest-first that is exactly what should happen:
`buffer(n+1)[0]` is one sample after `buffer(n)[0]` and two after `buffer(n)[1]`. The test now in
the record compares the pair that actually identifies the order.

**Sprint — NOT MEASURED, and the reason is stated rather than papered over.**

Three attempts:

| Attempt | Input | Result |
| --- | --- | --- |
| 1 | hold `W` (`0x11`) 3 s | walked, but the client died before analysis (an ad-hoc Frida script of mine failed to detach — see L3) |
| 2 | hold `Shift` (`0x2A`) + `W` 3 s | **path 0.00 u, 0 moving intervals** |
| 3 | hold `W` 7 s | 4.18 u total, then **0.00 u/s from second 2 onward** |

Attempt 2 moved nothing at all, so Shift+W is **not** the sprint binding — or the character was
already blocked. Attempt 3 shows movement for two seconds and then nothing for seven, which is
consistent with the character running into geometry rather than with a sprint ramp.

So the sprint ceiling is **not measured**, and no number is quoted for it. What *is* measured
across this campaign's runs: a walk peak of **2.76 u/s** in the cleanest 3 s segment (16.54 u of
straight-line path, 59 of 59 moving intervals at offset +90°) and **5.39 u/s** in the earlier
nine-episode set. Those two differ by 2x, which means the walk speed itself is not yet a settled
constant — it may depend on terrain, encumbrance, or whether the character is on a road.

**Consequence for the validator.** `docs/PLAN-backend-rust.md` Q9 asks for the sprint and mount
bounds so the movement validator's threshold is not tuned on a walk. It stays open. The safe
choice for a port is therefore **not** a speed constant but the structure the Python code already
has: validate against the SERVER's own previous position with a per-session calibrated reference,
and treat the speed window as configuration rather than as a decoded fact. Tuning a hard constant
on 2.76-vs-5.39 u/s evidence would reject legitimate movement.

**Two operational facts for the next session:**

* `az.py shot` reported "New World window not found" while the client was alive — the screenshot
  path needs the window title, and the harness had already lost it. A state check is cheaper than
  a screenshot anyway (the computer-use skill says so), and it answered the question here.
* A 7-second key hold is not the same experiment as a 3-second one: the second half of attempt 3
  produced no displacement, so a longer hold can be a *worse* measurement. Keep holds short and
  repeat them.

### L5 — T6: the presence decode is a STATIC task after all

`research/atlas/presence-codecs.json` recorded that the static route which decoded the movement
family on 1.400 is gone on 1.460: the name and GUID strings have zero static referrers, both
16-byte GUID forms occur zero times, and `FUN_1407de270` (the builder recorded for 1.400) has no
callers. Its conclusion was that the descriptor tables are assembled at runtime and the six
presence layouts need live instrumentation.

**That conclusion was about an address, not about the route.** It was also written when
`reverse/builds/30fe6461…/corpus/` did not exist — `builds.json` still says no corpus exists,
which is stale (L1).

With the corpus (423,609 ranges, 421,742 decompiled OK) the route is reachable:

```text
FUN_1461aa880     the descriptor builder, 3,520 call sites

  every getter has this shape:
      apuStack_48[0] = &UNK_<descriptor address>;
      uVar1 = FUN_1461aa880(apuStack_48);
      DAT_<cache> = uVar1;
```

`scripts/map-descriptors.py` extracts them: **3,517 descriptor getters**, descriptors spanning
`0x147f42d88 .. 0x1485840e8`. The builder advances its arena pointer by **0x40**, so the descriptor
stride is 0x40, and the getter's stack object carries a constructor at `+0x38` that the builder
invokes virtually.

**The AddActorMessage descriptor, read from the executable's `.rdata` (read-only, mapped by RVA):**

```text
0x1485800b0  40 75 a5 46 01 00 00 00   -> 0x146a57540     (+0x00)
             40 75 a5 46 01 00 00 00   -> 0x146a57540     (+0x08)
             50 75 a5 46 01 00 00 00   -> 0x146a57550     (+0x10)
             e0 75 a5 46 01 00 00 00   -> 0x146a575e0     (+0x18)
             b0 fb 78 40 01 00 00 00   -> 0x14078fbb0     (+0x20)  no static call sites
             30 de 46 40 01 00 00 00   -> 0x14046de30     (+0x28)  481 call sites
             "AddActorMessage\0"                            (+0x30)
```

and `0x1485800e0` — the address the atlas cited — is where the **name string** begins, followed by
`96C829CE-DFBC-4763-959C-32A6B22D81EF` and `bc291efa…`. So the atlas had the descriptor's *payload*
address, not the descriptor. Its getter is `FUN_140273730`, caching into `DAT_14a56ce7b`.

**What this changes.** The presence decode is no longer blocked on a live session: the next step is
to read the three codec-area pointers (`0x146a57540`, `0x146a57550`, `0x146a575e0`) and the
constructor at `+0x38`, looking for the 1.400 shape — "a codec facet at descriptor+0x48 whose +0x20
is MARSHAL and +0x28 is UNMARSHAL". `FUN_146a57550` is already in the corpus and looks like a
registration function: it calls `FUN_1461aaa00`, one letter away from the builder.

`presence-codecs.json` is corrected in place with the builder, the stride, the descriptor layout and
the address correction, so the next session does not repeat the dead end.

**What I did not finish, stated plainly.** I mapped the route and identified the descriptor, but I
did not read the codec facet out of it. That is where the six layouts actually live, and it is the
next session's first task — now with a script (`scripts/map-descriptors.py`) and an address instead
of a live-attach prerequisite.

### L6 — T5 (sprint), second attempt: still not measured, and why I stopped pushing

A second live session ran the sprint test cleanly, with no probe attached:

| Attempt | Input | Result |
| --- | --- | --- |
| walk | `W` (`0x11`) 3 s | **16.54 u** path, 2.76 u/s, **59 of 59** moving intervals at offset **+90°** |
| sprint | `Shift` (`0x2A`) + `W` 3 s | **0.00 u**, 0 moving intervals |

The walk segment is the cleanest single measurement of this whole campaign: 59 moving intervals
and **every one** at +90° from the camera yaw, which is the yaw frame confirmed a third time on a
third session.

The sprint attempt moved nothing at all. Two candidate explanations, and I could not distinguish
them tonight:

1. **`Shift+W` is not the sprint binding.** New World may treat running as the default and
   `Shift` as a walk modifier, or sprint may be bound elsewhere. The repository has no sprint
   binding recorded — `research/atlas/levers.md` and the client-map notes do not mention one —
   so this is an assumption I made, not a fact I looked up.
2. **The character was blocked.** The preceding 7-second hold produced movement for two seconds
   and then nothing, which is consistent with running into geometry.

Either way, `Q9` stays **open**, and the plan now says what that means in practice: the movement
validator must not use a hard speed constant. It validates against the server's own previous
position with a per-session calibrated reference — the structure `movement.py` already has —
because the walk speed itself measured 2.76 u/s here and 5.39 u/s in an earlier set, and a
constant chosen from either would be wrong for the other.

**I stopped here rather than keep guessing.** Three failed attempts at the same unknown is the
signal to record it and move on, not to try a fourth key combination on a machine the owner is
not watching. The next session has the specific thing to look up first: the client's own key
binding for sprint, from its options or its input map, before sending any key.

**Disk and cleanup.** Both raw logs from this session are compressed, not deleted:
`world.log.gz` (1.5 MB from 28 MB) and `world-tanda-b.log.gz` (697 KB from 16.6 MB), both
integrity-checked with `gunzip -t`. Tonight's Frida agent directory (44 MB) was removed; four
older ones from previous sessions were left alone because they are not this feature's artifacts.
Free disk after cleanup: **~85 GB of 222 GB**.

## Session 2 — the presence codec is decoded

### L7 — AddActorMessage's layout, from the corpus, with no live session

The previous session recorded the descriptor route and left the codec facet as the next task. It
is done, and it went further than planned: **`AddActorMessage`'s wire layout is decoded.**

**The facet exists on 1.460, and it is the 1.400 shape.** `AddActorMessage`'s real descriptor
getter is `FUN_146ac20a0` — found by grepping the corpus for the type name inlined as
little-endian immediates (`0x726f746341646441` = `"AddActor"`, `0x7373654d` = `"Mess"`, `0x6761` =
`"ag"`). It parses the brace GUID from `0x1485800f0` and installs a facet at `descriptor+0x48`.
Reading six qwords of `.rdata` at `0x148575298`:

```text
+0x00  0x146a33a20   deleting destructor (confirms the table: it restores &UNK_148575298)
+0x08  0x1407c7f40
+0x10  0x14151e350
+0x18  0x14151e3e0
+0x20  0x146a33990   MARSHAL
+0x28  0x146a339a0   UNMARSHAL
```

**The layout, every field read by code:**

| offset | size | reader | field |
| --- | --- | --- | --- |
| `0x00` | 16 | `FUN_1408787b0(…, 0x10)` | raw 16 bytes |
| `0x10` | 1 | direct | u8 |
| `0x18` | var | `FUN_146a6ebe0` | u8 count + payload |
| `0x28` | 8 | `FUN_14087af30` | u64 BE |
| `0x30` | 8 | `FUN_14087af30` | u64 BE |
| `0x38` | 8 | `FUN_14087af30` | u64 BE |
| `0x40` | 8 | `FUN_14087ae90` | two u32 BE |
| `0x48` | 1 | direct | u8 |
| `0x50` | var | `FUN_14087a570` | length-prefixed vector |
| `0x78` | var | `FUN_14087a570` | length-prefixed vector |
| `0xa0` | var | `FUN_14087a570` | length-prefixed vector |
| `0xc8` | 4 | `FUN_14087a3c0` | u32 BE |
| `0xcc` | 1 | `FUN_1408787b0(…, 1)` | bool |
| `0xd0` | var | `FUN_1415b62d0` | sub-record |
| `0xf4` | var | `FUN_1415b62d0` | sub-record |

**Big-endian throughout**, and that is measured rather than assumed: every integer reader goes
through `ntohl` — `FUN_146168b00` for the u64 path, `FUN_146168aa0` for the u32 path. That is the
same endianness as every other field this project has decoded, which is a useful cross-check.

**What is NOT decoded, stated plainly:** the *meaning* of each field. The offsets, widths and
readers are measured. Which u64 is what, what the three vectors contain, and what the two
`FUN_1415b62d0` sub-records carry are open. The 16-byte head is consistent with an actor id —
`ClientAddEntryMsg` (wire 164) is independently measured as `[00 01][a4][16-byte actor id]` — but
that is not proven for this message and is labelled as an inference in the atlas.

### L8 — three corrections, two of them to my own previous session

1. **The descriptor I recorded last session was the wrong one.** `0x1485800b0`'s slot `+0x10`
   registers `FragmentUpdateMsg` (its type object `FUN_146ac6910` inlines `"FragmentUpdateMsg"`),
   so those six qwords are not `AddActorMessage`'s. The real getter is `FUN_146ac20a0` and the
   facet is `0x148575298`. My identification rested on address adjacency to the name string, which
   is exactly the kind of inference the repository's rules warn about.
2. **"The GUID strings have zero static referrers" is false.** `0x1485800f0` has exactly one
   referrer, `FUN_146ac20a0`. The original claim was made against the 1.400 image.
3. **Four of the addresses I listed are not functions at all** — `0x146a57540`, `0x146a575e0`,
   `0x14078fbb0`, `0x14046de30` have no `.pdata` entry and appear nowhere in the corpus. They sit
   in inter-function padding, which is why they read as plausible code pointers in a raw `.rdata`
   dump.

**The general lesson.** Reading a raw descriptor from `.rdata` gives you pointers, not meaning. Two
of the four "functions" I reported were padding, and the descriptor I picked belonged to a
different message. The corpus is what settles it: a function that exists has a `FUNC` block, and a
type name appears as immediates inside the getter that owns it. That check costs one grep and would
have caught both mistakes.

### L9 — the recipe for the other five

`presence-codecs.json` now carries it: each getter inlines its type name as little-endian
immediates, so grepping those constants finds the getter, the `FUN_1407de410` call and the
`*puVar = &UNK_1485…` facet address. Then six qwords at that VA: slot 4 is MARSHAL, slot 5 is
UNMARSHAL. The same six-step read applies to `SpawnActorsMsg` (574), `Replicate` (391),
`ReplicateClient` (407), `FragmentUpdateMsg` (422) and `UpdateMsg` (106).

### L10 — all six facets located, three layouts decoded

`scripts/find-codec-facet.py` automates the recipe and is validated against `AddActorMessage` (it
reproduces the facet `0x148575298` and both slot addresses derived independently last session).

| message | wire | facet | MARSHAL | UNMARSHAL | layout |
| --- | --- | --- | --- | --- | --- |
| `AddActorMessage` | 449 | `0x148575298` | `0x146a33990` | `0x146a339a0` | **decoded**, 15 fields |
| `SpawnActorsMsg` | 574 | `0x14857a3f0` | `0x1407cdbe0` | `0x146a49b20` | **decoded: ONE u64 BE** |
| `Replicate` | 391 | `0x147f43110` | `0x1407c1040` | `0x1407c1090` | not read yet |
| `ReplicateClient` | 407 | `0x147f44b48` | `0x1407c1040` | `0x1407c5600` | not read yet |
| `FragmentUpdateMsg` | 422 | `0x147f44128` | `0x1407c4180` | `0x1407c41a0` | **decoded: u64 BE + u32 BE** |
| `UpdateMsg` | 106 | `0x147f44ca0` | `0x1407c1890` | `0x1407c5840` | not read yet |

**`SpawnActorsMsg` is a single `u64` big-endian — not a list.** `FUN_146a49b20` reads exactly one
value through `FUN_14087af30` into `param_3 + 1` and returns; there is no count, no loop, no
vector. That is a meaningful design constraint for the server: the message that makes actors
appear carries an *identifier*, and whatever the client does with it is driven by that id rather
than by an inline payload. It also matches the observation that the client's record slots and
actor ids are separate addressing schemes.

**`FragmentUpdateMsg` is a `u64` then a `u32`**, both big-endian (`FUN_1407d9520` → `FUN_1407dae40`
for the u64, then `FUN_14087a3c0` for the u32).

**`Replicate` and `ReplicateClient` share their MARSHAL** (`0x1407c1040`) and differ only in the
unmarshal — which makes sense for a message and its client-direction twin, and is a good sign the
two facet tables were read correctly rather than swapped.

**The 8-byte prefix collision, and how it is resolved.** Both names start with `Replicate`, so a
first-eight-bytes search returns both getters. The disambiguator is the immediates that *follow*
the key: `FUN_1407f36a0` continues with `0x65` (`'e'`) = `Replicate`, while `FUN_1407f38c0`
continues with `0x696c4365` (`'Clie'`) + `0x6e65` (`'en'`) + `0x74` (`'t'`) = `ReplicateClient`.
The script now matches per function body, so a longer name resolves to one getter.

**What is left, and it is bounded.** Three unmarshal bodies to read (`0x1407c1090`,
`0x1407c5600`, `0x1407c5840`), which needs no client and no probe. After that the wire half of
Phase 4 is fully decoded and the only open question is what the fields *mean*.

### L11 — the six split into three fixed layouts and three polymorphic ones

Reading the last two unmarshals changed the shape of the remaining work, and it is worth stating
because it is not what "decode the six codecs" implies.

**Fixed layouts (transcribable):**

| message | layout |
| --- | --- |
| `SpawnActorsMsg` (574) | one `u64` BE |
| `FragmentUpdateMsg` (422) | `u64` BE + `u32` BE |
| `AddActorMessage` (449) | 15 fields, `L7` |

**Polymorphic (no fixed field list):** `Replicate` (391), `ReplicateClient` (407), `UpdateMsg` (106).

`FUN_1407c1090` (Replicate's unmarshal) does exactly three things:

```c
lVar1 = FUN_1407e3e10(param_3, 1);              // construct a record object for its type
FUN_146161c20(lVar1 + 0x10, param_2, param_4);  // -> three virtuals: vtable+0x90, +0xa0, +0xb0
```

and `FUN_146161c20` is the whole story:

```c
cVar1 = (**(code **)(*param_1 + 0x90))(param_1, param_3);   // if 0 -> record fails
cVar1 = (**(code **)(*param_1 + 0xa0))(param_1, param_3);   // if 0 -> record fails
cVar1 = (**(code **)(*param_1 + 0xb0))(param_1, param_3);   // if 0 -> record fails
```

So **the wire shape is chosen by the record's own component type**, and the dispatch is the
`vtable+0x90` this atlas already named for the presence family. There is no per-message layout to
transcribe for these three: the layout is per *component type*.

`ReplicateClient` is the same structure with its own constructor — `FUN_1407e3fe0` instead of
`FUN_1407e3e10` — then the same `FUN_146161c20` and the same virtual triple. Two constructors, one
dispatch, which is exactly why the two messages share a MARSHAL and not an UNMARSHAL.

**What this means for Phase 4, stated honestly.** The three fixed-layout messages are enough to
tell a client that an actor exists (`SpawnActorsMsg` + `AddActorMessage`) and to update one
fragment (`FragmentUpdateMsg`). That is the wire half of "another player exists", and it is
decoded. Replicating *component state* — position, vitals, appearance — needs the per-component
codecs, which is a different and larger body of work: one reader per component type, dispatched
through `+0x90`. The corpus makes it tractable, and the same recipe applies (find the type, read
its reader), but it is not one function read away and this log does not pretend otherwise.

**`UpdateMsg` (106) is left unread.** With two of three polymorphic unmarshals confirmed identical
in structure, the expected finding there is the same shape with a third constructor. That is an
expectation, not a measurement, and it is recorded as such.

### L12 — T6 done, and Phase 1 started

`UpdateMsg` (106) turned out **not** to be polymorphic, correcting my own prediction: `FUN_1407c5840`
→ `FUN_1407d8d50` reads a prefix-varint length (via `FUN_14087b760`, the same ladder this crate
already implements), rejects anything at or above `0x201`, and copies the bytes. So **four** of the
six presence messages have fixed layouts and only `Replicate`/`ReplicateClient` dispatch per
component type. `presence.rs` now carries `UpdateMsg` with the 512-byte cap.

### L13 — Phase 1: `azoth-region`, and the parity that found two real bugs

The crate renders the channel document from the registry. The parity test requires the same 7,645
bytes the Python gateway produces, and building it caught two ordering defects that **no semantic
comparison would have found**:

1. **`serde_json::Map` is a `BTreeMap` by default**, so every object in the document came out
   alphabetised — `apiEndpoint, awsRegion, clientTag, stage, version` instead of the served
   `awsRegion, version, apiEndpoint, clientTag, stage`. Fixed with the `preserve_order` feature.
2. **The region's dotted `omni.privacy-settings.*` keys were a `BTreeMap`**, which sorted
   `client-endpoint` before `region` and moved them out of the order the document fixes. Changed to
   a `Vec` so the order is data rather than an accident of key names.

Both are the class of bug the plan's §11.1 exists for: a field cannot drift *silently*, so the check
has to be on bytes, not on parsed values. A JSON-value comparison passes on both of these.

**What the crate decides, and the reason recorded in code:**

* eligibility is a pure function including `build_sha256 == CHANNEL_BUILD_SHA256`, so a 1.400 world
  can never be handed a 1.460 client;
* allocation sorts by headroom then name, so two identical registries allocate the same world and a
  load test is reproducible;
* the ETag is FNV-1a 64 rather than the prototype's MD5 — the client needs a tag that changes with
  the body, not a particular algorithm, and the route is polled;
* the region's status is **not** rendered into the channel document (it is not part of that
  contract); what changes the bytes is the display name, and the test says so rather than implying a
  status flip is visible there.

**Two files crossed the 400-line limit** (`registry.rs`, `presence.rs`) so their assertions moved to
integration tests. The limit was not raised.

**State:** 105 tests across the workspace, `xtask` clean, 0 build warnings, pushed.
