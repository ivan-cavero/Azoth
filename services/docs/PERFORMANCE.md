# Performance — Azoth world process

Official New World lagged with **fewer** players than the design sheet claimed (~2500 + 7000 AI, 7 hubs, DynamoDB). Towns felt worse than empty woods: **density**, not just CCU, is what melted the tick.

Azoth optimizes for **many players close together** on one shard, then scales instances out. We do not copy Amazon's 7-hub + DynamoDB hot path.

## Targets (honest)

| Horizon | What “good” means |
| --- | --- |
| Fase 2 | 1 frozen spawn. No FPS claim. |
| Fase 3 | 1 moving player, client 60 fps, server tick p99 **< 8 ms** idle. |
| Fase 4 | **200** players in one settlement cell, tick p99 **< 16 ms**, **< 80 KB/s** down per client. |
| Later | 1 process: 1500–2500 CCU if AOI holds. More CCU = more **processes** (instances), not a bigger tick. |

KPI that matters: **players in one interest neighborhood**, not world population.

## Hard rules

1. **One sim thread.** The tick never waits on Postgres, DNS, disk, or TLS. Network I/O is other threads; the sim only drains a lock-free input queue.
2. **Fixed tick 30 Hz** (33.3 ms budget). Combat can subsample; do not run PhysX-complete every tick.
3. **No GC on the tick.** World is Rust. Gateway Python is off the hot path (login only).
4. **Do not replicate the map.** Coatlicue props stay on the client. Replicate living actors: players, AI, stateful gatherables, projectiles.
5. **AOI first.** Grid cells (the official world is already a grid). A client gets its cell + neighbors. Idle players far away: transform only (LOD). In combat: full replica budget.
6. **Unreliable for movement, reliable for inventory / combat events / quests.**
7. **Write-behind persistence.** Snapshots async. A crash may lose ≤ N seconds of position; never stall the tick.
8. **Instances are other processes.** A dungeon must not steal open-world tick time. Expedition = spawn a world worker, move the player (new `RepAddress` or instance id).

## Why official lagged (what we will not copy)

- Hub **handoff** at cell borders (actor migration between 7 EC2 boxes).
- **DynamoDB on the simulation path** (~800k writes / 30s at launch scale).
- Replicating too much (static world + every AI) into crowded towns.
- One fat interest radius for everyone.

Azoth: stay on **one process** until the tick is proven. Split by **instance** (dungeon/OPR), not by map tile, until we measure a real ceiling.

## Budget per tick (Fase 4 sketch)

```
33 ms total
  drain inputs          < 1 ms
  integrate movers      < 4 ms   (SoA transforms, no hashmap in inner loop)
  combat/AI nearby      < 6 ms   (only active cells)
  interest + serialize  < 4 ms
  slack                 rest     (if p99 > 16 ms under 200 clustered: cut AOI, not “add Redis”)
```

Metrics the world process must export from day 1 of movement: `tick_ms_p50/p99`, `replicas_per_client`, `bytes_out_per_client_s`, `actors_in_cell`, `queue_depth`.

## Language

Rust + openssl DTLS for world. Python gateway is allowed to be slow; nobody fights on HTTP. If openssl DTLS is the bottleneck, measure before rewriting — serialization and AOI will dominate first.
