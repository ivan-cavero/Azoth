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

1. **HTTP/1.1 only** — aws-sdk-cpp discards HTTP/1.0 bodies.
2. **getlogininfo is TWO schemas in one body**: lowercase `worlds` (INT enums, exactly the reflection keys — extra keys drop the object) for the dropdown; `LoginInfoList` OBJECT with PascalCase `Worlds`/`Characters`/`PublicStatusCode=0`/`WorldStatus="ACTIVE"` for the gate. One casing alone = empty panel (we proved both failure modes).
3. **Queue**: envelope key `LoginQueueResponse`, PascalCase fields, `Signature` non-empty (handoff gate); refresh path (`/queue/v2/<id>/jwt`) wants `Position: 0` + nested `Token`.
4. **Entitlements** is `{hasMoreResults, lineItems[]}` — `{entitlements: []}` was invented and wrong.
5. Without ETag on CMS the client crashes. Credentials `expiration` is a **double epoch**.
6. Hot-swapping overrides does NOT count: **restart the game** (panel does not re-render on re-poll).
7. External reference: nw-private-server/first-light (defunct, moved to Discord). Their VAs are build 1.365 — re-derive with `research/tools/reversing/bytepat.py`, never trust archived displacements (their archived patch rel32 was off by one).

## Exact frontier

1. Client → REP `:9000` with the Frida patch active → watch `services/world/rep_traffic.jsonl` for the DTLS handshake + V3 from the REAL client (our synthetic handshake already works).
2. Post-V3 ladder: CONNECT_REQUEST/ACK (system channel 3, msgId LAST byte) → SelfIdent → LevelInfoChanged → replica-creation message (state 10→14 map: `research/docs/REP-PROTOCOL.md`).
3. Known cosmetic: client lists every world under every region (it does not filter by `regionId`/`awsRegion`); region "ping" ~10ms is Caddy TLS+proxy overhead (loopback RTT is ~0).

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- The EAC memory ban is SCOPED: official process = never; our private runtime = OK (Frida patch proves it).
- After a session: `python az.py doc`, commit atlas.
