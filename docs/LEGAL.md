# Legal & community posture

**This is not legal advice.** It records how this project intends to behave so
contributors and operators stay aligned. Rights-holder enforcement and local
law can still apply. When in doubt, talk to a lawyer before publishing,
monetizing, or distributing binaries at scale.

## Why this project exists

Amazon Games announced that **New World: Aeternum** is delisted and that
official servers will be **taken offline on 2027-01-31** (announcement dated
2026-01-15):

https://www.newworld.com/en-us/news/articles/the-future-of-new-world-aeternum-what-to-expect

This repository is a **fan preservation / private-server** effort: an
independent, protocol-compatible world stack so people who already own the
client can keep playing on infrastructure they control after the official
service ends. It is **not** affiliated with, endorsed by, or sponsored by
Amazon, Amazon Games, or New World.

## Hard rules for this repository

1. **Do not commit New World client assets** (PAKs, audio, textures, shipped
   binaries, Steam trees). Players use a client they obtained lawfully.
2. **Do not commit Amazon server binaries or leaked server source.** Our
   server code is original work that speaks the observed wire protocol.
3. **Do not redistribute copyrighted game content** through GitHub releases,
   Discord bots, or “easy install” packs that include PAKs.
4. **Label the project unofficial** on any public surface (site, launcher,
   README hero). Never use Amazon logos or imply official status.
5. **Default non-commercial** until an entity, counsel, and written policy
   say otherwise. Ops cost recovery must be designed, not improvised.
6. **Secrets and raw captures stay private** (`research/sessions/`, ignored
   paths). Public evidence is curated and scrubbed.
7. **Respect other community projects.** This repo’s historical working name
   collides with [Azoth Central](https://projectazoth.com/); a rename is in
   progress ([ADR 0005](adr/0005-project-rename.md)). Do not impersonate them
   either.

## Collaboration

See [`CONTRIBUTING.md`](../CONTRIBUTING.md). Short version:

- You only submit material you have the right to submit (code, docs, captures
  you recorded, original art under a stated license).
- Captures of network traffic may contain session tokens — scrub before
  sharing; prefer atlas summaries over raw dumps in PRs.
- By contributing you agree your original code/docs may be relicensed with
  the project when a public license is chosen (today: see repo `LICENSE` if
  present; otherwise “all rights reserved / pending open-source license”).

## Operator responsibilities

If you run a public or semi-public world:

- You are responsible for ToS/EULA risk in your jurisdiction.
- You must not claim to be Amazon.
- You must not host or hotlink copyrighted asset mirrors from this project.
- You should be ready to take the service down if a rights-holder demands it.

## Seeking a better path

The cleanest long-term outcome is a **publisher-sanctioned** community server
or code hand-off. Attempts to open that conversation should be logged in
`docs/journal/` (dates, who was contacted, outcome) — never spun as “Amazon
approved us” without a written grant.

## Related

| Doc | Role |
| --- | --- |
| [`NOTICE`](../NOTICE) | Short trademark / affiliation notice |
| [`SECURITY.md`](SECURITY.md) | Threat model & privacy |
| [ADR 0003](adr/0003-legal-preservation-posture.md) | Decision record |
| Master plan §0A | Product framing of the same rules |
