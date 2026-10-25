> This prompt is not the driver. Read `STATUS.md` and `.agents/skills/everfall-next/SKILL.md`. The Rust tree `server/` was deleted. Do not recreate it from these steps.

# Prompt: Live client and request analysis

Act as the live-analysis specialist for one explicitly requested experiment
against the private New World client. Use live instrumentation only when
static analysis, existing logs, and captures cannot answer the stated
question. The purpose is to observe and explain client behavior for Azoth, not
to evade anti-cheat or inspect unrelated processes.

## Task input

```text
Question / one variable to measure:
Private client executable path and full SHA-256:
Expected process and launch route:
Evidence already available:
Permitted tools and expected output:
```

## Safety and evidence gate

1. Read `AGENTS.md` and `.agents/skills/azoth-live-debug/SKILL.md` in full.
   Live use must be explicitly requested by the task. Confirm that the exact
   process is the private client and verify its executable path/hash.
2. Before attaching any memory reader, Frida hook, or debugger, verify the
   current EAC state using the approved project procedure. If EAC is active,
   the state is uncertain, or the procedure cannot establish that it is
   inactive, stop live instrumentation and continue with static analysis,
   logs, or allowed server-side captures. Never bypass, disable, or evade EAC
   to make an experiment possible.
3. Inspect only the client process and only data needed for the assigned
   question. Capture game traffic only to Azoth's own gateway/world server;
   do not intercept or MITM Amazon endpoints. Keep raw payloads and sensitive
   values in ignored local session files.

## Work method

1. Establish a baseline and a single hypothesis. Change one variable per
   attempt. Record client build hash, process path/PID, launch route, tool and
   hook version, server revision, start time, and the exact action.
2. Capture the smallest useful trace: timestamp, direction, connection/session
   identity, endpoint, message/RMI or address, payload length and bytes/schema,
   order, retries, acknowledgements, and relevant state before/after. Pair it
   with the corresponding Game.log range and, where useful, Azoth server-side
   datagram/request logs.
3. Verify the experiment actually reached the target path before interpreting
   counters. For world attempts, require the current run's
   `ProcessPendingReliableMsgQueue processing 26 messages` marker; zero counts
   without that marker mean the attempt is unproven. Use `AZOTH_LOG_RAW=1` when
   distinguishing missing UDP from DTLS rejection.
4. Run one fresh client process for each world A/B attempt. Record failed
   attempts as negative results only after verifying the target path ran.
   Stop the relevant service before editing/replacing its append-only logs.
5. Corroborate important memory findings with a second signal: client log,
   static xref/disassembly, gateway/world capture, or visible state change.
   An address hit alone does not prove the meaning of a field or function.
6. Redact tokens, identifiers, and account data in summaries. Preserve raw
   traces only in ignored `research/sessions/`; add durable, minimal findings
   to the atlas with build hash, VA/offset or packet fixture, timing, confidence,
   and reproduction steps.
7. Close the experiment: identify the smallest causal behavior, its side
   effects, and the next unanswered question. Remove temporary hooks and
   abandoned alternatives from normal workflows and indexes. Do not leave
   instrumentation attached or running after the requested measurement.

## Deliver

- A compact timeline/trace with exact measurements and evidence locations.
- What was directly observed, independently validated, inferred, and remains
  unknown.
- The causal result and side effects, or a clear statement that the experiment
  did not reach the target path.
- The atlas/doc changes needed to make the result reusable and the cleanup
  performed.

Follow root `AGENTS.md`. Do not commit or push, and do not run or add tests
unless the user asks.
