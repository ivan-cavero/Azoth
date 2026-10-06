# Decompilation program

The goal is a reproducible, build-specific code map that helps Azoth answer
client and asset questions without repeating the same reverse engineering.
This is not a promise to recreate the original source or manually name every
compiler-generated function.

## Current baseline

- The local corpus is indexed against 423,579 `.pdata` functions for the
  installed client build. The latest tracked report shows 37 cumulative
  decompilation failures.
- A cached xref map, Ghidra runner, candidate namer, PAK reader, and readers for
  localization/DataSheet data are already in the repository.
- Confirmed function behavior lives in
  [`../atlas/client-functions.json`](../atlas/client-functions.json). Machine
  projects and pseudocode remain in the ignored local decompilation directory.

See the [tool workflow](DECOMPILATION.md) for commands and the
[backlog](DECOMP-BACKLOG.md) for measurements and remaining work.

## Work order

1. Keep the corpus tied to an executable fingerprint and produce an explicit
   report of total ranges, successful exports, and failures.
2. Retry the known failures and fix corpus bookkeeping only when it changes
   coverage or reliability.
3. Name functions needed by the current Azoth feature from strings, reflection
   metadata, callers, and decompilation. Keep unconfirmed names as candidates.
4. Verify protocol, component, and asset claims against bytes, client behavior,
   or an independent signal before treating them as facts.
5. Expand to other game systems and content formats when they unblock a
   concrete server or content task.

## Flow-scoped campaign (player-visible phases)

The bulk corpus gives raw coverage; understanding is organized by the phases a
player walks through. For each phase, decompile the functions the phase
actually exercises (string/reflection anchors first), record types, callers,
and what state each function expects, and record the phase's outgoing
requests with the atlas. Order:

1. **Launch and title screen** — engine startup, services init, "press any
   key" gate, settings bootstrapping.
2. **Login** — Steam auth handoff, gateway queue ticket, login RMI chain.
3. **Server select** — server list request/response, selection commit.
4. **Character select and creation** — list, create, delete, appearance data.
5. **World entry** — REP connection, V3 registration, spawn ladder
   (see [REP-PROTOCOL.md](REP-PROTOCOL.md)).
6. **In-world** — movement/physics authority, interaction, menus, zoning.

Connection-wrapper expectations (`GameConnectionWrapper` and similar state
machines) are analyzed per phase: which inputs it waits for, which queries it
issues, which state transition each one unlocks, and how failures or timeouts
propagate. These belong in the client function registry with call chains, not
in narrative docs.

Rules: one phase at a time; a phase is done when its message contract and
state transitions are in the atlas with evidence labels, not when a name list
looks plausible. Runtime observations come from `Game.log` ingests and
gateway/world traffic, never from live instrumentation while EAC state is
uncertain. For each phase keep one summary table of functions (VA, name tier,
what it expects, what it triggers) in the registry, and record negative
findings in the backlog. Learned per-screen behavior is written into
[`../atlas/client-map/`](../atlas/client-map/README.md) (growing knowledge
plan, one file per phase); the campaign manifest tracks decompilation state
and the client map records what was learned from it.

## Meaning of “complete”

- **Coverage:** every executable function range is represented in the local
  corpus, or appears in a tracked failure list.
- **Naming:** confirmed names have a VA, concise behavior, build, and method in
  the client function registry. Candidates remain labeled as candidates.
- **Verification:** code Azoth depends on is checked against another signal
  where practical. Other function bodies remain generated decompiler output.

Full range coverage is achievable. A claim that all pseudocode is 100%
semantically verified is not: the decompiler cannot recover intent, names,
types, or source-level structure that the binary does not contain. Preserve
that distinction in reports and code comments.

## Later direction

Asset editing and content modifications remain possible goals. First make the
current player component and movement path work. Do not build a full client
port, data-driven content platform, or bulk naming pipeline before a real use
case establishes what is missing.
