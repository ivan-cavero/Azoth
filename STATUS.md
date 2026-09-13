# Azoth — live state

> Full historical sessions: `docs/sessions/` (start at `2026-09-13_pre-monorepo-STATUS.md`, Spanish archive).
> RE findings: `research/atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
> A new finding goes to the atlas, not here.

## Where we are

- **Omni login fully OK** (result 0) → CHOOSE CHARACTER screen. Steam stub v3 → OmniSDK → tokens → credentials → campfire.
- **Current blocker:** the panel shows the REGION (`Azoth EU`, latency) but the world dropdown stays empty ("no hay mundos activos en tu región" on earlier variants). The client parses `getlogininfo` without error, then filters / fails to find the root.
- Environment: gateway `:8080` (HTTP/1.1, `publicStatusCode: 0`), Caddy `:443`, hosts in private mode. Start: `python az.py gateway start` (or `gateway reload` for hot-reload dev) / `az.py caddy` / `az.py game`.
- **Traffic capture is live**: every request/response lands in `services/gateway/traffic.jsonl` and `research/atlas/observed-endpoints.json`. After a session, `python az.py doc` regenerates `research/atlas/openapi.json`.

## What NOT to repeat (read before iterating shapes)

1. **The gateway must answer HTTP/1.1** — aws-sdk-cpp discards HTTP/1.0 bodies. Everything measured before that fix was garbage.
2. `publicStatusCode` must be **0** (`(psc & 0xffffe8b7) != 0` rejects; 1 failed the mask).
3. `status` must be `"ACTIVE"`.
4. Wire keys are **camelCase** (AZ registry `0x144f54cda`); the PascalCase block `0x148703900` is decorative (0 xrefs).
5. Without ETag on CMS the client crashes. Credentials `expiration` is a **double epoch**, not ISO.
6. The client only requests `worlds/list` when clicking a region (0 hits in normal login). The dropdown list comes from `getlogininfo` → `LoginInfoList` (bus `GetLoginInfoLists`).
7. Hot-swapping overrides does NOT count: **restart the game** (~2 min per shape) because the panel does not re-render on re-poll.

## Exact frontier

- 8 candidate JSON roots tried with sentinels (worlds, Worlds, LoginInfoList, WorldsInfo, regions, recommendedWorlds, DDD/EEE...) → **none painted**. Either the root is something else, or the dropdown is not fed by getlogininfo at all.
- Promising lead A: decompile the real GetLoginInfo unmarshaller (Ghidra headless: `research/tools/re/decomp.py`; paths `0x1464154e0` / `0x146412430`, NOT result vtable `0x148503018`).
- Promising lead B: lambda RTTI `MakeReturnCallbackWithStatus<GetLoginInfoResult, LoginInfoList>` — extracts `&result.<member>`; reading the lambda body gives the member offset.
- Promising lead C: capture a real Amazon response with a valid account (mitm of gateway-CF impossible due to TLS; left is unmarshaller RE or consumer `0x144f54ae3`).
- 400-probe as A/B: 200-parse-OK does not advance the panel; 400 does. If we serve the correct 200, the panel advances without error.

## Minor debt

- Accept-terms: RE the endpoint to persist consent (future DB).
- `mock_discovery/` is gitignored and disposable; `shape-*.json` regenerate via `az.py shape`.
- Old `emulator/` only keeps 2 logs locked by the old gateway process; they vanish on restart.
