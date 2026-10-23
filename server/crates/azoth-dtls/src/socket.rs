//! One UDP socket, many peers, demuxed by `(ip, port)`.
//!
//! WHY ONE SOCKET
//! ==============
//! A socket per player is the obvious design and it is the wrong one: file descriptors, kernel
//! receive buffers and per-datagram syscall cost all scale with the player count, and the
//! reference implementations that reach millions of packets per second all demux from a small
//! fixed set of sockets. The measured per-player load is ~20 datagrams/s ingress and ~62 egress
//! (`docs/PLAN-backend-rust.md` §0.4), so one socket is orders of magnitude away from its limit
//! at the 2,500-player gate.
//!
//! THE FRESH-CLIENTHELLO RESET, AND WHY IT IS COOKIE-AWARE
//! ====================================================
//! A ClientHello that **starts a new handshake** from an address that already has a session drops
//! that session first. This is not defensive tidiness; it is the fix for the project's
//! longest-lived "flaky REP" symptom. The prototype records it (`rep.py`, the
//! `dtls-session-reset` branch): the client reuses its source port after a previous session ends,
//! so the second and later world attempts in one client run arrive from a port the server still
//! holds a dead session for. Feeding a new handshake into the old DTLS state machine leaves it
//! stuck — measured 2026-09-27: the client retried its ClientHello 12 times from
//! `127.0.0.1:27000`, the server never replied and logged no error at all, and the client
//! surfaced `@mm_csdkerr_connection_failed` after 15 s in `WaitingForREPConnection`.
//!
//! The reset cannot be "any ClientHello from a known address", because the client's own cookie
//! exchange puts its 2nd ClientHello on the same 5-tuple as its 1st (§0.3) and that one must
//! *continue* the exchange. So a datagram resets the session when
//!
//! * the session has already completed its handshake — any ClientHello afterwards is a restart, or
//! * the ClientHello carries **no cookie** — the client is starting over from the first flight.
//!
//! A ClientHello that carries a cookie continues the session it belongs to. That single rule makes
//! the port-reuse fix and the mandated cookie exchange compatible, and it is the reason the cookie
//! is stateless and bound to the address rather than to the session object — see [`crate::peer`].
//!
//! WHAT `pump` DOES NOT DO
//! =======================
//! It does not tick, it does not call back, and it does not own a timer that the caller cannot
//! inspect. It blocks on one datagram, routes it, and returns what happened. The handshake inside
//! it is expensive crypto and must not run on the simulation tick (`§8.1`, `§18.2`); the shape
//! makes that a placement decision the caller makes once, not a per-call risk.

use std::collections::HashMap;
use std::io::ErrorKind;
use std::net::{SocketAddr, UdpSocket};
use std::time::{Duration, Instant};

use openssl::ssl::SslContext;

use crate::cert::Identity;
use crate::config::DtlsConfig;
use crate::peer::{self, Peer};
use crate::DtlsError;

/// The DTLS record content type for a handshake record.
const CONTENT_HANDSHAKE: u8 = 22;

/// The handshake message type for a ClientHello.
const HANDSHAKE_CLIENT_HELLO: u8 = 1;

/// Bytes before the first handshake message type: the 13-byte record header.
const RECORD_HEADER: usize = 13;

/// Offset of the handshake body inside a ClientHello datagram: record header plus the 12-byte
/// handshake header (`type`, 3-byte length, `message_seq`, 3-byte fragment offset, 3-byte fragment
/// length).
const CLIENT_HELLO_BODY: usize = RECORD_HEADER + 12;

/// Offset of `fragment_offset` inside the datagram, relative to the handshake header.
const FRAGMENT_OFFSET: usize = 6;

/// Inside the ClientHello body: `client_version` (2) then `random` (32).
const SESSION_ID_LEN: usize = CLIENT_HELLO_BODY + 34;

/// The longest this crate will block on a datagram before it re-checks handshake deadlines.
///
/// It is not a protocol value: it only bounds how late a timeout can be noticed, and it is capped
/// so that a long [`DtlsConfig::handshake_timeout`] does not make a short one imprecise.
const MAX_POLL_INTERVAL: Duration = Duration::from_millis(100);

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

/// A session and the bookkeeping the transport keeps beside it.
struct Session {
    peer: Peer,
    /// `Some` until the handshake completes; then the session is never expired here.
    deadline: Option<Instant>,
    /// `true` once [`TransportEvent::Established`] has been returned, so it is returned once.
    announced: bool,
}

/// The world server's UDP endpoint: one socket, one peer table, one shared DTLS context.
pub struct Transport {
    socket: UdpSocket,
    ctx: SslContext,
    peers: HashMap<SocketAddr, Session>,
    recv_buf: Vec<u8>,
    max_datagram: usize,
    handshake_timeout: Duration,
    poll_interval: Duration,
}

