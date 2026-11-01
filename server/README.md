# everfall-wire — build and test

`server/` is the Everfall Cargo workspace. `everfall-wire` encodes and decodes
the named fields of the entry bodies the server must send (`0x3`, `0x663`,
`0x65c`). `everfall-net` owns DTLS and links OpenSSL (see below).

## Prerequisites

1. **Pinned toolchain** — `rust-toolchain.toml` pins `1.98.0` for
   `x86_64-pc-windows-msvc`, with `rustfmt` and `clippy`. rustup installs it on
   the first `cargo` call.
2. **Windows SDK** — an `x86_64-pc-windows-msvc` link needs the Windows API
   import libraries (`kernel32.lib`, `ntdll.lib`, `ucrt.lib`, `userenv.lib`,
   `ws2_32.lib`, `dbghelp.lib`). Install the Windows 10/11 SDK with its **Lib**
   component (Visual Studio "Desktop development with C++"). The CRT libraries
   (`msvcrt.lib`, `vcruntime.lib`) come from the MSVC toolset that `windows-msvc`
   already requires.
3. **OpenSSL development package** — required by `everfall-net` only. Install
   the 64-bit OpenSSL development package (e.g. `winget install
   ShiningLight.OpenSSL.Dev`); the crate links it instead of building OpenSSL
   from source. `server/.cargo/config.toml` points `openssl-sys` at it with
   `OPENSSL_DIR`, `OPENSSL_LIB_DIR` and `OPENSSL_INCLUDE_DIR`. If the package is
   installed elsewhere or at a different version, update those three paths.

## Tests

```text
cd server
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

`cargo clippy` and `cargo fmt --check` do not link; they run on any machine with
the pinned toolchain. `cargo test` links a Windows executable and requires the
Windows SDK above.

## Linker

`server/.cargo/config.toml` selects `linker = "rust-lld"`. `rust-lld.exe` ships
inside the pinned toolchain, so the link step is independent of `PATH` and does
not depend on which `link.exe` is found first.

With the Windows SDK installed, a fresh checkout runs all three commands in a
plain shell with no environment variables set.
