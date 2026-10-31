# everfall-wire — build and test

`server/` is the Everfall Cargo workspace, one crate: `everfall-wire`. The crate
encodes and decodes the named fields of the entry bodies the server must send
(`0x3`, `0x663`, `0x65c`).

## Pinned toolchain

`rust-toolchain.toml` pins `1.98.0` for `x86_64-pc-windows-msvc`, with `rustfmt`
and `clippy`. rustup installs it on the first `cargo` call.

## Tests

```text
cd server
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

`cargo clippy` and `cargo fmt --check` do not link; they run on any machine with
the pinned toolchain. `cargo test` links a Windows executable, and that is where
this machine is special.

## Linker and SDK situation

An `x86_64-pc-windows-msvc` link needs two input sets:

1. **CRT** — `msvcrt.lib`, `vcruntime.lib`, `libcmt.lib`. These ship with the
   MSVC toolset, which `windows-msvc` already requires. Installed here:
   `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231\lib\x64`.
2. **Windows API import libraries** — `kernel32.lib`, `ucrt.lib`, `ntdll.lib`,
   `userenv.lib`, `ws2_32.lib`, `dbghelp.lib`. These ship with the **Windows
   SDK**. This machine has no Windows SDK: `C:\Program Files (x86)\Windows Kits`
   does not exist, a search for `kernel32.lib` under Visual Studio finds nothing,
   and the real MSVC `link.exe` fails `LNK1181: cannot open input file
   'kernel32.lib'`.

`server/.cargo/config.toml` selects `linker = "rust-lld"`. `rust-lld.exe` ships
inside the pinned toolchain, so the link step is independent of `PATH`; that also
dodges the trap here, where Git for Windows' `link.exe` shadows the MSVC linker.
Choosing the linker does not change what it searches: rust-lld still needs both
input sets on `LIB`.

### The Rust toolchain cannot produce the API import set

The pinned toolchain ships no Windows import libraries. The only `*.lib` under
`~/.rustup/toolchains` are the five `std-<hash>.dll.lib` for the dylib `std`.
`rust-lld` cannot take a `.dll` in place of an import library — it answers
`bad file type. Did you specify a DLL instead of an import library?` — and it
does not fall back from `kernel32.lib` to `kernel32.dll` or `libkernel32.a`.
So the Windows API import set must come from the Windows SDK, or from the
third-party provider below.

### The shim this machine uses

Without the SDK, the API import set is taken from an **LLVM-MinGW** install
(WinGet package `MartinStorsjo.LLVM-MinGW.UCRT`). The files under
`target/sdk-shim/` are byte-identical (md5) to that install's import libraries:

| `target/sdk-shim/` | LLVM-MinGW source |
| --- | --- |
| `kernel32.lib` | `x86_64-w64-mingw32/lib/libkernel32.a` |
| `ucrt.lib` | `x86_64-w64-mingw32/lib/libucrt.a` |
| `ntdll.lib` | `x86_64-w64-mingw32/lib/libntdll.a` |
| `userenv.lib` | `x86_64-w64-mingw32/lib/libuserenv.a` |
| `ws2_32.lib` | `x86_64-w64-mingw32/lib/libws2_32.a` |
| `dbghelp.lib` | `x86_64-w64-mingw32/lib/libdbghelp.a` |
| `advapi32.lib` | `x86_64-w64-mingw32/lib/libadvapi32.a` |

`**/target/` is gitignored, so nothing under `target/sdk-shim/` is committed.
`scripts/make-sdk-shim.ps1` reproduces the directory from an LLVM-MinGW root and
prints the `LIB` value (shim + MSVC CRT) the link needs:

```text
powershell -ExecutionPolicy Bypass -File server\scripts\make-sdk-shim.ps1 -EmitLib
```

## Can a fresh checkout run the tests?

- `cargo fmt --check` and `cargo clippy --all-targets -- -D warnings`: yes.
- `cargo test`: no, not on a machine without the Windows SDK. Clean shell:

```text
$ cargo test
error: linking with `rust-lld` failed: exit code: 1
  = note: rust-lld: error: could not open 'kernel32.lib': no such file or directory
          rust-lld: error: could not open 'ntdll.lib': no such file or directory
          ...
```

The one blocking component is the **Windows SDK import libraries**. Install the
Windows 10/11 SDK (Visual Studio "Desktop development with C++") and put its
`Lib\um\x64` and `Lib\ucrt\x64` on `LIB`, alongside the MSVC `lib\x64`; rustc
does not discover those directories by itself here (an explicit `link.exe` probe
still fails `LNK1181: cannot open input file 'kernel32.lib'`). The LLVM-MinGW
shim is this machine's substitute for that install, not a replacement for the
toolchain.
