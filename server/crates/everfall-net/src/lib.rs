//! DTLS 1.2 handshake spike for Everfall.
//!
//! This crate exists to answer one question the atlas cannot: **does the real
//! New World client accept a DTLS 1.2 handshake with an ECDSA certificate?**
//! dimpl has no RSA by design, and the Python lab presents an RSA 2048
//! certificate, so the client's tolerance for ECDSA is unknown until measured.
//!
//! # Why this crate exists, and why it is only the handshake
//!
//! `everfall-wire`, `everfall-sim` and `everfall-world` own the named fields of
//! the entry path. This crate owns none of them. It is a spike: it binds a UDP
//! socket, runs a [`dimpl`] server, and reports what the DTLS state machine
//! observed. It deliberately stops at `Connected`. The carrier handshake, the
//! registration ladder and any application data are *not* implemented here,
//! because those fields are the atlas's to name, and because the only open
//! question is whether the client completes the TLS layer at all.
//!
//! # Why default features are disabled
//!
//! `dimpl`'s default features enable `aws-lc-rs`, which builds `aws-lc-sys` --
//! a C library. That is unacceptable on this server: the whole point of the
//! spike is a clone-anywhere, pure-Rust build. `default-features = false` plus
//! `features = ["rust-crypto"]` selects dimpl's `RustCrypto` backend, and
//! [`cert`] mints the server certificate with `p256` + `x509-cert` rather than
//! dimpl's `rcgen` feature (which would also enable `aws-lc-rs`).
//!
//! The `server` binary proves the crate is wired correctly. It does **not**
//! prove the game client accepts it; that is the live attempt the parent runs.

pub mod cert;
pub mod server;

pub use crate::cert::{CertError, self_signed_p256};
pub use crate::server::{Milestone, NetError, Server};
