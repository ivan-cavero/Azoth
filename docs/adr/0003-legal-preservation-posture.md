# 0003. Legal preservation posture

Date: 2026-10-24
Status: accepted

## Context

Amazon Games will take New World: Aeternum offline on **2027-01-31** (delisted
2026-01-15). This repository builds a private, protocol-compatible server so
owners of the client can keep playing. Fan servers sit in a real legal grey
area (copyright, EULA, anti-circumvention). Contributors need clear defaults
before the repo is chaotic or publicly marketed.

## Decision

1. Ship **LEGAL.md**, **NOTICE**, and **CONTRIBUTING.md** describing an
   unofficial, preservation-oriented, **no-asset-in-git**, non-commercial-
   by-default posture.
2. Treat clean-room / original server code + observed protocol as the only
   acceptable implementation path in this repo.
3. Prefer dialogue with the rights-holder for a sanctioned path; log attempts;
   never claim endorsement without a written grant.
4. Defer monetization and public GitHub until policy + scrub gates pass.

## Consequences

- Agents and humans have a single place to point when asked “is this legal?”
  (honesty: we state posture, not a guarantee).
- Releases must never grow into asset mirrors.
- Marketing copy on `site/` must stay unofficial and rename-aware.

## Alternatives considered

- Ignore legal docs until launch — rejected; collaboration and public site
  need them first.
- Claim “abandonware” / orphan-work status — rejected; copyright does not
  vanish at shutdown.
- Distribute client PAKs for convenience — rejected; high infringement risk.
