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
  build `1.400.6031.6004151`. The latest tracked inventory reports 37 cumulative
  failures; this is historical evidence only. `python az.py migrate` preserves
  the old workspace under ignored `.azoth/archive/legacy-appdata/decomp/` after
  active analysis processes exit. Do not resume it as the new analysis source.
  Rebuild the corpus under `reverse/builds/<full-sha256>/`; see
  [DECOMP-BACKLOG.md](DECOMP-BACKLOG.md).
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
python az.py re pe info
python az.py re pe str <distinctive-text>
python az.py re pe callers <va>
python az.py re decompile --symbol <confirmed-name>
python az.py re decompile --target <va>
python az.py re decompile --callers-of <va>
python az.py re decompile --range <start>-<end>
```

For a long investigation, `python az.py re decompile --serve` keeps the
current Ghidra project open; send work with normal `python az.py re decompile`
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
python az.py re campaign init        # sync manifest -> per-build state
python az.py re campaign status      # per-phase coverage
python az.py re campaign add world-entry --target 0x146b6eb70 --note "inbound decode"
python az.py re campaign expand world-entry 0x146b6eb70   # + callers of that VA
python az.py re campaign run --phase login --batch 10
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
   (`python az.py re xref`, `re strings`, `re naming`) — cheap static signals.
2. If static signals cannot settle it, escalate to the dynamic workflow in
   `.agents/prompts/live-analysis.md`: verify the EAC gate, then reuse or
   adapt an existing probe from `reverse/probes/client/`. Proven patterns:
   hook the identified function to capture the object instance, then
   `MemoryAccessMonitor` the field range to find the writer
   (`frida-activity-timer.py` did exactly this for `+0xAA8`), or a hardware
   watchpoint on a pointer slot (`frida-mgr-watch.py`). List probes with
   `python az.py probe list`.
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
- For this build's raw file arithmetic, `.rdata` VAs use `fileoff + 0x1800`
  and `.text` VAs use `fileoff + 0xA00`. Re-derive these after a client update;
  prefer `peutil.py` when it can resolve the address directly.
- Ghidra 12 loads the Java helper as a compiled script bundle; `decomp.py`
  handles compilation. The tool also handles Windows paths with parentheses.
- Do not pipe a Ghidra import through a command that closes its output early;
  it can leave a partial project.
- Run `python az.py setup` to install Ghidra and its JDK under ignored
  `.azoth/tools/`. All generated projects, pseudocode, indexes, and caches live
  under `reverse/builds/<full-executable-sha256>/` by default. Git ignores this
  directory, so each exact client build has a separate project and corpus.
- New analysis uses that project-local workspace. The old per-user corpus is
  preserved for reference but is not an input to new analysis.

This workflow can provide complete range coverage and explicit failure
reporting. It cannot prove every decompiled statement is semantically correct.
Verify the code paths Azoth relies on; label the rest as generated pseudocode.
