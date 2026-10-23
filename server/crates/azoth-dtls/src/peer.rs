//! One DTLS session, driven through OpenSSL's memory BIOs instead of a socket.
//!
//! WHY MEMORY BIOS
//! ===============
//! `openssl` has no socket API: `SSL_accept`/`SSL_read` need a `BIO`, and the crate's `SslStream`
//! builds one from any Rust `Read + Write`. That is exactly the prototype's shape with pyOpenSSL —
//! "each peer gets an `SSL.Connection` driven through its internal memory-BIO pair (`bio_write` in,
//! `bio_read` out)" (`rep.py`). The consequence, and the reason [`crate::Transport`] rather than
//! [`Peer`] owns the socket, is that a `Peer` never blocks on I/O: it is handed a datagram and hands
//! datagrams back. That is what makes the handshake movable off the tick (§18.2) in practice.
//!
//! ONE RECORD PER DATAGRAM
//! =======================
//! `SslStream` exposes OpenSSL's output as a **byte stream**, but DTLS needs datagram boundaries.
//! [`Peer`] splits the output at record boundaries using the 13-byte record header, so every
//! datagram carries exactly one record — what all 125,485 packets of the 1.460 capture turn out to
//! be, and what identifies the REP flow in the first place (§0.3) — and each stays inside the path
//! MTU without a second fragmentation scheme.
//!
//! THE COOKIE EXCHANGE, AND WHY THE COOKIE IS STATELESS
//! ===================================================
//! OpenSSL's DTLS server sends no HelloVerifyRequest without a cookie generator, and it verifies the
//! returned cookie against one: by default against the cookie *this* `SSL` object generated
//! (`ssl/statem/statem_srvr.c`, `app_verify_cookie_cb` else `s->d1->cookie`). That default is
//! unusable here, because a session is rebuilt whenever a ClientHello restarts the exchange
//! ([`crate::socket`] says when), and a fresh object has no cookie to compare against: it would
//! reject the cookie, send another HelloVerifyRequest, and the client would loop.
//!
//! So this crate installs its own generator and verifier and makes the cookie **stateless**:
//! `SHA-256(secret ‖ peer address)` truncated to 20 bytes, with `secret` 32 random bytes per
//! [`server_context`]. Rebuilding a session then costs nothing and still proves the client can
//! receive at the address it claims — a spoofed source never receives the HelloVerifyRequest, so it
//! can never produce a cookie that verifies. 20 bytes is the length the official server used (§0.3).
//!
//! The first flight's record version is not ours to control and not one we need to: OpenSSL 3.6.5
//! sends `0xFEFF` for the HelloVerifyRequest but `0xFEFD` for the ServerHello, while the official
//! server sent `0xFEFF` for both — their build, not a protocol requirement — so we force neither.

use std::io::{self, Read, Write};
use std::net::SocketAddr;
use std::sync::OnceLock;

use openssl::error::ErrorStack;
use openssl::ex_data::Index;
use openssl::hash::{Hasher, MessageDigest};
use openssl::rand::rand_bytes;
use openssl::ssl::{
    ErrorCode, Ssl, SslContext, SslContextBuilder, SslMethod, SslOptions, SslStream, SslVerifyMode,
    SslVersion,
};

use crate::DtlsError;
use crate::cert::Identity;
use crate::config::DEFAULT_MAX_DATAGRAM;

/// The DTLS record header: type, version, epoch, sequence, length.
const RECORD_HEADER: usize = 13;

/// A DTLS record's length field sits at this offset inside the header.
const RECORD_LENGTH_OFFSET: usize = 11;

/// The cookie length the official server used, measured on the client's second ClientHello.
const COOKIE_LEN: usize = 20;

/// The size of the per-context cookie secret.
const SECRET_LEN: usize = 32;

/// The largest plaintext a single DTLS record can carry before OpenSSL must split it.
const MAX_PLAINTEXT: usize = 16 * 1024 + 1;

/// The suite the client offers and nothing else (`0xC030`).
const CIPHER_LIST: &str = "ECDHE-RSA-AES256-GCM-SHA384";

