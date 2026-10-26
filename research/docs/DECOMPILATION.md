# Decompilation workflow

This is the procedure for answering a concrete client-code question. The
[program and remaining work](DECOMP-PLAN.md) describe coverage and priorities;
the [backlog](DECOMP-BACKLOG.md) holds measured data-format work. Azoth-specific
evidence rules are in [the RE skill](../../.agents/skills/azoth-re/SKILL.md).

## What is already available

- `reverse/tools/decomp.py` resolves the local Ghidra/JDK install,
  decompiles requested function ranges, and reuses a project under the full
  executable SHA-256 workspace.
- The local corpus is indexed against 423,579 `.pdata` functions for client
  build `1.400.6031.6004151` (sha256 `8654f01d…c8e`), rebuilt fresh on
  2026-10-06 under `reverse/builds/8654f01d…c8e/corpus/`: **423,579 `ok`, 0
  `fail`** (full coverage after retry passes; see DECOMP-BACKLOG §0/§1.1 and
  §9 for the payload-ladder and fragment-parent techniques). Do not
  resume the old per-user workspace under ignored
  `.azoth/archive/legacy-appdata/decomp/`; it is historical evidence only.
- `xrefmap.py` builds the expensive xref map once and stores it in the local
  work directory. `namer.py` turns string references into review candidates.
- Confirmed function names and their evidence are tracked in
  `research/atlas/client-functions.json`. Candidate lists and pseudocode are
  generated artifacts, not source of truth.

## Find and read a function

Start with a distinctive string, reflection property, caller, or known address.
Use the xref map and string tools before scanning the executable again. A
string with no direct code xref may still be used through a pointer table, so
check that route before closing the lead.

```powershell
python ef.py re pe info
python ef.py re pe str <distinctive-text>
python ef.py re pe callers <va>
python ef.py re decompile --symbol <confirmed-name>
python ef.py re decompile --target <va>
python ef.py re decompile --callers-of <va>
python ef.py re decompile --range <start>-<end>
```

## The other direction: what the client sends, and what it expects back

A layout cannot be confirmed from pseudocode alone, so the byte side needs its own tools.
These answer "which message does this surface send" and "what shape is it on the wire":

```powershell
python ef.py re input-contract --surfaces        # surface -> keys -> message families
python ef.py re input-contract --check           # measured bindings, as a regression test
python ef.py re segment-types --corpus <log> --segments <plan.json> --offset <N>
python ef.py run capture-segments --plan panels   # drive the panels, label the windows
python ef.py re field-differential --type 0x5de --corpus <log> --segments <plan.json>
```

`input-contract` derives its inventory from the shipped PAK profiles and joins it to
`research/derived/wire-type-names.json`; it does not carry a hand-written list, because a
hand-written list misses surfaces. `segment-types` counts wire types per labelled window and
resolves each to its name. `field-differential --segments` compares bodies **within one
body width only**: a variable-length type shifts every offset after its insertion point, so a
cross-width diff reports one shifted region as dozens of fields.

The systems, their entry-point wire types and how to provoke each one are in
[INTERACTION-DECOMP-PLAN.md](INTERACTION-DECOMP-PLAN.md).

For a long investigation, `python ef.py re decompile --serve` keeps the
current Ghidra project open; send work with normal `python ef.py re decompile`
requests and stop it with `--stop`.
The first import is the expensive operation. Do not repeatedly create or
re-import the project for individual functions.

## Run the phase campaign

The [campaign manifest](../atlas/decomp-campaign.json) organizes understanding
by the player-visible phases in [DECOMP-PLAN.md](DECOMP-PLAN.md). The runner
keeps per-build pending/done state under the ignored build workspace and
reuses the long-lived decomp server, so after the first import a batch of ten
functions costs seconds.

```powershell
python ef.py re campaign init        # sync manifest -> per-build state
python ef.py re campaign status      # per-phase coverage
python ef.py re campaign add world-entry --target 0x146b6eb70 --note "inbound decode"
python ef.py re campaign expand world-entry 0x146b6eb70   # + callers of that VA
python ef.py re campaign run --phase login --batch 10
```

