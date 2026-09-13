# Launcher propio

## Qué es

Un cliente de escritorio (Windows primero) que:

- Comprueba versión contra **nuestro** update server (no Steam, no Amazon).
- Baja deltas: parche de `NewWorld.exe` (skip EAC, channel URL, pin DTLS), packs de contenido (`*.pak`), configs.
- Botón **Play** → `Bin64\NewWorld.exe` con working directory del install private.
- Muestra estado del emulator (gateway/world up) y noticias de nuestro CMS.

No envuelve EAC. No llama a `NewWorldLauncher.exe`. No necesita `steam.exe` en runtime.

## Seed del juego

El operador (tú) copia su install Steam **una vez** a un directorio private (p.ej. `private-client/` gitignored). Ese árbol es el origen. El launcher:

1. Verifica que existen PAKs / exe (el usuario posee el juego).
2. Aplica nuestros parches encima.
3. En un círculo cerrado de amigos: cada uno aporta su copia legal; el launcher no hospeda los 80+ GB de Amazon.

Distribuir el cliente completo de Amazon a quien no lo compró no es el objetivo de este repo.

## Play (spike)

`src/Start-NwPrivate.ps1`:

Azoth **no usa Steam en runtime**. `steam_appid.txt` en el árbol de Steam no basta: `SteamAPI_Init` habla con `steam.exe` por IPC y `SteamAPI_RestartAppIfNecessary` relanza por Steam. Program Files además no deja escribir el appid (la sesión `live_20260906_175804` murió en *Steam must be running* con Steam abierto).

El launcher:

1. Compila (si hace falta) `steam_stub/steam_api64.dll` — Init siempre OK, RestartAppIfNecessary = no.
2. Crea `%LOCALAPPDATA%\Azoth\game\` con junction a `assets` y hardlinks de `Bin64` **excepto** el `steam_api64.dll` de Valve.
3. Copia el stub + `steam_appid.txt` ahí.
4. Arranca **ese** `NewWorld.exe`. No toca el install de Steam. Official Play sigue intacto.

Señal verde: no hay `EasyAntiCheat_EOS.exe` ni MessageBox Steam; Game.log llega a `Channel service uri`.
Señal roja: crash de EAC embebido en el exe (entonces nop **solo en la copia runtime**).

## Update server (futuro)

HTTP nuestro: manifiesto de versión, hashes, deltas. El emulator gateway puede hospedarlo al principio (`/updates/...`). Más adelante un servicio aparte si hace falta.

## Relación con los otros submódulos

- **capture** sigue usando Steam+EAC para grabar official.
- **emulator** es a lo que Play conecta.
- Este repo no contiene el exe ni los PAKs.
