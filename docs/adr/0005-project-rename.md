# 0005. Project rename (leave “Azoth”)

Date: 2026-10-24
Status: accepted (name TBD)

## Context

The working title **Azoth** collides with an established New World
preservation community project, [Azoth Central](https://projectazoth.com/)
(capture tooling, protocol reference, public brand). Keeping the name confuses
players, steals search oxygen, and looks hostile. The owner of this repository
wants a distinct brand for the private authoritative server / studio platform.

## Decision

1. **Rename** the public brand, site title, launcher strings, and eventually
   crate prefixes / binary package names.
2. Until the new name is locked, docs say “this project” in legal/public
   surfaces and keep technical paths as-is to avoid a half-renamed tree.
3. Shortlist criteria: not Amazon/New World trademarks; not another live fan
   brand; pronounceable; available domain + GitHub org; fits “private world /
   preservation” without sounding like a cheat tool.
4. One cutover PR (or sequenced PR train) after the name lock — no drip-feed
   half renames across weeks.

## Name shortlist (candidates only — pick later)

| Candidate | Notes |
| --- | --- |
| **Aeternum Keep** | Evokes the setting; check trademark conflict |
| **First Ember** | Distinct from “First Light” if that brand is active |
| **Nighthaven OS** | Seasonal nod; may age poorly after Nighthaven |
| **RepForge** | Protocol-nerd; weak player brand |
| **Havenward** | Neutral preservation vibe |

Do **not** ship marketing under a shortlist entry until domain + conflict
search completes.

## Consequences

- NOTICE and LEGAL already disclaim the collision.
- `azoth-*` crates and `.azoth/` state dir rename in the cutover (state dir may
  keep a compatibility junction once).
- Public roadmap / landing copy waits for the name lock where possible.

## Alternatives considered

- Keep Azoth and “differentiate in subtitle” — rejected; collision is real.
- Random empty syllable brand — allowed if shortlist fails conflict checks.
