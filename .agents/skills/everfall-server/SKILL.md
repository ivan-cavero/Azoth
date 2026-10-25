---
name: everfall-server
description: >-
  Create or extend the Everfall Rust server after a meaning card names the
  fields. Use when adding server crates, the world tick, DTLS, or authoritative
  gameplay. Refuses the work while fields are unknown.
---

# Server

Load `rust`, `protocols`, and `security` before writing code.

If `research/atlas/meanings.md` still marks the fields unknown, stop and use `everfall-meaning`. Do not recreate the deleted byte ladder.

## Shape

- `everfall-sim`: state and rules. No sockets, no files, no capture import.
- `everfall-wire`: encode and decode named fields only.
- `everfall-net`: DTLS and UDP. OpenSSL stays here. Handshake off the 50 Hz tick.
- One world binary calls sim, then wire, then the socket.
- Channel and region HTTP stay in Python until their bodies are named the same way.

Unnamed bytes live only in a transformer crate. Each one has an id from the meanings file. Sim does not depend on that crate.

The stock client is the acceptance test. A patched client is a second explicit protocol, not a way around an unknown field.
