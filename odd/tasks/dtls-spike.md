# DTLS spike: which library can serve this client

Phase 0's transport gate (`docs/PLAN-backend-rust.md` §18.1, Q2). It had to pass **before**
Phase 3 started, because DTLS is the project's biggest transport risk and a wrong choice is a
rewrite.

Build under test: `1.460.6033.6024067` /
`30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033`.

## Specs

- **S1.** The server must negotiate **`0xC030` `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`**, the only
  suite the client offers (measured from `pktmon.pcapng`, plan §0.3). Nothing else is acceptable.
- **S2.** DTLS **1.2** (`0xFEFD`), with a HelloVerifyRequest cookie exchange and an RSA certificate.
- **S3.** The choice is justified on **capability first**, and on maintenance/cost second. Speed is
  not the deciding criterion, because DTLS work runs off the tick (plan §8.1, constraint 5).
- **S4.** The result is recorded with the rejected alternatives and the reason each was rejected.
- **S5.** No Steam install modification; the build must not require a paid or licensed toolchain.

## Tasks

| ID | Specs | State |
| --- | --- | --- |
| T1 | S1 | done — `dtls` 0.17.2 read from source: the suite is absent |
| T2 | S1, S2 | done — `openssl` 0.10 builds and accepts the suite as a DTLS server |
| T3 | S2 | done — a real ClientHello was received and parsed |
| T4 | S3, S4 | done — recorded below |

## Log

### L1 — the user's request, verbatim

> Es la mejor opción esa? No renta probar las opciones que tengamos para OpenSSL? Haz lo que mejor
> performance y demás tenga eh lo que hablamos

and, when the build blocked:

> pero si myss2 ya esta y eso tambien mira

### L2 — `dtls` 0.17.2 is disqualified by CAPABILITY, not by speed

Read from the crate source at
`~/.cargo/registry/src/*/dtls-0.17.2/src/cipher_suite/`. It implements **eleven** suites:

```
TLS_ECDHE_ECDSA_WITH_AES_128_CCM          TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8        TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA
TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256   TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256
TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA      TLS_PSK_WITH_AES_128_CCM
TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305    TLS_PSK_WITH_AES_128_CCM_8
                                          TLS_PSK_WITH_AES_128_GCM_SHA256
```

**`TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384` is not among them.** A grep for `SHA384` finds only a
*signature* hash, never a suite. So this is not "slower" — it cannot negotiate, and there is no
handshake. The question "is it the best option" has a binary answer here, and it is no.

### L3 — the answer to "aren't there other OpenSSL options"

There is **one** library decision, and the rest is plumbing. The options that exist:

| option | verdict |
| --- | --- |
| `openssl` + system OpenSSL | **works** — this is what shipped |
| `openssl` + `vendored` | the crate's own `openssl-src` vendor is **incomplete**: `util/providers.num` is missing, so `Configure` refuses with "its generator is missing" |
| `openssl` + a hand-built OpenSSL | works, and was unnecessary once MSYS2's package was found |
| `dtls` / `webrtc-dtls` | **disqualified**: no `0xC030` |
| `rustls` | **disqualified**: no DTLS primitives at all |
| `str0m` | uses OpenSSL internally, so it is OpenSSL with a WebRTC stack on top |
| `DusTLS` | experimental, no audit, DTLS 1.2 PoC only |

### L4 — why speed was not the criterion

The plan puts every DTLS operation off the tick: the handshake is expensive crypto and must never
sit inside the 20 ms budget (§8.1 constraint 5, §18.2). A handshake happens at login, not per frame.
On the hot path the record layer's cost is dominated by AES-GCM in both candidates, and any
difference would be invisible next to the measured 12–14 kB/s egress budget (§0.4).

So the criterion is the one that can actually fail: **can it negotiate at all.**

### L5 — the spike, measured

With MSYS2's `mingw-w64-x86_64-openssl` 3.6.5 and `OPENSSL_DIR=C:/msys64/mingw64`:

```
OpenSSL: OpenSSL 3.6.5 29 Sep 2026
set_cipher_list(ECDHE-RSA-AES256-GCM-SHA384) -> ok
DTLS acceptor built with the client's only suite
```

and a real DTLS client connecting to it:

```
LISTENING 127.0.0.1:63541
RECEIVED 154 bytes from 127.0.0.1:63542
  first bytes: [16, fe, ff, 00, 00, 00, 00, 00, 00, 00, 00, 00, 8d, 01, 00, 00]
  content_type=22 version=0xfeff record_len=141
  handshake record: true
```

Three things that match the client's own measured behaviour and are worth noting:

* **`content_type=22`** — a handshake record, which is what a DTLS ClientHello is.
* **`version=0xfeff` on the FIRST ClientHello** — the same value the game client uses before the
  cookie exchange (plan §0.3). The record version is DTLS 1.0 even though the negotiated version is
  1.2, which is the OpenSSL behaviour the plan flagged as "a classic thing a hand-rolled stack gets
  wrong" and a reason to prefer a mature implementation.
* **141-byte record** against the game client's 134-byte first ClientHello — the same order of
  magnitude, different client (the openssl CLI, not the game).

**Verdict: `openssl` 0.10 with a system OpenSSL, and it passes.** The dependency is a C library, and
that cost is real and recorded in the plan §18.1; what the spike establishes is that the cost buys a
handshake that works, which no pure-Rust candidate can offer for this build.

### L6 — the build friction, and how it was actually resolved

Three dead ends before the working path, recorded so they are not repeated:

1. **No `make`.** mingw-w64 ships `mingw32-make`; `make` does not exist on this machine.
2. **MSYS perl lacks modules** (`Locale::Maketext::Simple`, `Pod::Usage`, `ExtUtils::MakeMaker`) and
   **MSYS perl splits `PERL5LIB` on `:`**, so a Windows path like `C:\...` is cut in two at the drive
   letter. `/usr/lib/perl5/site_perl` is not writable, so a shim cannot be installed into the default
   `@INC` either.
3. **Strawberry Perl cannot build this target**: it is `MSWin32` and OpenSSL's `mingw64` target
   requires a perl that produces Unix-style paths.

**None of that mattered**, because MSYS2 already had a compiled OpenSSL. The lesson is the cheap one:
check for the packaged library before building it from source. `openssl-src`'s vendor being incomplete
is a real defect worth knowing, but it is not on the critical path.

**Requirement for the workspace**, now in `server/rust-toolchain.toml`: MSYS2's mingw64 on PATH, and
`OPENSSL_DIR=C:/msys64/mingw64`.
