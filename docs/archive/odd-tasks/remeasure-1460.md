# Feature: re-measure the build-scoped facts on 1.460

Phase 0 of `docs/PLAN-backend-rust.md`. Its job is to turn every "unverified on
1.460" row of that plan's §0.2 into **verified** (with a measurement id),
**refuted** (with the number), or **not-a-dependency**. Nothing may be ported on
an unverified offset.

Build under test: `1.460.6033.6024067` /
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`
(`research/atlas/builds.json`).

## Specs

- **S1.** "lanza las 3 tantas 1 a 1" — the three measurement batches run one
  after another, in order, and each finishes before the next starts.
- **S2.** "aun que estes toda la noche no pares" — the campaign runs to
  completion without stopping to ask for permission between batches.
- **S3.** Tanda A is read-only: "es lectura de archivos, no toca nada".
- **S4.** Tanda B needs the private client launched: "lanzar el cliente privado
  (`python az.py dev` + `scripts/private-run.py`), que es una acción real sobre
  la máquina y sobre la copia privada del ejecutable".
- **S5.** A batch may not be reported as done while a question it was supposed to
  answer is still open; an unanswered question is reported as **not exercised**,
  never as refuted.
- **S6.** Every measured number names the file it came from.
- **S7.** Tanda A's deliverable was: "¿Ya hay evidencia de movimiento en los logs
  de 1.460?", "¿Existe el corpus de 1.460?", "Inventario de offsets en código".
- **S8.** Tanda B's deliverable was: the channel-1 layout ("marcador `0.05`,
  posición en `marker+12`, forma idle 311 B vs moving 403–412 B, buffer de 5
  muestras"), the yaw frame ("Yaw medido desde +Y, forward = `(−sin, cos)`"), the
  walk speed ("Velocidad de caminata (3,83 u/s en 1.400)"), and the state-stream
  cadence.
- **S9.** Tanda C's deliverable was: the spawn-record position offset
  ("38332/38336"), the entity transform ("`+0x14c/+0x15c/+0x16c` stride `0x10`"),
  and the inventory entry grammar ("`00 01 82 5a`, 68 bytes antes").
- **S10.** Repository rule: "Do not commit or push unless the user explicitly
  asks." No commit is made by this feature.
- **S11.** Repository rule: the Steam install is read-only, and no process memory
  read, debugger or injection runs while EAC state is uncertain
  (`AGENTS.md`).

## Tasks

| ID | Specs | Route | State |
| --- | --- | --- | --- |
| T1 | S3, S7 | inline | done — log, corpus and offset inventory |
| T2 | S3, S8 | inline | done — channel-1 container, marker, field layout, cadence from the existing 409 MB log |
| T3 | S4, S8 | inline + live client | done — walk, yaw frame on W/A/D, speed, buffer, cadence (L4) |
| T4 | S4, S9 | inline + live client | done — spawn offset verified; transform probe unavailable; inventory grammar undecoded (L5) |
| T5 | S5, S6 | inline | done — evidence file written and the plan's §0.2 updated (L6) |

## Log

### L1 — the user's request, verbatim

> Claro lanza las 3 tantas 1 a 1, aun que estes toda la noche no pares

### L2 — T1 results (Tanda A, part 1)

**Q13 (does the 1.460 corpus exist) — ANSWERED: yes.**
`reverse/builds/30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033/corpus/`
holds `meta.json`, `progress.json`, `corpus.log` and shards totalling **1.1 GB**.
`research/atlas/builds.json` still says "No Ghidra project, no function scan and
no corpus exists for 30fe6461" — that claim is **stale** and is corrected by T5.
`docs/EXTRACTION-2026-10-22.md` (423,609 ranges, 421,742 ok) is the current one.

**A 409,673,652 B `world.log` exists** (`.azoth/logs/world.log`, mtime
2026-10-22 22:23) containing **17** `dtls-established`, **17** `replay-armed`,
**1,119** `movement-simulation-summary` and **11** `movement-simulation-live`
events. So the movement observer and the simulator both ran on 1.460 sessions.

**A real walking summary exists on 1.460** (`world.log`):
`{"samples": 604, "adopted": 604, "held": 0, "violations": 0,
"forward_speed": 0.309, "lateral_speed": 0.01, "mean_prediction_error_u": 0.0015,
"stream_flowing": true}`. Forward dominates lateral 31:1, which is consistent with
the documented yaw frame but is **not** a verification (0.309 u/s is far below a
walk).

**The offset inventory (S7, third item)** — constants the port would inherit,
all 1.400-derived:

| Constant | Where | Value |
| --- | --- | --- |
| `STATE_PLAYER_FRAGMENT_BOUNDARIES` | `rep.py:901` | `(2, 60, 3955, 4295, 4301, 4498, 5335, 5386, 7125)` — 9 boundaries, 9 fragments |
| spawn position pair | `rep.py` `apply_position_override`, `position_fragment_from_spawn` | payload offsets 38332/38336, f32be |
| entity template | `entities.py` | record 70, 2 fragments, 162 B, position at 6 and 74 |
| inventory entry marker | `inventory.py` | `00 01 82 5a`, entry starts 68 B before it |
| channel-1 position | `alc.py` | `marker(0.05) + 12` |
| entity transform | `STATUS.md` 2026-10-20 | `+0x14c/0x15c/0x16c`, stride `0x10` |

Two of these are already offset-free by construction and therefore not at risk:
`apply_position_override` anchors on the captured **value**, and `alc.py` locates
by **marker**. The other four are fixed offsets and are the actual debt.

### L3 — T2 results (Tanda A, part 2): the channel-1 stream on 1.460

Method: `scripts/logwire.py` + `scripts/measure-world-log.py`,
`scripts/measure-angle-frame.py`, `scripts/measure-position-field.py`, all reading
`.azoth/logs/world.log`. 1,164,485 log events parsed; **229,304** typed channel-1
records decoded.

**Container format — CONFIRMED unchanged.** The payload is the client's own
container `[u32 BE crc32][u32 BE len][target 16][00 01][varint type][body]`:

| Check | Result |
| --- | --- |
| length field == payload−8 | **229,304 / 229,304** |
| crc32(payload[8:]) == declared | **229,304 / 229,304** |
| `00 01` typed marker at offset 24 | 229,304 / 229,304 |
| wire type == `0x635` | 229,304 / 229,304 |

Zero mismatches on both self-validating fields, so the container is byte-identical
in shape to 1.400 and the walk is exact rather than approximately right.

**Target actor id — one value, and it is the known identity bug.** All 229,304
records carry `1a954abc4b3185bfbe37c3d8592618e0` — including the ones from the
second client (`127.0.0.1:27001`). Two clients, one character id, confirmed
again on this build.

**Payload and body sizes:**

| Payload | Body | Count |
| --- | --- | --- |
| 311 B | 283 B | 193,661 |
| 309 B | 281 B | 26,792 |
| 154 B | 126 B | 5,171 |
| 153 B | 125 B | 719 |
| 93 B | 65 B | 691 |

So the "idle 311 B" figure from 1.400 is the **payload** size; the body is 283 B.
The unit had never been stated, and it matters because the plan quoted it.

**The position marker — present, unambiguous, and at the same layout as 1.400.**

| Property | 1.400 (recorded) | 1.460 (measured) |
| --- | --- | --- |
| records with a `0.05f` marker | 190,716 of 213,202 | **222,389 of 229,304** |
| records with **more than one** marker | 0 | **0** (all 222,389 carry exactly 1) |
| records with no marker (pre-spawn) | 14,665 | **6,915** |
| dominant marker body offset | 91 | **91** (194,987 of 222,389) |
| dominant **position** body offset | **103** | **103** |
| second marker offset | 104 | 89 (26,947) |

**CORRECTION TO AN EARLIER DRAFT OF THIS DOCUMENT.** A first pass reported that the
position block "moved from 103 to 91" and called it the headline finding. That was wrong:
it compared 1.400's **position** offset (103) against 1.460's **marker** offset (91). They are
two different fields twelve bytes apart — `position = marker + 12` — so the layout is
**unchanged**. The corrected statement is the table above, and it is what a reader should
trust. The mistake is recorded rather than deleted because it is exactly the kind of unit
confusion that turns into a wrong atlas entry.

What *is* verified: the marker locator plus twelve lands on the position pair on 1.460, at
body offset **103** in the dominant 311-byte form, which is the same offset the 1.400 work
recorded for that form. So `alc.py`'s design (locate by marker, not by offset) is
**VERIFIED on 1.460** and its measured constant is unchanged.

**Field layout after the marker — CONFIRMED.** Dumping two records with different
body sizes (335 B and 356 B) shows the same layout in both:

```
marker(+0) = 3d4ccccd (0.05)   yaw(+4)   pitch(+8)   x(+12)   y(+16)
```

with `pitch = 80000000` (−0.0) and yaw ≈ −2.69 rad in both. So
`(yaw, pitch, x, y)` at `marker+4/+8/+12/+16` is build-independent in shape.

**The five-sample buffer — NOT EXERCISED, so not refuted.** Counting plausible
`(a,b,x,y)` quads after the marker: **1 quad** in 222,209 records, 2 in 177, 3 in
3. The 1.400 "moving = 403–412 B with FIVE positions" form never appears because
no session in this log walked. Reported as open (S5).

**The yaw frame — NOT VERIFIABLE from this log.** Per peer:

| Peer | samples | distinct positions | displacements ≥ 0.5 u |
| --- | --- | --- | --- |
| `127.0.0.1:27000` | 195,152 | 205 | **6** |
| `127.0.0.1:27001` | 27,237 | 79 | **0** |

Six displacements is not a measurement. At a 0.2 u floor the dominant offset is
90° (41% of 34 displacements), which is *consistent* with `heading = yaw + 90°`
but is far too thin to claim. Needs Tanda B.

**A false finding, caught and discarded.** Pooling both peers produced a clean
two-state "flip" between `(9342.903, 2790.054)` and `(9343.298, 2782.994)`,
7.071 u apart, 16,430 times each way — which reads as a broken locator. It is
**two clients interleaved in one log file**. Per peer there is no flip: every
dominant transition is a self-transition. Recorded because it is the kind of
artifact that becomes a wrong atlas entry.

**State-stream cadence — measured, and it contradicts the prototype's tuning.**

| Kind | events | median interval | payload sizes |
| --- | --- | --- | --- |
| `player` | 63,340 | **1.000 s** | 7168 (61,661), 7169 (1,679) |
| `world` | 16,612 | **1.000 s** | 7168, 1007, 1008, 990 |

Both streams ran at **1.00 Hz**. `rep.py` defaults the player record to
`STATE_STREAM_PLAYER_PERIOD_S = 0.25` (4 Hz) so that the ALC cable stays clear;
the runs in this log used 1.0 Hz and the sessions still reached `InGame`. Whether
4 Hz is required for the cable is therefore **still open** and is a Tanda B
observation.

The player bundle is **7168 B** payload (exactly 7 KiB), against the 1.400
recorded 7,154 B for the ongoing player-state variant — a 14 B difference that is
unexplained and is listed for T5.

### L4 — T3 results (Tanda B): the live walk on 1.460

Client launched with `scripts/private-run.py --settle 45`, verdict **`InGame reached,
world streaming (26 slice lines), player possessed`**. Window focused and verified
(`focus-window.py "New World" --check` → `foreground=0x4A070E ok=True`) before every
key, per the computer-use skill's measured trap. Movement driven with
`hold-key.py` (real SendInput scan codes): W `0x11`, S `0x1F`, A `0x1E`, D `0x20`.

**Sample rate: 20.05 Hz**, measured as samples over wall-clock span (2,166 samples in
108 s). This is the client's own input cadence, and it confirms the 20 Hz figure.

**The four-way frame test — CONFIRMED on three directions; S was not measured.**

The test needs the camera yaw fixed across the keys, and it was: **−154.04°** in every
segment. Three separate runs contributed, and the strength of each differs, so they are
reported with their own evidence rather than as one tidy table.

| Key | scan | path | moving intervals | dominant offset | verdict |
| --- | --- | --- | --- | --- | --- |
| W (forward), run 1 | `0x11` | 15.77 u in-frame | 58 | **+90° on 53 (91.4%)**, +85° on 4 | **solid** |
| A (strafe left) | `0x1E` | 11.35 u | 37 | **180° on 17**, then 190° ×7, 210° ×4, 220° ×3 | **solid** |
| D (strafe right) | `0x20` | 12.56 u | 38 | **0° on 36**, 40° ×1, 80° ×1 | **solid** |
| W, run 2 | `0x11` | 1.75 u | **0** | — | **weak — excluded** |
| S (backward) | `0x1F` | 0.32 u | **0** | — | **noise — excluded** |

The in-frame decomposition over run 1's walk is the cleanest single number: **forward
+15.77 u, lateral −0.17 u, lateral share 1.1%**. A walk whose motion is 99% along the
forward axis under the assumed frame is the frame being right.

So three independent directions at 90° spacing — **W=90°, A=180°, D=0°** — verify

```
forward      = (−sin(yaw), cos(yaw))   -> heading = yaw + 90°
strafe left  =  yaw + 180°
strafe right =  yaw +   0°
backward     =  yaw + 270°   (PREDICTED, NOT MEASURED)
```

**What is not established, and must not be written down as if it were:** S=270°. The S hold
moved 0.32 u with zero intervals above the 0.15 u floor — the player did not walk, so the
offset is unrecoverable from that run. W's second run has the same problem (1.75 u, zero
intervals). Both are excluded rather than averaged in. `S = 270°` follows from the other
three being mutually 90° apart and from the algebra, and it is listed in the plan as
predicted; it is not evidence.

A one-key test could not have distinguished a 90° error from a sign error. Three mutually
perpendicular directions can, which is why the extra keys were worth sending — and why the
two that failed to move had to be reported as failures rather than folded into the pattern.

**A label correction for the record.** The 1.400 note lists the same offset set with rotated
labels ("+90° strafe left, +180° back, −90° strafe right, 0° forward"). The offsets are the
same four values; the assignment here is the measured one, and it agrees with the conclusion
already in `STATUS.md` ("forward is `(−sin, cos)`").

**Walk speed: 5.39 u/s, not 3.83 u/s.**

| Episode | pairs | path | duration at 20.05 Hz | speed |
| --- | --- | --- | --- | --- |
| W #1 | 10 | 2.69 u | 0.50 s | 5.39 u/s |
| W #2 | 21 | 5.86 u | 1.05 s | 5.59 u/s |
| W #3 | 19 | 5.25 u | 0.95 s | 5.54 u/s |
| W #4 | 6 | 1.61 u | 0.30 s | 5.39 u/s |
| A | 5 | 1.32 u | 0.25 s | 5.29 u/s |
| D #1 | 12 | 3.14 u | 0.60 s | 5.24 u/s |
| D #2 | 20 | 5.49 u | 1.00 s | 5.50 u/s |
| D #3 | 13 | 3.57 u | 0.65 s | 5.51 u/s |
| D #4 | 7 | 1.82 u | 0.35 s | 5.21 u/s |

Median **5.39 u/s**, range 5.21–5.59 across nine episodes and three directions, which is
tight enough to call it the walk speed. **This is 41% above the 3.83 u/s recorded on
1.400**, so the 1.400-derived validator window would be wrong on this build. Why the
two differ is not determined (build change, character attributes, or a different
measurement method on 1.400); the plan's Q9 (sprint/mount bounds) is still open.

Speed is computed as path length over `intervals / 20.05 Hz`, **not** over the log's
timestamps: those have one-second resolution, and dividing by them fabricated an
8.5 u/s figure in the first pass. That artifact is why `measure-episodes.py` exists.

**The five-position sliding buffer — CONFIRMED on 1.460.**

Counting every `(f32, f32)` pair in the body that falls in a plausible world range:

| payload | body | n | position pairs in body | body offsets |
| --- | --- | --- | --- | --- |
| 311 | 283 | 3,182 | **1** | 103 |
| 309 | 281 | 516 | **1** | 101 |
| 351 | 323 | 462 | **5** | 103, 155, 206, 257, 308 |
| 401 | 373 | 55 | **5** | — |
| 411 | 383 | 48 | **5** | 115, 179, 242, 305, 368 |
| 341 | 313 | 30 | 4 | — |
| 331 | 303 | 15 | 3 | — |

So the idle form carries **one** position and the moving form carries **five**, matching
the 1.400 measurement. Two things a port must not assume:

1. **The stride between buffered samples is not constant**: 51/52 bytes in the 351-payload
   form, 63/64 in the 411-payload form. The entries are variable-length, so a port cannot
   index them by a fixed stride.
2. **The slot order is not resolvable at walking speed.** Testing `pos[0](n+1)` against
   `pos[1](n)` gives 0.148 u mean distance versus 0.074 u against `pos[0](n)`, which is
   inconclusive because consecutive samples differ by only ~0.27 u. Resolving "newest
   first" needs a sprint or a teleport. It does not block the port: the server reads the
   **first** position at `marker + 12`, which is the value 1.400 validated against the
   client's own accessor within 0.5 u over 600/600 entries.

**State-stream cadence: 1.00 Hz for both kinds**, unchanged in this session.

| kind | events | median interval | p10 | p90 | payload sizes |
| --- | --- | --- | --- | --- | --- |
| `player` | 63,340 | **1.000 s** | 1.000 | 1.000 | 7168 (61,661), 7169 (1,679) |
| `world` | 16,612 | **1.000 s** | 1.000 | 1.000 | 7168, 1007, 1008, 990 |

`rep.py` defaults the player record to 4 Hz (`STATE_STREAM_PLAYER_PERIOD_S = 0.25`) so the
ALC cable stays clear; these runs used 1.0 Hz and still reached `InGame`. Whether 4 Hz is
*required* for the cable is still open and is not settled by this log.

**One artifact to keep out of the atlas.** The first pass, run over the whole log, found a
clean two-state "flip" 7.071 u apart repeating 16,430 times each way. It is **two clients
interleaved in one file** (`127.0.0.1:27000` and `:27001`). Per peer there is no flip: every
dominant transition is a self-transition. Any future log analysis must key on `peer`.

### L5 — T4 results (Tanda C): spawn offset, transform, inventory

**Client state at the start of T4:** the Tanda B client had died (`NewWorld.exe` absent,
22 `State(InGame) is timeout` lines in `Game.log`, the last at 20:57:16). Tanda C therefore
ran its own launch.

**1. The spawn-record position offset — VERIFIED, by effect.**

World restarted with `AZOTH_STATE_POSITION=9500.0,2800.0` (mode `fixed`, confirmed in the
`config` event: `"state_position": "9500.0,2800.0"`, `"state_position_captured":
"4611fe91452e2bb9"`). The capture's own position for that record is
`4611fe91 452e2bb9` = `(9343.72, 2786.17)`, so the override moved it by ~157 u.

The client's own channel-1 feed, after spawn:

```
samples: 1495
  x 9498.380..9498.588   y 2801.373..2801.759
  most common: (9498.38, 2801.373) x1474
  samples within 50 u of the requested (9500,2800): 1495 / 1495
