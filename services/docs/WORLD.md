# World server

The implementation and operating details live in
[`services/world/README.md`](../world/README.md), next to the server code. That
file is the single service reference for startup, DTLS logs, replay settings,
and dependencies.

Current project blocker: the client loads the world and possesses the local
player, but the player has no physics components. See [live status](../../STATUS.md)
and the [world investigation](../../research/docs/WORLD-INVESTIGATION.md).

The [performance document](PERFORMANCE.md) contains future measurement targets;
they are not implemented guarantees for the current stub.
