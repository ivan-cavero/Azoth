---
name: azoth-re
description: Reverse engineer the New World client for Azoth when answering questions about its binary, protocol, PAK data, or component behavior.
---

# Azoth reverse engineering

Use this skill for static analysis, decompilation, client wire schemas, and
asset format work in this repository.

After the knowledge-OS reorg, the default coverage campaign is
[`docs/runbooks/agentic-boot-campaign.md`](../../../docs/runbooks/agentic-boot-campaign.md)
(prompt: `.agents/prompts/boot-naming-campaign.md`): name open → InGame before
deep combat RE.

## Choose the smallest decisive method

1. Confirm the exact client build and question.
2. Check `research/atlas/ontology/`, `research/atlas/`, and the focused
   reference under `research/docs/` before rediscovering a known fact.
3. For native code, query the cached xref map first; use strings and AZ
   reflection metadata to identify candidates, then decompile only the relevant
   function or caller chain with `python az.py re decompile`.
4. Use Capstone for byte layout and parser questions. Run `python az.py setup`
   once to install Ghidra/JDK in `.azoth/tools/`; keep each project, pseudocode,
   and cache under ignored `reverse/builds/<full-executable-sha256>/`.
5. Stop when the evidence answers the decision at hand. Do not expand a focused
   question into naming or validating the whole executable.

## Close each finding

- State the behavior that worked, the evidence that distinguishes it from the
  rejected variants, and why the client accepts it.
- Check side effects and whether a smaller implementation produces the same
  observed result.
- Keep the winning path in the runtime. Remove failed branches and candidate
  generators that no longer answer an open question; keep useful negative
  results in the atlas or the focused investigation note.
- Preserve one minimal fixture when it protects the confirmed contract. Do not
  keep a pile of experiment payloads as production fallbacks.

## Keep evidence separate from output

- The Ghidra pseudocode and corpus are navigation aids, not original source and
  not automatically verified semantics.
- Add a confirmed function to `research/atlas/client-functions.json` with its
  VA, concise behavior, and `found_by` evidence. Keep generated name candidates
  out of that registry until a human has checked them.
- Add HTTP/wire fields to the relevant atlas model with exact spelling, type,
  requiredness, and evidence. Mark guesses explicitly with
  `"evidence": "guessed"`.
- State the build and verification method. A name from a string/xref is a
  candidate; confirm the body, callers, or runtime effect before treating it
  as behavior.
- Record useful debug/config levers in `research/atlas/levers.md` when found.
- For a requested full-client decompilation, account for every executable
  function range, report decompiler successes and failures per exact build,
  and retry failures. Generated C remains pseudocode; only names and behavior
  checked against evidence belong in the confirmed function registry.

## Grow the client knowledge plan

Understanding is organized per player-visible screen in
`research/atlas/client-map/` (one file per phase, template in its README).
When analysis produces a finding about a screen's UI, state machine,
messages, or hidden surfaces (console commands, dev tools), write it into the
matching phase file with evidence links, following
`research/atlas/client-map/TEMPLATE.md`. For incremental decompilation use
`python az.py re campaign` (see `research/docs/DECOMPILATION.md`, section
"Run the phase campaign") and reflect what each batch teaches into the
client map, the campaign manifest, and `research/atlas/client-functions.json`.

Never use live process memory, Frida, or a debugger when EAC is active or its
state is uncertain. Private launch alone is not proof that EAC is absent. Keep
raw captures and account data under ignored `research/sessions/`.
