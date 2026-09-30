# World entry: repeatable debug loop

This is the short operator checklist for the black-screen investigation. The
measured findings and closed hypotheses are in
[WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md); raw protocol levers are in
[`../atlas/levers.md`](../atlas/levers.md).

## Current diagnosis

Latest fresh run: PID 39172, REP session 1059 at 2026-09-30 14:29Z. It loaded
`NewWorld_VitaeEterna`, drained 26 queued messages, and initialized
`GDERenderManager`; the captured frame is black, followed by
`State(InGame) is timeout`. The record-1 handler changed `state+0x618` from null
to non-null pointers, but manager `+0x08/+0x10` stayed null. The burst probe
counted 283 splits/visits (IDs 1–94), 94 portrayals, 148 table inserts, zero
calls to the local-player prototype builder `FUN_1416957c0`, and zero calls to
known actor factory `FUN_141563e20`. A new read-only hook saw 39 generic manager
dispatches, all at status 2, and no call to the manager context setter. Deferred
queues sampled empty at every drain entry despite the warnings. Session 1059
has full REP data and probes but no HTTP rows. Full evidence is under
`research/sessions/world_20260930T143111Z_pid39172_session1059/`.

Baseline PID 35508/session 1055 had all 1,338 outbound Carrier sequences
acknowledged and the same no-holder black frame; it has 45 gateway rows and 51
exact body sidecars under `research/sessions/world_20260930T134112Z_pid35508_session1055/`.

This confirms the black frame is not explained by missing Carrier ACKs. The
client consumes and dispatches record-1 metadata into a state slot, but no local
player context or actor is visible. The state slot and manager object are
distinct. The zero actor counts apply only to the known builder and factory;
other construction paths remain possible. Setting
`javelin.deferred-actions-max-depth` to 16 on PID 45476 did not change the
warnings or black frame. The 25 missing-facet RMI errors and deferred-action
recursion errors are observed; their causal relation to the missing local-player
view remains open. Next: trace the record-1 state object's constructor/type and
the inputs that could move the gated manager dispatch from status 2 to status 1.

The main signals to keep distinct:

| Signal | What it tells us |
| --- | --- |
| `ProcessPendingReliableMsgQueue processing 26 messages` | A real world attempt reached the queued-message drain. Without it, downstream counters are not evidence. |
| Client `CT_ACKS` coverage for seq `0x25` chunks | Whether Carrier acknowledged each datagram; this alone does not prove application decode or entity creation. |
| `rep_traffic.jsonl` replay sends/retries and `Game.log` bundle drain | Whether the server sent the data and whether the client progressed past the reliable-message queue. |
| `Received new local player metadata` trace / holder writes | The trace is category 3 and suppressed at this run's level; use actual holder evidence, not absence of that log line. PID 45592's one-shot getter probe captured both the holder entity and ready pointer as null. |
| `clientContext == nullptr` | Check for preceding `Cleanup()` or the delayed duplicate `LevelInfo`; this can be a consequence, not the root cause. |

## One valid A/B attempt

1. **Use a fresh game process for every variant.** Once a world attempt fails,
   that process destroys `ClientContext` and does not recreate it. Stop and
   relaunch `NewWorld.exe`; do not count retries in that process.
2. **Confirm one instance of each service.** Check the command lines for gateway,
   Caddy, and world server before measuring. Stale service processes can serve
   old code or replay state.
3. **Capture all local protocol boundaries.** Keep the attempt's `Game.log`,
   corresponding `services/world/rep_traffic.jsonl`, and gateway request/response
   records with their exact HTTP body sidecars. The world server's `AZOTH_LOG_RAW=1`
   setting records full encrypted UDP datagrams in both directions before/after
   DTLS, so a silent handshake failure can be distinguished from packets not
   arriving. Decrypted inbound app payloads are full; server sends are captured
   as `outbound-app-data.raw_full` by default.
   Snapshot one run without editing the live append-only log:
   `python scripts/capture-world-run.py --pid <NewWorld PID> --session <index>`
   (add `--burst-log <capture.jsonl>` and `--screenshot <file.small.jpg>` after shrinking with
   `scripts/shrink-image.py`). The raw snapshot lands under ignored
   `research/sessions/` and may contain private IDs and full plaintext.
