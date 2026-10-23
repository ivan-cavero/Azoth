//! The behaviours the world server's DTLS transport must have, driven by a **real** OpenSSL DTLS
//! client over loopback.
//!
//! WHY A REAL CLIENT AND NOT A REPLAYED CLIENTHELLO: this crate's constraints describe what a DTLS
//! *implementation* does — one usable cipher suite, and a cookie round the client insists on
//! (`docs/PLAN-backend-rust.md` §0.3). An OpenSSL client restricted to
//! `ECDHE-RSA-AES256-GCM-SHA384` proves the single-cipher constraint is satisfiable and performs the
//! cookie exchange itself; a replayed ClientHello would only prove a parser accepts bytes. Every
//! assertion below goes through the public API or the wire.
//!
//! WHAT IS DELIBERATELY NOT ASSERTED: the record-layer version of the first server flight. The
//! official server sent `0xFEFF` (DTLS 1.0) there; our OpenSSL 3.6.5 sends `0xFEFF` for the
//! HelloVerifyRequest and `0xFEFD` for the ServerHello. The client accepts both — the OpenSSL-based
//! Python prototype reaches `InGame` without ever setting a record version — so the byte is
//! OpenSSL's to choose and this crate must not force either value.

use std::io::{self, Read, Write};
use std::net::{SocketAddr, UdpSocket};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use azoth_dtls::{DtlsConfig, Identity, Transport, TransportEvent};
use openssl::ssl::{ErrorCode, Ssl, SslContext, SslMethod, SslStream, SslVerifyMode, SslVersion};

/// `0xC030`, the only suite the game client offers, by its OpenSSL name.
const ONLY_SUITE: &str = "ECDHE-RSA-AES256-GCM-SHA384";
/// Handshake message types (RFC 6347).
const CLIENT_HELLO: u8 = 1;
const SERVER_HELLO: u8 = 2;
const HELLO_VERIFY_REQUEST: u8 = 3;
/// How long a test waits before declaring a hang: the server thread signs with RSA-2048 at startup.
const PATIENCE: Duration = Duration::from_secs(20);

/// Every datagram the client's socket saw, in order, with `true` for client→server. One
/// interleaved list rather than two: a round trip is only visible on a single timeline.
type Recorder = Arc<Mutex<Vec<(bool, Vec<u8>)>>>;

/// An ephemeral loopback bind: port 0, read back from the socket, so no two tests — parallel or
/// not — can ever collide on an address.
fn loopback() -> SocketAddr {
    "127.0.0.1:0".parse().expect("a literal address")
}

/// One RSA pair for the whole binary; generating it per test would cost seconds and assert nothing.
fn shared_identity() -> Identity {
    static IDENTITY: OnceLock<Identity> = OnceLock::new();
    IDENTITY.get_or_init(|| Identity::generate().expect("generate the server identity")).clone()
}

/// A world server on its own thread — the placement `pump`'s blocking shape forces.
///
/// The command channel exists because [`Transport::pump`] only *receives*; sending is a separate
/// call that the test drives, and a `None` command stops the thread.
struct World {
    addr: SocketAddr,
    events: Receiver<TransportEvent>,
    commands: Sender<Option<(SocketAddr, Vec<u8>)>>,
    thread: Option<JoinHandle<()>>,
}

impl World {
    /// Bind `config` and serve on a thread of its own; `addr` is the port the OS chose.
    fn start(config: DtlsConfig) -> Self {
        let mut transport = Transport::bind(&config, shared_identity()).expect("bind the socket");
        let addr = transport.local_addr().expect("read the bound address");
        let (event_tx, events) = mpsc::channel();
        let (commands, command_rx) = mpsc::channel::<Option<(SocketAddr, Vec<u8>)>>();
        let thread = thread::spawn(move || {
            loop {
                while let Ok(command) = command_rx.try_recv() {
                    let Some((peer, bytes)) = command else { return };
                    transport.send(peer, &bytes).expect("send");
                }
                for event in transport.pump().expect("pump the world socket") {
                    if event_tx.send(event).is_err() {
                        return;
                    }
                }
            }
        });
        Self { addr, events, commands, thread: Some(thread) }
    }

