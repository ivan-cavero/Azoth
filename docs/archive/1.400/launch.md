# Launch — engine startup, title screen, settings bootstrap

Build analyzed: 8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e ·
Status: current as of 2026-10-06 (campaign launch phase, 12 functions decompiled
under `reverse/builds/8654f01d…c8e/campaign/launch/`).

## Overview

Ordered flow, statically derived from the decompiled batch (all labels
`statically-derived` unless noted):

1. **PAK mount** — `PaksList.lst` is read and each pak validated
   (`0x147215b60`: "Error opening '%s'", "Pak file validation error: '%s'").
   This is why the PAK edit path (DECOMP-BACKLOG 2.4) requires the patch pak
   as the first `PaksList.lst` line — earlier lines claim priority here.
2. **GameStartup interface** — `0x14720a8c0` parses the command line
   (`-noprompt`, `-minimal`, `-norandom`, `-remotesonic`, `-modrestart`,
   `restart`), environment (`AMAZON_GAMES_GAME_SESSION`, `PRODUCT_ID`,
   `AMAZON_GAMES_SDK_DLL_PATH`), installs `CryExceptionHandlerTerminateProcess`,
   and owns the restart flow ("Failed to restart the game: %s").
3. **CVar registration** — three tables: engine `sys_*` (`0x147124b40`, 305
   strings), game `g_*` debug/dev (`0x141031660`, 760 strings), and
   connection/loading CVars (`0x146441c70`, 61 strings).
4. **Platform init** — `0x14102ee20`: Steam gate
   (`steam_appid.txt` trap, "Steam must be running…", "Steam Initialized!"),
   input profile `libs/config/defaultProfile.xml`, and the local-dev
   connection modes (`client-connection.client-gateway.mode`,
   `client-connection.authorization.mode` with observed literals
   `stubbed`/`dummy`; `client-connection.enable-local-dev`).
5. **Splash + loading screen** — `sys_splashscreen*` CVar family (same table
   as 3); loading screen timing `g_minLoadScreenTime` / `g_maxLoadScreenTime`
   / `g_ignoreLoadTimeout` (`0x146441c70`).
6. **Main menu entry** — `MainMenuSystemComponent` (`0x14451f860`); frontend
   level selected by `javelin.frontend-level-name` +
   `javelin.frontend-coatlicue-project-path` (`0x1410509e0`).
7. **Connection warnings, deferred until loading screen is gone** —
   `GameConnectionWrapper::UpdateWarnings` (`0x14646d460`) queues
   `ShowConnectionWarningMessage()` and writes `Client.ConnectionWarning`
   0/1/2 + `Client.ConnectionIsBad` only when `IsLoadingScreenShown()` is
   false.

## UI surfaces (exhaustive)

Hidden surfaces found in the CVar/console registration functions
(`statically-derived` from string tables inside the bodies):

| Surface | Type | Effect | Evidence |
| --- | --- | --- | --- |
| `nw_isInMainMenu` | console command | prints whether player is in main menu | 0x141031660 string refs |
| `nw_exitToMainMenu` | console command | exits to main menu | 0x141031660 |
| `nw_showLoadingScreen` | console command | triggers a loading screen | 0x141031660 |
| `g_debugGameCamera` / `g_debugExperience` / `g_debugVitals` / `g_debugStatMultipliers` | CVar | debug overlays | 0x141031660 |
| `g_showNPCNametags`, `g_showFloatingCombatText`, `g_forceUserNameTags` | CVar | nametag/combat text toggles | 0x141031660, 0x146441c70 |
| `g_selectWorldId`, `g_showHiddenWorlds` | CVar | **world selection without UI** — direct server-select input | 0x146441c70 |
| `g_loginQueueBypass`, `g_maintenanceModeBypass` | CVar | skips login queue / maintenance gate ("Don't login to a world through the login queue", "Allow login during maintenance mode") | 0x146441c70 |
| `g_createCharacterRateLimitBypass`, `g_createCharacterAccountLimitBypass` | CVar | character-creation limit bypass | 0x146441c70 |
| `g_connectWithCapabilities` | CVar | "Exercise any special permissions which are available when connecting" | 0x146441c70 |
| `g_minLoadScreenTime` / `g_maxLoadScreenTime` / `g_ignoreLoadTimeout` | CVar | loading screen timing | 0x146441c70 |
| `g_worldsCMS*CloudfrontKey` / `g_worldsCMS*Key` | CVar | worlds CMS CloudFront signing keys (server-select data source) | 0x141031660 |
| `client-connection.client-gateway.mode` / `client-connection.authorization.mode` | config | local-dev modes with literals `stubbed`/`dummy` — **the client's own built-in way to point at a local gateway** | 0x14102ee20 |
| `-minimal`, `-noprompt`, `-modrestart`, `restart` | cmdline | startup modes / restart flow | 0x14720a8c0 |

