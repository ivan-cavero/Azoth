//! DTLS 1.2 handshake spike for Everfall, on OpenSSL.
//!
//! This crate answers one question the atlas cannot: **does the real New World
//! REP client accept this crate's DTLS layer?** It binds a UDP socket, runs an
//! OpenSSL DTLS 1.2 server that presents an RSA 2048 certificate, and reports
//! what the state machine observed. It deliberately stops at `Connected`. The
//! carrier handshake, the registration ladder and application data are *not*
//! owned here, because those fields belong to the atlas.
//!
//! # Why OpenSSL, and why the decision is not open again
//!
//! This was decided by measurement, not preference.
//!
//! `dimpl`, a pure-Rust Sans-IO DTLS 1.2 engine, was tried first. Bound on the
//! REP port and run against a clean client, the client sent **twelve 159-byte
//! `ClientHellos` and `dimpl` produced no flight at all**, ending in
//! `dtls error: timeout: connect`. The client's DTLS works against the Python
//! lab world, which signs with an **RSA 2048** certificate (`CN=New World`),
//! and `dimpl` lists RSA as an explicit non-goal. So the server must present an
//! RSA certificate, which a pure-ECDSA engine cannot do.
//!
//! OpenSSL does RSA and ECDSA, is the audited stack the Python lab already uses
//! through pyOpenSSL, and is what `docs/PLAN.md` prescribes for this crate
//! ("DTLS and UDP. OpenSSL stays inside this crate"). The certificate is minted
//! in memory by [`cert::RsaIdentity`] with `CN=New World`, matching
//! `services/world/src/azoth_world/rep.py`.
//!
//! # Dependencies
//!
//! The only dependency is the [`openssl`] crate, linked against a **prebuilt
//! OpenSSL development package** (see `server/README.md`);
//! `server/.cargo/config.toml` points `openssl-sys` at it with `OPENSSL_DIR`,
//! `OPENSSL_LIB_DIR` and `OPENSSL_INCLUDE_DIR`. The `vendored` feature is
//! deliberately not used: it compiles OpenSSL from source and needs a C
//! toolchain and Perl, and on this machine the compiler's PDB handling makes
//! that build fail reproducibly. No C is compiled by this workspace. [`time`]
//! is kept for milestone timestamps and the certificate serial.
//!
//! The `server` binary proves the crate is wired correctly. It does **not**
//! prove the game client accepts it; that is the live attempt the parent runs.

pub mod cert;
pub mod server;

pub use crate::cert::{CertError, RsaIdentity};
pub use crate::server::{Milestone, NetError, Server};