    /// The next event `wanted` accepts, discarding the rest.
    fn wait_for(
        &self,
        wanted: impl Fn(&TransportEvent) -> bool,
        within: Duration,
    ) -> Option<TransportEvent> {
        let deadline = Instant::now() + within;
        loop {
            let remaining = deadline.checked_duration_since(Instant::now())?;
            match self.events.recv_timeout(remaining) {
                Ok(event) if wanted(&event) => return Some(event),
                Ok(_) => {}
                Err(_) => return None,
            }
        }
    }

    fn established(&self, peer: SocketAddr) -> bool {
        let seen = |e: &TransportEvent| matches!(e, TransportEvent::Established(a) if *a == peer);
        self.wait_for(seen, PATIENCE).is_some()
    }

    fn dropped(&self, peer: SocketAddr, within: Duration) -> bool {
        let seen = |e: &TransportEvent| matches!(e, TransportEvent::Dropped(a) if *a == peer);
        self.wait_for(seen, within).is_some()
    }

    fn next_data(&self) -> Option<(SocketAddr, Vec<u8>)> {
        let wanted = |e: &TransportEvent| matches!(e, TransportEvent::Data { .. });
        match self.wait_for(wanted, PATIENCE)? {
            TransportEvent::Data { peer, bytes } => Some((peer, bytes)),
            _ => None,
        }
    }

    fn send(&self, peer: SocketAddr, bytes: &[u8]) {
        self.commands.send(Some((peer, bytes.to_vec()))).expect("the world thread is alive");
    }
}

impl Drop for World {
    fn drop(&mut self) {
        let _ = self.commands.send(None);
        let _ = self.thread.take().map(|thread| thread.join());
    }
}

/// A UDP socket presented to OpenSSL as a byte stream, recording every datagram it carries.
///
/// The buffering is not optional: OpenSSL's DTLS reader asks the BIO for the 13-byte record header
/// first and the body second, so handing it a whole datagram in one `read` would truncate.
struct ClientIo {
    socket: UdpSocket,
    peer: SocketAddr,
    inbound: Vec<u8>,
    wire: Recorder,
}

impl ClientIo {
    fn record(&self, from_client: bool, bytes: Vec<u8>) {
        self.wire.lock().expect("not poisoned").push((from_client, bytes));
    }
}

impl Read for ClientIo {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        while self.inbound.is_empty() {
            let mut datagram = [0u8; 2048];
            match self.socket.recv_from(&mut datagram) {
                Ok((len, from)) if from == self.peer => {
                    self.record(false, datagram[..len].to_vec());
                    self.inbound.extend_from_slice(&datagram[..len]);
                }
                Ok(_) => continue,
                Err(e) if quiet(&e) => return Err(io::ErrorKind::WouldBlock.into()),
                Err(e) => return Err(e),
            }
        }
        let len = buf.len().min(self.inbound.len());
        buf[..len].copy_from_slice(&self.inbound[..len]);
        self.inbound.drain(..len);
        Ok(len)
    }
}

impl Write for ClientIo {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let len = self.socket.send_to(buf, self.peer)?;
        self.record(true, buf[..len].to_vec());
        Ok(len)
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn quiet(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut | io::ErrorKind::ConnectionReset
    )
}

/// A DTLS 1.2 client offering only `0xC030`, like the game client does.
struct Client {
    stream: SslStream<ClientIo>,
    local: SocketAddr,
    wire: Recorder,
}

impl Client {
    fn connect(world: SocketAddr, local: Option<SocketAddr>) -> Result<Self, String> {
        let local = local.unwrap_or_else(loopback);
        let wire = Recorder::default();
        let socket = UdpSocket::bind(local).map_err(|e| format!("bind {local}: {e}"))?;
        let patience = Some(Duration::from_millis(50));
        socket.set_read_timeout(patience).map_err(|e| format!("read timeout: {e}"))?;
        let local = socket.local_addr().map_err(|e| format!("local addr: {e}"))?;
        let mut ssl = Ssl::new(&client_context()).map_err(|e| format!("new session: {e}"))?;
        ssl.set_connect_state();
        let io = ClientIo { socket, peer: world, inbound: Vec::new(), wire: Arc::clone(&wire) };
        let stream = SslStream::new(ssl, io).map_err(|e| format!("wrap the socket: {e}"))?;
        let mut client = Self { stream, local, wire };
        client.drive(|s| s.do_handshake())?;
        Ok(client)
    }

