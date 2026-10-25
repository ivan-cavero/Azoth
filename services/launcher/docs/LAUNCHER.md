# Private client launch

## Current implementation

`services/launcher/src/Start-NwPrivate.ps1` prepares a runtime under the
ignored repo-local `private-client/runtime/` directory. It copies
`NewWorld.exe` and writable configs so disk patches cannot reach the Steam
install, links the large read-only asset tree, and uses the Azoth Steam API
stub.

The game does not honour the launcher's `$env:LOCALAPPDATA` override: it
resolves its profile through the Windows known-folder API, so `Game.log` and
`savedata` land under the real `%LOCALAPPDATA%\AGS\New World` and
`%APPDATA%\AGS\New World\savedata`. See
[`PRIVATE-CLIENT-RUNBOOK.md`](../../../research/docs/PRIVATE-CLIENT-RUNBOOK.md)
for the full path table and the Caddy CA trust step a cold setup needs.

`python ef.py game` starts a hidden supervisor and stores its output in
`.azoth/logs/`. `python ef.py game status|stop|restart` manages the same process.
The `-Watch` flow applies build-specific memory probes only after checking that
the target PID is the project-local executable and no EAC process is active.
Treat these as client experiments and re-derive every address when the client
build changes.

## Not implemented yet

There is no desktop updater, patch CDN, launcher UI, or content distribution
service. Keep those ideas out of startup code until there is a concrete update
need.
