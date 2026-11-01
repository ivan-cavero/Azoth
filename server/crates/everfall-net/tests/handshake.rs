//! Loopback proof that the crate is wired correctly.
//!
//! This runs a real dimpl client against [`everfall_net::Server`] over real
//! loopback UDP and asserts both sides reach `Connected`, then exchanges one
//! application-data round trip. It proves the ceremony and the certificate are
//! valid to a peer. It does **not** prove the New World client accepts ECDSA;
//! that is the live attempt the parent runs.

use std::io::ErrorKind;
use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use dimpl::{Config, Dtls, Output};
use everfall_net::{Milestone, NetError, Server, self_signed_p256};

const PING: &[u8] = b"everfall-ping";
const PONG: &[u8] = b"everfall-pong";
const DEADLINE: Duration = Duration::from_secs(10);

#[test]
fn dtls12_handshake_and_round_trip_over_loopback() {
    let server = Server::bind(
        "127.0.0.1:0".parse().expect("server addr"),
        self_signed_p256().expect("server certificate"),
    )
    .expect("bind server");
    let server_addr = server.local_addr().expect("server local addr");

    let stop = Arc::new(AtomicBool::new(false));
    let server_thread = {
        let stop = Arc::clone(&stop);
        thread::spawn(move || run_server(server, &stop))
    };

    let (client_connected, got_pong) = run_client(server_addr).expect("client run");

    stop.store(true, Ordering::Relaxed);
    let milestones = server_thread.join().expect("server thread panicked");

    assert!(client_connected, "client did not reach Connected");
    assert!(
        got_pong,
        "client did not receive the echoed application data"
    );
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

/// Run the client to `Connected` plus one application-data round trip.
fn run_client(server_addr: SocketAddr) -> Result<(bool, bool), NetError> {
    let config = Arc::new(
        Config::builder()
            .require_client_certificate(false)
            .build()
            .expect("client config"),
    );
    let mut client = Dtls::new_12(
        config,
        self_signed_p256().expect("client cert"),
        Instant::now(),
    );
    client.set_active(true);

    let socket = UdpSocket::bind("127.0.0.1:0").expect("client socket");
    socket.connect(server_addr).expect("connect client socket");

    let deadline = Instant::now() + DEADLINE;
    let mut connected = false;
    let mut sent_ping = false;
    let mut got_pong = false;
    let mut buffer = vec![0u8; 2048];

    while Instant::now() < deadline {
        let now = Instant::now();
        client.handle_timeout(now)?;

        let mut wait = Duration::from_millis(100);
        loop {
            match client.poll_output(&mut buffer) {
                Output::Packet(packet) => {
                    socket.send(packet).expect("client send");
                }
                Output::BufferTooSmall { needed } => buffer.resize(needed, 0),
                Output::Timeout(timeout) => {
                    wait = timeout.saturating_duration_since(now).min(wait);
                    break;
                }
                Output::Connected => connected = true,
                Output::ApplicationData(data) if data == PONG => got_pong = true,
                _ => {}
            }
        }

        if connected && !sent_ping {
            client.send_application_data(PING)?;
            sent_ping = true;
            // Loop again so the ping is flushed before we block on the socket.
            continue;
        }
        if connected && got_pong {
            break;
        }

        socket
            .set_read_timeout(Some(wait))
            .expect("client read timeout");

        let mut inbound = [0u8; 2048];
        match socket.recv(&mut inbound) {
            Ok(bytes) => client.handle_packet(&inbound[..bytes])?,
            Err(error) if is_timeout(&error) => {}
            Err(error) => return Err(NetError::Io(error)),
        }
    }

    Ok((connected, got_pong))
}

fn is_timeout(error: &std::io::Error) -> bool {
    matches!(error.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut)
}
