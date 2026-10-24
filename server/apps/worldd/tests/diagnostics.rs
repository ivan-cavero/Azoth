//! What the diagnostics report, and what they stay quiet about.
//!
//! WHY THESE TESTS DRIVE `Transport` DIRECTLY
//! ==========================================
//! The gap this feature closes sits between the socket and the session: a datagram that arrives and
//! produces **no** [`TransportEvent`] at all. Only a real socket shows that, so the tests put a
//! `Transport` on a loopback port and read the lines its sink produced — the same arrangement
//! `crates/azoth-dtls/tests/handshake.rs` uses for the handshake itself, minus the OpenSSL client
//! (which `worldd` cannot depend on; the completed handshake is proved there and against the running
//! binary).
//!
//! The modules are included by `#[path]` because `worldd` is a binary crate, exactly as
//! `tests/entry.rs` does it: the real `Diagnostics`, the real classification and the real flag
//! parser are what these assertions are about.

#[path = "../src/config.rs"]
mod config;
#[path = "../src/diagnostics.rs"]
mod diagnostics;

use std::net::{SocketAddr, UdpSocket};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use azoth_dtls::{DtlsConfig, Identity, Transport, TransportEvent};

use crate::config::Config;
use crate::diagnostics::Diagnostics;

/// How long a test waits before declaring a hang.
const PATIENCE: Duration = Duration::from_secs(10);

/// One RSA pair for the whole binary: generating one per test would cost seconds and assert nothing.
fn identity() -> Identity {
    static IDENTITY: OnceLock<Identity> = OnceLock::new();
    IDENTITY
        .get_or_init(|| Identity::generate().expect("generate the server identity"))
        .clone()
}

/// A transport on an OS-chosen loopback port.
fn transport() -> Transport {
    transport_with(DtlsConfig::default().handshake_timeout)
}

/// The same, with a handshake deadline short enough for a test to reach it.
fn transport_with(handshake_timeout: Duration) -> Transport {
    let config = DtlsConfig {
        bind: "127.0.0.1:0".parse().expect("a literal address"),
        handshake_timeout,
        ..DtlsConfig::default()
    };
    Transport::bind(&config, identity()).expect("bind the loopback socket")
}

/// A UDP socket standing in for the game client, with a timeout so a missing reply fails rather than
/// hangs.
fn client() -> UdpSocket {
    let socket = UdpSocket::bind("127.0.0.1:0").expect("bind the client socket");
    socket
        .set_read_timeout(Some(PATIENCE))
        .expect("a read timeout");
    socket
}

/// Every line the diagnostics wrote, in order.
#[derive(Clone, Default)]
struct Recorder(Arc<Mutex<Vec<String>>>);

impl Recorder {
    fn lines(&self) -> Vec<String> {
        self.0.lock().expect("the recorder lock").clone()
    }

    /// How many `inbound` lines have been written.
    fn inbound(&self) -> usize {
        self.lines()
            .iter()
            .filter(|line| line.contains(" inbound "))
            .count()
    }

    /// A writer the diagnostics can render into.
    fn sink(&self) -> Box<dyn Fn(&str) + Send + Sync> {
        let lines = Arc::clone(&self.0);
        Box::new(move |line: &str| {
            lines
                .lock()
                .expect("the recorder lock")
                .push(line.to_owned());
        })
    }
}

/// Install diagnostics on `transport`, writing into `recorder`, and return the state the event path
/// needs — the same two halves `worldd`'s socket thread wires together.
fn watch(transport: &mut Transport, recorder: &Recorder) -> Arc<Diagnostics> {
    let diagnostics = Arc::new(Diagnostics::to_sink(recorder.sink()));
    diagnostics.install(transport);
    diagnostics
}

/// Pump until `done` says so, reporting every event to the diagnostics as `worldd` does and
/// returning them.
fn pump_until(
    transport: &mut Transport,
    diagnostics: &Diagnostics,
    done: impl Fn() -> bool,
) -> Vec<TransportEvent> {
    let deadline = Instant::now() + PATIENCE;
    let mut events = Vec::new();
    while !done() {
        assert!(
            Instant::now() < deadline,
            "the transport never reported the datagram"
        );
        for event in transport.pump().expect("pump the transport") {
            diagnostics.event(&event);
            events.push(event);
        }
    }
    events
}

