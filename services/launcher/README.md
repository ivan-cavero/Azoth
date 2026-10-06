# Launcher

The current private launcher is
[`src/Start-NwPrivate.ps1`](src/Start-NwPrivate.ps1). It prepares the ignored
`private-client/runtime/` tree from the operator's Steam install, copies the
executable and writable configuration files, and links the read-only assets.
The game profile and logs also stay under `private-client/profile/`. The
`python az.py game` supervisor hides the launcher console and records lifecycle
state and launcher output under `.azoth/`.

`python az.py migrate` moves the previous per-user runtime/profile into those
project-local paths. Run it once after closing the game and any Ghidra process
using the old analysis workspace. Existing private executables are preserved;
pass `-RefreshExe` to the PowerShell launcher only when you want a fresh copy
from Steam.

The seven instrumentation and build-bound patch helpers used during private
startup live in [`runtime-tools/`](runtime-tools/). General operator scripts
stay in the root `scripts/` directory; one-off client probes live under
`reverse/probes/client/`.

The fuller launcher/update client is a future product direction, not an
implemented service. See [launcher notes](docs/LAUNCHER.md).
