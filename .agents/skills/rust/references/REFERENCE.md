# Rust reference

Project rules, not a language tour. Read this when the `SKILL.md` checklist is not enough.

## Errors

Libraries return `Result<T, E>` with a small error enum. The binary maps that to a log line and a non-zero exit. Do not `unwrap` a parse failure on a client datagram. A bad datagram is a disconnect or a counter, chosen in the skill for that message, not a panic that kills the other players.

`?` crosses a function only when the error type already means the same failure. Do not use `Box<dyn Error>` inside sim.

## Ownership on the tick

The world owns player state. Systems take `&mut World` or a narrower `&mut` of the component they change. They do not return a fresh copy of the world.

Reuse buffers across ticks: one scratch `Vec<u8>` per connection for the outgoing datagram, cleared, not reallocated, when the size stays in the same band. Measure before introducing a pool, an arena, or a lock-free queue.

Share immutable data with `Arc` when many tasks read it (config, a static table). Do not put `Mutex` around the whole world so a socket thread can poke it. The socket thread sends an event. The tick mutates.

## Channels

Bounded channels between the socket thread and the tick. If the tick's outbound channel is full, count the drop or the coalesce. An unbounded channel is a leak under a slow client.

## Types

Newtypes for ids the game can mix up: account, character, actor, territory. Do not pass bare `u64` through sim for all of them.

`f32` transforms stay in one component. Do not let wire code invent a coordinate system. Wire copies numbers sim already decided.

Invalid states are enums. A player is connecting, loading, or in the world. Do not use a pile of booleans that can all be true.

## Performance

Order of work:

1. Make the tick do the right state change.
2. Measure tick time and bytes per player on a fixed scene.
3. Then change a data structure, with the number in the commit message.

Interest first: do not serialize an actor for a viewer who cannot see them. Serialize after the set is known.

Do not parse the same datagram twice. Decode at the edge into a sim event.

## What the deleted server got wrong

It compiled captured bodies into the binary and sent them because the capture contained them. Self-identification was 21 zero bytes. Level info left 26 bytes unnamed. Spawn was 46,393 captured bytes. Do not restore that shape. A transformer crate may hold those bytes only with an id from the meanings file, and that set must not grow.

## Dependencies

Prefer the standard library. Add a crate only when the user agrees. Pin it in the workspace `Cargo.toml`. Do not turn on `openssl/vendored` for day-to-day tests. OpenSSL is linked from the system and called only inside `everfall-net`.
