# Scripts index

Diagnostic scripts stay directly in scripts/ because az.py, launcher flows,
and experiment notes invoke many of them by path. This index groups them by
job; do not move a script without updating every caller and document.

## Start/operate the game

- az.py game, az.py mode, az.py dev, az.py world start, az.py shot,
  az.py click, and az.py key are the normal entry points.
- try-world-shape.py — shape A/B harness.
- capture-world-run.py — snapshot one DTLS session, Game.log, process hash,
  matching gateway JSONL rows and exact HTTP body sidecars, optional burst-probe
  log/reduced screenshot, and `ack-window.py` output under ignored
  `research/sessions/`. It reads append-only logs without editing them; raw
  evidence can contain private identities, tokens, and full plaintext payloads.
- shrink-image.py — shrink a screenshot before reading it. Never read the raw
  PNG.
- send-input.py, click-window.py, post-input.py — input methods. The game
  consumes Raw Input; use the validated SendInput path for real interaction.

## Client static analysis

Most reusable RE tooling lives in research/tools/reversing/, not here. Start
at research/docs/DECOMPILATION.md for peutil, xrefmap, Ghidra, and the symbol
database. The scripts below are focused live probes or patch helpers:

- patch-*.py — narrow byte patches. Read each script's build/offset and
  restore behavior before use.
- frida-*.py — targeted probes for the private runtime only when EAC is
  confirmed inactive. The repository's EAC rule always takes precedence.
- experiment-v3-*.py, trace-session.py, world-inject.py — protocol/session
  experiments; read the matching atlas lever and experiment notes first.

## World black-screen investigation

Start with research/docs/WORLD-DEBUGGING.md. Current focused probe families:

- Carrier delivery: ack-window.py maps each replay chunk to its Carrier
  sequence and reports client ACK gaps; ack-coverage.py gives a compact summary.

- State bundle/context: frida-context-init.py, frida-bundle-chain.py,
  frida-reader-capture.py, frida-burst-capture.py, frida-slot-watch.py,
  frida-deferred-actions.py, frida-rep-gate.py.
  `frida-burst-capture.py` also records the gated manager-context dispatch,
  its indirect setter, and local-player prototype-builder calls; zero counts
  are meaningful only after the bundle drain is confirmed in `Game.log`.
- Entity table and possession: frida-entity-table.py, frida-node-actors.py,
  frida-mgr-watch.py, frida-possess-valid.py, frida-possess-all.py.
- Replication/portrayal: frida-dispatch-probe.py, frida-portray-probe.py,
  frida-real-pump-probe.py, frida-player-id-watch.py.
- Patch helpers: see patch-predicate-flag.py, patch-timeout-watchdog.py,
  patch-spawn-gate.py, and the corresponding entries in research/atlas/levers.md.
- `frida-set-deferred-depth.py` changes the deferred-action batch limit only in
  the selected process. It requires an explicit EAC-inactive acknowledgement;
  use one fresh process per value and retain its JSONL before/after record.

Probe names describe historical experiments, not guarantees that a probe is
safe or still valid for the installed build. Check its offsets, target process,
and EAC status before use. Prefer static analysis and server-side evidence when
runtime instrumentation is not allowed.

## Rule for adding a script

1. Give it one narrow purpose and a name that identifies the subsystem.
2. Put shared reusable code in a module/tool rather than copying probe logic.
3. Record the exact build, evidence, and invocation in the relevant research
   doc or atlas entry.
4. Add it to this index only if it is a stable operator entry point. One-off
   experiments can remain discoverable through the investigation log.