    /// Retry `step` while OpenSSL asks for more data, until [`PATIENCE`] runs out.
    fn drive<T>(
        &mut self,
        mut step: impl FnMut(&mut SslStream<ClientIo>) -> Result<T, openssl::ssl::Error>,
    ) -> Result<T, String> {
        let deadline = Instant::now() + PATIENCE;
        loop {
            match step(&mut self.stream) {
                Ok(value) => return Ok(value),
                Err(e) if e.code() == ErrorCode::WANT_READ => {}
                Err(e) => return Err(e.to_string()),
            }
            if Instant::now() >= deadline {
                return Err("no progress before the deadline".to_owned());
            }
        }
    }

    fn send(&mut self, plaintext: &[u8]) -> Result<(), String> {
        self.drive(|s| s.ssl_write(plaintext)).map(|_| ())
    }

    fn recv(&mut self) -> Result<Vec<u8>, String> {
        let mut buf = [0u8; 4096];
        self.drive(|s| s.ssl_read(&mut buf)).map(|n| buf[..n].to_vec())
    }

    /// Every datagram the socket saw, in the order it saw them.
    fn frames(&self) -> Vec<(bool, Vec<u8>)> {
        self.wire.lock().expect("not poisoned").clone()
    }
}

/// A client context offering exactly the one suite the game client offers.
fn client_context() -> SslContext {
    let mut builder = SslContext::builder(SslMethod::dtls_client()).expect("DTLS client context");
    builder.set_cipher_list(ONLY_SUITE).expect("the single suite");
    builder.set_min_proto_version(Some(SslVersion::DTLS1_2)).expect("floor");
    builder.set_max_proto_version(Some(SslVersion::DTLS1_2)).expect("ceiling");
    // A self-signed server certificate, and a client whose verify path is patched on disk.
    builder.set_verify(SslVerifyMode::NONE);
    builder.build()
}

fn handshake_type(datagram: &[u8]) -> Option<u8> {
    datagram.first().filter(|kind| **kind == 22)?;
    datagram.get(13).copied()
}

/// `client_version`(2) + `random`(32) + `session_id_len`(1) + session id + `cookie_len`(1), past the
/// 13-byte record header and the 12-byte handshake header.
fn client_hello_cookie_len(datagram: &[u8]) -> Option<usize> {
    let session_id_len = usize::from(*datagram.get(13 + 12 + 34)?);
    Some(usize::from(*datagram.get(13 + 12 + 35 + session_id_len)?))
}

#[test]
fn a_client_offering_only_the_one_suite_completes_a_handshake() {
    let world = World::start(DtlsConfig::new(loopback()));
    let client = Client::connect(world.addr, None).expect("the client completes a handshake");
    let cipher = client.stream.ssl().current_cipher();
    assert_eq!(cipher.map(|c| c.name()), Some(ONLY_SUITE), "the only suite offered");
    assert_eq!(client.stream.ssl().version_str(), "DTLSv1.2", "client_version 0xFEFD, nothing else");
    assert!(world.established(client.local), "reported as established");
}

#[test]
fn the_cookieless_first_flight_does_not_complete_in_one_round_trip() {
    let world = World::start(DtlsConfig::new(loopback()));
    let client = Client::connect(world.addr, None).expect("the client completes a handshake");
    let frames = client.frames();

    // NOT asserted here: the record-layer version. The official server sent 0xFEFF, our OpenSSL
    // sends 0xFEFF for the HelloVerifyRequest and 0xFEFD for the ServerHello, the client accepts
    // both, and the byte is OpenSSL's to choose (see the module docs). This test owns the shape.
    let at = |wanted: u8, from_client: bool| {
        frames.iter().position(|(ours, d)| *ours == from_client && handshake_type(d) == Some(wanted))
    };
    let first = at(CLIENT_HELLO, true).expect("the client opens with a ClientHello");
    let verify = at(HELLO_VERIFY_REQUEST, false)
        .expect("a cookieless ClientHello must be answered with a HelloVerifyRequest");
    let hello =
        at(SERVER_HELLO, false).expect("the cookie-bearing ClientHello must then be answered");
    let second = (first + 1..frames.len())
        .find(|&at| frames[at].0 && handshake_type(&frames[at].1) == Some(CLIENT_HELLO))
        .expect("the client retries with a cookie");

    // One round trip cannot finish the exchange: the server answers the cookieless ClientHello with
    // a HelloVerifyRequest, and only the flight that carries the cookie back earns a ServerHello.
    assert!(first < verify, "the HelloVerifyRequest answers the first ClientHello");
    assert!(verify < second, "the second flight follows the HelloVerifyRequest");
    assert!(second < hello, "the ServerHello only follows the cookie-bearing flight");
    assert_eq!(client_hello_cookie_len(&frames[first].1), Some(0), "the first is cookieless");
    assert!(
        client_hello_cookie_len(&frames[second].1).is_some_and(|len| len > 0),
        "the second carries the cookie the server issued"
    );
    assert!(world.established(client.local), "the exchange completes on the second flight");
}

