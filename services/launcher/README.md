# Launcher

The current private launcher is
[`src/Start-NwPrivate.ps1`](src/Start-NwPrivate.ps1). It prepares the ignored
`private-client/runtime/` tree from the operator's Steam install, copies the
executable and writable configuration files, and links the read-only assets.
The `python az.py game` supervisor hides the launcher console and records
lifecycle state and launcher output under `.azoth/`.

Two environment facts measured 2026-10-07, both in
[`PRIVATE-CLIENT-RUNBOOK.md`](../../research/docs/PRIVATE-CLIENT-RUNBOOK.md):

- The launcher sets `$env:LOCALAPPDATA` to `private-client/profile/Local`, but
  **the game ignores it** and resolves its profile through the Windows
  known-folder API. `Game.log` and `savedata` land under the real
  `%LOCALAPPDATA%\AGS\New World` and `%APPDATA%\AGS\New World\savedata`.
- The client validates gateway TLS through Schannel, so Windows must trust
  Caddy's current local CA before a private run. Run
  `python scripts/trust-caddy-ca.py` once after Caddy has created its PKI.

`python az.py migrate` moves the previous per-user runtime/profile into those
project-local paths. Run it once after closing the game and any Ghidra process
using the old analysis workspace. Existing private executables are preserved;
pass `-RefreshExe` to the PowerShell launcher only when you want a fresh copy
from Steam.

The seven instrumentation and build-bound patch helpers used during private
startup live in [`runtime-tools/`](runtime-tools/). General operator scripts
stay in the root `scripts/` directory; one-off client probes live under
`reverse/probes/client/`.

**`-Watch` timing.** The watch flow applies the world-phase memory patches once
the process has mapped. Applying them during load hung the client
(`WaitingForQueuedLogin`, `Not Responding`) in the 2026-10-07 A/B; the same
build reached the world without them. The DTLS bypass now runs as a pre-launch
disk patch (the Frida trust-patch crashed the client during startup mapping),
but the world-phase patches still need the client to be at character select.
For a controlled attempt, launch without `-Watch` and apply the patches
manually at char select; see the runbook.

The fuller launcher/update client is a future product direction, not an
implemented service. See [launcher notes](docs/LAUNCHER.md).
