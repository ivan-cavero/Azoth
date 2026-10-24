//! DTLS 1.2 transport for the world server: the record layer, the mandatory
//! cookie exchange, and the one-socket UDP peer demux.
//!
//! WHY THIS CRATE EXISTS
//! =====================
//! The client's REP flow is a DTLS session over UDP, and the shape of that session is not
//! negotiable — it was measured byte by byte from the 1.460 capture
//! (`docs/PLAN-backend-rust.md` §0.3, parsed from
//! `research/sessions/live_20261022_r1460_trading_timed/network/pktmon.pcapng`). Every fact
//! below is from that parse, and each one is a constraint on this crate:
//!
//! * **Exactly one usable cipher suite.** The client offers `0xC030`
//!   `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384` and `0x00FF`
//!   `TLS_EMPTY_RENEGOTIATION_INFO_SCSV`, and nothing else, in all six ClientHellos of both
//!   captures. There is no fallback: a server that cannot negotiate `0xC030` cannot serve this
//!   build at all. That single fact eliminated `dtls`/`webrtc-dtls` (they implement eleven
//!   suites and `AES_256_GCM_SHA384` is not among them) and `rustls` (no DTLS primitives),
//!   and it is why this crate sits on `openssl` (`odd/tasks/dtls-spike.md` L2, L3).
//! * **DTLS 1.2**, `client_version = 0xFEFD`.
//! * **The certificate must be RSA**, because the suite is `ECDHE_**RSA**`. The certificate
//!   itself is cosmetic — a self-signed `CN=New World` pair is accepted because the client's
//!   verify path is patched on disk — but the *key type* is not negotiable. See [`cert`].
//! * **The cookie exchange is mandatory.** The client sends three ClientHellos: no cookie →
//!   HelloVerifyRequest → cookie → a **fresh** handshake with a different `random` on the same
//!   5-tuple. A server that answers a cookieless ClientHello with a ServerHello does not
//!   complete. [`peer`] therefore drives OpenSSL's cookie callbacks, and [`Transport`] rebuilds
//!   the session when a ClientHello arrives from an address it already holds.
//! * **The record version is not the negotiated version, and it is not ours to choose.** The
//!   official server's HelloVerifyRequest and ServerHello carried record version `0xFEFF` (DTLS
//!   1.0) while negotiating 1.2. Our OpenSSL 3.6.5 sends `0xFEFF` for the HelloVerifyRequest and
//!   `0xFEFD` for the ServerHello. The client accepts both — the OpenSSL-based Python prototype
//!   never sets a record version at all and still reaches `InGame` — so this crate forces neither
//!   value and no test asserts one.
//! * **Datagrams stay under ~1200 bytes.** The capture's maxima are 1,152 B (c2s) and 1,166 B
//!   (s2c) and the prototype's `REPLAY_CHUNK_SIZE` is 1100. IP fragmentation makes a single
//!   lost fragment lose the whole datagram, so [`Transport`] splits OpenSSL's output at DTLS
//!   record boundaries — one record per datagram, which is exactly what all 125,485 captured
//!   packets were — and [`DtlsConfig::max_datagram`] bounds both the receive buffer and the
//!   plaintext a single [`peer::Peer::write_app`] may carry.
//! * `extended_master_secret` (`0x0017`) and `encrypt_then_mac` (`0x0016`) are offered by the
//!   client and are honoured, because OpenSSL enables both by default and this crate does not
//!   turn them off.
//!
//! WHY ONE SOCKET, MANY PEERS
//! ==========================
//! [`Transport`] owns **one** `UdpSocket` and demuxes datagrams by `(ip, port)` into a
//! `HashMap<SocketAddr, Peer>`. One socket per player is the obvious alternative and it is the
//! wrong one: it multiplies file descriptors, kernel socket buffers and per-datagram syscall
//! cost by the player count, and the reference implementations that reach millions of packets
//! per second all demux from a small fixed set of sockets. The measured per-player budget is
//! ~20 datagrams/s in and ~62 out (`§0.4`), so a single socket is nowhere near its limit.
//!
//! THE HANDSHAKE MUST NEVER RUN ON THE TICK
//! ========================================
//! A DTLS handshake is RSA-2048 signing plus an ECDHE exchange: milliseconds of CPU, against a
//! 20 ms tick whose per-player budget at the 2,500-player gate is **4 µs** (`§8.1`). A
//! handshake inside the tick would blow that budget by three orders of magnitude for every
//! player joining, and §8.1's rule — "keep tick work under ~50% of budget" — is not survivable
//! with even one handshake in it. The plan's answer (`§18.2`) is that the tick runs on a
//! dedicated `std::thread` and the transport does not.
//!
//! The API is shaped so the correct placement is the natural one, not merely the documented
//! one: [`Transport::pump`] is **blocking** and **returns events**. It takes no tick callback,
//! owns no timer, and never calls back into the caller. There is no way to make it run inside
//! the tick without blocking the tick, which is the failure the shape forbids. A caller runs
//! `pump` on its own thread (or inside `tokio::task::spawn_blocking`) and forwards the returned
//! events to the simulation through a channel; the simulation never touches a socket.
//!
//! WHAT THIS CRATE DOES NOT OWN
//! ============================
//! Retransmission timers. The prototype does not implement them either (`rep.py`'s DTLS notes:
//! "No retransmit timers on loopback"), and OpenSSL's `DTLSv1_handle_timeout` is not driven
//! here. On loopback nothing is lost, so the handshake completes deterministically; under real
//! loss the client retries and [`Transport`] resets on the retried ClientHello. Replay
//! protection, session tickets, heartbeats and the authentication deadline belong to
//! `azoth-session`.
//!
//! WHY THE TRANSPORT REPORTS THROUGH A SINK AND NOT A LOG CALL
//! ===========================================================
//! [`Transport`] can show a caller every datagram it received, sent, or could not route, and it
//! does that through a sink the caller installs ([`Transport::set_trace`]) instead of logging
//! itself. Three reasons:
//!
//! * **A library does not own the process's stderr.** Whether the caller wants `log`, `tracing`, a
//!   bounded ring buffer, a pcap or silence is the caller's decision, and a transport that picked
//!   one would be wrong for every other caller.
//! * **Formatting on the datagram path is a measured cost.** A 2,500-player world is ~150,000
//!   datagrams/s (`§0.4`); a hex dump per datagram is not a log, it is a throughput bug, and it is
//!   the shape of the prototype's 7.3 GB afternoon (§12, §18.8). A caller that installs nothing
//!   pays one `Option` check per datagram.
//! * **The event channel stays meaningful.** [`TransportEvent`] says what a *session* did;
//!   [`TransportTrace`] says what the *socket* saw, including the datagrams that never became a
//!   session. That is the difference between "nothing arrived" and "a handshake completed".

