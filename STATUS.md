# Azoth — live state

> Full historical sessions: `docs/sessions/` (start at `2026-09-13_pre-monorepo-STATUS.md`, Spanish archive).
> RE findings: `research/atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
> A new finding goes to the atlas, not here.

## Where we are

- **Character select renders** (2026-09-14): dual-schema `getlogininfo` (lowercase `worlds` for the dropdown + `LoginInfoList` OBJECT with PascalCase `Worlds`/`Characters` for the gate; external-verified shapes) → panel shows 1/1 + seeded character; VER MUNDOS table populated; queue ticket accepted (`LoginQueueResponse` envelope, non-empty `Signature`) → UI reaches "POSICIÓN EN LA COLA: 1" and polls the refresh path.
- **Current frontier: the REP/DTLS connection.** The client now wants to connect to `RepAddress` (`127.0.0.1:9000`). `services/world` (Javelin REP server) is BUILT: Carrier framing lib + V3 registration round-trip + DTLS 1.2 via pyOpenSSL; tests include a real DTLS handshake. The client pins an embedded `CN=New World` cert → handshake only completes with the in-memory verify-bypass (`scripts/frida-trust-patch.py`; site VERIFIED byte-identical on our build: `0x145dce8b5`, see `research/docs/REP-PROTOCOL.md`).
- Stack up: gateway `:8080` (TCP_NODELAY: region ping 40-70ms → ~10ms), Caddy `:443`, hosts private (34/34, `switch-mode.ps1 status` checks drift), world `:9000`, game via `az.py game` + Frida patch.
- One lore-named world per region (Everfall/Windsward/First Light/Monarch's Bluffs/Cutlass Keys); all `repAddress` → the single REP at `:9000`.

## What NOT to repeat (read before iterating shapes)

Full method lessons: `research/docs/LESSONS.md` — the 10 rules behind every stall we hit. Highlights:

1. **HTTP/1.1 only** — aws-sdk-cpp discards HTTP/1.0 bodies.
2. **getlogininfo is TWO schemas in one body**: lowercase `worlds` (INT enums, exactly the reflection keys — **extra keys DROP the object**) for the dropdown; `LoginInfoList` OBJECT with PascalCase `Worlds`/`Characters`/`PublicStatusCode=0`/`WorldStatus="ACTIVE"` for the gate. One casing alone = empty panel (both failure modes proven).
3. **`Characters: []` empties the whole panel** — seed a character entry; UI paths are gated by list contents.
4. **Queue**: envelope key `LoginQueueResponse`, PascalCase fields, `Signature` non-empty (handoff gate); refresh path (`/queue/v2/<id>/jwt`) wants `Position: 0` + nested `Token`.
5. **Entitlements** is `{hasMoreResults, lineItems[]}` — `{entitlements: []}` was invented and wrong.
6. Without ETag on CMS the client crashes. Credentials `expiration` is a **double epoch**.
7. Hot-swapping overrides does NOT count: **restart the game** (panel does not re-render on re-poll).
8. **Region scope**: the client reads getlogininfo via ITS region's gateway-CF host; scope world lists per region or every world repeats under every region.
9. **TCP_NODELAY** on server responses: without it, delayed-ACK/Nagle adds ~40ms the client reports as "ping".
10. External reference: nw-private-server/first-light (defunct, moved to Discord). Their VAs are build 1.365 — re-derive with `research/tools/reversing/bytepat.py`, never trust archived displacements (their archived patch rel32 was off by one).

## Exact frontier

- **InGame reached (first ever, 2026-09-19 19:09):** the 4th gate 13->14 is
  NOPed at the call site (`0x14644a8ed`: `test rax,rax; je` -> 9x NOP,
  `scripts/patch-spawn-gate.py`, stdlib WriteProcessMemory — NO Frida: the
  Interceptor crashed frida-agent.dll at startup). The FSM virtual returns
  `[mgr+8]` (local player entity, `0x146800d10`) which is NULL because the
  replica stream never created it; NOPing the branch forces the transition.
  v1 lesson: patching the getter BODY (600+ callers) crashes at startup
  (c0000005 @ NewWorld+0x104285d) — always patch the call site.
- **Transport SOLVED (2026-09-20 15:53):** replay chunks bundled into ~4KB
  datagrams (REPLAY_DGRAM_TARGET) + reliable retransmission with per-dg
  cap (REPLAY_RESEND_LIMIT=6). Client CT_ACKS now continuous ([42..44],
  [38..41]) — zero loss. The old 12.7KB StateBundle datagram was never
  acked (4229 resends did nothing); at 1100B/chunk bundled to 4KB it goes
  through. `scripts/ack-coverage.py` + `scripts/trace-session.py` are the
  analysis tools for this layer.
- **Current blocker: replica layer never creates the local player (30s
  `connection_ingame_timeout`, stable).** Everything wire-level works:
  InGame reached every attempt, replay r2..r176 (46KB bundle incl.)
  delivered with continuous client acks, V3 response in the VLQ-prefixed
  form the registration parser requires, eos-stub alive. Experiments that
  FAILED and must not repeat: raw Cmd_Greetings on ch0 (`Failed to
  unmarshal num_bytes=1/90` — Javelin does not use stock GM Greetings),
  re-sending r2/r4/r5 after replay (duplicates + seq collisions →
  `csdkerr_registration_unmarshal_error`), 4KB chunk bundling
  (BAD_PACKETS), unprefixed V3 body (`registration_unmarshal_error`
  before InGame — registration REQUIRES the VLQ prefix). The 89B V3
  record also logs a cosmetic `Failed to unmarshal num_bytes=90` from the
  replica reader (both consumers share ch0 0x21; official channel layout
  not preserved in the capture) — harmless, game proceeds.
- **Next session's single task: Ghidra RE of the Javelin replica
  dispatcher.** Entry points already derived: `FUN_1461ac8d0` (envelope
  unmarshal, decompiled at `research/derived/decomp/unmarshal-
  envelope.txt`, callers 0x146a6ec17/0x146b086f2/0x146b6ec5f), the FSM
  state-14 case is a no-op (switch has no case 0xe), and the manager
  gate the spawn-NOP bypasses returns `[mgr+8]` (local player entity,
  `0x146800d10`). Question to answer: which typed-stream message(s)
  after r176 trigger local-player replica creation (candidates: a
  Cmd_NewProxy carrying the player actor, or a Javelin-specific
  post-bundle message missing from the 1.365 capture).
- Client auto-retries every ~20s (58 V3 registrations in 15 min; each
  re-arms the replay from r2 — fine, the client re-requests everything).
- Dev workflow: `python az.py dev` = ONE console, hot-reload for gateway
  + world, caddy if :443 free, `dev stop` kills all (game untouched).
  Launch it DETACHED (Start-Process) so it survives agent restarts — as a
  child of the agent shell it died with the session (2026-09-20 morning).
  Game input without stealing the mouse is impossible (Raw Input, see
  LESSONS #11); screenshots via `python az.py shot`.
- Known cosmetic: seeded `Azoth_Dev` exists in every world (mock-level, not per-world persistence).
- Ops gotcha: duplicated service processes after restarts — kill by command line before diagnosing (LESSONS.md #9).

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- The EAC memory ban is SCOPED: official process = never; our private runtime = OK (Frida patch proves it).
- After a session: `python az.py doc`, commit atlas.
