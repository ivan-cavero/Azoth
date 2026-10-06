# steam_api64 stub v2 (minimal)

Valve's `steam_api64.dll` talks to `steam.exe`. Azoth replaces it only in the
ignored `private-client/runtime/Bin64/` tree, never in the Steam install.

```
powershell -File steam_stub\build.ps1
powershell -File src\Start-NwPrivate.ps1
```

## Why v2 (and why v1 crashed)

`NewWorld.exe` 1.400 statically imports **only 8 symbols** from `steam_api64.dll`
(`SteamAPI_Init`, `GetHSteamUser`, `RunCallbacks`, `Shutdown`, `Register/UnregisterCallback`,
`SteamInternal_ContextInit`, `FindOrCreateUserInterface`) and resolves
`SteamUser023` / `SteamFriends017` / `SteamUtils010` via `ContextInit`.
Verify with `pip install pefile` that the built DLL's static imports match
the list above and that the three interfaces resolve via `ContextInit`.
v1 exported 1065 symbols with **one shared dummy vtable returning 1 for every slot**.
Any method returning a pointer then dereferenced `0x1` → random startup crashes.
v2 exports ~22 symbols (`src/stub.def`) with **3 separate vtables + tiny Apps008**,
type-correct safe defaults (pointers → `NULL`/`""`, never `0x1`), and routes by
version string (`SteamUser*` → user, `SteamFriends*` → friends, …).

Debug: `AZOTH_STUB_LOG=1` writes `.azoth/tmp/azoth_stub.log` in the project
runtime environment (interface versions and ticket diagnostics).

## What it answers

- `SteamAPI_Init` → 1. `RestartAppIfNecessary` → 0. `IsSteamRunning` → 1.
- `User023`: `BLoggedOn` → true, `GetSteamID` → **address of a static ID**
  (client 1.400 derefs the slot-2 result as `CSteamID*` at `NewWorld+0x5a7f7ae`;
  returning the integer faults with `0xc0000005` — proven with `tools/azoth_dbg.py`),
  `GetAuthSessionTicket` → 32×`0xA5` + async `163` completion, encrypted-ticket
  and webapi-ticket fakes (`168`) for the Omni login.
- `Friends017`: `GetPersonaName` → `AzothPlayer`, state → online, no friends (count 0, names `""`, never `NULL`).
- `Utils010`: `GetAppID` → `1063730`, lang → `english`, country → `US`, battery → AC,
  `IsAPICallCompleted` → true, `GetAPICallResult` → fake `k_EResultOK` for our handles.
- `Apps008` fallback (64 slots, real SDK order): subscribed → true, language → `english`,
  beta/install-dir/launch-param → `""`, owner → fake SteamID.
- `RunCallbacks` dispatches `101` (connected), `163` (ticket OK), `168` (webapi OK)
  once per registration. Without this the game retries
  `Getting steam auth session ticket` every 10 s forever.
- Dummy tickets are rejected by Amazon. Never point this client at official hosts.

## Validated (client 1.400.6031.6004151, 2026-09-07, 5+ launches)

No `steam.exe`, no `EasyAntiCheat_EOS.exe`, no crash. `Game.log` shows `Steam Initialized!`
→ channel OK → frontend `NW_Frontend_NightHaven` → `AuthManager Initializing` →
`OmniSDK 1.6` → ticket accepted locally (`steam|a5a5…`) → `Omni CreateSession`
against **real Amazon fails with 303** (`OnCampfireLoginFailed @mm_authresult_Error_Persona`,
clean retry with backoff). That 303 is the gateway's job (hosts redirect + omni/queue
endpoints), not the stub's — the stub's frontier is done.

## Layout

- `src/stub.c`, `src/stub.def`, `src/config.h` — hand-written, no generator.
- `tools/check_imports.py` — exe imports vs `.def`.
- `tools/azoth_dbg.py` — minimal Windows debugger (ctypes only): launches the game,
  catches the first `0xc0000005` with registers + stack, or detaches on timeout.
  How the slot-2/`0x5a7f7ae` crash was proven.
- `tests/test_stub.py` — minimal-exports + vtable invariants.
