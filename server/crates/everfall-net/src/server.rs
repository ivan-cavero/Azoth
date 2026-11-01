//! A single-connection OpenSSL DTLS 1.2 server driven from a blocking loop.
//!
//! No Tokio, no async. OpenSSL owns the state machine and drives it through a
//! `Read + Write` transport ([`UdpPeer`]) that reads one datagram per call and
//! writes one datagram per call, which preserves DTLS record boundaries over
//! UDP. [`Server::step`] advances the handshake or reads application data for
//! up to the socket's read timeout, then reports the milestones it observed.
//! The binary prints them with timestamps; the `handshake` test asserts on them.

use std::io::{self, Read, Write};
use std::net::{SocketAddr, UdpSocket};
use std::time::Duration;

use openssl::error::ErrorStack;
use openssl::ssl::{
    Error as SslError, ErrorCode, Ssl, SslContext, SslMethod, SslStream, SslVerifyMode, SslVersion,
};

use crate::cert::RsaIdentity;

/// Largest application-data payload read from the peer in one record.
const MAX_APPLICATION: usize = 2_048;

/// DTLS path MTU advertised to OpenSSL. Small enough to stay under any
/// loopback limit; large enough for the handshake flights.
const MTU: u32 = 1_200;

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

/// A fatal error while driving the server. Any source ends the run.
#[derive(Debug)]
pub enum NetError {
    /// The UDP socket failed.
    Io(io::Error),
    /// OpenSSL reported a fatal DTLS error; the connection must be dropped.
    Ssl(SslError),
    /// An OpenSSL configuration step failed before any datagram was exchanged.
    Stack(ErrorStack),
}

impl std::fmt::Display for NetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "socket error: {error}"),
            Self::Ssl(error) => write!(f, "dtls error: {error}"),
            Self::Stack(error) => write!(f, "openssl error: {error}"),
        }
    }
}

impl std::error::Error for NetError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Ssl(error) => Some(error),
            Self::Stack(error) => Some(error),
        }
    }
}

impl From<io::Error> for NetError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<SslError> for NetError {
    fn from(error: SslError) -> Self {
        Self::Ssl(error)
    }
}

impl From<ErrorStack> for NetError {
    fn from(error: ErrorStack) -> Self {
        Self::Stack(error)
    }
}

/// One OpenSSL DTLS 1.2 server bound to a UDP socket.
#[derive(Debug)]
pub struct Server {
    stream: SslStream<UdpPeer>,
    connected: bool,
}

impl Server {
    /// Bind `addr` and prepare a DTLS 1.2 server that presents `identity`.
    ///
    /// Client certificates are not requested: the New World REP client does not
    /// present one, so verification stays off and no `CertificateRequest` is
    /// sent. The DTLS version is pinned to 1.2, the version the client speaks.
    ///
    /// # Errors
    ///
    /// Returns [`NetError::Io`] if the socket cannot be bound, or
    /// [`NetError::Stack`] if the OpenSSL context cannot be configured.
    pub fn bind(addr: SocketAddr, identity: &RsaIdentity) -> Result<Self, NetError> {
        let socket = UdpSocket::bind(addr)?;
        let context = dtls_context(identity)?;
        let mut ssl = Ssl::new(&context)?;
        ssl.set_mtu(MTU)?;
        let stream = SslStream::new(ssl, UdpPeer::new(socket))?;

        Ok(Self {
            stream,
            connected: false,
        })
    }

