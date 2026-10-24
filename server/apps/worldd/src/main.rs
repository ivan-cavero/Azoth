//! `worldd`: the world server.
//!
//! WHY THIS BINARY EXISTS
//! ======================
//! This is the process a player's client talks to for gameplay: one UDP socket, a fixed 50 Hz tick,
//! and the ladder that takes a registered client to `InGame`. Everything else in the workspace is
//! either a library it uses or a different process it does not talk to on the data path.
//!
//! WHAT IT OWNS, AND WHAT IT DELIBERATELY DOES NOT
//! ===============================================
//! It owns the socket, the per-peer sessions, the ladder, and the state stream. It does **not** own
//! identity or placement: the ticket it validates came from a region, and the character it spawns
//! came from the identity database. That separation is why the world can keep serving its players
//! while the region is unreachable — which is the whole reason the region is not on the data path.
//!
//! NO REPLAY PUMP, AND THAT IS THE ACCEPTANCE
//! =========================================
//! The Python prototype is a replayer: it forwards captured bytes on a timer and its behaviour is
//! tuned by roughly forty `AZOTH_*` environment variables. This binary has **no replay pump and no
//! environment variables at all**. If the client reaches `InGame` against it, the world is
//! originating its own state rather than replaying someone else's — which is the Phase 3 acceptance
//! (`docs/archive/odd-tasks/phase-3-world.md` S5).
//!
//! THE TICK AND THE HANDSHAKE ARE SEPARATE, BY CONSTRUCTION
//! ======================================================
//! `Transport::pump` blocks and does the expensive crypto; the tick never calls it. A player
//! joining mid-tick cannot stall a 20 ms budget because joining does not happen inside one. This is
//! the constraint the plan's §8.1 states, and the crate boundaries enforce it rather than a comment.
//!
//! The two threads talk in both directions over bounded channels: events go to the tick, and the
//! datagrams the tick decides on go back to the thread that owns the socket. The return path is
//! drained around every `pump`, so a datagram waits at most one poll interval (≤ 100 ms) to be
//! written. That bound is why the tick is the *output clock* rather than a reply pump: a peer that
//! owes no state still gets its keepalive every tick ([`crate::egress`]), and the socket thread is
//! what turns 50 Hz of decisions into 50 Hz of writes.
//!
//! WHAT AN OPERATOR CAN SEE, AND WHY IT IS OPT-IN
//! ==============================================
//! With no flag this binary prints one line per *lifecycle* decision and nothing per datagram, which
//! leaves one question unanswerable: did the client send anything at all? `--diagnostics` installs a
//! trace sink on the transport and prints one line per datagram in each direction, plus the
//! classification of what arrived — see [`crate::diagnostics`], and plan §12 for why the hex dump is
//! a flag rather than a default.
//!
//! WHERE THE CAPTURED BODIES COME FROM
//! ==================================
//! The ladder's two captured payloads are compiled in from the fixture that records their provenance
//! and their build (`crates/azoth-wire/tests/fixtures/`, S8), not read from a path at startup. The
//! library crate deliberately does not embed them (S7), so the app layer is where a captured byte
//! string becomes servable — and compiling them in means a world cannot start against a half-copied
//! fixture set, which would reach `WaitingForPlayerSpawn` and stop there with no error.

pub mod config;
pub mod diagnostics;
pub mod entry;
pub mod ladder;
pub mod ops;
pub mod presence;
pub mod tick;
pub mod tickets;

// `egress` is declared by `entry` (see its module docs: the integration tests compile `entry.rs`
// without it) and re-exported here so the obvious path works from anywhere in the binary.
pub use entry::egress;

use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::Arc;
use std::thread;

use azoth_dtls::{DtlsConfig, Identity, Transport, TransportEvent};
use azoth_wire::ladder::{LEVEL_INFO_CHANGED_TAIL, LEVEL_INFO_CHANGED_TYPE};
use azoth_wire::spawn::SpawnRecord;

