# 2026-10-16 — the server reads the client's own position (and the 94-minute step)

Two results: a new server capability that unblocks authoritative movement validation, and a precise
diagnosis of the remaining 2-hour gate.

## 1. The server can READ the player's position

The client streams its own world position ~20 times a second on channel 1 (wire type `0x635`,
`ActionListComponentServerFacet_ReceiveInputFromClient`), and until now the server stored that body
only for an echo experiment. It now parses it.

**How the layout was found.** The container is the standard typed record
`[u32 BE crc32][u32 BE len][16-byte actor target][00 01][prefix-varint type]`, so the body begins at
offset **28** — not 18, which is where an existing tool (`scripts/decode-ch1-635.py`) looked and why
it reported "no channel-1 records" on a log that was full of them. (Fixed.) The body then begins with
another 16-byte local id, the server facet the client is calling
(`fbde4b9a600d428fbf85314bbc4a951a` in the sessions measured — the same value family the capture's
input-response target uses), followed by a header and a variable number of buffered input entries.
**The entry grammar is not decoded, and the module says so.**

**The anchor, and why it is safe.** Every body that carries a position contains the 4-byte constant
`3d 4c cc cd` — a float32 **0.05**, which matches the client's own
`javelin.alc-interpolation.normal-movement-quantization` — and the position pair is **always 12 bytes
after it**, as big-endian float32. Measured over 6 000 live bodies: the anchor count is **1..1** in
every length that has one, and **0** in the short forms (65–126 B in one session, 39–100 B in
another), which carry no position at all. The extractor anchors on that constant and then
**range-checks** the pair, failing closed (returns nothing) rather than handing a caller a
plausible-looking lie.

**Accuracy, against the client's OWN instrument** (`frida-player-position` calls `FUN_140fddfa0`, the
accessor behind the client's `nw_getPlayerPosition` command):

| measurement | value |
| --- | --- |
| offline, 6 559 paired samples | median **0.54 u** standing, **0.81 u** walking (offset removed) |
| live, server logging + probe attached | 4.03 u raw → **0.73 u** after removing the median offset |
| direction of movement | matches to **0.3°** (W −67.2° vs −67.5°; S 113.0° vs 113.0°) |

**The offset is geometric, not a lag.** A lag sweep over −0.3 … +2.0 s left the median **flat**, so
no time shift explains it: the two values are the same motion sampled at **different reference points
on the character**, ~2–3.7 u apart, and the constant differs between sessions. That is the one thing
that must be calibrated before a validation check can use the value.

**Implementation and tests.**

| item | where |
| --- | --- |
| parser | `services/world/src/azoth_world/javelin/alc.py` |
| wiring | `rep.py`: `ALC_POSITION_ENABLED`, `ALC_POSITION_LOG_S`, `PeerSession._note_alc_input` |
| log line | `{"event": "alc-position", "x": …, "y": …, "body_len": …, "anchor_offset": …, "n": …}` at 1/s |
| kept value | `session.alc_position` (updated on every record, so a check can use the newest sample) |
| tests | `services/world/tests/test_alc.py`, 8 tests over **real captured vectors** |

**What this unblocks:** roadmap item B5, server-side movement validation (anti-teleport, speed clamp).
The server can now compare the position the client claims against its own model. Still needed:
calibrate the reference offset, and pick a speed bound from measurement rather than convention.

## 2. The 2-hour soak's remaining gate, located to the second

The soak itself passed (124+ minutes; a later run reached 135 min of logging) — what fails is the
client's own connection state, starting at a single discrete event.

| time | event |
| --- | --- |
| `02:36:56` | the client's channel-1 record changes shape **once**: 257–259 B → **68 B** |
| `02:37:25` | first `[GameConnection] State(InGame) is timeout : frames 10, currentTimeoutIntervalCount 1` — **29 s after the step**, exactly the watchdog's 30 s budget |
| `02:37:25` onward | that line repeats **every 30 s** (83 occurrences) |
| `~03:07` | `scripts/watch-indicator.py` reports the HUD cable **RED**; world still rendered, player still possessed |
| `03:18:34` | the last `Game.log` line; the client stops responding (the process still existed, so this is a hang, not an exit) |

**Nothing on the server changes across the onset.** Per-minute world-log counts for `02:50`–`03:18`:
`app-data` 1200/min, `state-stream` 282–285/min, `heartbeat` 59, `keepalive` 59, `input-response` 59,
`replay` ~401, `outbound-app-data` ~2700 — all constant — and `scripts/ack-audit.py` reports the ACK
stream **healthy** (widest CT_ACKS range 16383, 0 at/over the limit, no retransmit storm). The
client's PID never changed (`6888` from `01:02` to the end), so this is one process degrading.

**What the step is, in the decoded terms above.** The body carries the position plus a variable
number of buffered input entries — 257–259 B with four of them, 68 B with one — so the step is the
client's **input batching changing from four entries to one**. That is consistent with
`javelin-server.ALC-max-input-to-combine` no longer being honoured, or with an accumulator resetting.
**That reading is an inference**: the entry grammar is not decoded.

**Next.** Decode the entry grammar, or find which `javelin.alc-*` cvar governs the batch size, and
test whether answering the client's channel-1 stream (an actual ALC response) keeps the larger form.
The candidate cvars are already enumerated in the binary: `javelin-server.ALC-max-input-to-combine`,
`alc-movement-reporting-period-seconds`, `alc-speed-hack-fix-v2-max-buffered-inputs`,
`enable-alc-movement-reporting`, `alc-request-input-throttle-server-override-delay-ms`.

## Validation

196 world tests OK (8 new), 24 gateway OK, 12 Rust OK, `gen-protocol-fixture.py --check` OK.

## Files

- `services/world/src/azoth_world/javelin/alc.py` (new), `javelin/__init__.py`, `rep.py`
- `services/world/tests/test_alc.py` (new)
- `scripts/decode-ch1-635.py` — container offset corrected (16 → 24/26), which is why it found nothing
- `.azoth/night/ch1-window-diff.py`, `ch1-timeline.py`, `ch1-counter.py`, `ch1-vs-accessor.py`
  (analysis tools, ignored)
- `.azoth/night/runs/alcpos-165235`, `.azoth/night/runs/ch1pos-162154` (run records, ignored)
