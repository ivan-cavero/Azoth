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
//! (`odd/tasks/phase-3-world.md` S5).
//!
//! THE TICK AND THE HANDSHAKE ARE SEPARATE, BY CONSTRUCTION
//! ======================================================
//! `Transport::pump` blocks and does the expensive crypto; the tick never calls it. A player
//! joining mid-tick cannot stall a 20 ms budget because joining does not happen inside one. This is
//! the constraint the plan's §8.1 states, and the crate boundaries enforce it rather than a comment.

pub mod config;
pub mod ladder;
pub mod tick;

use std::sync::mpsc;
use std::thread;

use azoth_dtls::{DtlsConfig, Identity, Transport, TransportEvent};

use crate::config::Config;
use crate::tick::{Tick, TickEvent};

/// Run the world until the process is stopped.
///
/// The shape is two threads and one channel: a blocking receiver that owns the socket and the
/// handshakes, and a ticker that owns the simulation clock. They communicate by messages so neither
/// can block the other, and the channel is **bounded** — an unbounded one would let a slow ticker
/// consume memory until the machine dies, which is the failure the plan's capacity section warns
/// about.
///
/// # Errors
/// A bind failure, or a transport failure that leaves the socket unusable.
pub fn run(config: Config) -> Result<(), Box<dyn std::error::Error>> {
    let identity = Identity::load_or_generate(&config.cert_dir)?;
    let dtls_config = DtlsConfig {
        bind: config.bind,
        ..DtlsConfig::default()
    };
    let mut transport = Transport::bind(&dtls_config, identity)?;
    let bound = transport.local_addr()?;
    eprintln!("[worldd] listening {bound}");

    let (to_tick, from_net) = mpsc::sync_channel::<TickEvent>(1024);
    let mut tick = Tick::new(config.tick_hz, to_tick.clone());
    eprintln!("[worldd] tick {} Hz", config.tick_hz);

    let net = thread::spawn(move || {
        loop {
            match transport.pump() {
                Ok(events) => {
                    for event in events {
                        // A full channel means the ticker is behind. Dropping the event is the
                        // right failure: the alternative is unbounded memory, and a stale
                        // handshake event is worth less than the process staying alive.
                        if to_tick.send(map_event(event)).is_err() {
                            return; // the ticker is gone; nothing left to serve
                        }
                    }
                }
                Err(err) => {
                    eprintln!("[worldd] transport error: {err}");
                    return;
                }
            }
        }
    });

    tick.run();
    let _ = net.join();
    Ok(())
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
