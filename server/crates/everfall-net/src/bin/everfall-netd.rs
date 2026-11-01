//! `everfall-netd` -- the DTLS spike server.
//!
//! Binds a UDP socket (default `127.0.0.1:9000`, the client's REP address),
//! mints an RSA 2048 self-signed certificate (`CN=New World`) in memory, and
//! drives an OpenSSL DTLS 1.2 handshake from a blocking loop. Every milestone
//! is printed with a wall-clock timestamp so the live attempt is readable from
//! the terminal.
//!
//! The port comes from the first CLI argument, else `EVERFALL_NET_PORT`, else
//! `9000`.

use std::env;
use std::fmt::Arguments;
use std::net::{Ipv4Addr, SocketAddr};
use std::process::ExitCode;
use std::time::Duration;

use everfall_net::{Milestone, RsaIdentity, Server};

/// Default port: the client's measured REP address.
const DEFAULT_PORT: u16 = 9000;

/// Print one timestamped line.
fn log(args: Arguments<'_>) {
    println!("[{}] {args}", stamp());
}

/// Timestamp for every log line.
fn stamp() -> String {
    time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap_or_else(|_| String::from("(no-clock)"))
}

fn main() -> ExitCode {
    let port = match port_from_args_or_env() {
        Ok(port) => port,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::FAILURE;
        }
    };
    let bind = SocketAddr::from((Ipv4Addr::LOCALHOST, port));

    let certificate = match RsaIdentity::generate() {
        Ok(identity) => identity,
        Err(error) => {
            log(format_args!("{error}"));
            return ExitCode::FAILURE;
        }
    };

    let mut server = match Server::bind(bind, &certificate) {
        Ok(server) => server,
        Err(error) => {
            log(format_args!("bind failed: {error}"));
            return ExitCode::FAILURE;
        }
    };

    log(format_args!(
        "everfall-netd listening on {bind} (DTLS 1.2, RSA 2048 self-signed CN=New World, minted in memory)"
    ));

    loop {
        match server.step(Duration::from_secs(1)) {
            Ok(events) => {
                for event in events {
                    match event {
                        Milestone::Datagram { from, bytes } => {
                            log(format_args!("datagram received: {bytes} bytes from {from}"));
                        }
                        Milestone::FlightSent { to, bytes } => {
                            log(format_args!("flight sent: {bytes} bytes to {to}"));
                        }
                        Milestone::Connected => log(format_args!("Connected")),
                        Milestone::ApplicationData(data) => {
                            log(format_args!("application data: {} bytes", data.len()));
                        }
                        Milestone::CloseNotify => log(format_args!("close_notify")),
                    }
                }
            }
            Err(error) => {
                log(format_args!("fatal Error: {error}"));
                return ExitCode::FAILURE;
            }
        }
    }
}

/// Resolve the bind port from `argv[1]`, else `EVERFALL_NET_PORT`, else 9000.
fn port_from_args_or_env() -> Result<u16, String> {
    if let Some(arg) = env::args().nth(1) {
        return arg
            .parse()
            .map_err(|_| format!("invalid port argument: {arg:?}"));
    }
    match env::var("EVERFALL_NET_PORT") {
        Ok(value) => value
            .parse()
            .map_err(|_| format!("invalid EVERFALL_NET_PORT: {value:?}")),
        Err(_) => Ok(DEFAULT_PORT),
    }
}
