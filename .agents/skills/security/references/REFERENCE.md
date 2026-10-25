# Security reference

## Assets

| Asset | What goes wrong | Control |
| --- | --- | --- |
| Session token | Stolen from a log or a capture committed to git | Redact captures. Gitignore certs and traffic logs |
| Character state | Client claims an item or a position | Server authority. Ignore the claim |
| Admin action | Sent on the same socket as movement | Separate port, separate auth, audit line before the action |
| Private client | Patch applied to the Steam install | Steam stays read-only |
| Launcher binary | Swapped dependency | Pinned checksums in `toolchain.lock.json` |

## Easy Anti-Cheat

Stop if you cannot show the process was launched without EAC. Do not document a bypass as a feature. Probes live under `reverse/probes/client/` and run through `python ef.py probe` against the private client only.

## Supply chain

`python ef.py setup` installs pinned tools under `.azoth/`. Do not point those downloads at a mirror. If a checksum fails, stop.

npm installs for the site use `platform/web/package-lock.json`. Do not pipe a remote script into a shell.

## Git

Tracked files must not contain a home-directory path (`check-paths` fails the build). Docs under `docs/archive/` and `docs/journal/` are scanned more loosely because they quote old notes. Do not put a fresh secret there either.

## Disclosure

`docs/LEGAL.md` is the preservation posture. This skill is not legal advice. When a change touches redistribution, accounts, or payments, read that file before writing the feature.