```

So the client spawned at the position the server wrote, not at the capture's. This is the
strongest form of the measurement — the client **reports its own position back** through the
input stream, so no probe is needed. The residual (9498.4, 2801.4) versus (9500, 2800) is
the documented per-session reference-frame offset (`alc.py` warns it is 2–4 u and varies per
session), not an offset error.

The write itself is offset-free by construction: `apply_position_override` anchors on the
captured **value**, not on an offset. What this run proves is that the **anchor value is
still present in the 1.460 spawn record and still feeds the client's position** — i.e. the
spawn path is intact on this build, and a Rust port that composes the spawn record from
persisted state must write the same pair.

Side effect, and it is a useful one: because the server held a position the client did not
agree with, the correction ladder ran for real. `movement-ready` 1, `movement-desync` 1,
`movement-simulation-held` 1, `movement-correction-decision` 3, then
**`movement-correction-disconnect` 1478**. The documented escalation
(ACCEPT → HOLD → FREEZE → DISCONNECT) is therefore confirmed on 1.460, and it is what ended
the session.

**2. The entity transform — NOT MEASURED. The probe is unavailable, not negative.**

`python az.py probe frida-actor-transform` was run twice against the live client:

| attempt | timeout | outcome |
| --- | --- | --- |
| 1 | 240 s | `[census] scanning 1055 ranges, 3000 MB` → `TIMED OUT - no summary` |
| 2 | 900 s | `[census] scanning 1059 ranges, 3000 MB` → `TIMED OUT - no summary` after 15 min |

The probe's own text is explicit that this must be read as *no result, not as a negative*.
A whole-memory scan of 3 GB does not finish in 15 minutes on this machine, so
`frida-actor-transform` cannot produce the `+0x14c/+0x15c/+0x16c` reading here without
either a narrower range or the entity anchor (`FUN_1413fb700`) that `STATUS.md` records as
the working one. **Recorded as unavailable and left for a follow-up that changes the probe,
not as refuted.** This does not block the port: the transform offset is only needed to
*verify* that a replicated actor landed at the server's position, and that verification is
Phase 4's business.

**3. The inventory grammar — MY EARLIER "REFUTATION" WAS MY OWN BUG. The documentation
was right.**

This is the most important correction in this document, so it is stated plainly: an earlier
draft of this section claimed `inventory.py`'s entry description was wrong (427 entries
"not supported", `marker − 68` "does not land on a field boundary"). **Both claims were
false, and they were false because the hexdump reader in
`scripts/measure-inventory-grammar.py` was broken.**

The bug: a classic hexdump puts an **extra space between the eighth and ninth byte groups**.
The reader's regex allowed only single spaces between byte pairs, so it captured **half of
every line** and zero-padded the rest. Every byte offset after the first eight per line was
wrong, which silently corrupted the blocks and produced a plausible-looking but false
measurement. The same bug corrupted the `0x73_T0x8_R` state bundle, which then "refuted" the
bundle prologue — and the Rust parity test caught that one first, which is how the reader bug
was found at all.

After fixing the reader (`^([0-9a-f]{8})  (.+?)\s*\|`, then strip all whitespace), the
measurements are:

| Claim in `inventory.py` | Measured on the corpus | Verdict |
| --- | --- | --- |
| the empty form is **153 B** | **153 B** | **confirmed** |
| the populated form is **99,819 B** | **99,819 B** | **confirmed** |
| the populated body has **427 entries** | **428** marker occurrences, **427** marker-to-marker gaps | **confirmed** (427 entries) |
| "the entry starts **68 bytes before** the marker" | `marker − 68` lands exactly on `w-world\|`, a NUL-padded container name | **confirmed** |
| entries are not fixed-stride | gaps span **231…233 B** (427 distinct gaps: 233×338, 232×79, 231×10) | **confirmed** |
| the entry carries `isCollected` | the populated block has no redaction in that region | **confirmed** |
| "u32 BE length of the type name" after the marker | the length is a **single byte** at `marker + 8` (`0x0e` = 14, then `SkinCollection`); `marker + 4` is a zero u32 | **one field-width detail is off**, the substance (a length-prefixed type name) is right |

So the entry codec is **decoded as far as the container is concerned**: 68-byte NUL-padded
container name, `00 01 82 5a` marker, a zero u32, a `u8` type-name length, the name, then the
item fields. The only correction to `inventory.py` is the field width at `marker + 4`, and it
should be fixed there rather than re-derived.

**The lesson is worth more than the measurement.** A hexdump parser is a measurement
instrument, and a broken instrument does not produce a "negative result" — it produces a
confident wrong one. The repository already says decompiler output is not verified source; the
same caution applies to *our own* capture readers. Two things now guard against a repeat:
`scripts/export-wire-fixtures.py` and the Rust parity test both read the same blocks and would
fail on a corrupted read, and the reader itself documents the trap in a comment.

**Consequence for the plan:** the inventory entry codec is **not** the "known" item §5.3 of
the plan treats it as, and the corpus copy is not a usable reference body. Originating an
inventory therefore requires decoding the entry from the client's own reader — the same
live-instrumentation method as the presence codecs (§8.6). §5.3 and §15 Phase 6 are
corrected accordingly.

### L6 — Phase 0 exit status

| Plan §0.2 row | Status |
| --- | --- |
| channel-1 container format | **verified** (229,304/229,304 pass len+crc) |
| channel-1 position locator (`marker+12`) | **verified** (222,389 records, 1 marker each, lands on the pair) |
| channel-1 field layout `(yaw,pitch,x,y)` | **verified** |
| yaw frame `forward = (−sin, cos)` | **verified** on W/A/D (90/180/0 at fixed camera yaw); S is predicted, not measured |
| walk speed | **verified** at 5.39 u/s, and the 1.400 value of 3.83 u/s is **superseded** |
| five-position buffer | **verified present**; slot order still open (needs a sprint) |
| state-stream cadence | **verified** 1.00 Hz both kinds |
| spawn-record position | **verified by effect** (client spawned at the server's value) |
| entity transform `+0x14c/+0x15c/+0x16c` | **not measured** — probe unavailable (two timeouts) |
| inventory entry grammar | **verified** — 427 entries, `marker − 68` is the container name, 231–233 B stride; only the `u32`-vs-`u8` field width at `marker + 4` needed correcting (L5 §3) |
| entity template record 70 | not re-measured (not needed until Phase 4) |
| `MEASURED_USED_SLOTS` | not re-measured (slot 95 confirmed NULL in the 1.460 lever run per `STATUS.md`) |
| reference-frame offset | **not a dependency** (per-session, calibrated at runtime) |

Phase 0 is **not** fully closed: three rows remain, two of which need a different probe or a
decode rather than a re-run. That is reported rather than claimed.

### L7 — Disk hygiene for this campaign

The raw evidence for Tanda B is **409 MB** of `world.log` JSON. It is kept, compressed, not
deleted:

```text
.azoth/logs/world-before-tanda-c.log.gz     23 MB  (was 409 MB, 94% smaller)
```

To re-run any measurement script against it:

```bash
gunzip -k .azoth/logs/world-before-tanda-c.log.gz   # -> the .log beside it
python scripts/measure-episodes.py .azoth/logs/world-before-tanda-c.log --from-line 1200127
```

**Why the log is that large, and the guard for next time.** The world server logs every
inbound datagram's hex when payload logging is on, and a live session produces roughly
1 MB/s. One afternoon of experiments on 2026-10-19 reached **7.3 GB** on a disk at 78%
(`rep.py`, `OUTBOUND_PAYLOAD_LOG` comment). This campaign produced 409 MB in about an hour.

Rules that follow, and that the Rust design already encodes:

* Rotate `world.log` **only while the world is stopped** — it is append-only while running
  (`AGENTS.md`). Done that way here.
* Compress rather than delete: a measurement without its raw source cannot be re-checked,
  and re-running costs a client launch.
* The Rust world must not have a hex-payload mode that can be enabled in a normal run:
  §12.1's three-way split (metric / log / audit) and the bounded, non-sampled-by-default
  payload logging in `azoth-observe` exist so that "turn on debugging" cannot fill a disk.

Frida's own footprint: each probe run leaves ~44 MB of extracted agent DLLs under
`.azoth/tmp/frida-*`. The two created by this campaign were removed; the four from earlier
sessions were left alone because they are not this feature's artifacts.

**Disk after cleanup: 87.4 GB free of 222 GB.**
