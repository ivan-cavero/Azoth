//! Opt-in inbound/outbound diagnostics: what the transport actually saw.
//!
//! WHY IT IS OFF BY DEFAULT, AND WHY THAT IS NOT TIMIDITY
//! =====================================================
//! Hex-dumping datagrams is the most useful thing a broken REP session can produce, and it is also
//! the fastest way to take a machine down. The prototype turned it on unconditionally once: a live
//! world sends ~200 datagrams/s of ~1 KB, `OUTBOUND_PAYLOAD_LOG` hex-dumped every one of them, and
//! `world.log` grew at ~1 MB/s until one afternoon of experiments had left **7.3 GB** on a disk at
//! 78% (`STATUS.md`, 2026-10-19; `docs/ROADMAP.md` §4; plan §12). The visible symptom was the game
//! becoming unresponsive and the client being killed, which was briefly misdiagnosed as a client
//! bug. The prototype's fix was to make the verbose form opt-in, and plan §18.8 states the rule this
//! module keeps: a payload dump is a debug feature, not a log level.
//!
//! So `--diagnostics` is off unless an operator asks for it, and the operator then owns the
//! consequence. The volume is not incidental: one line per datagram in each direction is ~2.5× the
//! datagram rate, which is a deliberate choice made for a *short* investigation, not a setting a
//! world runs with.
//!
//! WHAT IT PRINTS, AND WHY EACH LINE EXISTS
//! =======================================
//! One line per event on stderr, each prefixed `[worldd] diagnostics` so `grep` is the only tool
//! needed:
//!
//! * `inbound from=<addr> len=<n> class=<...> hex=<16 bytes>` — a raw datagram arrived. The
//!   classification is the DTLS record content type and version (`class=dtls type=22 version=FEFD`)
//!   or `class=not-dtls`. This is the line that separates "the client sent nothing" from "the
//!   client sent something this server could not use".
//! * `outbound to=<addr> len=<n> hex=<16 bytes>` — a datagram is about to be written.
//! * `unroutable from=<addr> len=<n> reason=<phrase> hex=<16 bytes>` — a datagram had nowhere to go.
//! * `peer=<addr> event=<new|established|dropped>` — the session lifecycle. `new` is the first
//!   datagram from an address with no session, which is the only way a ClientHello is ever visible:
//!   it produces no [`TransportEvent`] at all.
//!
//! Only the first 16 bytes are shown. That is enough to identify content type, version, epoch and
//! record sequence — the fields that say *what kind of traffic this is* — and it is what keeps a
//! line short enough to grep and to read on a terminal.
//!
//! WHY THE ADDRESS BOOKKEEPING LIVES HERE AND NOT IN THE TRANSPORT
//! ==============================================================
//! The transport reports observations; deciding that an address is a *new peer* is a judgement about
//! the session table, which the transport already keeps and does not expose. So this module keeps the
//! addresses it has announced and drops one when the transport says the session went away, which
//! costs a `HashSet` insert per datagram and only while diagnostics are on.

use std::collections::HashSet;
use std::fmt::Write as _;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use azoth_dtls::{Transport, TransportEvent, TransportTrace};

use crate::config::Config;

/// How many leading bytes of a datagram a line shows: enough for a DTLS record header, short enough
/// to stay readable and greppable.
const PREFIX: usize = 16;

/// The DTLS record content types RFC 6347 defines: `change_cipher_spec` (20) through
/// `application_data` (23). 24 (`heartbeat`) is deliberately outside — it is an extension, and this
/// server's client never sends one, so a datagram starting with it is not traffic we understand.
const DTLS_CONTENT_TYPES: std::ops::RangeInclusive<u8> = 20..=23;

/// The diagnostics a configuration asks for, or `None` when `--diagnostics` was not given.
///
/// `None` is what keeps the cost at zero: no sink is installed, so the transport pays one `Option`
/// check per datagram and this module never allocates.
#[must_use]
pub fn from_config(config: &Config) -> Option<Arc<Diagnostics>> {
    config.diagnostics.then(|| Arc::new(Diagnostics::to_stderr()))
}

/// The line writer, shared by the transport thread and the event path.
pub struct Diagnostics {
    /// Where a rendered line goes. A `Fn` rather than `FnMut` so the whole object can be shared.
    write: Box<dyn Fn(&str) + Send + Sync>,
    /// The addresses already announced as new, so `event=new` prints once per session.
    seen: Mutex<HashSet<SocketAddr>>,
}

impl Diagnostics {
    /// A sink that writes one line per event to stderr.
    #[must_use]
    pub fn to_stderr() -> Self {
        Self::to_sink(Box::new(|line| eprintln!("{line}")))
    }

    /// A sink that hands every rendered line to `write`, which is how a test captures them.
    #[must_use]
    pub fn to_sink(write: Box<dyn Fn(&str) + Send + Sync>) -> Self {
        Self {
            write,
            seen: Mutex::new(HashSet::new()),
        }
    }

    /// Install this as the transport's trace sink, so every datagram it sees becomes a line.
    pub fn install(self: &Arc<Self>, transport: &mut Transport) {
        let shared = Arc::clone(self);
        transport.set_trace(Some(Box::new(move |trace| shared.trace(&trace))));
    }

