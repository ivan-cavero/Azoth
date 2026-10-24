# Platform (player-facing)

Skeletons for product surfaces outside the sim tick (master plan R8 / P14).

| Path | Role |
| --- | --- |
| `launcher/` | Download, verify signed patches, start private client |
| `web/` | Accounts, privacy settings, rankings (opt-in), supporter store later |

Runtime authority stays in `server/`. This tree must not grow wire codecs or
sim rules. See `docs/LEGAL.md` before any store UI.
