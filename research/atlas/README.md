# Atlas — master registry of the client surface

Source of truth for **everything we know** about what `NewWorld.exe`
(1.400.6031.6004151) says and expects: endpoints, fields, types, required/
optional, errors, and debug levers. Every RE finding lands here **at the moment
of discovery** (not in STATUS.md, not in the chat).

## Files

| File | Content |
| --- | --- |
| [`endpoints.json`](endpoints.json) | REST operations: method, path, operation, response, status |
| [`models.json`](models.json) | RE'd data models: exact wire keys, types, registration order |
| [`errors.json`](errors.json) | Observed error codes and their real cause |
| [`levers.md`](levers.md) | Client debug/config levers: tested, alive, dead, to investigate |
| [`observed-endpoints.json`](observed-endpoints.json) | **Auto-generated** by the gateway: every endpoint family the client actually requested, with captured examples. Tracked — commit it. |
| [`openapi.json`](openapi.json) | **Auto-generated** OpenAPI 3.1 rendering of the observed traffic (`python az.py doc`). Tracked — commit it. |

## Rules

1. **One finding = one atlas commit.** If it is only in STATUS.md or the
   conversation, it does not exist.
2. **RE'd field = exact name + type + required/optional + evidence** (exe VA or
   capture).
3. The shapes served by the gateway are generated from here, not the other way
   around: if `models.json` and the gateway code diverge, the atlas wins and the
   gateway gets fixed.
4. **Invented** fields (never seen in the exe or a capture) are marked
   `"evidence": "guessed"`.
5. `research/schemas/live/*.json` are real captured responses: the on-the-ground
   counterpart of the atlas.
6. After every play session: `python az.py doc`, then commit the updated
   `observed-endpoints.json` / `openapi.json`. A family the client requested and
   we do not mock (gateway 404) is the next work item.

## How it was filled so far

- Xrefmap + AZ reflection registry of the exe (blocks `0x144f54cda`,
  `0x1483c0900`, `0x148703900`).
- Capstone parsers: `ags_fed_acc_token.cpp`, `platform_persona_account.cpp`,
  `ags_persona_account.cpp`, `jwt_reader`.
- Live channel/CMS captures (`research/schemas/live/`).
- REST path table in `.rdata` @ `0x84ff388` (JavelinGatewayService operations).
- Live traffic capture through our own gateway (`observed-endpoints.json`).