Work loop: pick a phase, run a batch, read the emitted `.c` files under
`reverse/builds/<sha256>/campaign/<phase>/`, resolve anchors (`re pe str`,
`re xref`, `re naming`) to choose the next targets, and grow the phase with
`add` / `expand`. Decompile-and-file is not understanding: a phase is done
when its message contract and state transitions are recorded in `research/atlas/`
with evidence labels. Confirmed facts go to
[`../atlas/client-functions.json`](../atlas/client-functions.json); failed or
skipped ranges stay visible in `campaign status` for retry.

## When the pseudocode does not answer the question

Ghidra output for this build has no game RTTI (`/GR-`, measured — see
`reverse/tools/rtti.py`), so unknown structs appear as `undefined4` fields and
Ghidra will never recover them. That is expected, not a dead end. When a
decompiled field or offset is the open question:

1. Re-read the callers, string references, and AZ reflection metadata first
   (`python ef.py re xref`, `re strings`, `re naming`) — cheap static signals.
2. If static signals cannot settle it, escalate to the dynamic workflow in
   `.agents/prompts/live-analysis.md`: verify the EAC gate, then reuse or
   adapt an existing probe from `reverse/probes/client/`. Proven patterns:
   hook the identified function to capture the object instance, then
   `MemoryAccessMonitor` the field range to find the writer
   (`frida-activity-timer.py` did exactly this for `+0xAA8`), or a hardware
   watchpoint on a pointer slot (`frida-mgr-watch.py`). List probes with
   `python ef.py probe list`.
3. Record the confirmed type and writer back into
   `research/atlas/client-functions.json` with the probe and run as evidence.
   Never paste the runtime finding back into pseudocode as if it were source.

## Record only what is supported

- Confirmed behavior: add a concise entry to
  `research/atlas/client-functions.json` with the VA and `found_by` evidence.
- Candidate names: keep them in generated candidate output until the function
  body or an independent signal confirms them.
- Wire properties: add exact key, type, requiredness, and evidence to the
  relevant atlas model. Mark guesses as `"evidence": "guessed"`.
- Build changes: fingerprint the new executable and revalidate addresses before
  carrying findings forward.

## Limits and tool traps

- A Ghidra result is pseudocode, not recovered original source. Its formatting,
  types, and names may be wrong even when the control flow is useful.
- Use exact `.pdata` function bounds. `decomp.py` snaps requested windows to
  real functions to avoid mid-instruction decompilation.
- **`.pdata` is not the whole `.text` (measured 2026-10-09).** The corpus is
  `.pdata`-driven, so leaf functions with no unwind info are absent from it. A
  scan of `.text` for the accessor shape `48 8D 05 rel32 C3` (`lea rax,[rip+X];
  ret`) followed by `CC CC` padding finds **13,943 standalone leaf functions and
  0 of them are in `corpus/ranges.txt`**. The typed dispatcher's type accessors
  are exactly this shape, which is why the movement type path never showed up in
  the corpus. Reach such a function with `decomp.py --range` (it bypasses the
  `.pdata` lookup); `--target` refuses with "not inside any .pdata function".
  Coverage numbers in this repo count `.pdata` ranges only.
- For this build's raw file arithmetic, `.rdata` VAs use `fileoff + 0x1800`
  and `.text` VAs use `fileoff + 0xA00`. Re-derive these after a client update;
  prefer `peutil.py` when it can resolve the address directly.
- Ghidra 12 loads the Java helper as a compiled script bundle; `decomp.py`
  handles compilation. The tool also handles Windows paths with parentheses.
- Do not pipe a Ghidra import through a command that closes its output early;
  it can leave a partial project.
- Run `python ef.py setup` to install Ghidra and its JDK under ignored
  `.azoth/tools/`. All generated projects, pseudocode, indexes, and caches live
  under `reverse/builds/<full-executable-sha256>/` by default. Git ignores this
  directory, so each exact client build has a separate project and corpus.
- New analysis uses that project-local workspace. The old per-user corpus is
  preserved for reference but is not an input to new analysis.

This workflow can provide complete range coverage and explicit failure
reporting. It cannot prove every decompiled statement is semantically correct.
Verify the code paths Azoth relies on; label the rest as generated pseudocode.