/// Build the `SslContext` every peer shares.
///
/// Shared because it holds the certificate, the cipher list and the cookie callbacks: the three
/// things identical for every player. The cookie secret lives inside those callbacks and is never
/// exposed, so sharing a context does not share the secret with anyone.
///
/// # Errors
///
/// Returns [`DtlsError::OpenSsl`] if the identity or the random secret cannot be produced.
pub(crate) fn server_context(identity: &Identity) -> Result<SslContext, DtlsError> {
    let mut secret = [0u8; SECRET_LEN];
    rand_bytes(&mut secret)?;

    let index = address_index()?;
    let mut builder = SslContextBuilder::new(SslMethod::dtls_server())?;
    let certificate = identity.certificate()?;
    let private_key = identity.private_key()?;
    builder.set_certificate(&certificate)?;
    builder.set_private_key(&private_key)?;
    // The client offers no certificate and its verify path is patched on disk, so requesting one
    // would only produce a handshake it cannot complete.
    builder.set_verify(SslVerifyMode::NONE);
    builder.set_cipher_list(CIPHER_LIST)?;
    builder.set_min_proto_version(Some(SslVersion::DTLS1_2))?;
    builder.set_max_proto_version(Some(SslVersion::DTLS1_2))?;
    // Without this OpenSSL answers the *cookieless* first ClientHello with a ServerHello, and the
    // measured client never completes that way: it insists on the cookie round.
    builder.set_options(SslOptions::COOKIE_EXCHANGE);

    builder.set_cookie_generate_cb(move |ssl, out| {
        let addr = *ssl.ex_data(index).ok_or_else(ErrorStack::get)?;
        let cookie = cookie_for(&secret, addr)?;
        let slot = out.get_mut(..COOKIE_LEN).ok_or_else(ErrorStack::get)?;
        slot.copy_from_slice(&cookie);
        Ok(COOKIE_LEN)
    });
    builder.set_cookie_verify_cb(move |ssl, offered| {
        let Some(addr) = ssl.ex_data(index).copied() else {
            return false;
        };
        cookie_for(&secret, addr).is_ok_and(|expected| constant_time_eq(&expected, offered))
    });

    Ok(builder.build())
}

/// The per-process `SSL` ex-data slot carrying the peer's address into the cookie callbacks. One
/// slot for the process, because it is only a key.
fn address_index() -> Result<Index<Ssl, SocketAddr>, DtlsError> {
    static INDEX: OnceLock<Index<Ssl, SocketAddr>> = OnceLock::new();
    if let Some(index) = INDEX.get() {
        return Ok(*index);
    }
    let created = Ssl::new_ex_index::<SocketAddr>().map_err(DtlsError::OpenSsl)?;
    Ok(*INDEX.get_or_init(|| created))
}

/// `SHA-256(secret ‖ address)`, truncated. Address-dependent by construction, so a cookie is only
/// ever valid for the source address that received it.
fn cookie_for(secret: &[u8; SECRET_LEN], addr: SocketAddr) -> Result<[u8; COOKIE_LEN], ErrorStack> {
    let mut hasher = Hasher::new(MessageDigest::sha256())?;
    hasher.update(secret)?;
    match addr.ip() {
        std::net::IpAddr::V4(v4) => hasher.update(&v4.octets())?,
        std::net::IpAddr::V6(v6) => hasher.update(&v6.octets())?,
    }
    hasher.update(&addr.port().to_be_bytes())?;
    let digest = hasher.finish()?;
    let mut cookie = [0u8; COOKIE_LEN];
    cookie.copy_from_slice(&digest[..COOKIE_LEN]);
    Ok(cookie)
}

/// Compare without an early exit, so timing does not reveal how many leading bytes of a forged
/// cookie were right. Hand-written: a dependency for six lines of `xor` is not worth it.
fn constant_time_eq(expected: &[u8], offered: &[u8]) -> bool {
    if expected.len() != offered.len() {
        return false;
    }
    let mut diff = 0u8;
    for (a, b) in expected.iter().zip(offered) {
        diff |= a ^ b;
    }
    diff == 0
}

