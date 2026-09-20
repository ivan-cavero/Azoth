# Lessons — method errors that cost days, so they are never repeated

Written 2026-09-14 after the world-panel breakthrough ended a multi-week
stall. Each lesson here has a concrete incident behind it. Read before
starting any new RE round. Related: `DECOMPILATION.md` (procedure),
`REP-PROTOCOL.md` (wire), atlas rules in `atlas/README.md`.

## 1. A silent parser cannot be beaten by guessing — decompile it FIRST

**Incident:** ~2 weeks iterating `getlogininfo` body shapes blind (8 root
keys × casings × field sets, 2-minute game restart per test) with zero
feedback: aws-sdk-cpp fails parses silently, the UI just stays empty.

**Rule:** the moment a shape is unknown, the FIRST move is decompiling the
unmarshaller — not variant #1 of 30. The hints were in our own notes
(`MakeReturnCallbackWithStatus<GetLoginInfoResult, LoginInfoList>`) for days.

**Cost of the right move:** the dual-schema answer was one external trace
read + one afternoon once the unmarshaller functions were known.

## 2. "Extra keys are harmless" is per-model — verify per consumer

**Incident:** we served `name`/`regionId`/union-of-casings "for safety".
The lowercase worlds dropdown model DROPS THE OBJECT on any extra key.
Our safety fields were the bug.

**Rule:** strictness is a property of each model. For every wire model,
determine (by decompile or live A/B) whether unknown keys are ignored or
fatal, and record it in `atlas/models.json`. Default assumption: fatal for
UI reflection models, lenient for aws-sdk models — but verify.

## 3. One body can serve TWO consumers with different casings

**Incident:** we believed camelCase vs PascalCase was an either/or wire
truth ("the PascalCase block is decorative" — true for ListWorlds, FALSE
for GetLoginInfo). The real body carries BOTH: lowercase worlds for the
dropdown, `LoginInfoList` OBJECT with PascalCase Worlds/Characters for the
character gate. Serving either alone = empty panel (both modes proven).

**Rule:** find the consumer before deciding the casing. Different UI parts
can read different schemas from the same document. "Decorative (0 xrefs)"
verdicts are scoped to the function that was traced, not to the codebase.

## 4. Empty seed data gates whole UI paths

**Incident:** with worlds finally correct, the panel was STILL empty —
because `Characters: []`. The character panel renders nothing without at
least one character entry. We had `characters: []` for weeks thinking it
was "just honest".

**Rule:** the client renders lists, so every list that gates a screen needs
a valid seed entry in the mock. Seed data is not lying — it is the minimal
state the UI needs to walk its own path.

## 5. External RE is leverage, not shame — read it BEFORE the marathon

**Incident:** nw-private-server/first-light had the exact shapes, envelope
key names, and parser VAs public for months while we guessed.

**Rule:** for any mainstream game, search for prior art (GitHub, Discord
communities, ragezone) BEFORE the first decompile session. Copy the METHOD
(and verify every byte on OUR build), not the bytes. Their VAs were from a
different build; their archived patch rel32 was even off by one —
re-derive, always (`bytepat.py` exists for this).

## 6. Runtime instrumentation in OUR runtime is a different risk class

**Incident:** the EAC ban (correct for the official process) was read as
"no Frida ever", costing the single highest-leverage tool.

**Rule:** the ban scope = processes with EAC. Our private runtime (no EAC,
no Steam) is a lab: Frida attach, in-memory patches, traces — all fair
game there, all forbidden on the official client. Recorded in
`atlas/levers.md`.

## 7. The client measures FULL request time, not network RTT

**Incident:** "ping 50ms to our own machine". Windows delayed-ACK/Nagle
stalled the second write of every response ~40ms; plus Caddy TLS hop.

**Rule:** region "ping" = whole HTTPS request time. Fixes: `TCP_NODELAY`
on the server handler (one line), keep-alives, and knowing loopback TLS
still costs ~10ms. Do not chase network ghosts before timing the server.

## 8. Debug what the process sees, not what you assume it got

**Incident:** the REP client looped CONNECT_REQUEST for 30s while we
"answered". Only after logging RAW hex did we see the real payload format
(`[u32 BE len][cookie]`, msgId LAST byte) — our ACK had been malformed.

**Rule:** every server MUST log raw bytes + decoded view of what it
receives (gateway does this via traffic.jsonl; world does via
rep_traffic.jsonl). "We sent an answer" is not evidence the answer was
correct. Round-trip tests (parse(serialize(x)) == x) are the unit-level
version of the same rule.

## 9. Process hygiene: one service, one instance

**Incident:** repeated debugging of "why no answer" while TWO world
servers / TWO gateways ran — the client was talking to the stale one with
old code. Cost hours across a session (worse after server restarts).

**Rule:** before diagnosing behavior, enumerate processes by command line
(`Get-CimInstance Win32_Process`) and kill duplicates. `az.py start`
windows make this easy to miss. A launcher-side "start if not running"
guard is the structural fix.

## 10. Hosts/redirect drift is silent — check, don't assume

**Incident:** the allowlist had 34 hosts but the hosts file block had 8:
latency probes hit real AWS (2s pings) while everything "worked".

**Rule:** redirection state must be verifiable: `switch-mode.ps1 status`
exits non-zero on drift. Any environment-dependent behavior (hosts, certs,
services up) gets a status command, not a memory.

## 11. The game UI ignores PostMessage — only real SendInput lands

**Incident (2026-09-19):** `scripts/post-input.py` (WM_KEYDOWN/WM_CHAR/
WM_MOUSEMOVE+WM_LBUTTONDOWN posted to the window) did nothing: the OK
modal never closed. The engine reads Raw Input; window-message input is
not consumed anywhere.

**Rule:** background input without stealing the user's mouse is NOT
possible via window messages. The only channel is SendInput
(`click-window.py`/`send-input.py`), which steals mouse+focus — ask the
user before firing. For UI iteration, restarting the game (`az.py game`)
is the no-steal alternative. Screenshot channel: `python az.py shot`
(GDI PrintWindow → `%TEMP%\azoth_shot.png`) + `shrink-image.py`.

## Quick pre-flight for any new session

1. `switch-mode.ps1 status` → in-sync?
2. One gateway, one world, one caddy? (by command line, not memory)
3. Tests green? (`az.py gateway test`, `az.py world test`)
4. Is the shape I'm about to guess already decompiled — or decompilable
   in one sitting? If yes: decompile, don't guess.
5. Does the client log what it parsed? If not, hook or raw-log it first.