use crate::config::Config;
use crate::diagnostics::Diagnostics;
use crate::egress::Outbound;
use crate::entry::WorldEntry;
use crate::tick::{Tick, TickEvent};

/// The captured spawn payload, `record_id 1` and 48 fragments.
const SPAWN_TEMPLATE: &[u8] =
    include_bytes!("../../../crates/azoth-wire/tests/fixtures/spawn-record-1.bin");
/// The captured `LevelInfoChanged` body, wire type `0x663`, as hex in its provenance fixture.
const LADDER_FIXTURE: &str =
    include_str!("../../../crates/azoth-wire/tests/fixtures/ladder.json");

/// Run the world until the process is stopped.
///
/// # Errors
/// A bind failure, a transport failure that leaves the socket unusable, a ticket file that is not
/// there, or a captured template that no longer has its measured shape.
pub fn run(config: Config) -> Result<(), Box<dyn std::error::Error>> {
    let tickets = tickets::TicketStore::load(Path::new(tickets::DEFAULT_PATH))?;
    let (level_info_body, spawn_payload) = captured_bodies()?;
    eprintln!(
        "[worldd] {} ticket(s) from {}",
        tickets.len(),
        tickets::DEFAULT_PATH
    );
    let entry = WorldEntry::new(tickets, level_info_body, spawn_payload);

    let identity = Identity::load_or_generate(&config.cert_dir)?;
    let dtls_config = DtlsConfig {
        bind: config.bind,
        ..DtlsConfig::default()
    };
    let transport = Transport::bind(&dtls_config, identity)?;
    eprintln!("[worldd] listening {}", transport.local_addr()?);
    let (transport, diagnostics) = attach_diagnostics(&config, transport);
    let (to_tick, from_net) = mpsc::sync_channel::<TickEvent>(1024);
    let (to_net, from_tick) = mpsc::sync_channel::<Outbound>(4096);
    let mut tick = Tick::new(config.tick_hz, from_net, to_tick.clone());
    tick.attach_entry(entry, to_net);
    // The world re-reads the ticket file every tick, because `regiond` mints a ticket *after* this
    // process has started: the measured defect was a client that handshook and registered against a
    // world holding zero tickets, so nothing ever answered it.
    tick.attach_ticket_file(PathBuf::from(tickets::DEFAULT_PATH));
    eprintln!("[worldd] tick {} Hz", config.tick_hz);

    let _net = thread::spawn(move || serve(transport, to_tick, from_tick, diagnostics));

    // `run` never returns: the world serves until the process is stopped. The socket thread is
    // detached deliberately — it exits when the tick's channel closes, which only happens on
    // shutdown.
    tick.run()
}

/// The socket's thread: pump, forward events, write what the tick decided.
fn serve(
    mut transport: Transport,
    to_tick: mpsc::SyncSender<TickEvent>,
    from_tick: mpsc::Receiver<Outbound>,
    diagnostics: Option<Arc<Diagnostics>>,
) {
    loop {
        write_pending(&mut transport, &from_tick);
        let events = match transport.pump() {
            Ok(events) => events,
            Err(err) => {
                eprintln!("[worldd] transport error: {err}");
                return;
            }
        };
        for event in events {
            // The lifecycle line goes out before the event is forwarded, so a log reads in the order
            // the transport observed things.
            if let Some(active) = &diagnostics {
                active.event(&event);
            }
            // A full channel means the ticker is behind. Dropping the event is the right failure:
            // the alternative is unbounded memory, and a stale handshake event is worth less than
            // the process staying alive.
            if to_tick.send(map_event(event)).is_err() {
                return; // the ticker is gone; nothing left to serve
            }
        }
        write_pending(&mut transport, &from_tick);
    }
}

