# World server

The implementation and operating details live in
[`services/world/README.md`](../world/README.md), next to the server code. That
file is the single service reference for startup, DTLS logs, replay settings,
and dependencies.

Current blockers: REP transport can remain up for hours, but the client still
shows a red ALC/HUD connection warning; the ALC door stays closed and its input
stamp stops updating. The local player entity was re-measured with both
`CharacterPhysicsComponent` and `GameRigidBodyComponent`, so component absence is
not the diagnosis. Movement remains unproven: the player transform has not been
shown to change, and reliable position message 4216 currently fails facet-target
dispatch. See [live status](../../STATUS.md), the
[world investigation](../../research/docs/WORLD-INVESTIGATION.md), and the
[ordered work plan](../../docs/ROADMAP.md).

The [performance document](PERFORMANCE.md) contains future measurement targets;
they are not implemented guarantees for the current stub.