/// The memory BIO pair one session is driven through.
///
/// `Read` never blocks: an empty inbound buffer is `WouldBlock`, which `openssl`'s stream BIO turns
/// into `SSL_ERROR_WANT_READ`. That is what lets [`Peer::feed`] return without a finished
/// handshake instead of waiting for one.
#[derive(Default)]
struct MemPipe {
    /// Datagrams waiting for OpenSSL, concatenated. OpenSSL reads records one at a time, so a
    /// datagram is never split across two reads.
    inbound: Vec<u8>,
    /// Bytes OpenSSL wrote that the caller has not sent yet.
    outbound: Vec<u8>,
}

impl MemPipe {
    fn push(&mut self, datagram: &[u8]) {
        self.inbound.extend_from_slice(datagram);
    }

    fn take_outbound(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.outbound)
    }
}

impl Read for MemPipe {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        if self.inbound.is_empty() {
            return Err(io::Error::new(io::ErrorKind::WouldBlock, "no datagram"));
        }
        let n = buf.len().min(self.inbound.len());
        buf[..n].copy_from_slice(&self.inbound[..n]);
        self.inbound.drain(..n);
        Ok(n)
    }
}

impl Write for MemPipe {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.outbound.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// One peer's DTLS session: an `Ssl`, the memory BIO pair it talks through, and its address.
pub struct Peer {
    stream: SslStream<MemPipe>,
    addr: SocketAddr,
    max_datagram: usize,
    established: bool,
    read_buf: Vec<u8>,
}

impl Peer {
    /// Create a session for `addr` with the measured default datagram ceiling.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::OpenSsl`] if OpenSSL cannot allocate the session.
    pub fn new(ctx: &SslContext, addr: SocketAddr) -> Result<Self, DtlsError> {
        Self::with_max_datagram(ctx, addr, DEFAULT_MAX_DATAGRAM)
    }

    /// Create a session whose records are bounded by `max_datagram` instead of the default.
    ///
    /// The bound is handed to OpenSSL as the DTLS link MTU (`SSL_set_mtu`), so a large handshake
    /// message is fragmented into records that fit rather than emitted as one oversized record.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::OpenSsl`] if OpenSSL cannot allocate the session or rejects the MTU.
    pub fn with_max_datagram(
        ctx: &SslContext,
        addr: SocketAddr,
        max_datagram: usize,
    ) -> Result<Self, DtlsError> {
        let mut ssl = Ssl::new(ctx)?;
        ssl.set_accept_state();
        // Read by the cookie callbacks, so it must be set before the first ClientHello is fed:
        // the generator runs while that record is being processed.
        ssl.set_ex_data(address_index()?, addr);
        ssl.set_mtu(u32::try_from(max_datagram).unwrap_or(u32::MAX))?;

        Ok(Self {
            stream: SslStream::new(ssl, MemPipe::default())?,
            addr,
            max_datagram,
            established: false,
            read_buf: vec![0u8; MAX_PLAINTEXT],
        })
    }

