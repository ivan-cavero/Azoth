> This prompt is not the driver. Read `STATUS.md` and `.agents/skills/everfall-next/SKILL.md`. The Rust tree `server/` was deleted. Do not recreate it from these steps.

# Prompt: Build and review a useful client decompilation

Act as the reverse-engineering maintainer for the exact New World client build
in scope. Produce a navigable, build-scoped decompilation that helps answer a
specific question or measures corpus coverage honestly. Decompiled output is
pseudocode: it is not original source, and readable output is not proof that
its types, names, control flow, or semantics are correct.

## Task input

```text
Goal / question:
Client executable path and full SHA-256:
Functions, modules, or ranges in scope (or request full coverage):
Existing atlas entries / candidate names:
Required output and acceptance criteria:
```

## Work method

1. Read `AGENTS.md`, `.agents/skills/azoth-re/SKILL.md`,
   `research/docs/DECOMPILATION.md`, and the current decompilation plan. Verify
   the executable identity with its full SHA-256 before using addresses,
   offsets, names, or cached analysis. Keep every generated project isolated
   under ignored `reverse/builds/<full-sha256>/`.
2. For a focused question, start with the cached xref map and relevant strings
   or reflection data, then decompile the smallest useful function set. For a
   full-coverage request, enumerate functions/ranges, track completion and
   failures, and report coverage rather than implying that a partial export is
   complete. For incremental phase work use the campaign runner
   (`python ef.py re campaign ...`): read the current phase's state, run a
   batch, review the emitted `.c` files, then grow the phase with `add` /
   `expand` from string, reflection, and xref anchors. Keep the committed
   manifest as the phase map; never edit generated state into it.
3. For each important result, record exact function VA and file offset,
   callers/xrefs, relevant bytes or string evidence, decompiler/tool version,
   and the question the output answers. Check boundaries and call targets
   against disassembly. Verify key semantics with an independent signal such
   as a caller, reflection registration, log, known request, or runtime trace
   when allowed.
4. Use names in explicit confidence tiers: confirmed (supported by multiple
   independent signals), candidate (useful but not independently established),
   and unknown. Do not turn a demangler guess, RTTI class, parameter guess, or
   decompiler variable into a canonical name without evidence. Preserve
   original symbols where present.
5. Review output for bad function boundaries, missing callees, merged or
   split functions, nonsensical types, dead decorative strings, and obvious
   decompiler artifacts. Improve navigation and naming in generated indexes;
   do not hand-edit pseudocode into something that looks like verified source.
   When an untyped field (`undefined4`, unknown offset) is the open question,
   follow `research/docs/DECOMPILATION.md` "When the pseudocode does not
   answer the question": cheap static signals first, then the gated dynamic
   workflow with an existing probe — never guess a struct layout.
6. Put durable confirmed function facts in `research/atlas/client-functions.json`
   and protocol facts in the corresponding atlas registry. Keep large
   generated artifacts, Ghidra projects, and raw data ignored and regenerable.
   Note negative findings and remaining gaps in the focused backlog.
7. Do not use ReadProcessMemory, Frida, or a debugger if EAC is active or its
   state is uncertain. Use the live-analysis workflow only when explicitly
   requested and permitted by repository rules.

## Deliver

- State the full executable SHA-256 and exact scope.
- Provide a navigable index and reproducible regeneration command/path.
- Report function/range coverage, failures, naming confidence, and known
  decompiler limitations.
- For every conclusion, link its evidence and separate observed facts from
  interpretation. Never describe pseudocode as "100% verified source"; state
  what was verified and what remains inferred.
- Update the appropriate atlas/backlog so the result survives beyond this
  task. Avoid copying the same finding into multiple long-form docs.

Follow root `AGENTS.md`. Do not commit or push, and do not run or add tests
unless the user asks.