impl Transport {
    /// Bind the socket and build the DTLS context from `identity`.
    ///
    /// Port `0` in [`DtlsConfig::bind`] asks the operating system to pick a port;
    /// [`Transport::local_addr`] reports what was chosen.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::Io`] if the socket cannot be bound or its read timeout cannot be set,
    /// and [`DtlsError::OpenSsl`] if the certificate or context cannot be built.
    pub fn bind(config: &DtlsConfig, identity: Identity) -> Result<Self, DtlsError> {
        let ctx = peer::server_context(&identity)?;
        let socket = UdpSocket::bind(config.bind)?;
        // Bounded so a quiet socket still lets `pump` notice an expired handshake. Never larger
        // than the deadline itself, or a short deadline could only be enforced a full period late.
        let poll_interval = config.handshake_timeout.min(MAX_POLL_INTERVAL);
        socket.set_read_timeout(Some(poll_interval.max(Duration::from_millis(1))))?;

        Ok(Self {
            socket,
            ctx,
            peers: HashMap::new(),
            recv_buf: vec![0u8; config.max_datagram],
            max_datagram: config.max_datagram,
            handshake_timeout: config.handshake_timeout,
            poll_interval,
        })
    }

    /// The address the socket actually bound, which is how a caller learns a port chosen by the
    /// operating system.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::Io`] if the local address cannot be read.
    pub fn local_addr(&self) -> Result<SocketAddr, DtlsError> {
        Ok(self.socket.local_addr()?)
    }

    /// How many sessions the table holds, including ones still handshaking.
    #[must_use]
    pub fn peer_count(&self) -> usize {
        self.peers.len()
    }

    /// Block for one datagram, route it to its peer, and report what happened.
    ///
    /// Returns an empty vector when the wait produced no datagram, which is the normal case on a
    /// quiet world; it is not an error and it is not a tick.
    ///
    /// A per-peer failure (OpenSSL rejecting a record) drops that peer and reports
    /// [`TransportEvent::Dropped`] rather than returning an error: one player's broken state
    /// machine must never take the socket down. The prototype does the same thing for the same
    /// reason (`rep.py`: a `feed-error` logs a traceback and calls `drop`, and the UDP loop
    /// survives).
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::Io`] only for a socket-level failure, and [`DtlsError::OpenSsl`] if a
    /// new session cannot be allocated.
    pub fn pump(&mut self) -> Result<Vec<TransportEvent>, DtlsError> {
        let mut events = Vec::new();

        let received = {
            let Self {
                socket, recv_buf, ..
            } = self;
            socket.recv_from(recv_buf)
        };
        match received {
            Ok((len, addr)) => {
                let datagram = self.recv_buf[..len].to_vec();
                self.route(addr, &datagram, &mut events)?;
            }
            // A read timeout is the designed way to re-check deadlines, not a failure.
            Err(e) if is_quiet(&e) => {}
            Err(e) => return Err(DtlsError::Io(e)),
        }

        events.extend(self.expire());
        Ok(events)
    }

    /// Encrypt `plaintext` and send it to `peer` as one datagram.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::UnknownPeer`] if no session is held for `peer`,
    /// [`DtlsError::NotEstablished`] before its handshake completes, and
    /// [`DtlsError::DatagramTooLarge`] if the plaintext does not fit one record.
    pub fn send(&mut self, peer: SocketAddr, plaintext: &[u8]) -> Result<(), DtlsError> {
        let session = self
            .peers
            .get_mut(&peer)
            .ok_or(DtlsError::UnknownPeer(peer))?;
        let datagram = session.peer.write_app(plaintext)?;
        self.socket.send_to(&datagram, peer)?;
        Ok(())
    }

    /// Route one received datagram into its session, appending whatever it produced.
    fn route(
        &mut self,
        addr: SocketAddr,
        datagram: &[u8],
        events: &mut Vec<TransportEvent>,
    ) -> Result<(), DtlsError> {
        if self.starts_a_new_handshake(addr, datagram) && self.peers.remove(&addr).is_some() {
            events.push(TransportEvent::Dropped(addr));
        }

        if !self.peers.contains_key(&addr) {
            let peer = Peer::with_max_datagram(&self.ctx, addr, self.max_datagram)?;
            self.peers.insert(
                addr,
                Session {
                    peer,
                    deadline: Some(Instant::now() + self.handshake_timeout),
                    announced: false,
                },
            );
        }

        let fed = self
            .peers
            .get_mut(&addr)
            .map_or(Ok(Vec::new()), |session| session.peer.feed(datagram));
        match fed {
            Ok(datagrams) => self.flush(addr, datagrams),
            Err(_) => {
                self.peers.remove(&addr);
                events.push(TransportEvent::Dropped(addr));
                return Ok(());
            }
        }

        if let Some(session) = self.peers.get_mut(&addr)
            && session.peer.is_established()
            && !session.announced
        {
            session.announced = true;
            session.deadline = None;
            events.push(TransportEvent::Established(addr));
        }

        let mut retransmits = Vec::new();
        let read = self.peers.get_mut(&addr).map(|session| {
            let records = session.peer.read_app();
            retransmits = session.peer.take_outbound();
            records
        });
        self.flush(addr, retransmits);

        match read {
            Some(Ok(records)) => {
                for bytes in records {
                    events.push(TransportEvent::Data { peer: addr, bytes });
                }
            }
            Some(Err(_)) => {
                self.peers.remove(&addr);
                events.push(TransportEvent::Dropped(addr));
            }
            None => {}
        }

        Ok(())
    }

    /// Send every datagram to one peer. A refused send is the peer being gone, not the socket.
    fn flush(&mut self, addr: SocketAddr, datagrams: Vec<Vec<u8>>) {
        for datagram in datagrams {
            // A send the OS refuses means the peer vanished between two packets (ICMP port
            // unreachable on Windows surfaces exactly here), so it is not a transport failure.
            if self.socket.send_to(&datagram, addr).is_err() {
                break;
            }
        }
    }

    /// Drop every session whose handshake deadline has passed.
    fn expire(&mut self) -> Vec<TransportEvent> {
        let now = Instant::now();
        let expired: Vec<SocketAddr> = self
            .peers
            .iter()
            .filter(|(_, session)| session.deadline.is_some_and(|at| at <= now))
            .map(|(addr, _)| *addr)
            .collect();
        for addr in &expired {
            self.peers.remove(addr);
        }
        expired.into_iter().map(TransportEvent::Dropped).collect()
    }

    /// The interval `pump` blocks for before re-checking deadlines.
    #[must_use]
    pub fn poll_interval(&self) -> Duration {
        self.poll_interval
    }

    /// Whether this datagram begins a *new* handshake for an address we may already hold.
    ///
    /// See the module docs: an established session is always restarted, and a handshaking one only
    /// when the ClientHello carries no cookie, because that is the client starting from its first
    /// flight rather than answering our HelloVerifyRequest.
    fn starts_a_new_handshake(&self, addr: SocketAddr, datagram: &[u8]) -> bool {
        if !is_client_hello(datagram) {
            return false;
        }
        match self.peers.get(&addr) {
            None => false,
            Some(session) if session.peer.is_established() => true,
            Some(_) => client_hello_cookie_len(datagram) == Some(0),
        }
    }
}

