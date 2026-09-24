# Azoth — live state

> Full historical sessions: `docs/sessions/` (start at `2026-09-13_pre-monorepo-STATUS.md`, Spanish archive).
> RE findings: `research/atlas/` (endpoints, models, errors, levers, observed traffic + OpenAPI).
> A new finding goes to the atlas, not here.

## Where we are (2026-09-24)

- **The client enters the world.** After character select → queue → V3 → REP replay, the client
  loads `NewWorld_VitaeEterna`, starts `streamingGDEManager` and `GDERenderManager`, processes the
  state bundles and reaches `WaitingForPlayerSpawn`.
- **Single blocker: the local player actor is never possessed.** Black screen (no camera/actor),
  `connection_player_timeout` fires at 120 s → `Popup_OnConnectionFail_InWorld`. Everything below
  the world is proven working.
- **Exact static cause of the black screen:** in `LoadContextAndLevel` (`FUN_146448cd0`) the client
  calls `clientContext->Initialize()` (`0x146448ee8`) and 1 ms later `Cleanup()`, because the
  virtual predicate at `0x146448f67` — `(**[*(pGame+0x60)+0x28+0x88])(...)` — returns non-zero and
  jumps to `0x1464490e1` (`[ctx+0x1a2]=1; FUN_146455e90(ctx)`). Live log: `[ClientContext]
  Initialize()` → `[ClientContext] Cleanup()`.
- **Next single task:** identify the `+0x88` vtable slot (object `*(pGame+0x60)+0x28`, the level
  streaming manager) and the state/message that makes it return 0. That is what unblocks the local
  actor + movement; no more blind A/B will move it.

## METHOD: one A/B = one fresh game process (learned the hard way)

- After a failed world attempt the client **destroys its `ClientContext`** and never re-creates it
  in the same process. Every later attempt logs
  `HandleUnexpectedMessage skipping ReceiveStateBundle ... clientContext == nullptr` for every
  bundle and falls back to the menu. **Restart `NewWorld.exe` for every A/B** or the result is garbage.
- This invalidates every negative measured on a reused process. Re-tested fresh: `0x65c` IDs,
  `interest=91` IDs, 36-byte text UUID remap, broad `mixed` — all still negative.
- The world loads on the first attempt **regardless of the substitution**; the earlier
  "persona loads the world" claim was conflated with the fresh-process effect. The persona rewrite
  is still the safest default (it feeds the live identity) but is not proven to be load-bearing.

## Replay A/B levers (world env, all default off, see `research/atlas/levers.md`)

| Env | What it does |
| --- | --- |
| `AZOTH_REPLAY_SPAN_SUBSTITUTION=character\|session\|persona\|mixed` | fills redacted spans of length 16/18/19/20/36/61 in the replay with live identity values |
| `AZOTH_REPLAY_SPAN_SEQS` / `AZOTH_REPLAY_SPAN_LENGTHS` | scope the substitution (e.g. `0x25,0x29,0x2a` + `16,61`) |
| `AZOTH_REPLAY_SPAN_SUBSTITUTION2` / `_SEQS2` / `_LENGTHS2` | second pass with a different selector (e.g. `session` on `0x6`) |
| `AZOTH_REPLAY_SPLIT_SEQ` / `AZOTH_REPLAY_SPLIT_DELAY_S` | hold everything from `seq >= SPLIT` until the client has loaded the level |
| `AZOTH_REPLAY_FRESH_LEVELINFO=session` | fresh key for the duplicate `0x663` at seq `0x4d` (produces a second `Initialize`) |
| `AZOTH_REPLAY_IDENTITY_REMAP=session\|character` | the six 36-byte dashed-UUID slots only |

Validated live on 2026-09-24 (fresh process each): first `Initialize` cleans up; a delayed second
`Initialize` after the map is loaded also cleans up; `0x65c` IDs = session UUID does not change it;
`interest=91` IDs are not the key. See the atlas for the full matrix.

## State-bundle wire (static, build 1.400)

- Type-`0x08` body: `[record_id VLQ][u8 fragment_count]`, then per fragment
  `[fragment_key VLQ][fragment_type_index VLQ][payload]` (`FUN_146af20d0` → `FUN_146af2340`).
- First record of the 46 KB init bundle: **id 1, 48 fragments**; id 1 is the local-player slot in
  `FUN_141717fc0` (`state + 0x608 + id*0x10`; log `Received new local player metadata, updating
  m_localPlayersServerGDERef`). The 13 world actors are other records of the same bundle.
- First fragment: key `0x47`, type index **972** (VLQ `8e 4c`, not `0x8e`=142), GUID
  `DE1A18A9-CE9E-4336-8DF8-698A73C579D4` (old index 144 / typeIndex 972); current getter
  `FUN_1416fcb20`, vtable `0x14801b088`.
- **No type-index shift 1.365 → 1.400:** the installed `typeindex.json` (7052 entries) maps index
  972 / 0x65c / 0x663 / 0x16a0 to the same GUIDs as the 1.365 registry. Do not chase a remap.
- `0x65c` is the **WORLD DATA** blob (first-light codec `world_data_blob_65c.py`, 12706 B) with two
  redacted 16-byte IDs at `+0x05` and `+12690`.

## What NOT to repeat (condensed)

1. **HTTP/1.1 only** — aws-sdk-cpp discards HTTP/1.0 bodies.
2. **getlogininfo is TWO schemas in one body**: lowercase `worlds` (exact reflection keys, extra
   keys DROP the object) + `LoginInfoList` OBJECT with PascalCase `Worlds`/`Characters`.
3. **`Characters: []` empties the panel**; seed a character (canonical: `Azoth` / `11111111-…`).
4. **Queue**: envelope `LoginQueueResponse`, PascalCase, non-empty `Signature`; refresh wants
   `Position: 0` + nested `Token`.
5. **Entitlements** is `{hasMoreResults, lineItems[]}`.
6. Without ETag on CMS the client crashes; credentials `expiration` is a **double epoch**.
7. **Restart the game to re-render** (and now: to get a valid A/B attempt).
8. **Region scope**: scope world lists per region host.
9. **TCP_NODELAY** on responses.
10. first-light VAs are build 1.365 — re-derive with `bytepat.py`; never trust archived displacements.
11. Raw `Cmd_Greetings`, re-sending r2/r4/r5 after replay, 4KB chunk bundling and unprefixed V3
    bodies all failed — do not retry (details in `research/atlas/levers.md`).

## Ops / environment notes

- Stack: gateway `:8080`, Caddy `:443`, world `:9000`, hosts private. `python az.py dev` for
  gateway+world (hot reload); launch it detached. `python az.py shot` + `scripts/shrink-image.py`
  for screenshots (never Read the raw PNG).
- Caddy can hang on some hosts after a restart; verify
  `https://d1w0bfy6smo4d1.cloudfront.net/prod/game/getlogininfo/jwt/omni` through `:443` (200)
  before blaming the world server.
- The private runtime copy currently has the DTLS disk patch applied
  (`scripts/patch-dtls-disk.py`, sha256 `537403d4…`); restore it with
  `python scripts/patch-dtls-disk.py restore` when finished. The official Steam exe is untouched.
- EAC memory ban is SCOPED: official process = never; our private runtime = allowed (but this
  session deliberately stayed static/server-side).

## Minor debt

- `services/world` needs `pyOpenSSL` (the one deliberate non-stdlib dep — stdlib ssl has no DTLS).
- After a session: `python az.py doc` (regenerate `research/atlas/openapi.json`) and commit the atlas.
