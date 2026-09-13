# Our own launcher

## What it is

A desktop client (Windows first) that:

- Checks the version against **our** update server (not Steam, not Amazon).
- Downloads deltas: patch for `NewWorld.exe` (skip EAC, channel URL, DTLS pin), content packs (`*.pak`), configs.
- **Play** button → `Bin64\NewWorld.exe` with the working directory of the private install.
- Shows emulator status (gateway/world up) and news from our CMS.

It does not wrap EAC. It does not call `NewWorldLauncher.exe`. It does not need `steam.exe` at runtime.

## Game seed

The operator (you) copies your Steam install **once** to a private directory (e.g. `private-client/`, gitignored). That tree is the origin. The launcher:

1. Verifies the PAKs / exe exist (the user owns the game).
2. Applies our patches on top.
3. In a closed circle of friends: each member contributes their legal copy; the launcher does not host Amazon's 80+ GB.

Distributing Amazon's full client to someone who did not buy it is not this repo's goal.

## Play (spike)

`src/Start-NwPrivate.ps1`:

Azoth **does not use Steam at runtime**. `steam_appid.txt` in the Steam tree is not enough: `SteamAPI_Init` talks to `steam.exe` over IPC and `SteamAPI_RestartAppIfNecessary` relaunches through Steam. Program Files also refuses to let you write the appid (the `live_20260906_175804` session died on *Steam must be running* with Steam open).

The launcher:

1. Builds (if needed) `steam_stub/steam_api64.dll` — Init always OK, RestartAppIfNecessary = no.
2. Creates `%LOCALAPPDATA%\Azoth\game\` with a junction to `assets` and hardlinks of `Bin64` **except** Valve's `steam_api64.dll`.
3. Copies the stub + `steam_appid.txt` there.
4. Launches **that** `NewWorld.exe`. It does not touch the Steam install. Official Play stays intact.

Green signal: no `EasyAntiCheat_EOS.exe` and no Steam MessageBox; Game.log reaches `Channel service uri`.
Red signal: crash of the EAC embedded in the exe (then nop **only on the runtime copy**).

## Update server (future)

Our own HTTP: version manifest, hashes, deltas. The emulator gateway can host it at first (`/updates/...`). A separate service later if needed.

## Relationship with the other submodules

- **capture** keeps using Steam+EAC to record official.
- **emulator** is what Play connects to.
- This repo contains neither the exe nor the PAKs.