    /// The actual bound address (useful when binding port 0).
    ///
    /// # Errors
    ///
    /// Returns the socket error from `local_addr`.
    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        self.stream.get_ref().socket.local_addr()
    }

    /// Whether the handshake has completed.
    pub fn is_connected(&self) -> bool {
        self.connected
    }

    /// Queue application data for the peer.
    ///
    /// # Errors
    ///
    /// Returns [`NetError::Ssl`] if the connection is closed or handshaking, or
    /// [`NetError::Io`] if the underlying datagram could not be sent.
    pub fn send_application_data(&mut self, data: &[u8]) -> Result<usize, NetError> {
        self.stream.ssl_write(data).map_err(NetError::Ssl)
    }

    /// Drive one step: advance the handshake, then read application data, for
    /// up to `max_wait`. Returns the milestones observed this step.
    ///
    /// # Errors
    ///
    /// Returns [`NetError`] if the socket fails or OpenSSL reports a fatal
    /// error.
    pub fn step(&mut self, max_wait: Duration) -> Result<Vec<Milestone>, NetError> {
        self.stream
            .get_mut()
            .socket
            .set_read_timeout(Some(max_wait))?;

        let mut events = Vec::new();

        if !self.connected {
            match self.stream.accept() {
                Ok(()) => {
                    self.connected = true;
                    events.push(Milestone::Connected);
                }
                Err(error) if wants_io(&error) => {}
                Err(error) => return Err(NetError::Ssl(error)),
            }
        }

        if self.connected {
            let mut buffer = [0u8; MAX_APPLICATION];
            match self.stream.ssl_read(&mut buffer) {
                Ok(0) => events.push(Milestone::CloseNotify),
                Ok(bytes) => events.push(Milestone::ApplicationData(buffer[..bytes].to_vec())),
                Err(error) if wants_io(&error) => {}
                Err(error) if error.code() == ErrorCode::ZERO_RETURN => {
                    events.push(Milestone::CloseNotify);
                }
                Err(error) => return Err(NetError::Ssl(error)),
            }
        }

        self.stream.get_mut().drain_events(&mut events);
        Ok(events)
    }
}

/// Build the DTLS 1.2 server context around `identity`.
fn dtls_context(identity: &RsaIdentity) -> Result<SslContext, NetError> {
    let mut builder = SslContext::builder(SslMethod::dtls_server())?;
    builder.set_min_proto_version(Some(SslVersion::DTLS1_2))?;
    builder.set_max_proto_version(Some(SslVersion::DTLS1_2))?;
    builder.set_certificate(identity.certificate())?;
    builder.set_private_key(identity.private_key())?;
    builder.check_private_key()?;
    builder.set_verify(SslVerifyMode::NONE);
    Ok(builder.build())
}

/// `true` when OpenSSL wants more datagrams or writability before continuing.
fn wants_io(error: &SslError) -> bool {
    matches!(error.code(), ErrorCode::WANT_READ | ErrorCode::WANT_WRITE)
}

/// A UDP transport for OpenSSL's memory BIO: one datagram per read and write.
///
/// The peer address is learned from the first inbound datagram (the server
/// socket is unconnected), and every milestone the transport observes is queued
/// for [`Server::step`] to drain.
#[derive(Debug)]
struct UdpPeer {
    socket: UdpSocket,
    peer: Option<SocketAddr>,
    events: Vec<Milestone>,
}

impl UdpPeer {
    fn new(socket: UdpSocket) -> Self {
        Self {
            socket,
            peer: None,
            events: Vec::new(),
        }
    }

    /// Move the queued transport milestones into `events`.
    fn drain_events(&mut self, events: &mut Vec<Milestone>) {
        events.append(&mut self.events);
    }
}

impl Read for UdpPeer {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self.socket.recv_from(buf) {
            Ok((bytes, from)) => {
                if self.peer.is_none() {
                    self.peer = Some(from);
                }
                self.events.push(Milestone::Datagram { from, bytes });
                Ok(bytes)
            }
            // A read timeout means "no datagram yet", which is exactly
            // retriable for OpenSSL's DTLS state machine. Windows reports a
            // UDP read timeout as `TimedOut` (WSAETIMEDOUT); OpenSSL's BIO
            // only treats `WouldBlock` as retriable, so normalise it here.
            Err(error) if error.kind() == io::ErrorKind::TimedOut => {
                Err(io::Error::from(io::ErrorKind::WouldBlock))
            }
            Err(error) => Err(error),
        }
    }
}

impl Write for UdpPeer {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let Some(peer) = self.peer else {
            return Err(io::Error::new(
                io::ErrorKind::NotConnected,
                "no peer datagram received yet",
            ));
        };
        let bytes = self.socket.send_to(buf, peer)?;
        self.events.push(Milestone::FlightSent { to: peer, bytes });
        Ok(bytes)
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
