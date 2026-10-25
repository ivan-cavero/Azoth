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

**Rule:** the ban applies to any process with EAC active. A private launch is
not proof EAC is absent: confirm the actual target process before any Frida,
memory read, or debugger session. If EAC is active or its state is uncertain,
use static analysis, Game.log, and server-side traces. Recorded in
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
(`Get-CimInstance Win32_Process`) and kill duplicates. `ef.py start`
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
user before firing. For UI iteration, restarting the game (`ef.py game`)
is the no-steal alternative. Screenshot channel: `python ef.py shot`
(GDI PrintWindow → `%TEMP%\azoth_shot.png`) + `shrink-image.py`.

## 12. "Services are running" is not "the client can talk" — trust is a layer

**Incident (2026-10-07):** gateway, world, and caddy all reported `running`,
hosts were `in-sync`, and DNS resolved the redirected hosts to loopback — yet
the client hung at the title gate with **zero** gateway requests. Caddy had
regenerated its local CA in a fresh data dir (same subject, new key) while
Windows still trusted the old root. Nothing logged an error on the client side.

**Rule:** TLS trust is a first-class environment layer. Verify it end-to-end
with a client that uses the same store as the game (Schannel:
`Invoke-WebRequest`), not with a tool that carries its own CA bundle (Git Bash
`curl` gives a false negative). `python scripts/trust-caddy-ca.py --check`
makes the state verifiable, like `switch-mode.ps1 status` does for hosts.

## 13. Prefer a disk byte-patch over Frida when the address is fixed

**Incident (2026-10-07):** the Frida DTLS trust-patch attached while the client
was still mapping and crashed it (`c0000005` in ntdll, before `Game.log`). The
same change applied to the repo-local executable copy on disk started normally
and carried the client through the whole REP path.

**Rule:** Frida is for dynamic questions (hooks, pointers, tables, calls). For a
fixed byte at a known VA, use `ReadProcessMemory`/`WriteProcessMemory` from
stdlib, or a disk patch on the private copy. And apply world-phase memory
patches only once the client is at character select — applying them during load
hangs it.

## Search the repo for the measured path before inventing one

**Incident (2026-10-25):** chasing why the client never left the Aeternum splash,
I invented input calls by hand. I posted Enter (VK 0x0D) via
`scripts/gui/post-input.py` — nothing. Then a real scan code 0x1C (Enter) via
`scripts/gui/send-input.py` — still nothing. Two launches spent on the wrong key.

The repo already had the answer, written down: `scripts/session/private-run.py`
says `pass the splash gate with a scan-code Space` and does
`hold-key.py "New World" 0x39 0.15`. Scan **0x39 is Space, not Enter**. With it
the client reached character select in ~20 s. The same script also refuses to
send keys when the window rejects focus, which is exactly the failure mode the
`azoth-computer-use` skill warns about (`SetForegroundWindow` is refused unless
the caller is foreground, and the key lands in whatever window the user is in).

**Rule:** when the question is "how do I drive the client past step X", the
first search is the repo (`grep -rn "splash\|attract\|hold-key\|scan" scripts/`),
not a fresh key to try. A script that already automates the step encodes the
measured key, the measured duration and the focus guard. Guessing costs a
10-minute launch per wrong guess; the search costs one command.

**Corollary:** a record's `NEXT:` line is a hypothesis, not an instruction. The
`frontend_splash_loop_after_livekernelfault_20261005` record pointed at
`post-input.py` with Enter, and both halves were wrong for this gate.

## Quick pre-flight for any new session

1. `switch-mode.ps1 status` → in-sync?
2. One gateway, one world, one caddy? (by command line, not memory)
3. `python scripts/trust-caddy-ca.py --check` → caddy CA trusted?
4. Tests green? (`ef.py gateway test`, `ef.py world test`)
5. Is the shape I'm about to guess already decompiled — or decompilable
   in one sitting? If yes: decompile, don't guess.
6. Does the client log what it parsed? If not, hook or raw-log it first.
