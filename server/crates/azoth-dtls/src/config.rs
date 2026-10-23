//! The three numbers that describe the world server's UDP endpoint.
//!
//! WHY THESE ARE CONFIGURATION AND NOT CONSTANTS
//! ============================================
//! `bind` differs per world and per test. The other two differ for one reason: the transport is
//! exercised by tests that must not wait 30 seconds for a timeout, and by a loopback development
//! server that must. Neither is a protocol fact, so neither belongs in code.
//!
//! WHY THE DEFAULTS ARE WHAT THEY ARE
//! ==================================
//! * `bind` — `127.0.0.1:9000` is the port the Python prototype binds (`rep.py`
//!   `RepServer.__init__`), so the client's ticket `RepAddress` and the launcher profile keep
//!   working against the Rust server with no client-side change.
//! * `max_datagram` — **1200** is not a round number chosen for comfort. The 1.460 capture's
//!   largest UDP payload is 1,152 B client→server and 1,166 B server→client, and the
//!   prototype's `REPLAY_CHUNK_SIZE` is 1100 (`docs/PLAN-backend-rust.md` §0.4). Above the
//!   path MTU a datagram is IP-fragmented, and one lost fragment loses the entire datagram —
//!   for a real-time game that converts a 1% packet loss into a much larger record loss.
//! * `handshake_timeout` — 30 s. The client gives up on a failed REP handshake after 15 s
//!   (`rep.py`'s `dtls-session-reset` note: "the client gave up with
//!   `@mm_csdkerr_connection_failed` after 15 s"), so 30 s is twice the client's own patience:
//!   long enough that we never drop a session the client still considers alive, short enough
//!   that a half-open handshake cannot sit in the table forever.

use std::net::SocketAddr;
use std::time::Duration;

/// The datagram ceiling used when [`DtlsConfig::max_datagram`] is not set: the measured path
/// MTU headroom, not an arbitrary number (see the module docs).
pub(crate) const DEFAULT_MAX_DATAGRAM: usize = 1200;

/// The handshake deadline used when [`DtlsConfig::handshake_timeout`] is not set.
const DEFAULT_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(30);

/// The address the prototype binds, so an existing client profile reaches this server.
const DEFAULT_BIND: &str = "127.0.0.1:9000";

/// Where the world server listens, and the two limits the transport enforces.
///
/// # Examples
///
/// ```
/// use azoth_dtls::DtlsConfig;
///
/// let config = DtlsConfig::default();
/// assert_eq!(config.bind.to_string(), "127.0.0.1:9000");
/// assert_eq!(config.max_datagram, 1200);
/// ```
#[derive(Clone, Debug)]
pub struct DtlsConfig {
    /// The UDP address to bind. Port `0` asks the operating system to choose, which is how the
    /// tests get a free port; [`crate::Transport::local_addr`] reports what was chosen.
    pub bind: SocketAddr,
    /// The largest datagram this transport will send or accept, in bytes.
    ///
    /// It bounds two things: the receive buffer handed to `recv_from`, and the plaintext a
    /// single [`crate::peer::Peer::write_app`] call may carry once the DTLS record overhead
    /// (13-byte header, 8-byte explicit nonce, 16-byte GCM tag) is accounted for. A record
    /// OpenSSL produces above this size is rejected rather than sent, because sending it would
    /// invite IP fragmentation.
    pub max_datagram: usize,
    /// How long a session may stay in the table without completing its handshake.
    ///
    /// Measured against the peer's first datagram, not against its last: the client's whole
    /// exchange takes three ClientHellos and a handful of milliseconds on loopback, so a peer
    /// that has not finished after this long is not going to. Sessions that *have* completed
    /// the handshake are never expired here — the heartbeat and the authentication deadline
    /// belong to `azoth-session`.
    pub handshake_timeout: Duration,
}

impl Default for DtlsConfig {
    fn default() -> Self {
        Self {
            bind: DEFAULT_BIND
                .parse()
                .expect("the default bind address is a valid socket address literal"),
            max_datagram: DEFAULT_MAX_DATAGRAM,
            handshake_timeout: DEFAULT_HANDSHAKE_TIMEOUT,
        }
    }
}

impl DtlsConfig {
    /// A configuration for one address, with the measured defaults for everything else.
    #[must_use]
    pub fn new(bind: SocketAddr) -> Self {
        Self {
            bind,
            ..Self::default()
        }
    }
}
