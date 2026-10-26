# Client probes: read this before trusting a capture

These scripts attach Frida to the private `NewWorld.exe` and hook hardcoded virtual
addresses. **A VA only means something for the build it was derived on.**

## The failure mode this warning exists for

`Interceptor.attach` succeeds on **any** address. Hooking a stale VA does not raise,
does not log, and does not fail to attach: the hooks fire, the events arrive, and the
capture file is written. It looks exactly like a successful measurement of the wrong
code.

Measured 2026-10-26 on build `30fe6461` (1.460): the three VAs
`frida-fragment-grammar.py` was built against were derived on `8654f01d` (1.400). At
`0x14087b5c0` the 1.460 exe holds `0f 16 da 0f 28 c3 …` — `movhps`/`movaps`/`mulps`
SIMD arithmetic, not the varint branch ladder those hooks assume.

## The rule

A probe that hooks a VA must declare the build it was derived on and call the guard:

```python
from _paths import probe_capture, require_build, safe_shutdown

PROBE_BUILD_SHA256 = "<sha256 of private-client/runtime/Bin64/NewWorld.exe>"
...
require_build(PROBE_BUILD_SHA256, "my-probe")
```

`require_build` hashes the exe the launcher would actually run — the **private copy**,
not the Steam install, because the copy differs by the DTLS bypass and its hash is the
only one that describes the running code. It fails closed on three states: a different
build, an unreadable exe, and a probe that declares no build at all.

The guard is `reverse/probes/client/_paths.py::require_build`;
`reverse/tools/tests/test_probe_build_guard.py` pins its behaviour.

## Status of the existing probes

**One of 128 probes carries a guard as of 2026-10-26.** Everything else was written
between 2026-10 and 2026-10-25 against 1.400 (`8654f01d`), so:

- A capture taken **before 2026-10-26** is valid for the build it was taken on. Do not
  discard it; do not read it as describing 1.460.
- Running any of those probes **today** on the 1.460 lab will attach happily and
  measure whatever now lives at those addresses. The result is not interpretable.

The honest position is that these are historical instruments. Reviving one is two
steps: re-derive its VAs against the target build, then record that build's runtime
SHA-256 in `PROBE_BUILD_SHA256`.

## Builds

| Role | SHA-256 | Version |
| --- | --- | --- |
| Static-analysis target (Steam install) | `30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033` | `1.460.6033.6024067` |
| Private copy the launcher runs | `97f17df315aef97bed1303bb9d57330be67e9e0c9e22acb59dde68de837b743c` | same + DTLS bypass at `0x145DCF9F5` |
| Previous build (all pre-2026-10-26 probes) | `8654f01d324636d9f74f1c793b0cc4a417c3c5fa9847d9913c358ca29e0fdc8e` | `1.400.6031.6004151` |

Never decompile the private copy: its VAs belong to whichever build it is. Static
analysis reads the Steam install.

## Shutdown

Use `safe_shutdown` from `_paths`. A bare `session.detach()` after hooking a hot
function was measured to kill the client minutes later with an
execute-after-unload fault (`frida-agent.dll_unloaded` at `0x9c7e0`), and that has
been mistaken for a client bug twice. See the module docstring in `_paths.py`.
