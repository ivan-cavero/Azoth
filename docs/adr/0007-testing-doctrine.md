# 0007. Testing doctrine — scenarios over decoration

Date: 2026-10-24
Status: accepted

## Context

The project needs confidence for a protocol-compatible MMORPG server, web
dashboards, and contributor onboarding. Classic “unit test every function”
produces noise and still misses the failures that burn us (handshake, ticket
lifecycle, ladder order, privacy denies, chunking).

## Decision

1. Prefer **scenario / integration / e2e** tests that encode a real failure
   mode or player-visible outcome.
2. Use **property tests** (`proptest`) for codecs and invariants.
3. Use **Criterion** for hot-path benches; publish hardware records for
   capacity claims.
4. Web: Vitest for pure logic; **Playwright** for critical user journeys;
   assert observable UI, not internals.
5. Default CI is offline and deterministic; live client / network tests are
   opt-in (`#[ignore]`, `az test e2e`, nightly).
6. Reject PRs whose only new tests assert trivial getters with no error path.

## Consequences

- Fewer tests, higher signal.
- Harness investment (`az test e2e`, fixtures) is first-class work.
- Coverage % is a ratchet on domain crates, not a vanity metric.

## Alternatives considered

- 90% line-coverage mandate — rejected; farms noise.
- Only manual playtests — rejected; does not scale to contributors/CI.
