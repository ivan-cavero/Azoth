# Javelin inbound dispatch — static map (build 1.400)

> Static RE, 2026-09-27. Every VA is in `research/atlas/client-functions.json` with `found_by`.
> No runtime access; nothing carried over from the 1.365 replay.

## Two rings, do not confuse them

The stream processor (`0x770` bytes, ctor `0x146b69ad0`, vtable `0x148590ab8`) owns two
different queues:

| ring | producer | popper |
| --- | --- | --- |
| `proc+0x120` | `FUN_146b6f190` fallback @ `0x146b6fde3` (types 8A40, 972, …) | **not found** |
| `proc+0x50` | (ctor arg / transport) | `FUN_146b6d180` ← the real dispatch |

`FUN_146b6d600` installs a fresh refcounted ring owner at `+0x120/+0x128` and never touches
`+0x50`, which comes from the ctor argument (`FUN_14615e0c0()`). A popper for `+0x120` was not
proven; do not assume `FUN_146b6d090` (vtable slot `+0x40`) drains it — it is only the getter.

## Proven pipeline

```text
transport
  → iface 0x1485915B8 slot +0x10  (thunk 0x146b71594: jmp 0x146b6eb70)
  → FUN_146b6eb70                 inbound decode entry
        byte count → proc+0x710
        FUN_146154030             decode context
        FUN_1461ac8d0             typed-envelope unmarshal
  → FUN_146b6f190 @ 0x146b6ed39  10-GUID compare
        hit  → inline handler
        miss → FUN_146b6bf50 push {object, owner} → proc+0x120

FUN_145aa23f0                     per-frame tick (processor at wrapper+0xb0)
  → FUN_146b6d180(proc, tick_arg, 0)     sole caller
        pop {object, owner} LIFO from proc+0x50
        object->vtable[+0x30]     → type GUID
        FUN_140a174c0             → 16-byte key; hash = key.lo ^ key.hi
        bucket = proc+0x20[hash & proc+0x38], 0x20-byte nodes, key at +0x10/+0x18
        hit  → ((*(void**)node+0x20))[+0x08](node+0x28)
        miss → proc->vtable[+0x08]
        then proc->vtable[+0x10] once per drain
```

`object->vtable[+0x30]` is the authoritative type→handler binding point. It is the same GUID
getter already proven for:

- `8A40AEC2-AE07-4F92-9BF3-78FC0CC94FDF` (type `0x08`): `0x14643a240` → `FUN_146437070`
- `DE1A18A9-CE9E-4336-8DF8-698A73C579D4` (index 972): `0x14154a900` → `FUN_1416fcb20`

## Interface handles

`0x148591498` = 42 slots = 12 own + 5 embedded 6-slot interface sub-vftables
(`0x1485914f8 / …528 / …558 / …588 / …5b8`). A handle is a 16-byte `{sub_vtable, impl}` pair;
slot `+0x10` forwards to the impl. The inbound interface is **V6** (`0x1485915b8`).

`FUN_146425cb0` creates the processor and stores it at `connection+0x1000`; `FUN_146b70af0`
installs the connection's three listener cells at `proc+0x58/+0x98/+0xd8`. The three connection
interfaces are `0x148502988/…9b8/…9e8` → `FUN_146474e80 / FUN_146475490 / FUN_1464755e0`
(socket-connected / disconnected / registration-received).

## Open items

1. **Writer of the `proc+0x20` GUID→handler map** — this is what binds 8A40/972 to actor/replica
   handling. `FUN_146b70af0` is *not* that writer.
2. **Popper of `proc+0x120`** — needs a type-based filter on the callee vtable; a `+0x40`
   dispatch scan alone is 1000+ candidates.
3. Local-player actor prototype: factory `FUN_141563e20` (sole caller `FUN_1416957c0`), copy-ctor
   `FUN_14161b570` (vtable `0x148033f90` = `nw+8033f90`, the valid actor vtable). The default
   prototype comes from `FUN_14161b9b0`; the remaining hole is who supplies the live prototype.
