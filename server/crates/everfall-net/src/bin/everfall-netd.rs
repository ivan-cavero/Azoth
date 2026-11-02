//! `everfall-netd` -- the DTLS spike server and REP carrier driver.
//!
//! Binds a UDP socket (default `127.0.0.1:9000`, the client's REP address),
//! mints an RSA 2048 self-signed certificate (`CN=New World`) in memory, and
//! drives an OpenSSL DTLS 1.2 handshake from a blocking loop. Every milestone
//! is printed with a wall-clock timestamp so the live attempt is readable from
//! the terminal.
//!
//! Each decrypted application datagram is handed to [`everfall_world::RepSession`],
//! which answers the Carrier `SM_CONNECT_REQUEST` with the acceptance flight and
//! the client's V3 registration with the `0x3` response. Those reply datagrams
//! are written back through the same DTLS session, which is what carries the
//! client past `WaitingForREPConnection`.
//!
//! Once the registration is answered, the session's post-registration ladder is
//! released on the server's own clock: the self-identification record, level
//! info, and the state bundle the emitter authors. The rungs are loaded from the
//! committed corpus and re-encoded through their Atlas cards, so the BYTES are
//! the server's framing while the VALUES are still the capture's until the
//! simulation owns them.
//!
//! The port comes from the first CLI argument, else `EVERFALL_NET_PORT`, else
//! `9000`.

use std::env;
use std::fmt::Arguments;
use std::fs;
use std::net::{Ipv4Addr, SocketAddr};
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use everfall_net::{Milestone, RsaIdentity, Server};
use everfall_world::{Decision, PostV3Ladder, RepSession};

/// Default port: the client's measured REP address.
const DEFAULT_PORT: u16 = 9000;

/// The idle poll when no ladder record is imminent (~50 Hz).
const IDLE_STEP_MS: u64 = 20;

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

/// The server clock in milliseconds, wrapped to the Carrier's `u32` field.
fn clock_ms() -> u32 {
    let millis = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis());
    (millis & 0xFFFF_FFFF) as u32
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

    let mut session = RepSession::new();
    match post_v3_ladder() {
        Ok(ladder) => {
            let rungs = ladder.records().len();
            session.set_ladder(ladder);
            log(format_args!(
                "post-registration ladder armed: {rungs} record(s) (self-ident 0x65c, level info 0x663, emitted state 0x08)"
            ));
        }
        Err(error) => log(format_args!(
            "post-registration ladder unavailable, answering registration only: {error}"
        )),
    }

    loop {
        // Sleep at most until the next ladder record is due, so the reference's
        // 4 ms chunk gap is honoured instead of being rounded up to the idle
        // poll. The session still refuses an early record, so this only wakes it.
        let wait_ms = if server.is_connected() {
            session
                .ladder_wait_ms(clock_ms())
                .map_or(IDLE_STEP_MS, |ms| u64::from(ms).min(IDLE_STEP_MS))
        } else {
            IDLE_STEP_MS
        };
        match server.step(Duration::from_millis(wait_ms.max(1))) {
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
                            answer(&mut session, &mut server, &data);
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
        if server.is_connected() {
            pump_ladder(&mut session, &mut server);
        }
    }
}

/// Send the post-registration datagram the session's clock says is due.
fn pump_ladder(session: &mut RepSession, server: &mut Server) {
    match session.tick(clock_ms()) {
        Ok(replies) => {
            for reply in replies {
                match server.send_application_data(&reply) {
                    Ok(sent) => log(format_args!("ladder sent: {sent} bytes")),
                    Err(error) => log(format_args!("ladder send failed: {error}")),
                }
            }
        }
        Err(error) => log(format_args!("ladder error: {error}")),
    }
}

