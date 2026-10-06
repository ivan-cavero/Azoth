---
name: azoth-server
description: Design or implement Azoth's world server, protocol behavior, Rust port, or scalable game-content runtime.
---

# Azoth server development

Use this skill for server-side behavior, protocol implementation, backend
language ports, content support, or capacity work.

- Read `STATUS.md`, `services/docs/WORLD.md`, the relevant protocol document,
  and the matching facts in `research/atlas/` before changing behavior.
- Keep the server faithful to the observed New World client contract. Add a
  route, packet, field, state transition, or game rule only when evidence or a
  concrete supported feature requires it.
- Treat Python as the current protocol prototype. Port to Rust incrementally
  after a behavior is understood and can be compared against captured fixtures
  or a live private-client result. Preserve wire compatibility across ports.
- The operational goal is 2,500 concurrent players per world server first,
  with 10,000 as the capacity target. Do not describe either as achieved until
  a representative load test records hardware, traffic mix, duration, tick
  deadlines, bandwidth, CPU, memory, allocations, and reconnect results.
- Keep decompilers, Frida probes, packet capture, admin controls, and operator
  workflows outside the production server binary. The runtime should contain
  only protocol, game-domain behavior, authored content, and ordinary
  observability needed to operate it.
- Classify new content before implementation: data the shipped client already
  understands can be authored and validated as data; new gameplay behavior
  needs server support; a capability the client cannot represent also needs a
  client-side change. Preserve stable content IDs and source-to-runtime
  validation when a content pipeline is introduced.
- Optimize from the measured packet and simulation hot paths. Prefer bounded
  per-connection state and explicit entity-interest filtering; introduce
  sharding or shared infrastructure only after a benchmark identifies the
  process boundary as the limit.
- At the end of a protocol experiment, record the winning request/response,
  why it works, its state effects, and the deciding evidence. Keep that single
  behavior in the server; remove rejected response branches and temporary
  fallbacks. Preserve rejected observations as atlas evidence, not executable
  server paths.