pub mod cert;
pub mod config;
pub mod peer;
pub mod socket;

use std::net::SocketAddr;

pub use cert::Identity;
pub use config::DtlsConfig;
pub use peer::Peer;
pub use socket::Transport;

/// What [`Transport::pump`] observed while handling one datagram or one deadline expiry.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportEvent {
    /// The handshake completed for this peer. It can now be written to.
    Established(SocketAddr),
    /// Decrypted application data arrived from this peer, one entry per DTLS record.
    Data {
        /// Who sent it.
        peer: SocketAddr,
        /// The plaintext of one record.
        bytes: Vec<u8>,
    },
    /// The peer's handshake timed out, its session rejected a datagram, or a fresh ClientHello
    /// replaced it. All three mean the same thing to the caller: anything held for this address
    /// is stale.
    Dropped(SocketAddr),
}

/// What the transport saw, for diagnostics. Off unless a caller installs a sink.
///
/// WHY A SINK AND NOT A LOG CALL
/// =============================
/// A library does not own the process's stderr and does not know whether its caller wants `log`,
/// `tracing`, a ring buffer or silence, so it hands over the observation and lets the caller render
/// it. That also keeps a formatting cost off the datagram path: a caller that installs nothing pays
/// one `Option` check per datagram, which is the whole reason this is a sink and not an
/// unconditional `eprintln!` (the crate docs have the 7.3 GB incident). The payloads are borrowed
/// from the transport's own buffers, so a trace copies nothing and a sink must finish with it
/// before returning.
#[derive(Clone, Copy, Debug)]
pub enum TransportTrace<'a> {
    /// A raw datagram arrived, before any DTLS handling.
    Received {
        /// Who sent it.
        from: SocketAddr,
        /// The datagram exactly as it arrived.
        bytes: &'a [u8],
    },
    /// A datagram is about to be written.
    Sending {
        /// Where it is going.
        to: SocketAddr,
        /// The datagram that will be written.
        bytes: &'a [u8],
    },
    /// A datagram could not be routed to a peer.
    Unroutable {
        /// Who sent it.
        from: SocketAddr,
        /// The datagram that could not be routed.
        bytes: &'a [u8],
        /// Why, in one phrase.
        reason: &'a str,
    },
}