#[test]
fn application_data_round_trips_in_both_directions() {
    let world = World::start(DtlsConfig::new(loopback()));
    let mut client = Client::connect(world.addr, None).expect("the client completes a handshake");
    assert!(world.established(client.local));

    client.send(b"client to server").expect("the client writes");
    let (peer, bytes) = world.next_data().expect("the transport surfaces the plaintext");
    assert_eq!(peer, client.local, "the data is attributed to its sender");
    assert_eq!(bytes, b"client to server", "the plaintext must survive the record layer");

    world.send(client.local, b"server to client");
    assert_eq!(client.recv().expect("the client reads"), b"server to client");
}

#[test]
fn one_socket_tracks_two_peers_independently() {
    let world = World::start(DtlsConfig::new(loopback()));
    let mut first = Client::connect(world.addr, None).expect("the first client handshakes");
    let mut second = Client::connect(world.addr, None).expect("the second client handshakes");
    assert_ne!(first.local, second.local, "the demux keys on the address");
    assert!(world.established(first.local));
    assert!(world.established(second.local));

    first.send(b"from the first").expect("first writes");
    second.send(b"from the second").expect("second writes");
    let seen: Vec<_> = (0..2).map(|_| world.next_data().expect("both peers' data arrive")).collect();
    assert!(seen.contains(&(first.local, b"from the first".to_vec())));
    assert!(seen.contains(&(second.local, b"from the second".to_vec())));

    world.send(second.local, b"only the second");
    assert_eq!(second.recv().expect("second reads"), b"only the second");
    world.send(first.local, b"only the first");
    assert_eq!(first.recv().expect("first reads"), b"only the first");
}

#[test]
fn a_fresh_client_hello_from_a_known_address_replaces_the_session() {
    let world = World::start(DtlsConfig::new(loopback()));
    let first = Client::connect(world.addr, None).expect("the first session handshakes");
    let port = first.local.port();
    assert!(world.established(first.local));
    // The client is gone, but the server still holds its session — that is the whole hazard.
    drop(first);

    // The source port comes from the first ephemeral bind, so nothing here is a fixed port; the OS
    // may need a moment to release it, hence the retries.
    let reuse = SocketAddr::from(([127, 0, 0, 1], port));
    let mut second = (0..50)
        .find_map(|attempt| {
            if attempt > 0 {
                thread::sleep(Duration::from_millis(50));
            }
            Client::connect(world.addr, Some(reuse)).ok()
        })
        .expect("the client reuses its source port after a session ends");
    let reused = second.local;
    assert_eq!(reused.port(), port, "the reused port is the test");
    assert!(world.dropped(reused, PATIENCE), "the old session must be dropped");
    assert!(world.established(reused), "the rebuilt session must handshake");

    let payload = b"new session, same port".to_vec();
    second.send(&payload).expect("the new session writes");
    let wanted = |e: &TransportEvent| matches!(e, TransportEvent::Data { bytes, .. } if *bytes == payload);
    assert!(world.wait_for(wanted, PATIENCE).is_some(), "the rebuilt session carries data");
}

#[test]
fn a_peer_that_never_finishes_its_handshake_is_dropped() {
    let timeout = Duration::from_millis(300);
    let world = World::start(DtlsConfig {
        bind: loopback(),
        max_datagram: 1200,
        handshake_timeout: timeout,
    });
    let silent = UdpSocket::bind(loopback()).expect("bind a silent peer");
    let silent_addr = silent.local_addr().expect("its address");
    // A record header promising 200 body bytes and delivering none: the session is created, the
    // handshake can never progress, and OpenSSL raises no error — the half-open state this exists for.
    let truncated = [22u8, 0xFE, 0xFD, 0, 0, 0, 0, 0, 0, 0, 0, 0, 200];
    silent.send_to(&truncated, world.addr).expect("send the truncated record");
    assert!(
        world.dropped(silent_addr, timeout * 20),
        "a peer that sends one datagram and nothing else must be dropped after {timeout:?}"
    );
}
