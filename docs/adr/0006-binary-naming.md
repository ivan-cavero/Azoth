# 0006. Process binary naming (`worldd` → `world`)

Date: 2026-10-24
Status: accepted

## Context

Unix daemons often use a trailing `d` (`sshd`, `httpd`). This repo used
`worldd`, `channeld`, `regiond`, `opsd`. “worldd” reads as a stutter (world +
d) and feels odd for a game server people will type and document. The master
plan already sketches public names without the suffix in the deploy diagram.

## Decision

1. **Published / CLI names:** `world`, `region`, `channel`, `ops`.
2. **Cargo package names** may keep the `*d` suffix until the project rename
   cutover (ADR 0005) to avoid churn in `Cargo.toml` + docs mid-flight.
3. `az.py` / compose / k8s manifests should prefer the public names once
   aliases exist (`[[bin]] name = "world"` or install-time rename).
4. Docs written from this ADR onward say **world process** or `` `world` ``
   when speaking to operators; `worldd` is the current crate id.

## Consequences

- Operators get short, obvious commands.
- One aliasing step in packaging; no behaviour change.
- Rename-of-brand PR can also rename crates `azoth-world` etc.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep `worldd` forever | Owner dislike; awkward in speech |
| `azw` / cryptic short names | Hostile to newcomers |
| `gameserver` | Too generic; collides everywhere |
