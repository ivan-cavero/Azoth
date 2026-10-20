# 2026-10-18T15:35Z — the vtable at runtime: the answer, and it refutes my own static reading

One probe, one question: **which vtable does the dispatcher actually call per fragment, and what
does the `+0x60` slot do?**

The static session before this had concluded there was a "per-fragment predicate the server does not
control". That conclusion was **wrong**, and this run is what showed it.

## Method

New read-only probe `reverse/probes/client/frida-fragment-vtable.py`: hooks `FUN_141717fc0` on
enter, walks the fragment vector it receives (`begin` at `+0`, end at `+8`, element stride `0x18`,
object at element `+8`), and reports each fragment's key, object pointer and vtable plus the `+0x60`
and `+0x90` slots. It calls no client function and writes no client memory; it ends through
`safe_shutdown`.

Capture: **400 records**, including **25 spawn records (48 fragments)** and **63 local-player
records (9 fragments)** — both `record_id 1`, separated only by count, which is why the count filter
matters.

## Finding 1 — there is no per-fragment filter

`slot +0x60` is **identical for every fragment of every record**: `0x7ff602ad4910`, with module base
`0x7ff602840000` → **RVA `0x294910`**. Disassembled:

```asm
0x140294910:  xor  al, al
0x140294912:  ret
```

It returns **0 unconditionally**. So `if (cVar5 == '\0')` in the dispatcher is **always taken** and
every fragment is processed. My earlier "the gate is per-fragment and the server does not control
it" was a misreading of a call whose result I had not resolved.

## Finding 2 — the component maps are first-write-wins

Both maps have the same shape. `FUN_1415e5140` is the one called per fragment, keyed on the fragment
key:

```c
do {
  if (*param_3 == (int)puVar9[2]) {
    *(undefined1 *)(param_2 + 1) = 0;   /* NOT inserted */
    goto LAB_1415e52d3;                 /* returns the EXISTING entry */
  }
  ...
} while (uVar7 < uVar6);
```

An **already-present key is not replaced**, and the caller receives the existing entry. The new
fragment is discarded. `FUN_1415e68b0` behaves the same way.

## Finding 3 — key 16 is a distinct component type

The position fragment (key 16) has the **same vtable** in both records (`0x7ff60a93f900`), but a
**different `+0x90` reader** than every other fragment — `0x142a436b0` vs `0x1417b4110`. So it is a
genuinely different component, not an alias.

## Why this explains every measurement in this project

| observation | explanation |
| --- | --- |
| the spawn-position override worked, 0.0000 u (2026-10-14) | sent **at spawn**, when the keys were **absent** → every fragment inserted |
| four correction shapes accepted with 0 errors and no effect | each re-sends **key 16**, which is **already present** → discarded |
| the character stayed visible with the hybrid | the record is parsed and applied normally; only the key insert is refused |
| the full spawn record looped made the character invisible | a different failure: re-sending all 48 keys at 1 Hz is not the same as one refused insert |

**Re-sending a key cannot work by construction.** That closes the payload-shape line for good, and
it is a much better explanation than the filter I had invented.

## What the next experiment must be

Not another payload shape. Either:

* **remove, then insert** — the AOI trait registry already contains `replica_portrayal_remove`, so
  the client has a path that clears a component and would let a subsequent insert land; or
* a **delta/update message** for the position component, if one exists in the wire registry.

## Files

* `fragment-vtable.jsonl` — 400 records with per-fragment key, object, vtable and the two slots.
* `runner.log`, `Game.log` — the run reached the world (26 slice lines) and stayed healthy.
