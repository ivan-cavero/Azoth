# corpus-naming — from 423k `FUN_<va>` to named code (layer 3 groundwork)

Owner feature doc for the naming workstream: DECOMP-BACKLOG §1.2 ("the corpus
has no names, types or strings") and §3 (named loaders). Tool procedure in
[DECOMPILATION.md](../../research/docs/DECOMPILATION.md).

## Why this feature exists

The layer-1 corpus is a search index, not readable source: every function is
`FUN_<va>`. There is no PDB (DECOMP-BACKLOG §1.3), so names come from three
sources only: the AZ reflection registry, distinctive strings referenced by a
function, and MSVC RTTI metadata embedded in the exe. This feature builds the
offline tools that turn those sources into candidate names, confirmed into
`research/derived/symbols.json` one system at a time.

## Tasks

- [x] T1 — **`rtti.py`**: static MSVC RTTI scan of the exe (stdlib only). Walk
      TypeDescriptors (`.?AV…` name strings) → CompleteObjectLocators →
      vftables → first-N virtual functions. Output: a candidate pool of
      class names with vftable VAs (`research/derived/rtti-classes.json`,
      tracked, regenerable). No Ghidra run, no process access.
      **Result 2026-10-05: the vftable half is a measured negative** — the
      game code is compiled `/GR-`; only imported-CRT classes carry COLs.
      The tool still delivers the 4,820-name TypeDescriptor pool (T2 fuel).
- [ ] T2 — **Confirm the first system from the name pool** into
      `symbols.json` by hand (one key per entry, `found_by` cites the tool
      and the evidence chain). The RTTI vftable route is closed (`/GR-`);
      confirmation now flows from the TD-name pool + AZ reflection +
      string xrefs, never RTTI metadata alone.
- [ ] T3 — **`namer.py` v2 (strings)**: for each distinctive string VA from
      `peutil.py str`, find corpus functions referencing `&UNK_<va>` and
      propose `<concept>_user` candidates. Runs offline over the shard
      `.idx` + shard text.
- [ ] T4 — Type injection into `decomp.py`'s Ghidra helper (MSVC
      `std::string` 32-byte SSO layout, `AZStd::string`) so pseudocode stops
      rendering strings as raw bytes. Incremental Java change; only after
      T1–T3 prove the pipeline.

## Constraints

- Offline only: corpus files and the exe on disk. Nothing touches a live
  process; EAC rules in EAC.md are unchanged for the official client.
- `symbols.json` keys are inserted by hand (edit tool), never rewritten by a
  script. The RTTI pool is a candidate source, not authority — a name is
  "confirmed" when a second signal (reflection registry, string xref, live
  trace) agrees with the RTTI metadata.

## Evidence log

| When | What |
| --- | --- |
| 2026-10-05 | Feature opened. Prior art consulted (DECOMP-BACKLOG §11): Ghidra's RTTI class recovery works PDB-less; this feature reproduces the first half (name → vftable chain) in stdlib Python so it needs no Ghidra analysis run. |
| 2026-10-05 | **T1 built and selftest OK. Measured negative: the game code has NO vftable RTTI (`/GR-`).** 4,820 TypeDescriptors (`.data`, vfptr → CRT type_info) but only 1,959 COLs — enumerated two independent ways (TD u32-RVA refs at COL+12, and the self-referential `pSelf` field; both agree exactly) — and every COL vftable has 0 slots inside `.text` (imported msvcp140/vcruntime classes; exceptions/STL only). x64 COL layout correction found on the way: `pTypeDescriptor` is a DWORD RVA at COL+12, not a qword at +0x18. Ghidra's RTTI recovery can therefore never name game classes on this build; DECOMP-BACKLOG §7's RTTI payoff note is retracted for game classes. Naming path: AZ reflection registry + string xrefs (T3) — which is exactly what `component_names_resolved` already used. |
