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

- **Preferred here:** `rustup default stable-x86_64-pc-windows-gnu` + MSYS2
  `C:\msys64\mingw64` OpenSSL. Always:
  `python az.py cargo test -p azoth-dtls` (strips WinLibs from PATH; sets
  `OPENSSL_DIR` + GNU linker). Bare `cargo` often fails by mixing WinLibs gcc
  with MSYS crt/libs — that is not “OpenSSL broken.”
- **MSVC + vcpkg:** needs `link.exe` (VS Build Tools) + `openssl:x64-windows`.
  Do **not** point `OPENSSL_DIR` at MinGW.

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