/// `true` for a received datagram that begins with a ClientHello.
///
/// Record layout: `[type:1][version:2][epoch:2][seq:6][length:2]`, then the handshake message,
/// whose first byte is its type (`1` = ClientHello). Only the type byte is inspected: the client
/// retries this record with an increasing record sequence number, so nothing later in the header
/// is stable enough to compare. A datagram whose first record is a ClientHello is one — the
/// capture shows every datagram carries exactly one record (§0.3).
fn is_client_hello(datagram: &[u8]) -> bool {
    datagram.len() > RECORD_HEADER
        && datagram[0] == CONTENT_HANDSHAKE
        && datagram[RECORD_HEADER] == HANDSHAKE_CLIENT_HELLO
}

/// The `cookie_len` field of a ClientHello, or `None` when it cannot be read from this datagram.
///
/// Returns `None` for a fragment beyond the first one (`fragment_offset != 0`), because the
/// `cookie_len` byte is only at a known offset in a message that starts here.
fn client_hello_cookie_len(datagram: &[u8]) -> Option<usize> {
    let fragment_offset_at = CLIENT_HELLO_BODY - 12 + FRAGMENT_OFFSET;
    let fragment_offset = datagram.get(fragment_offset_at..fragment_offset_at + 3)?;
    if fragment_offset != [0, 0, 0] {
        return None;
    }
    let session_id_len = usize::from(*datagram.get(SESSION_ID_LEN)?);
    let cookie_len = *datagram.get(SESSION_ID_LEN + 1 + session_id_len)?;
    Some(usize::from(cookie_len))
}

/// `true` for a receive error that only means "nothing arrived".
///
/// `ConnectionReset` is in the list because of a measured Windows failure, not defensively: a
/// `send_to` to a client that already closed is answered with ICMP port-unreachable, and the
/// *next* `recv_from` then raises `WSAECONNRESET` (10054). The prototype treated that as fatal
/// and killed the whole REP process — the client then sat in `WaitingForREPConnection` until it
/// timed out.
fn is_quiet(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        ErrorKind::WouldBlock
            | ErrorKind::TimedOut
            | ErrorKind::Interrupted
            | ErrorKind::ConnectionReset
            | ErrorKind::ConnectionAborted
    )
}