/// Where the transport reports what it saw.
///
/// `Send + Sync` because the transport is moved to the thread that owns the socket, and `Fn` rather
/// than `FnMut` because a sink keeps its own interior mutability — which is what lets one sink be
/// shared by the transport and by whatever else the caller reports to it.
pub type TraceSink = Box<dyn Fn(TransportTrace<'_>) + Send + Sync>;

/// Everything this crate can fail at.
///
/// There is one error type because every failure here is fatal to *one peer* or to *the
/// socket*, and a caller distinguishes them by which call returned the error — not by which
/// variant it is. A peer-level failure is reported as [`TransportEvent::Dropped`] by
/// [`Transport::pump`] rather than through this type, so `pump`'s error channel stays reserved
/// for failures of the transport itself.
#[derive(Debug)]
pub enum DtlsError {
    /// The UDP socket failed: bind, receive, or send.
    Io(std::io::Error),
    /// OpenSSL rejected an operation on one session. The session cannot continue.
    Ssl(openssl::ssl::Error),
    /// OpenSSL's configuration or certificate plumbing failed.
    OpenSsl(openssl::error::ErrorStack),
    /// A DTLS record, or the plaintext that would produce one, does not fit in
    /// [`DtlsConfig::max_datagram`]. Sending it would invite IP fragmentation, which turns one
    /// lost fragment into a lost datagram (`§0.4`).
    DatagramTooLarge {
        /// The size that was produced or requested, in bytes.
        len: usize,
        /// The configured ceiling, in bytes.
        max: usize,
    },
    /// The peer exists but its handshake has not completed, so there is no key to write with.
    NotEstablished(SocketAddr),
    /// No session is held for this address. It was never seen, or it was dropped.
    UnknownPeer(SocketAddr),
}

impl std::fmt::Display for DtlsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "udp socket: {e}"),
            Self::Ssl(e) => write!(f, "dtls session: {e}"),
            Self::OpenSsl(e) => write!(f, "openssl: {e}"),
            Self::DatagramTooLarge { len, max } => {
                write!(f, "{len} bytes exceeds the {max}-byte datagram limit")
            }
            Self::NotEstablished(addr) => write!(f, "{addr} has not completed its handshake"),
            Self::UnknownPeer(addr) => write!(f, "no session for {addr}"),
        }
    }
}

impl std::error::Error for DtlsError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(e) => Some(e),
            Self::Ssl(e) => Some(e),
            Self::OpenSsl(e) => Some(e),
            Self::DatagramTooLarge { .. }
            | Self::NotEstablished(_)
            | Self::UnknownPeer(_) => None,
        }
    }
}

impl From<std::io::Error> for DtlsError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<openssl::ssl::Error> for DtlsError {
    fn from(value: openssl::ssl::Error) -> Self {
        Self::Ssl(value)
    }
}

impl From<openssl::error::ErrorStack> for DtlsError {
    fn from(value: openssl::error::ErrorStack) -> Self {
        Self::OpenSsl(value)
    }
}
