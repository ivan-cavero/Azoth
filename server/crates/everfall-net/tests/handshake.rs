//! Loopback proof that the crate is wired correctly.
//!
//! This runs a real `openssl`-crate DTLS 1.2 client against
//! [`everfall_net::Server`] over real loopback UDP. Both sides must reach
//! `Connected`, and one application-data round trip must complete. It proves
//! the ceremony and the RSA certificate are valid to a peer; it does **not**
//! prove the New World client accepts them, because the stock client pins its
//! own trust root.

use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use everfall_net::{Milestone, NetError, RsaIdentity, Server};
use openssl::nid::Nid;
use openssl::ssl::{ErrorCode, Ssl, SslContext, SslMethod, SslStream};

const PING: &[u8] = b"everfall-ping";
const PONG: &[u8] = b"everfall-pong";
const DEADLINE: Duration = Duration::from_secs(10);
const IO_WAIT: Duration = Duration::from_millis(100);
const MTU: u32 = 1200;
const MAX_RECORD: usize = 4096;

#[test]
fn openssl_dtls12_handshake_and_round_trip_over_loopback() {
    let identity = RsaIdentity::generate().expect("server identity");
    let server =
        Server::bind("127.0.0.1:0".parse().expect("server addr"), &identity).expect("bind server");
    let server_addr = server.local_addr().expect("server local addr");

    let stop = Arc::new(AtomicBool::new(false));
    let server_thread = {
        let stop = Arc::clone(&stop);
        thread::spawn(move || run_server(server, &stop))
    };

    let client_connected = run_client(server_addr).expect("client run");

    stop.store(true, Ordering::Relaxed);
    let milestones = server_thread.join().expect("server thread panicked");

    assert!(client_connected, "client did not reach Connected");
    assert!(
        milestones.contains(&Milestone::Connected),
        "server did not reach Connected: {milestones:?}"
    );
    assert!(
        milestones
            .iter()
            .any(|m| matches!(m, Milestone::Datagram { .. })),
        "server saw no datagrams: {milestones:?}"
    );
    assert!(
        milestones
            .iter()
            .any(|m| matches!(m, Milestone::FlightSent { .. })),
        "server sent no flights: {milestones:?}"
    );
    assert!(
        milestones
            .iter()
            .any(|m| matches!(m, Milestone::ApplicationData(data) if data.as_slice() == PING)),
        "server did not receive the ping: {milestones:?}"
    );
}

#[test]
fn certificate_is_rsa_2048_with_cn_new_world() {
    let identity = RsaIdentity::generate().expect("identity");
    let certificate = identity.certificate();

    let key = certificate.public_key().expect("public key");
    let rsa = key.rsa().expect("RSA public key");
    assert_eq!(rsa.size(), 256, "RSA modulus must be 2048 bits (256 bytes)");

    let subject_cn = certificate
        .subject_name()
        .entries_by_nid(Nid::COMMONNAME)
        .next()
        .expect("subject CN entry");
    assert_eq!(subject_cn.data().as_slice(), b"New World");

    let issuer_cn = certificate
        .issuer_name()
        .entries_by_nid(Nid::COMMONNAME)
        .next()
        .expect("issuer CN entry");
    assert_eq!(issuer_cn.data().as_slice(), b"New World");
}

/// Drive the server until told to stop, echoing the ping back as the pong.
fn run_server(mut server: Server, stop: &AtomicBool) -> Vec<Milestone> {
    let mut milestones = Vec::new();
    while !stop.load(Ordering::Relaxed) {
        let events = server
            .step(Duration::from_millis(100))
            .expect("server step failed");

        for event in &events {
            if let Milestone::ApplicationData(data) = event
                && data.as_slice() == PING
            {
                server.send_application_data(PONG).expect("queue pong");
            }
        }
        milestones.extend(events);
    }
    milestones
}

/// Run the `openssl` client to `Connected` plus one application-data round trip.
fn run_client(server_addr: SocketAddr) -> Result<bool, NetError> {
    let context = SslContext::builder(SslMethod::dtls_client())
        .map_err(NetError::Stack)?
        .build();
    let socket = UdpSocket::bind("127.0.0.1:0")?;
    let mut ssl = Ssl::new(&context).map_err(NetError::Stack)?;
    ssl.set_mtu(MTU).map_err(NetError::Stack)?;
    let mut stream = SslStream::new(
        ssl,
        UdpTransport {
            socket,
            peer: server_addr,
        },
    )
    .map_err(NetError::Stack)?;

    let deadline = Instant::now() + DEADLINE;
    loop {
        stream
            .get_ref()
            .socket
            .set_read_timeout(Some(IO_WAIT))
            .expect("client read timeout");

        match stream.connect() {
            Ok(()) => break,
            Err(error) if wants_io(&error) => {}
            Err(error) => return Err(NetError::Ssl(error)),
        }
        if Instant::now() >= deadline {
            return Err(NetError::Io(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "client handshake timed out",
            )));
        }
    }

    stream.ssl_write(PING).map_err(NetError::Ssl)?;

    let deadline = Instant::now() + DEADLINE;
    let mut buffer = [0u8; MAX_RECORD];
    loop {
        stream
            .get_ref()
            .socket
            .set_read_timeout(Some(IO_WAIT))
            .expect("client read timeout");

        match stream.ssl_read(&mut buffer) {
            Ok(bytes) if &buffer[..bytes] == PONG => return Ok(true),
            Ok(_) => {}
            Err(error) if wants_io(&error) => {}
            Err(error) => return Err(NetError::Ssl(error)),
        }
        if Instant::now() >= deadline {
            return Err(NetError::Io(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "client did not receive the pong",
            )));
        }
    }
}

/// `true` when OpenSSL wants more datagrams or writability before continuing.
fn wants_io(error: &openssl::ssl::Error) -> bool {
    matches!(error.code(), ErrorCode::WANT_READ | ErrorCode::WANT_WRITE)
}

/// A UDP transport for rust-openssl's `SslStream`, one datagram per read/write.
struct UdpTransport {
    socket: UdpSocket,
    peer: SocketAddr,
}

impl std::io::Read for UdpTransport {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self.socket.recv_from(buf) {
            Ok((bytes, _from)) => Ok(bytes),
            // See `UdpPeer::read`: a UDP read timeout must reach OpenSSL as
            // `WouldBlock`, or the DTLS state machine treats it as fatal.
            Err(error) if error.kind() == std::io::ErrorKind::TimedOut => {
                Err(std::io::Error::from(std::io::ErrorKind::WouldBlock))
            }
            Err(error) => Err(error),
        }
    }
}

impl std::io::Write for UdpTransport {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.socket.send_to(buf, self.peer)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
