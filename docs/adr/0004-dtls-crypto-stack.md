# 0004. DTLS crypto stack

Date: 2026-10-24
Status: accepted

## Context

The New World 1.460 client speaks **DTLS 1.2** and offers a single cipher suite
in measured ClientHellos: **`0xC030`**
(`TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`) plus the renegotiation SCSV. Cookie
HelloVerifyRequest is mandatory. Details: `docs/PLAN-backend-rust.md` §0.3.

We need performance and clone-anywhere builds, but correctness against the
real client dominates. Windows already showed MinGW/MSVC OpenSSL link pain.

Industry TLS benches (rustls / BoringSSL / OpenSSL 3.6) are **TLS**, not DTLS.
OpenSSL 3.2+ has a reported ~14% DTLS write PPS regression vs 3.1
(openssl/openssl#26055). rustls has no DTLS yet (rustls/rustls#40). Pure-Rust
DTLS crates (e.g. NoxTLS) claim `0xC030` but are unproven against this client.

## Decision

1. **Production path remains OpenSSL** via the `openssl` crate, isolated in
   `azoth-dtls` (no game logic imports OpenSSL).
2. **One documented native toolchain per OS** for developers; Docker images
   may static-link. Do not enable Windows `vendored` OpenSSL for daily
   iteration.
3. **Never mix MinGW-built OpenSSL with MSVC rustc** (or the reverse).
4. Evaluate alternate DTLS implementations **only** behind the `azoth-dtls`
   boundary, with an A/B harness against the real client + PPS/CPU metrics.
5. Do not rewrite DTLS from scratch before the playable spine.

## Consequences

- Link/env docs become part of clone-anywhere (server AGENTS + deploy).
- Crypto swap later does not rewrite ladder/sim.
- We accept OpenSSL’s DTLS performance until measured otherwise.

## Alternatives considered

| Option | Why not now |
| --- | --- |
| rustls | No DTLS |
| BoringSSL / aws-lc alone | No drop-in Rust DTLS server for our suite |
| NoxTLS / dimpl | Spike candidate later; not proven on NW |
| Custom record layer | Schedule risk; security risk |
| Force OpenSSL 3.1 forever | Version pin without harness is premature |