    /// Feed one received datagram, returning the datagrams to send back.
    ///
    /// The cookieless ClientHello returns a HelloVerifyRequest; the one carrying the cookie returns
    /// the ServerHello flight; the client's `Finished` returns the server's
    /// `ChangeCipherSpec`/`Finished` and sets [`Peer::is_established`].
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::Ssl`] if OpenSSL rejects the datagram; the caller drops the peer.
    pub fn feed(&mut self, datagram: &[u8]) -> Result<Vec<Vec<u8>>, DtlsError> {
        self.stream.get_mut().push(datagram);

        if !self.established {
            match self.stream.do_handshake() {
                Ok(()) => self.established = true,
                // Not a failure: the exchange takes three ClientHellos, so a partial handshake is
                // the normal state for the first two.
                Err(e) if wants_more(&e) => {}
                Err(e) => return Err(DtlsError::Ssl(e)),
            }
        }

        Ok(self.take_outbound())
    }

    /// Decrypt whatever application data has arrived, one entry per DTLS record.
    ///
    /// Returns nothing until the handshake completes, and nothing when only handshake traffic
    /// arrived. Bytes OpenSSL produces while reading (post-handshake retransmissions) stay in the
    /// outbound buffer and must be collected with [`Peer::take_outbound`].
    /// # Errors
    ///
    /// Returns [`DtlsError::Ssl`] if OpenSSL rejects a record.
    pub fn read_app(&mut self) -> Result<Vec<Vec<u8>>, DtlsError> {
        if !self.established {
            return Ok(Vec::new());
        }
        let mut records = Vec::new();
        loop {
            match self.stream.ssl_read(&mut self.read_buf) {
                // A zero-length read is the peer's `close_notify`: nothing more will arrive.
                Ok(0) => break,
                Ok(n) => records.push(self.read_buf[..n].to_vec()),
                Err(e) if wants_more(&e) => break,
                Err(e) => return Err(DtlsError::Ssl(e)),
            }
        }
        Ok(records)
    }

    /// Encrypt `plaintext` into exactly one datagram.
    ///
    /// One call is one record, so the plaintext must leave room for the record overhead inside
    /// [`crate::DtlsConfig::max_datagram`]. A caller with more to send makes several calls;
    /// batching is a replication decision (`azoth-replica`), not a transport one.
    ///
    /// # Errors
    ///
    /// Returns [`DtlsError::NotEstablished`] before the handshake completes, [`DtlsError::Ssl`] if
    /// OpenSSL rejects the write, and [`DtlsError::DatagramTooLarge`] if the result is not a single
    /// record that fits.
    pub fn write_app(&mut self, plaintext: &[u8]) -> Result<Vec<u8>, DtlsError> {
        if !self.established {
            return Err(DtlsError::NotEstablished(self.addr));
        }
        let written = self.stream.ssl_write(plaintext)?;
        let datagrams = self.take_outbound();

        // A short write or more than one record means OpenSSL fragmented to respect the MTU.
        // Neither can be returned as "one datagram", so it is refused rather than quietly breaking
        // the ~1200-byte rule.
        let single = datagrams.len() == 1;
        let fits = datagrams.first().is_some_and(|d| d.len() <= self.max_datagram);
        if written != plaintext.len() || !single || !fits {
            return Err(DtlsError::DatagramTooLarge {
                len: datagrams.first().map_or(plaintext.len(), Vec::len),
                max: self.max_datagram,
            });
        }
        match datagrams.into_iter().next() {
            Some(record) => Ok(record),
            // Unreachable: `single` above proved there is exactly one.
            None => Err(DtlsError::DatagramTooLarge {
                len: 0,
                max: self.max_datagram,
            }),
        }
    }

    /// `true` once both sides have finished the handshake.
    #[must_use]
    pub fn is_established(&self) -> bool {
        self.established
    }

    /// The address this session's datagrams go to.
    #[must_use]
    pub fn addr(&self) -> SocketAddr {
        self.addr
    }

    /// Collect datagrams OpenSSL produced that no other method returned.
    ///
    /// A caller driving [`Peer`] directly must call this after [`Peer::read_app`]; a caller going
    /// through [`crate::Transport`] does not, because the transport flushes it.
    pub fn take_outbound(&mut self) -> Vec<Vec<u8>> {
        split_records(&self.stream.get_mut().take_outbound())
    }

    /// The datagram ceiling this session was built with.
    #[must_use]
    pub fn max_datagram(&self) -> usize {
        self.max_datagram
    }
}

/// `true` for the "come back when there is more data" codes. Both are normal: the handshake needs
/// the next ClientHello, and the read path runs out of records.
fn wants_more(error: &openssl::ssl::Error) -> bool {
    matches!(error.code(), ErrorCode::WANT_READ | ErrorCode::WANT_WRITE)
}

/// Split a DTLS byte stream into one datagram per record. A trailing partial record is emitted as
/// its own datagram rather than dropped: it cannot normally happen, and dropping it would turn an
/// impossible state into a hang.
fn split_records(mut bytes: &[u8]) -> Vec<Vec<u8>> {
    let mut datagrams = Vec::new();
    while !bytes.is_empty() {
        if bytes.len() < RECORD_HEADER {
            datagrams.push(bytes.to_vec());
            break;
        }
        let length = usize::from(u16::from_be_bytes([
            bytes[RECORD_LENGTH_OFFSET],
            bytes[RECORD_LENGTH_OFFSET + 1],
        ]));
        let total = RECORD_HEADER + length;
        let end = total.min(bytes.len());
        datagrams.push(bytes[..end].to_vec());
        if total > bytes.len() {
            break;
        }
        bytes = &bytes[end..];
    }
    datagrams
}
