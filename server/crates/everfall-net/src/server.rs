//! A single-connection dimpl DTLS server driven from a blocking loop.
//!
//! No Tokio, no async: dimpl is Sans-IO, so the state machine is fed datagrams
//! and advanced by a timer, exactly as its model intends. [`Server::step`]
//! drains pending output, waits for the next datagram or timer, and reports the
//! milestones it observed. The binary prints them with timestamps; the
//! `handshake` test asserts on them.

use std::io;
use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use std::time::{Duration, Instant};

use dimpl::{Config, Dtls, DtlsCertificate, Error as DtlsError, Output};

/// Largest datagram accepted, and the buffer dimpl is polled with.
const MAX_DATAGRAM: usize = 2_048;

/// A milestone the server observed while driving the handshake.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Milestone {
    /// A datagram arrived on the socket.
    Datagram {
        /// Sender address.
        from: SocketAddr,
        /// Datagram length in bytes.
        bytes: usize,
    },
    /// A DTLS record was sent to the peer.
    FlightSent {
        /// Destination address.
        to: SocketAddr,
        /// Record length in bytes.
        bytes: usize,
    },
    /// The handshake completed.
    Connected,
    /// Plaintext application data arrived from the peer.
    ApplicationData(Vec<u8>),
    /// The peer sent `close_notify`.
    CloseNotify,
}

/// A fatal error while driving the server. Either source ends the run.
#[derive(Debug)]
pub enum NetError {
    /// The UDP socket failed.
    Io(io::Error),
    /// dimpl reported a fatal DTLS error; the connection must be dropped.
    Dtls(DtlsError),
}

impl std::fmt::Display for NetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "socket error: {error}"),
            Self::Dtls(error) => write!(f, "dtls error: {error}"),
        }
    }
}

impl std::error::Error for NetError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Dtls(error) => Some(error),
        }
    }
}

impl From<io::Error> for NetError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<DtlsError> for NetError {
    fn from(error: DtlsError) -> Self {
        Self::Dtls(error)
    }
}

/// One dimpl DTLS 1.2 server bound to a UDP socket.
#[derive(Debug)]
pub struct Server {
    socket: UdpSocket,
    dtls: Dtls,
    peer: Option<SocketAddr>,
    next_timeout: Option<Instant>,
    connected: bool,
}

impl Server {
    /// Bind `addr` and prepare a DTLS 1.2 server with `certificate`.
    ///
    /// Client certificates are not required: the New World REP client does not
    /// present one, and requiring it would make dimpl send a `CertificateRequest`
    /// the spike does not need. The server cookie exchange stays at dimpl's
    /// default (enabled), which matches the client's mandatory `HelloVerifyRequest`.
    ///
    /// # Errors
    ///
    /// Returns [`NetError::Io`] if the socket cannot be bound, or
    /// [`NetError::Dtls`] if dimpl rejects the configuration.
    pub fn bind(addr: SocketAddr, certificate: DtlsCertificate) -> Result<Self, NetError> {
        let config = Config::builder()
            .require_client_certificate(false)
            .build()
            .map_err(NetError::Dtls)?;

        let socket = UdpSocket::bind(addr)?;
        let dtls = Dtls::new_12(Arc::new(config), certificate, Instant::now());

        Ok(Self {
            socket,
            dtls,
            peer: None,
            next_timeout: None,
            connected: false,
        })
    }

    /// The actual bound address (useful when binding port 0).
    ///
    /// # Errors
    ///
    /// Returns the socket error from `local_addr`.
    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        self.socket.local_addr()
    }

    /// Whether the handshake has completed.
    pub fn is_connected(&self) -> bool {
        self.connected
    }

    /// Queue application data for the peer.
    ///
    /// # Errors
    ///
    /// Returns [`NetError::Dtls`] if the connection is closed or handshaking.
    pub fn send_application_data(&mut self, data: &[u8]) -> Result<usize, NetError> {
        Ok(self.dtls.send_application_data(data)?)
    }

    /// Drive one step: flush output, then wait up to `max_wait` for a datagram
    /// or the next dimpl timer. Returns the milestones observed this step.
    ///
    /// # Errors
    ///
    /// Returns [`NetError`] if the socket fails or dimpl reports a fatal error.
    pub fn step(&mut self, max_wait: Duration) -> Result<Vec<Milestone>, NetError> {
        let mut events = Vec::new();

        let now = Instant::now();
        self.dtls.handle_timeout(now)?;
        self.drain(&mut events)?;

        let wait = match self.next_timeout {
            Some(deadline) if deadline > now => (deadline - now).min(max_wait),
            Some(_) => Duration::ZERO,
            None => max_wait,
        };
        self.socket.set_read_timeout(Some(wait))?;

        let mut buffer = [0u8; MAX_DATAGRAM];
        match self.socket.recv_from(&mut buffer) {
            Ok((bytes, from)) => {
                self.peer = Some(from);
                events.push(Milestone::Datagram { from, bytes });
                self.dtls.handle_packet(&buffer[..bytes])?;
                self.drain(&mut events)?;
            }
            Err(error) if is_timeout(&error) => {}
            Err(error) => return Err(NetError::Io(error)),
        }

        Ok(events)
    }

    /// Poll dimpl to `Timeout`, sending every record it produces.
    fn drain(&mut self, events: &mut Vec<Milestone>) -> Result<(), NetError> {
        let mut buffer = vec![0u8; MAX_DATAGRAM];
        loop {
            match self.dtls.poll_output(&mut buffer) {
                Output::Packet(record) => {
                    if let Some(to) = self.peer {
                        self.socket.send_to(record, to)?;
                        events.push(Milestone::FlightSent {
                            to,
                            bytes: record.len(),
                        });
                    }
                }
                Output::BufferTooSmall { needed } => buffer.resize(needed, 0),
                Output::Timeout(deadline) => {
                    self.next_timeout = Some(deadline);
                    break;
                }
                Output::Connected => {
                    self.connected = true;
                    events.push(Milestone::Connected);
                }
                Output::ApplicationData(data) => {
                    events.push(Milestone::ApplicationData(data.to_vec()));
                }
                Output::CloseNotify => events.push(Milestone::CloseNotify),
                // The spike owns the handshake only; the enum is non-exhaustive,
                // and peer certificates and SRTP keying material are not part of
                // its contract.
                _ => {}
            }
        }
        Ok(())
    }
}

/// `recv_from` timeout surfaces as `WouldBlock` on Unix and `TimedOut` on
/// Windows; both mean "no datagram arrived in time".
fn is_timeout(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
    )
}
