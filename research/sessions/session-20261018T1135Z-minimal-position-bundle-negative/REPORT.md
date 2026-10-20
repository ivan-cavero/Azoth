# 2026-10-18T11:35Z — the position fragment is located, and sending it alone does not move the player

Two results. The first is durable and useful. The second is a clean negative and it closes a
line of work.

## The position fragment is now LOCATED from the client

The 46393-byte spawn payload is 48 fragments, and their boundaries were not derivable from the
bytes: a fragment carries no length field, its payload length is implied by its type, and the
first fragment of the spawn record is type 4878 — outside the nine types the 7154-byte record
had already given us.

So they were read from the client. `python az.py probe frida-fragment-grammar --min-fragments 20`
produced **25 captures of the same 48 offsets, byte-identical**:

```
2, 25, 171, 280, 320, 6233, 6247, 6275, 6285, 11039, ... 46286, 46304
```

**The position is in fragment #35**, payload offset `38310..38397`, header `10 0b`
(**key=16, type=11**) — the same key/type pair as fragment #6 of the 7154-byte player record,
which is a strong hint that this component is replicated in both records. The replay store's
**24 captured copies** of the spawn record carry a byte-identical fragment #35; only the value
inside it differs.

That yields a **101-byte** record-1 bundle carrying only the position (103 with the rewritten
replication counter), i.e. **451x smaller** than the 46407-byte spawn record, and it round-trips
through the verified parser with `record_id=1, fragment_count=1`.

**A probe defect was found and fixed on the way.** `frida-fragment-grammar` read the record's
`out_u16` in the record reader's `onLeave` and attached it to each fragment event — but fragments
are emitted in the fragment reader's `onLeave`, which runs *before* the record's. Every one of the
300 previously captured fragment events carried `recordId: null`, so the docstring's promise that
"every fragment event carries the record id" was false and nobody had noticed. The probe now
buffers fragments and emits them at record leave, and filters by fragment count — necessary
anyway, because **the spawn record and the player metadata record are both `record_id 1`** and
only their fragment count (48 vs 9) tells them apart.

## The negative: sending the fragment alone does not reposition the player

With the minimal bundle wired to the correction path, the sequence was:

| step | measurement |
| --- | --- |
| calibration | offset `(-2.2002, +3.3777)`, residual 0.0000 |
| walk 3 s | claim moved, error grew to **3.186 u** |
| detection | `movement-desync` 3.186 u, streak 5 |
| correction sent | **102 bytes**, one `state-stream kind=position` |
| client errors | `Failed to unmarshal` **0**, `ValidationError` **0**, `transportError` **0** |
| character | **visible** (the previous attempt made it invisible) |
| error afterwards | **grew to 16.5 u and stayed there** |

The bundle is valid, the session is healthy, the character renders — and **the position is not
applied**. A record-1 bundle with a single fragment is not a repositioning message. The client
appears to need the record's full fragment set to act on it, which is consistent with the
earlier measurement that the *full* spawn record did move the player at spawn (0.0000 u error,
2026-10-14): the difference is the record's completeness, not the presence of the pair.

So the position is **locatable** but not **addressable** as a standalone message with the
knowledge available today. Closing this line requires knowing what the client does with the
other 47 fragments — whether it treats the record as an atomic unit — which is a decompilation
question, not a protocol-shape question.

## Two defects of mine, both caught by measurement

1. **A non-dataclass correction body.** The correction was queued as a `SimpleNamespace`, and
   `_send_state_bundle` calls `dataclasses.replace(msg, body=...)`. That raised
   `TypeError: replace() should be called on dataclass instances`, the UDP loop swallowed it, and
   the session died with a client `transportError 4`. Fixed by using `ReplayMessage`; a test now
   asserts `dataclasses.is_dataclass()` on the queued correction.
2. **Unbounded cap logging.** The cap check logged on every sample while the divergence persisted
   — hundreds of lines a second, burying the session log. Now logged once per session.

Both were invisible in the client log, which is why they took a live run each to find.

## What is established

* The 48 fragment boundaries of the spawn record, from the client, deterministic across 25
  captures and byte-identical across the replay store's 24 copies.
* The position lives in fragment #35 (`key=16, type=11`).
* A 101-byte bundle can carry it, and the client accepts it without error.
* **It does not move the player.**

## What is not

Correction of a mid-session desync. Detection works (`movement-desync`, verified), the offset is
calibrated correctly (residual 0.0000), and correction does not. `AZOTH_MOVEMENT_CORRECT`
defaults to `0`.

## Files

* `fragment-grammar.jsonl` — the probe capture: 39 records, 25 of them the 48-fragment spawn.
* `movement-events.jsonl`, `position-sends.jsonl` — the correction and its single send.
* `Game.log` — the client log, 0 errors of any kind.