/// The one datagram the server answered `client` with.
fn reply(client: &UdpSocket) -> Vec<u8> {
    let mut buf = [0u8; 2048];
    let (len, _) = client.recv_from(&mut buf).expect("a reply from the server");
    buf[..len].to_vec()
}

/// A hand-built DTLS 1.2 ClientHello: record content type 22, version `0xFEFD`, no cookie.
///
/// This is the shape that produces a HelloVerifyRequest and **no** [`TransportEvent`], which is the
/// case the trace exists for. Only what OpenSSL reads before it answers is set: the version, a
/// random, an empty session id, an empty cookie, the one suite the client offers (`0xC030`), null
/// compression, and no extensions.
fn client_hello() -> Vec<u8> {
    /// The body: version (2) + random (32) + session id (1) + cookie (1) + suites (4) + compression
    /// (2) + extensions (2).
    const BODY: usize = 44;

    let mut body = Vec::with_capacity(BODY);
    body.extend_from_slice(&[0xFE, 0xFD]); // client_version, DTLS 1.2
    body.extend_from_slice(&[0x5A; 32]); // random
    body.push(0); // session_id length
    body.push(0); // cookie length: the first flight, so no cookie
    body.extend_from_slice(&[0x00, 0x02, 0xC0, 0x30]); // cipher suites: 0xC030 only
    body.extend_from_slice(&[0x01, 0x00]); // compression methods: null
    body.extend_from_slice(&[0x00, 0x00]); // extensions: none
    assert_eq!(body.len(), BODY);

    let body_len = u8::try_from(BODY).expect("the body fits one length byte");
    let mut handshake = vec![1u8]; // ClientHello
    handshake.extend_from_slice(&[0, 0, body_len]); // message length
    handshake.extend_from_slice(&[0, 0]); // message_seq
    handshake.extend_from_slice(&[0, 0, 0]); // fragment_offset
    handshake.extend_from_slice(&[0, 0, body_len]); // fragment_length
    handshake.extend_from_slice(&body);

    let mut record = vec![22u8, 0xFE, 0xFD, 0, 0]; // handshake, DTLS 1.2, epoch 0
    record.extend_from_slice(&[0; 6]); // record sequence
    record.extend_from_slice(&u16::try_from(handshake.len()).expect("a small record").to_be_bytes());
    record.extend_from_slice(&handshake);
    record
}

/// The `[worldd] diagnostics inbound` line, for the address and payload the test used.
fn inbound_line(client: &UdpSocket, len: usize, class: &str, hex: &str) -> String {
    let from: SocketAddr = client.local_addr().expect("the client address");
    format!("[worldd] diagnostics inbound from={from} len={len} {class} hex={hex}")
}

/// The `[worldd] diagnostics peer` line for the first datagram from an address.
fn new_peer_line(client: &UdpSocket) -> String {
    let from: SocketAddr = client.local_addr().expect("the client address");
    format!("[worldd] diagnostics peer={from} event=new")
}

#[test]
fn a_client_hello_is_classified_as_dtls_with_its_type_and_version() {
    let mut transport = transport();
    let recorder = Recorder::default();
    let diagnostics = watch(&mut transport, &recorder);
    let client = client();
    let server = transport.local_addr().expect("the bound address");

    let hello = client_hello();
    client.send_to(&hello, server).expect("send the ClientHello");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() > 0);

    let lines = recorder.lines();
    assert_eq!(
        lines[0],
        new_peer_line(&client),
        "the first datagram from an address announces the peer"
    );
    assert_eq!(
        lines[1],
        inbound_line(
            &client,
            hello.len(),
            "class=dtls type=22 version=FEFD",
            // The 13-byte record header plus the first three handshake bytes: content type 22,
            // version 0xFEFD, epoch 0, sequence 0, record length 0x0038, ClientHello (1).
            "16fefd00000000000000000038010000"
        ),
        "the inbound line names the source, the length and the classification"
    );
    assert_eq!(recorder.inbound(), 1, "one datagram, one line: {lines:?}");
}

#[test]
fn a_non_dtls_datagram_is_reported_as_not_dtls() {
    let mut transport = transport();
    let recorder = Recorder::default();
    let diagnostics = watch(&mut transport, &recorder);
    let client = client();
    let server = transport.local_addr().expect("the bound address");

    let garbage = b"GET / HTTP/1.1\r\n";
    client.send_to(garbage, server).expect("send the garbage");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() > 0);

    let lines = recorder.lines();
    assert_eq!(
        lines[1],
        inbound_line(&client, garbage.len(), "class=not-dtls", "474554202f20485454502f312e310d0a"),
        "a datagram that is not DTLS is still reported, and says so"
    );
    assert_eq!(recorder.inbound(), 1, "one datagram, one line: {lines:?}");
}