/// Install the trace sink `--diagnostics` asks for, returning what the event path needs.
///
/// The transport is returned unchanged when the flag is absent: no sink is installed, so nothing on
/// the datagram path formats or allocates (plan §12, plan §18.8).
/// The note sink's body: one line, same prefix as the transport trace.
fn note_line(peer: std::net::SocketAddr, reason: &str) {
    eprintln!("[worldd] diagnostics peer={peer} note={reason}");
}

fn attach_diagnostics(
    config: &Config,
    mut transport: Transport,
) -> (Transport, Option<Arc<Diagnostics>>) {
    let diagnostics = diagnostics::from_config(config);
    if let Some(active) = &diagnostics {
        active.install(&mut transport);
        eprintln!("[worldd] diagnostics on: one line per datagram, first 16 bytes in hex");
    }
    (transport, diagnostics)
}

/// Write every datagram the tick has decided on, without blocking.
fn write_pending(transport: &mut Transport, from_tick: &mpsc::Receiver<Outbound>) {
    while let Ok(out) = from_tick.try_recv() {
        // A refused send is a peer the transport no longer holds, or a datagram that does not fit
        // one record. Both are reported rather than retried: every rung is a reliable record, so a
        // lost datagram is the resend table's job, not this loop's.
        if let Err(err) = transport.send(out.peer, &out.datagram) {
            eprintln!("[worldd] send to {} failed: {err}", out.peer);
        }
    }
}

/// Map a transport event into the ticker's vocabulary.
///
/// The two crates are separate on purpose — `azoth-dtls` knows nothing about sessions and
/// `azoth-session` knows nothing about sockets — so the app layer is where their types meet.
fn map_event(event: TransportEvent) -> TickEvent {
    match event {
        TransportEvent::Established(peer) => TickEvent::Established(peer),
        TransportEvent::Data { peer, bytes } => TickEvent::Data { peer, bytes },
        TransportEvent::Dropped(peer) => TickEvent::Dropped(peer),
    }
}

/// The ladder's two captured bodies, validated against their measured shape.
fn captured_bodies() -> Result<(Vec<u8>, Vec<u8>), Box<dyn std::error::Error>> {
    let spawn = SpawnRecord::from_template(SPAWN_TEMPLATE)?;
    let fixture: serde_json::Value = serde_json::from_str(LADDER_FIXTURE)?;
    let hex = fixture["level_info_changed"]["body_hex"]
        .as_str()
        .ok_or("ladder.json carries no level_info_changed.body_hex")?;
    let body = decode_hex(hex)?;
    // The same arithmetic `azoth_wire::ladder`'s own test does: two length-prefixed strings, four
    // f32, two u32, four flag bytes, and the tail nobody has explained yet.
    let expected = (1 + azoth_wire::ladder::DEFAULT_LEVEL.len())
        + (1 + azoth_wire::ladder::DEFAULT_LEVEL_PREFIX.len())
        + 16
        + 8
        + 4
        + LEVEL_INFO_CHANGED_TAIL;
    if body.len() != expected || LEVEL_INFO_CHANGED_TYPE != 0x663 {
        return Err(format!(
            "the LevelInfoChanged body is {} bytes, the measured layout says {expected}",
            body.len()
        )
        .into());
    }
    Ok((body, spawn.payload().to_vec()))
}

/// Decode the fixture's hex, which is how a captured body is stored so a diff is readable.
fn decode_hex(text: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let digit = |byte: u8| (byte as char).to_digit(16).ok_or("a non-hex digit in the fixture");
    let mut out = Vec::with_capacity(text.len() / 2);
    for pair in text.as_bytes().chunks_exact(2) {
        out.push((digit(pair[0])? * 16 + digit(pair[1])?) as u8);
    }
    if text.len() % 2 != 0 {
        return Err("an odd number of hex digits in the fixture".into());
    }
    Ok(out)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = match Config::from_args(std::env::args().skip(1)) {
        Ok(config) => config,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    run(config)
}
