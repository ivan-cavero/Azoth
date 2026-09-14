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

- **REP Carrier handshake**: real client completes DTLS (`dtls-established` in `services/world/rep_traffic.jsonl`) and loops CONNECT_REQUEST (system ch3, msgId LAST byte, payload `[u32 BE len][cookie]`, raw hex logged) ~1/s for ~30s, then "ERROR DE CONEXIÓN". Our echo-ACK is not yet accepted — next: compare against a real-login capture reference or hook the client's cookie-compare function.
- Post-V3 ladder after the handshake: SelfIdent → LevelInfoChanged → replica-creation (state 10→14 map: `research/docs/REP-PROTOCOL.md`).
- Known cosmetic: seeded `Azoth_Dev` exists in every world (mock-level, not per-world persistence).
- Ops gotcha: duplicated service processes after restarts — kill by command line before diagnosing (LESSONS.md #9).

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- The EAC memory ban is SCOPED: official process = never; our private runtime = OK (Frida patch proves it).
- After a session: `python az.py doc`, commit atlas.