/// Hand one decrypted datagram to the world and send every reply it returns.
fn answer(session: &mut RepSession, server: &mut Server, data: &[u8]) {
    let was_answered = session.v3_responded();
    match session.on_app_data(data, clock_ms()) {
        Ok(replies) => {
            if replies.is_empty() {
                log(format_args!("no carrier reply"));
            }
            for reply in replies {
                match server.send_application_data(&reply) {
                    Ok(sent) => log(format_args!("rep reply sent: {sent} bytes")),
                    Err(error) => log(format_args!("rep reply failed: {error}")),
                }
            }
        }
        Err(error) => log(format_args!("rep error: {error}")),
    }
    if !was_answered && session.v3_responded() {
        log(format_args!(
            "registration answered: the client should now pass WaitingForREPConnection"
        ));
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

/// The repository root, from this crate's compile-time manifest directory.
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn read_text(relative: &str) -> Result<String, String> {
    fs::read_to_string(repo_root().join(relative)).map_err(|error| format!("{relative}: {error}"))
}

/// Decode a `"<hex>"` string into bytes.
fn hex_bytes(hex: &str) -> Result<Vec<u8>, String> {
    if !hex.len().is_multiple_of(2) {
        return Err(format!("odd hex length: {}", hex.len()));
    }
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16)
                .map_err(|error| format!("hex digit pair: {error}"))
        })
        .collect()
}

/// One committed body for a wire id from `wire-bodies.json`.
fn wire_body(text: &str, wire_id: u32) -> Option<Vec<u8>> {
    let needle = format!("\"wire_id\": {wire_id},");
    let at = text.find(&needle)?;
    let body_key = "\"body\": \"";
    let body_at = text[at..].find(body_key)? + body_key.len() + at;
    let rest = &text[body_at..];
    let end = rest.find('"')?;
    hex_bytes(&rest[..end]).ok()
}

/// The captured `0x9e` state bundle body, marker included.
fn state_bundle_body(text: &str, source: &str) -> Option<Vec<u8>> {
    let needle = format!("\"source\": \"{source}\"");
    let at = text.find(&needle)?;
    let body_key = "\"body\": \"";
    let body_at = text[..at].rfind(body_key)? + body_key.len();
    let rest = &text[body_at..];
    let end = rest.find('"')?;
    hex_bytes(&rest[..end]).ok()
}

/// The measured `(key, type_index, payload_len)` extents of the bundle.
fn fragment_extents(text: &str) -> Vec<(u64, u64, usize)> {
    let mut out = Vec::new();
    let mut current: Option<(u64, u64, usize)> = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("\"key\": ") {
            if let Some(done) = current.take() {
                out.push(done);
            }
            current = Some((number(rest), 0, 0));
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"type_index\": "), current.as_mut())
        {
            slot.1 = number(rest);
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"payload_length\": "), current.as_mut())
        {
            slot.2 = number(rest) as usize;
        }
    }
    if let Some(done) = current {
        out.push(done);
    }
    out
}

fn number(field: &str) -> u64 {
    field.trim_end_matches(',').parse().unwrap_or(0)
}

/// Load and re-encode the post-registration rungs from the committed corpus.
///
/// The message bodies are decoded into their Atlas cards by
/// [`PostV3Ladder::from_captured`], and the state rung is re-emitted from typed
/// components, so the bytes are the server's even though the values are still
/// the capture's.
fn post_v3_ladder() -> Result<PostV3Ladder, String> {
    let bodies = read_text("research/fixtures/wire/wire-bodies.json")?;
    let self_identification = wire_body(&bodies, 0x65c).ok_or("0x65c body absent")?;
    let level_info = wire_body(&bodies, 0x663).ok_or("0x663 body absent")?;

    let bundles = read_text("research/fixtures/wire/wire-fixtures.json")?;
    let state = state_bundle_body(&bundles, "0x9e_T0x8_R.bin").ok_or("0x9e bundle absent")?;

    let fragments = read_text("research/derived/state-bundle-fragments.json")?;
    let extents = fragment_extents(&fragments);
    if extents.len() != 9 {
        return Err(format!(
            "expected 9 bundle extents, found {}",
            extents.len()
        ));
    }

    PostV3Ladder::from_captured(
        &self_identification,
        &level_info,
        &state,
        &extents,
        &Decision::Accepted,
    )
    .map_err(|error| error.to_string())
}
