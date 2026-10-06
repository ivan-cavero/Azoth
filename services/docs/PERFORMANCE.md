# Performance

The capacity objective is 2,500 concurrent players per server for the first
public scale and 10,000 per server as the design target. These are requirements
to validate, not claims about the current world server. The current process is
still a protocol and client-behavior prototype; it does not yet run a complete
movement simulation.

Do not optimize an imagined MMO workload. Once one local player moves, collect
a baseline for:

- tick duration and missed deadlines;
- allocations in packet handling and simulation;
- bytes sent per client and active entities per update;
- CPU and memory under a representative clustered-player workload.

Keep those numbers as explicit load-test gates. Before any capacity claim,
replay representative client traffic and simulated players at 2,500 and 10,000
while measuring tick deadlines, per-client bandwidth, entity fan-out, CPU,
memory, allocations, and reconnect behavior. Record hardware, client mix,
duration, and pass thresholds with each result.

The Rust world service should preserve the verified New World wire contract and
include only runtime behavior required to serve that contract and authored
gameplay. Keep decompilation, packet capture, operator probes, admin consoles,
and test-only instrumentation outside the production server binary. Begin with
one measured server process; use bounded per-connection state and explicit
interest filtering before adding sharding or shared infrastructure. The
current Python service remains the protocol prototype until movement works and
benchmarks show which components need replacement. Gateway HTTP is outside the
simulation hot path.
