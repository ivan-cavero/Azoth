# 0002. Roadmap three-layer model

Date: 2026-10-24
Status: accepted

## Context

`site/src/data/roadmap-full.ts` (v1) mixes a useful client-surface inventory
with a public narrative still framed around the Python/replay era. It does not
scale as both engineering tracker and landing-page story.

## Decision

Three layers:

1. **Gates** — few stable phases in `docs/PLAN-master-platform.md` / short
   `docs/ROADMAP.md`.
2. **Work graph** — many machine-oriented nodes (issues / future
   `research/atlas/work/`); not shown raw on the landing page.
3. **Public display** — curated eras E0–E5 in `site/src/data/roadmap-v2.ts`
   (served after cutover); v1 archived as input, not deleted.

`done` on the public layer still requires authentic evidence per `site/README.md`.

## Consequences

- Landing page stops looking like a facet dump.
- Agents update the work graph freely; public sync is gated.
- Facet/content backlog from v1 survives as work-graph fuel for playable eras.

## Alternatives considered

- Keep growing v1 in place — rejected; agent and visitor confusion.
- Single merged tracker — rejected; public `done` discipline would erode.