4. **Mark the run boundary.** `Game.log` accumulates sessions; use the latest
   `Executable: NewWorld.exe` marker. Record the timestamp, process id, replay
   settings, and whether the 26-message drain happened.
5. **Change one variable.** Keep a baseline and compare ACK coverage for every
   chunk of seq `0x25`, retries, first missing chunk, and whether processing
   advances past the initial 26. Do not change chunk pacing, duplicate
   `LevelInfo`, and identity substitution in the same run.
6. **Write the result down immediately.** Use the template below. Confirmed
   wire/function discoveries also go to the atlas/symbols at once; this log is
   for the experiment matrix, not a replacement for those sources of truth.

## Next diagnostic order

Start with evidence collection before changing the replay:

1. The latest clean attempt is preserved under `research/sessions/` as session
   1055 (latest snapshot 13:41Z). All outbound Carrier sequences are ACKed; don't spend another restart
   on transport pacing without a new ACK gap.
2. Do not spend another game restart on chunk pacing unless a new capture shows
   a Carrier ACK gap. First inspect the reliable StateBundle body and correlate
   the application stages and correlate per-record portrayal/insert/factory
   counts. The updated `frida-burst-capture.py` records those maps; attach before
   a new process enters the world. Existing Frida probe offsets must be
   revalidated against the installed build and used only after EAC-inactive
   status is confirmed for that exact process.
3. Follow the first missing boundary: carrier receive → application reader →
   bundle split → record visitor → portrayal/insert/create → local-player slot
   → possession/camera. Keep the RMI missing-target errors as a separate
   symptom until their target IDs are mapped to replay records.
4. Change one variable only after a cheap static/fixture analysis predicts a
   deciding signal; use a fresh game process for each live variant.

Each live variant costs a fresh game process. The first baseline determines
which branch of this plan is worth paying for.

## Experiment entry template

```text
Date/time:
Build / executable hash:
Fresh process (pid): yes/no
Service instances verified:
Hypothesis:
Single changed variable:
Settings / command:
Expected signal:
Observed: (26-message drain? ACK coverage? replay retries? player metadata?)
Game.log excerpt / time range:
rep_traffic excerpt / time range:
Conclusion: confirmed / rejected / inconclusive
Next smallest experiment:
Atlas or symbols updated:
```

## Safety and interpretation

- The repo rule is strict: **never use ReadProcessMemory, Frida, or a debugger
  with EAC active**. Do not infer that “private mode” means EAC is absent; verify
  the actual process configuration first. If EAC status is uncertain, stay with
  static decompilation, Game.log, and server-side traffic.
- A zero Frida counter is not proof a hook is broken unless the 26-message drain
  proves the measured path ran. When runtime instrumentation is permitted, hook
  the attempt's progress markers first.
- Use the exact build's offsets. First-light addresses are not valid evidence
  for this build unless re-derived.
- For screenshots, run `python scripts/shrink-image.py <capture.png>` before
  opening an image; never read the raw PNG.
- Do not truncate `traffic.jsonl` while the gateway is running. Stop it before
  any cleanup.

## Relevant commands

```powershell
python az.py world test
python az.py world start
python az.py dev
python research/tools/reversing/peutil.py selftest
python research/tools/reversing/decomp.py --serve
```

Use either `az.py world start` or the combined `az.py dev` workflow as
appropriate; do not start a second world server. For command details, see
[`services/world/README.md`](../../services/world/README.md) and
[`../docs/DECOMPILATION.md`](DECOMPILATION.md).