## Client state machine

- PAK mount failure → validation error path in `0x147215b60` (exact failure
  screen still `open:`).
- Steam gate failure → error dialogs ("Steam must be running…",
  "Unexpected steam_appid.txt file found. Remove this file from the New World
  folder.") — the steam_appid.txt check is a **hard trap relevant to the
  private client**.
- Restart loop: `0x14720a8c0` re-execs the game (`restart ` prefix,
  `-modrestart`) — the launcher's "restart into mode X" mechanism.
- Connection-warning escalation (observed in `0x14646d460`):
  `Client.ConnectionWarning` 0 → 1 → 2, plus `Client.ConnectionIsBad`;
  suppressed while a loading screen is shown.

## Messages and payloads

- `open:` no Amazon-side message expected before user input; confirm with
  gateway `traffic.jsonl` on a fresh private launch (gateway stopped state
  today).
- Local: `client-connection.client-gateway.mode` = `stubbed`/`dummy` and
  `client-connection.enable-local-dev` are client-side config switches —
  cross-check against how the Azoth launcher currently points the client at
  the local gateway (may be a cleaner switch than the current approach).

## Functions involved

| Function (name tier) | VA (build) | What it expects | What it triggers | Evidence |
| --- | --- | --- | --- | --- |
| javelin_frame_tick_driver (confirmed) | 0x145aa23f0 | queued frame jobs | startup phase progression | client-functions.json |
| pak_list_startup_mount (candidate) | 0x147215b60 | PaksList.lst on disk | pak mounting + validation | campaign/launch/0x147215b60…c |
| gamestartup_interface_factory (candidate) | 0x14720a8c0 | cmdline + env | GameStartup interface, restart flow | campaign/launch/0x14720a8c0…c |
| engine_sys_cvar_registration (candidate) | 0x147124b40 | — | sys_* CVar table | campaign/launch/0x147124b40…c |
| game_cvar_console_registration (candidate) | 0x141031660 | — | g_* CVar + console command table | campaign/launch/0x141031660…c |
| connection_loading_cvar_registration (candidate) | 0x146441c70 | — | connection/loading/bypass CVar table | campaign/launch/0x146441c70…c |
| steam_platform_init_hub (candidate) | 0x14102ee20 | Steam running, no steam_appid.txt | Steam init, client-connection modes | campaign/launch/0x14102ee20…c |
| frontend_level_getters (candidate) | 0x1410509e0 | CVar values | frontend level/project paths | campaign/launch/0x1410509e0…c |
| mainmenu_system_component (candidate) | 0x14451f860 | AZ component registration | main menu system component | campaign/launch/0x14451f860…c |
| gameconnection_wrapper_update_warnings (confirmed — self-naming log string inside body) | 0x14646d460 | loading screen state | Client.ConnectionWarning writes | campaign/launch/0x14646d460…c |
| game_loop_warning_telemetry (candidate) | 0x14646c720 | fps thresholds, connection state | connection-fail-while-loading, map change gating | campaign/launch/0x14646c720…c |
| store_reflection_registration (candidate) | 0x14513cb70 | — | CatalogOffer/StoreSlot/entitlements type registration (386 KB) | campaign/launch/0x14513cb70…c |

## Data and assets

- `PaksList.lst` (game root) — first lines claim mount priority; the patch-pak
  edit path hooks here (DECOMP-BACKLOG 2.4).
- `libs/config/defaultProfile.xml` — input profile.
- `ShaderCacheStartup.pak` — referenced by startup streaming
  (`0x145f5ae20`, `0x1471436a0`).
- `bootstrapareas.json` — pathing bootstrap (`0x146a0e480`), pre-gameplay.
- Localization: UI text (press-any-key etc.) is **not** in the exe; it comes
  from localization paks (see negative findings).

## Settings / options

The client option store and its named operations (added 2026-10-08).

### The `OptionsDataBus` component

`FUN_1445a7470` (0x1445a7470-0x1445acd39) registers the settings component and
binds its named methods through the helper `FUN_144556990` (name -> function
pointer):

| Method | Purpose |
| --- | --- |
| `InitializeSerializedOptions` | first-load default init (log: `Failed to find Options file ''. Initializing to Defaults`) |
| `SerializeOptions` | save/load driver (log: `Saving to`/`Moving to @savedata@/temp_usersettings_<hash>.javsave`) |
| `SaveJson` / `LoadJson` | the JSON (de)serialization |
| `OpenLanguageSpecificUrl` | localized help URLs |
| `OpenTermsInBrowser`, `OpenPrivacyInBrowser`, `OpenNoticesInBrowser`, `OpenCodeOfConductInBrowser`, `OpenAntiCheatDisclosure` | legal/document links |
| `OpenTwitchStreamInBrowser`, `OpenForumsInBrowser`, `OpenNewWorldSiteInBrowser`, `OpenHelpInBrowser` | external links |
| `CopyVersionInfoToClipboard` | build string |

### Where the values live

- Saved file: `@savedata@/usersettings_<hash>.javsave` (the `<hash>` is
  per-account/character; measured `E02D01D81483A0FF` on this machine).
- The store is read through `local_option_lookup` (`FUN_140fca4e0`) against a
  **thread-local** store (`FUN_141027e40`), which is also the mechanism the
  local-player possession gate uses to find the character UUID (see
  `../client-functions.json`, `local_option_gate_status_writer`).
- `ClientOverride.json` is looked up via the PAK internal VFS
  (`@assets@/ClientOverride.json`) and is **not** read as a loose file — a PAK
  repack is required to change it (atlas/levers.md, dead-lever list).

### Server interaction

**None.** Settings are entirely client-side; the server never sees them. The
only server-visible effect observed is the character UUID the option store
supplies to the login queue request (see `character-select.md`).

## Open questions

Operational bring-up (hosts, Caddy CA trust, patch timing, evidence paths) is
in [`../../docs/PRIVATE-CLIENT-RUNBOOK.md`](../../docs/PRIVATE-CLIENT-RUNBOOK.md).
The items below are about the client's own launch code.

- `open:` exact failure UI when PAK validation fails at startup (needs one
  observed run with a broken PaksList.lst entry).
- `open:` whether `client-connection.client-gateway.mode=stubbed` produces a
  fully local client without any gateway — would matter for the private
  runtime's current DTLS/gateway approach.
- `open:` splash-loop LiveKernelFault environment failure (atlas note) — which
  init step precedes it; needs a fresh private launch with logging.
- `open:` who calls `0x147215b60` (no direct E8 caller found in the sweep;
  likely reached via the engine's module init table).

## Negative findings

- **"press any key" does not exist in the exe** (`.rdata` scan, 154 string
  needles). The title-screen gate text comes from localization paks; anchor
  hunts for the gate must go through the localization index, not exe strings.
- `0x14513cb70` looked like loading-screen logic from its strings but is
  store/entitlements reflection registration (CatalogOffer, StoreSlot,
  TransactionEntitlement…) — loading-screen *ids* only ride along.
- No `MainMenu`-related direct callers of the frontend hub `0x14102ee20` were
  found via E8 sweep (its callers come through vtable/AZ system registration),
  so the phase grew through string anchors instead.
