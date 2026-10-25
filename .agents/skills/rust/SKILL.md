---
name: rust
description: >-
  Everfall Rust rules for an authoritative game server: crate boundaries,
  errors, the 50 Hz tick, mutation, and unsafe. Use when writing or reviewing
  any Rust, Cargo.toml, or server crate, including the day server/ is recreated.
  Load rust-best-practices with it; this file decides where they disagree.
paths:
  - "**/*.rs"
  - "**/Cargo.toml"
---

# Rust

Load this before any `.rs` edit. Also load `everfall-server` if the change adds a crate, and `protocols` if the change encodes a client message. The long checklist is [reference.md](references/REFERENCE.md).

There is no `server/` tree until a row in `research/atlas/meanings.md` names the fields. This skill does not authorize creating that tree.

## Precedence

Three sources meet on a `.rs` file, and they are not equal.

| Order | Source | Covers |
| --- | --- | --- |
| 1 | This file, `everfall-server`, `protocols`, `docs/PLAN.md` | What the server is allowed to do: meaning cards, crate boundaries, the 20 ms tick, OpenSSL in one crate, tickets, no token in a log |
| 2 | `rust-best-practices` | How to write the Rust that does it: API shape, derives, error types, doc sections, iterator idiom |
| 3 | `rust-review` | How to report on it: a prioritized report, never a rewrite |

Where 2 and 3 contradict 1, 1 wins and the contradiction is worth a line in
`references/REFERENCE.md` so the next agent does not re-derive it. A rule from 2
is a default for what 1 does not say, never a reason to add a field, a crate, or
a dependency that 1 withholds.

Two upstream defaults are already overruled for this project, in
[`lints/lints.toml`](lints/lints.toml): `as_conversions` is allowed because a
codec is byte-offset arithmetic, and `print_stdout` is allowed because `worldd`
diagnostics and `xtask` are operator-facing binaries. `missing_errors_doc` and
`missing_panics_doc` are allowed because the deleted tree carried 179 `expect()`
calls in `src/`, and a `# Panics` section on each one is noise.

The review skill owes two answers upstream does not know about: does every
encoded field have a name in `research/atlas/meanings.md`, and does the change
keep I/O out of the simulation crate. A report that skips them is incomplete.

## Boundaries

| Crate | May do | Must not |
| --- | --- | --- |
| `everfall-sim` | Own state. Mutate it on the tick. Decide if an action is legal. | Open a socket, read a file, import a capture, encode bytes |
| `everfall-wire` | Encode and decode named fields | Decide game rules |
| `everfall-net` | DTLS, UDP, handshake | Run game rules. OpenSSL stays in this crate |
| world binary | Call sim, then wire, then the socket | Embed an unexplained byte string |

Handshake and crypto run off the 50 Hz tick. A player joining must not spend the 20 ms budget.

## Language bar

- Mutation is required. The simulation updates structs in place. Do not wrap the world in clones to look pure.
- `Result` for anything that can fail at runtime. `unwrap` and `expect` only in tests and in `main` after a message that tells the operator what broke.
- No `unsafe` without a comment that says the invariant and why safe Rust cannot hold it.
- Crates added in the change deny clippy warnings.
- No `std::env` outside the binary's config module.
- Log with the tracing-style fields this repo grows into. Never log a token, a ticket, or a private key.
- A public function's name is the comment. Keep a comment only for a measured number (chunk size, tick, crash).

## Tests

A gameplay test states the fact: this message tells the client a named thing. Byte equality against a capture belongs only in the capture-transformer crate, and the test names the capture file and the client SHA-256.

## Before you finish

- [ ] Sim has no I/O import
- [ ] Every encoded field is named in `research/atlas/meanings.md`
- [ ] The tick function does not perform a handshake
- [ ] `cargo test` for the crates you touched is green
- [ ] `cargo clippy --all-targets --all-features -- -D warnings` is green under
      [`lints/`](lints/), not under a `#[allow]` written to get past it