    /// Report one transport event: the three session transitions worth a line.
    ///
    /// Decrypted application data is deliberately silent. The `inbound` line already showed the
    /// datagram that carried it, and a line per record is the shape that produced 7.3 GB.
    pub fn event(&self, event: &TransportEvent) {
        match event {
            TransportEvent::Established(peer) => self.emit(&format!("peer={peer} event=established")),
            TransportEvent::Dropped(peer) => {
                self.forget(peer);
                self.emit(&format!("peer={peer} event=dropped"));
            }
            TransportEvent::Data { .. } => {}
        }
    }

    /// Render one observation, announcing a first-seen address before its inbound line.
    fn trace(&self, trace: &TransportTrace<'_>) {
        match trace {
            TransportTrace::Received { from, bytes } => {
                if self.announce(from) {
                    self.emit(&format!("peer={from} event=new"));
                }
                self.emit(&format!(
                    "inbound from={from} len={} {} hex={}",
                    bytes.len(),
                    classify(bytes),
                    hex_prefix(bytes)
                ));
            }
            TransportTrace::Sending { to, bytes } => self.emit(&format!(
                "outbound to={to} len={} hex={}",
                bytes.len(),
                hex_prefix(bytes)
            )),
            TransportTrace::Unroutable {
                from,
                bytes,
                reason,
            } => {
                // No session was created, so the next datagram from here is new again.
                self.forget(from);
                self.emit(&format!(
                    "unroutable from={from} len={} reason={reason} hex={}",
                    bytes.len(),
                    hex_prefix(bytes)
                ));
            }
        }
    }

    /// Whether this address is being announced for the first time, recording it either way.
    fn announce(&self, addr: &SocketAddr) -> bool {
        self.seen
            .lock()
            .is_ok_and(|mut seen| seen.insert(*addr))
    }

    /// Stop treating this address as a live peer.
    fn forget(&self, addr: &SocketAddr) {
        if let Ok(mut seen) = self.seen.lock() {
            seen.remove(addr);
        }
    }

    /// Write one rendered line, prefixed so every diagnostics line greps the same way.
    fn emit(&self, line: &str) {
        (self.write)(&format!("[worldd] diagnostics {line}"));
    }
}

/// The classification field: a DTLS content type and version, or `not-dtls`.
///
/// Only the first three bytes are read, because those are the record's type and version and they
/// are present in *every* DTLS datagram regardless of what the rest of it contains. A datagram too
/// short to hold them cannot be DTLS, and saying so is the point of the field.
fn classify(bytes: &[u8]) -> String {
    match bytes {
        [content, version_hi, version_lo, ..] if DTLS_CONTENT_TYPES.contains(content) => {
            format!("class=dtls type={content} version={version_hi:02X}{version_lo:02X}")
        }
        _ => "class=not-dtls".to_string(),
    }
}

/// The first [`PREFIX`] bytes as lowercase hex, which is what makes two lines comparable by eye.
fn hex_prefix(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(PREFIX * 2);
    for byte in bytes.iter().take(PREFIX) {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_dtls_record_header_is_classified_with_its_type_and_version() {
        let hello = [22u8, 0xFE, 0xFD, 0, 0, 0, 0];
        assert_eq!(classify(&hello), "class=dtls type=22 version=FEFD");
    }

    #[test]
    fn every_content_type_from_change_cipher_spec_to_application_data_is_dtls() {
        for content in DTLS_CONTENT_TYPES {
            let record = [content, 0xFE, 0xFD];
            assert!(
                classify(&record).starts_with("class=dtls"),
                "content type {content}"
            );
        }
        // 24 is heartbeat: an extension this client never sends.
        assert_eq!(classify(&[24, 0xFE, 0xFD]), "class=not-dtls");
    }

    #[test]
    fn a_datagram_too_short_for_a_record_header_is_not_dtls() {
        assert_eq!(classify(&[]), "class=not-dtls");
        assert_eq!(classify(&[22, 0xFE]), "class=not-dtls");
    }

    #[test]
    fn the_hex_prefix_is_capped_at_sixteen_bytes() {
        let long = [0xABu8; 32];
        assert_eq!(hex_prefix(&long), "ab".repeat(PREFIX));
        assert_eq!(hex_prefix(&[]), "");
    }
}

/// A process-wide note channel, so a deep code path can report why it did nothing.
///
/// WHY A GLOBAL: the diagnostics sink lives in `main`, and threading a handle down into
/// `WorldEntry::registration` would change every signature for a path that exists to explain
/// failures. It is set once at startup and read-only afterwards; when nothing is installed the cost
/// is one atomic load.
static NOTE_SINK: std::sync::OnceLock<fn(std::net::SocketAddr, &str)> = std::sync::OnceLock::new();

/// Install the note sink. Called once, from `main`, only when diagnostics are on.
pub fn install_note_sink(sink: fn(std::net::SocketAddr, &str)) {
    let _ = NOTE_SINK.set(sink);
}

/// Report why a code path produced nothing. Silent when no sink is installed.
pub fn note(peer: std::net::SocketAddr, reason: &str) {
    if let Some(sink) = NOTE_SINK.get() {
        sink(peer, reason);
    }
}
