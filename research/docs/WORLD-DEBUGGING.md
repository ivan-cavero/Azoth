# World debugging loop

The active question is in [STATUS.md](../../STATUS.md). Read the matching
evidence in [WORLD-INVESTIGATION.md](WORLD-INVESTIGATION.md) and the relevant
entry in `research/atlas/client-functions.json` before changing a replay or
starting a game attempt.

## Decide if a live attempt is needed

Prefer static decompilation, existing `rep_traffic.jsonl`, and fixtures first.
One live run costs a full client restart and should distinguish one specific
cause. Do not repeat a line already closed in STATUS or the atlas.

## A valid attempt

1. Check `python ef.py mode status`; confirm only one gateway, world server,
   and Caddy process is serving the test.
2. Start a fresh private game process for each A/B variant. A failed world
   attempt destroys that process's `ClientContext`.
3. Mark this process's `Game.log` start. Do not trust counters until the log
   shows `ProcessPendingReliableMsgQueue processing 26 messages`.
4. Set `AZOTH_LOG_RAW=1` on the world server if the question involves packet
   delivery or DTLS. `python ef.py dev` does not inherit environment changes
   made in another shell.
5. Change one variable, then capture the attempt:

   ```powershell
   python scripts/capture-world-run.py --pid <NewWorld-pid> --session <name>
   ```

6. Record the first boundary reached: UDP, DTLS, Carrier ACK, application
   reader, state bundle, component creation, or player behavior. Update the
   source atlas/symbol record with the result.

Never edit an append-only service log while that service is running. Before
opening a screenshot, shrink it with `python scripts/shrink-image.py`.
