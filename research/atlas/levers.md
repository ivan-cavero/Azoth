# Client debug and configuration levers

Everything discovered about activating/deactivating/questioning the client. Keep
up to date: **one new lever = one line here** (memory/decomp finding → write it
NOW, not "for later").

## Alive (tested, working)

| Lever | How | Effect |
| --- | --- | --- |
| `g_showHiddenWorlds` | cvar, "UI will show worlds which are flagged as hidden" | `+g_showHiddenWorlds 1` via CLI **did not apply** (`+cvar` args do not apply in retail). Access path pending. |
| World panel advances on HTTP 400 | gateway serves `__http_error` on getlogininfo | The UI shows "Falló al iniciar sesión ValidationException" and **advances** to character select. Useful as an A/B probe: 200-parse-OK → no advance; 400 → advance. |
| Real synthetic click | `scripts/click-window.py` (SendInput) | `orca computer click` does NOT reach the game; SendInput does (validated: changed tab). |
| Steam stub debug | `AZOTH_STUB_LOG=1` + `services/launcher/steam_stub/tools/azoth_dbg.py` | Minimal debugger for client 0xC0000005 crashes: RIP, registers, stack walk with NewWorld.exe+X offsets. |
| hosts mode switch | `deploy/switch-mode.ps1` (or `az.py mode`) | official / private / official-capture: redirects Amazon hosts to 127.0.0.1. |
| Spawn-gate force 13→14 | `scripts/patch-spawn-gate.py` (WriteProcessMemory, no Frida) | NOPs `test rax,rax; je` at FSM `0x14644a8ed` (manager virtual returns `[mgr+8]`=NULL). **Client reached InGame 2026-09-19 19:09.** v1 lesson: patching the getter body (`0x146800d10`, 600+ callers) crashes at start — patch the call site only. |
| Ladder force 11→12→13 | `scripts/frida-rep-force-ladder.py` | Forces `[carrier+0xA0]==2`, `[+0xBC8]`, `[+0x252]` getters to 1. Stable, part of `az.py game` watch flow. |
| Admin without UAC | scheduled task `AzothAdminProxy` (docs/ADMIN.md) | Write cmd to `%LOCALAPPDATA%\Azoth\admin\cmd.txt`, `Start-ScheduledTask`, read out.txt. |
| Gateway hot-reload | `python az.py gateway reload` | Dev mode: restarts the gateway automatically on any `.py` change under `services/gateway/src/`. |
| Full traffic capture | automatic in the gateway | Every request/response → `services/gateway/traffic.jsonl` + `research/atlas/observed-endpoints.json`. OpenAPI: `python az.py doc`. |

## Dead / closed (do not waste time again)

| OCR kit (`ocr-image.ps1`, `ocr-window.py`, `capture-window.py`) | Removed 2026-09-13: the orca computer-use skill covers screenshots/interaction; only SendInput (`az.py click`/`key`) remains because `orca click` never reaches the game window (validated). |
| Memory/instrumentation ban — SCOPED (2026-09-14) | The Frida/ReadProcessMemory ban covers the OFFICIAL process (EAC kernel callbacks). Our private runtime (Start-NwPrivate.ps1, no EAC, no Steam) is fair game: `scripts/frida-trust-patch.py` runs against it. Official process = still never. |

| Lever | Why not |
| --- | --- |
| `ClientOverride.json` in the install | The game looks for it in `@assets@/` via the PAK internal VFS — 5 locations tried, none read. Redirecting config via loose file requires a **PAK repack**. |
| Retail console (`~` / VK_OEM_3) | Does not open a console in retail; `orca press-key` cannot send the key. `CXConsole` exists but is unreachable. |
| `+ui_dumpDataLayer 1` via CLI | Wrote no dump: probably a non-retail build flag or different syntax (the real CLI uses `-FPSWarningThreshold <lo>,<hi>`). |
| PascalCase aws-sdk model block | 0 xrefs of any kind → decorative. The real wire is camelCase. |
| `big_parser` 0x144f40780 | NOT the HTTP parser: it is a reflection/behavior-context registry. |
| Mitm capture of the official session | `captures/official/official-login.mitm` = Microsoft Store noise (0 hits of amazongames). Capturing official HTTPS is useless: Amazon's TLS. |
| Frida/inject/ReadProcessMemory on official | EAC EOS: kernel ObRegisterCallbacks. Documented in `research/docs/EAC.md`. Only post-2027 or a private build. |