#[test]
fn with_diagnostics_off_a_datagram_produces_no_output() {
    // Off unless asked for: `run` installs nothing when the flag is absent, so the transport has no
    // sink and pays one `Option` check per datagram (plan §12 — the prototype's 7.3 GB log).
    assert!(
        diagnostics::from_config(&Config::default()).is_none(),
        "no flag, no diagnostics"
    );
    let asked = Config::from_args(["--diagnostics".to_string()]).expect("parses");
    assert!(
        diagnostics::from_config(&asked).is_some(),
        "the flag installs them"
    );

    let mut transport = transport();
    let recorder = Recorder::default();
    let diagnostics = watch(&mut transport, &recorder);
    let server = transport.local_addr().expect("the bound address");

    let loud = client();
    loud.send_to(&client_hello(), server).expect("send the first");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() == 1);

    // Turning tracing off is what `run` does by not installing a sink. The next datagram is still
    // handled — a second peer appears — and writes nothing.
    transport.set_trace(None);
    let quiet = client();
    quiet.send_to(&client_hello(), server).expect("send the second");
    let deadline = Instant::now() + PATIENCE;
    while transport.peer_count() < 2 {
        assert!(
            Instant::now() < deadline,
            "the second peer was never created, so the silence proves nothing"
        );
        for event in transport.pump().expect("pump the transport") {
            diagnostics.event(&event);
        }
    }
    assert_eq!(
        recorder.inbound(),
        1,
        "with no sink installed a datagram produces no output: {:?}",
        recorder.lines()
    );
}

#[test]
fn garbage_after_a_valid_peer_does_not_kill_the_network_loop() {
    // A short handshake deadline, so the test reaches the drop path without sleeping for 30 s.
    let mut transport = transport_with(Duration::from_millis(400));
    let recorder = Recorder::default();
    let diagnostics = watch(&mut transport, &recorder);
    let server = transport.local_addr().expect("the bound address");

    // A well-formed ClientHello: the transport answers with a HelloVerifyRequest and holds a peer.
    let first = client();
    first
        .send_to(&client_hello(), server)
        .expect("send the first ClientHello");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() == 1);
    let verify = reply(&first);
    assert_eq!(verify[0], 22, "a handshake record");
    assert_eq!(verify[13], 3, "HelloVerifyRequest");
    assert_eq!(transport.peer_count(), 1);

    // Garbage from that same address. OpenSSL ignores a record whose content type it does not know,
    // so the peer survives it; the point of the assertion is that `pump` returned normally, because
    // one player's broken state machine must never take the socket down.
    first
        .send_to(b"not a dtls record at all", server)
        .expect("send garbage");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() == 2);

    // The loop still expires what it holds: the half-open handshake times out and says so.
    pump_until(&mut transport, &diagnostics, || {
        recorder.lines().iter().any(|line| line.contains("event=dropped"))
    });
    assert_eq!(transport.peer_count(), 0, "the deadline still expires the peer");

    // A second peer is still served: the loop is alive and its send path still works.
    let second = client();
    second
        .send_to(&client_hello(), server)
        .expect("send the second ClientHello");
    pump_until(&mut transport, &diagnostics, || recorder.inbound() == 3);
    assert_eq!(
        reply(&second)[13],
        3,
        "the second peer is answered with its own HelloVerifyRequest"
    );
}

#[test]
fn a_client_hello_produces_a_received_trace_and_no_transport_event() {
    let mut transport = transport();
    let recorder = Recorder::default();
    let diagnostics = watch(&mut transport, &recorder);
    let client = client();
    let server = transport.local_addr().expect("the bound address");

    let hello = client_hello();
    client.send_to(&hello, server).expect("send the ClientHello");
    let events = pump_until(&mut transport, &diagnostics, || recorder.inbound() > 0);

    // The gap this closes: the transport saw the datagram, and had nothing to tell the tick about.
    assert!(
        events.is_empty(),
        "a ClientHello completes no session, so it produces no event: {events:?}"
    );
    let lines = recorder.lines();
    assert!(
        lines
            .iter()
            .any(|line| line.contains("class=dtls type=22 version=FEFD")),
        "the datagram must still be visible: {lines:?}"
    );
}
