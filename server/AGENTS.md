# server/ agent notes

Rust authoritative runtime. Root [`AGENTS.md`](../AGENTS.md) still applies.

## Layout

| Path | Owns |
| --- | --- |
| `apps/channeld` | Platform HTTP |
| `apps/regiond` | Discovery, tickets, placement |
| `apps/worldd` | DTLS + REP + tick; **no replay pump** (public binary name → `world`, ADR 0006) |
| `crates/azoth-wire` | Codecs only |
| `crates/azoth-session` / `azoth-dtls` | Transport lifecycle |
| `crates/azoth-model` | Domain identities / transforms (no I/O) |
| `crates/azoth-commands` | Typed ops commands + RBAC (`worldd::ops`) |
| `crates/azoth-privacy` | Default-deny profile visibility (`regiond::privacy_gate`) |
| Future `azoth-sim` / `azoth-replica` | Sim + AOI (see PLAN-backend-rust) |

## Rules

- Prefer `azoth-model` domain types over raw string/`f32` soup in app code; offsets belong in wire + ontology.
- Every ladder/outbound path should name an ontology uid (see `ladder::Step::ontology_uid`).
- Captured templates are seeds with provenance — not the long-term game; replace with composed domain state when layouts are known.
- No `std::env::var` outside a crate `config` module.
- Parity: fixtures and tests under each crate; do not invent fields without evidence.
- Keep Frida/Ghidra/admin out of production binaries.
- Mechanics plan: [`docs/PLAN-backend-rust.md`](../docs/PLAN-backend-rust.md).
- DTLS crypto: OpenSSL only inside `azoth-dtls` ([ADR 0004](../docs/adr/0004-dtls-crypto-stack.md)).

## OpenSSL on Windows (clone-anywhere)

Pick **one** toolchain and stick to it for the machine:

- **MSVC + vcpkg** (preferred for MSVC `rustc`): install `openssl:x64-windows`,
  set `VCPKG_ROOT`, let `openssl-sys` find it; or set `OPENSSL_DIR`.
- **MSYS2 MinGW**: only if `rustc` itself is the GNU/MinGW target — do **not**
  mix MinGW `libssl` into an MSVC-built `worldd` (link errors / exit 101).

Avoid `openssl/vendored` for daily `cargo test` on Windows (very slow). Docker
release images may static-link once. Measure PPS before chasing OpenSSL
version pins.

## Commands

```text
cd server
cargo test -p azoth-wire
cargo test -p azoth-model
cargo test -p worldd
cargo xtask check   # when available
```