## To investigate (findings noted, untested)

| Lever | Where seen | What it promises |
| --- | --- | --- |
| DTLS verify bypass (REP trust) | **VERIFIED on our build**: CMP `0x145dce8ad` + JZ `0x145dce8b5` -> `0x145dce9d4` (`bytepat.py dtls-verify`); site is byte-identical to the external trace. Patch: `E9 1A 01 00 00 90` via `scripts/frida-trust-patch.py` (recomputes rel32; the archived external bytes were off by one). Details: `research/docs/REP-PROTOCOL.md` | Force the DTLS driver's permissive verify path so the handshake against our REP server succeeds. In-memory only, against the private runtime (no EAC). The embedded `CN=New World` cert means our own CA can never validate — this patch is the only viable trust path. |
| `game-security.enable-anticheat` (bare key on the layer doc) | WorldId S3 layer. FUN_146193620 (`0x146193620`, 0 E8 callers) looks up the BARE string `enable-anticheat` (`lea` at `0x1461936a7` → `0x1484cb300`) on the layer document. Nested/dotted copies miss that lookup. Serve **bare** + nested + dotted on every S3 layer. Six `cmp ecx,0x102 / sete [rbp+0x6f]` sites store 1 for ANY JSON bool — Frida rewrites each to `mov byte [rbp+0x6f],0`. **Not sufficient:** Game.log 2026-09-18 19:18:04 still `@mm_csdkerr_server_requires_anticheat` 24ms after socket with WorldId 501B (bare false) + all sete patches + FUN_1444f5700 skip. ClientSDK is not gating on this JSON flag at socket time. | Disable the config-side default-true AC flag. |
| RegistrationResponse trailer `01 00 00 01` | Official Mixed-Nuts capture; first-light copied it verbatim. Live 1.400 with `00 00 00 00` **accepted** V3 (`received registration response from REP`, Game.log 2026-09-18 19:38:18) and advanced to `WaitingForActorGameConnection`. Keep `00 00 00 00`. | Stop advertising "official AC-required server" on our RegistrationResponse. |
| Post-V3 must not wait for V3 silence | After V3 accept the client streams ch0 1115B (flags 0x05 reliable) + 161B. Treating ch0>64 as V3 re-emitted ~700 RegistrationResponses. Answer V3 once. Synthesized SelfIdent+LIC AV'd at FUN_146b6f190 (dump 3664). Silence after one V3 → `@mm_csdkerr_disconnect (4)` at 10s (Game.log 2026-09-18 20:15). Need Carrier CT_ACKS on later envelopes + CLOCK_SYNC keepalive; not hypothesized app messages. | Keep ClientSDK from disconnecting after V3. |
| `ui_dumpDataLayer` | cvar string in the exe ("Dumps debug info of UiDataLayer to log") | Dump the UI data-layer state: which worlds are loaded and why they don't paint. |
| In-process local-dev mode | `client-connection.enable-local-dev` (documented, requires PAK repack) | The game's own stub services persisting to `_persistence/*.json` — reveals the EXACT shapes the client expects without a gateway. |
| `auth-testing` fault injection | `client-connection.auth-testing.*` (same repack requirement) | Controlled auth failure injection. |
| Cvars via file | `system_windows_pc.cfg` / `user_preload_settings.cfg` | `+cvar` args don't apply, but the preload cfg IS read — possible path for `g_showHiddenWorlds 1`. |
| `g_loginWithWorldTypes` | cvar string ("Consider available world types before requesting login") | If there is an allowed-type list, an out-of-list type is silently discarded — candidate predicate for the empty world list. |
| `@mm_defaultworldname/desc/motd` | exe strings | Panel localization; may reveal the world-dropdown render path. |
| Launcher debug output | Game.log echoes active config | `Gateway Signing Host`, `Gateway Address`, `HTTP Gateway Address`, `Gateway Mode`, `ClusterId` — all come from the channel JSON we serve. |
