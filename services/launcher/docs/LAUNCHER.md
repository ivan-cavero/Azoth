# Private client launch

## Current implementation

`services/launcher/src/Start-NwPrivate.ps1` prepares a runtime under the
ignored repo-local `private-client/runtime/` directory. It copies
`NewWorld.exe` and writable configs so disk patches cannot reach the Steam
install, links the large read-only asset tree, and uses the Azoth Steam API
stub. The client profile and `Game.log` live in `private-client/profile/`.

`python az.py game` starts a hidden supervisor and stores its output in
`.azoth/logs/`. `python az.py game status|stop|restart` manages the same process.
The `-Watch` flow applies build-specific memory probes only after checking that
the target PID is the project-local executable and no EAC process is active.
Treat these as client experiments and re-derive every address when the client
build changes.

## Not implemented yet

There is no desktop updater, patch CDN, launcher UI, or content distribution
service. Keep those ideas out of startup code until there is a concrete update
need.
