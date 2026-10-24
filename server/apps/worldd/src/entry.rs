//! The state machine that turns a registered peer into a spawning one.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! The tick tracked peers and answered nothing: a client could complete its DTLS handshake, send a
//! registration and sit in `WaitingForREPConnection` until it timed out, with no error anywhere. This
//! is the missing half — answer the Carrier, read the V3, validate the ticket, walk the ladder — kept
//! out of [`crate::tick`] so the clock and the protocol decisions are read and tested separately.
//!
//! THE THREE DECISIONS, IN ORDER
//! ============================
//! 1. [`WorldEntry::established`] opens a session in [`SessionState::Transport`] and sends nothing.
//! 2. [`WorldEntry::data`] answers a channel-3 `SM_CONNECT_REQUEST` with the acceptance flight; else it
//!    looks for a V3 registration, validates the ticket it names, and answers with
//!    `RegistrationResponseMsg` plus the ladder's first rung or rejects the peer. Anything else gets
//!    `Nothing`: the prototype's `channel == 0 and size > 64` heuristic answered game data as a
//!    registration — measured 2026-10-09, 15 of 17 same-sized records were game data and
//!    `OnLocalNetworkConnectionWarning` climbed until the transport dropped.
//! 3. Each datagram and each tick then advances the ladder by one datagram, and the response and the
//!    first rung leave as **two datagrams in order** — batching two rungs crashed the client
//!    (`azoth_wire::ladder`). [`WorldEntry::tick`] serves one peer per call.
//!
//! WHY THE FLIGHT ANSWERS THE REQUEST, AND WHAT IT ACKNOWLEDGES
//! ===========================================================
//! A flight sent at the handshake can only carry an empty welcome, and the client validates it: the
//! version echoed is the `u32` the client wrote into its own `SM_CONNECT_REQUEST`
//! (`rep.py::handle_app_data`: `if requests and not handshake_done`, then `payload[:-1][:4]`). So the
//! trigger is that request, on channel 3, and the reply's envelope sequence echoes the one that carried
//! it. EVERY REQUEST IS ANSWERED AND NO FLAG RECORDS THAT ONE WAS SENT: the client's Carrier resends
//! until one of our datagrams is acknowledged (1 s lost-packet timeout).
//! THE ACK RANGE IS A DIFFERENT NUMBER FROM THE ECHO: a degenerate range (`ack_first == ack_last`,
//! only the datagram carrying the request) is not an acknowledgement the client accepts — MEASURED
//! 2026-09-18 (`Game.log` 20:15:08→18) it retransmits its 1115-byte channel-0 record for ~10 s, then
//! reports `@mm_csdkerr_disconnect (4)`. So each peer counts its inbound datagrams and
//! [`azoth_wire::carrier::ack_window_first`] slides the range over the most recent
//! `ACK_WINDOW_DEFAULT` of them — never wider, because a range half the 16-bit sequence space is the
//! 2026-10-14 retransmit storm.
//!
//! THE V3 BODY NEEDS NO FRAMING STRIPPED, AND THE OUTBOUND ONE DOES
//! ==============================================================
//! Measured on a live 1.460 session (`.azoth/logs/world.log.gz`, 2026-10-22): the registration arrives
//! as channel-0 records with `MF_CHUNKS` (`numChunks 3`, 1115-byte chunks), and the reassembled payload
//! starts with the retry form's 32-byte prelude — tagged record type `4` with value `6033` at offset
//! 32, exactly where `azoth_wire::v3::parse` reads it. So the request body carries **no** VLQ prefix
//! and **no** typed marker; the prefix belongs to the reply only, without which the client dies with
//! `registration_unmarshal_error` (measured 2026-09-20). The container and VLQ forms are accepted too.
//! WHAT THIS PHASE DOES NOT DO: no inbound acknowledgement is parsed, so nothing is ever marked
//! delivered — the resend table retransmits each rung up to `max_resend_tries` and then drops it.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::Path;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use azoth_session::{CloseReason, Session, SessionConfig, SessionEvent, SessionState};
use azoth_wire::carrier::{AcceptanceFlight, Reassembly, connect_request, registration_body};
use azoth_wire::v3::RegistrationRequest;
use azoth_wire::{envelope, record};

use crate::ladder::Ladder;
use crate::tickets::{session_token, TicketStore};

/// A datagram the entry wants written, addressed to one peer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outbound {
    /// Who to write it to.
    pub peer: SocketAddr,
    /// The plaintext to hand the transport.
    pub datagram: Vec<u8>,
}
/// What the entry wants done next.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EntryOutcome {
    /// Send these bytes to this peer, in this order.
    Send {
        /// The destination.
        peer: SocketAddr,
        /// One entry per datagram: never a batch of rungs inside one datagram.
        datagrams: Vec<Vec<u8>>,
    },
    /// Nothing to do.
    Nothing,
    /// Reject the peer: close its session. The session is already closed and forgotten here, and
    /// `&'static str` keeps attacker-controlled text out of an outcome.
    Reject {
        /// Who was rejected.
        peer: SocketAddr,
        /// Why, in one phrase.
        reason: &'static str,
    },
}

impl EntryOutcome {
    /// Split into the datagrams to write and, when the peer was rejected, the reason to log.
    #[must_use]
    pub fn split(self) -> (Vec<Outbound>, Option<(SocketAddr, &'static str)>) {
        match self {
            Self::Send { peer, datagrams } => {
                let out = datagrams.into_iter().map(|datagram| Outbound { peer, datagram });
                (out.collect(), None)
            }
            Self::Nothing => (Vec::new(), None),
            Self::Reject { peer, reason } => (Vec::new(), Some((peer, reason))),
        }
    }
}

#[derive(Debug)]
struct Peer {
    session: Session,
    ladder: Option<Ladder>,
    /// The bytes queued under each reliable sequence, which is what a retransmission resends; the
    /// session says *which* sequences are due and keeps no bytes of its own.
    outbox: HashMap<u16, Vec<u8>>,
    inbound: Reassembly,
    /// Inbound datagrams counted and the last envelope sequence seen: the ACK range's width and end.
    inbound_datagrams: u32,
    last_inbound_seq: u16,
}

impl Peer {
    /// A peer with an open session, nothing queued, and no datagram counted yet.
    fn new(session: Session) -> Self {
        Self {
            session,
            ladder: None,
            outbox: HashMap::new(),
            inbound: Reassembly::default(),
            inbound_datagrams: 0,
            last_inbound_seq: 0,
        }
    }
}

/// Per-peer sessions, ladders, and the tickets they are validated against.
pub struct WorldEntry {
    tickets: TicketStore,
    level_info_body: Vec<u8>,
    spawn_payload: Vec<u8>,
    config: SessionConfig,
    peers: HashMap<SocketAddr, Peer>,
    /// Insertion order, and where the next [`WorldEntry::tick`] starts walking it.
    rotation: Vec<SocketAddr>,
    cursor: usize,
}

impl WorldEntry {
    /// Build the entry from the ladder's two captured bodies, so a test can drive the ladder itself.
    #[must_use]
    pub fn new(tickets: TicketStore, level_info_body: Vec<u8>, spawn_payload: Vec<u8>) -> Self {
        Self {
            tickets,
            level_info_body,
            spawn_payload,
            config: SessionConfig::default(),
            peers: HashMap::new(),
            rotation: Vec::new(),
            cursor: 0,
        }
    }

    /// A peer's DTLS handshake completed: open a session and send nothing.
    ///
    /// A fresh handshake from an address we already hold replaces what was there: the transport sends
    /// `Dropped` first, and the client reuses its source port across attempts. The acceptance flight is
    /// not sent here — it needs the client's version, which only arrives in its `SM_CONNECT_REQUEST`.
    pub fn established(&mut self, peer: SocketAddr) -> EntryOutcome {
        let now = Instant::now();
        if !self.peers.contains_key(&peer) {
            self.rotation.push(peer);
        }
        self.peers.insert(peer, Peer::new(Session::new_at(peer, self.config.clone(), now)));
        EntryOutcome::Nothing
    }

    /// Decrypted application data arrived: answer the Carrier request first, then look for a V3.
    pub fn data(&mut self, peer: SocketAddr, bytes: &[u8]) -> EntryOutcome {
        if !self.peers.contains_key(&peer) {
            // The transport announces a peer before it can deliver its data, so this is stale.
            return EntryOutcome::Nothing;
        }
        let now = Instant::now();
        // Every inbound datagram counts, the one carrying the request included: only a Carrier
        // envelope has a sequence to name.
        if let Ok((inbound, _)) = envelope::parse(bytes) {
            self.observe(peer, inbound.sequence, now);
        }
        if let Some((sequence, payload)) = connect_request(bytes) {
            return self.answer_request(peer, sequence, &payload);
        }
        if self.peers[&peer].ladder.is_some() {
            return self.serve(peer, now);
        }
        match self.registration(peer, bytes) {
            Some(request) => self.register(peer, &request, now),
            None => EntryOutcome::Nothing,
        }
    }

    /// A peer went away.
    pub fn dropped(&mut self, peer: SocketAddr) {
        self.peers.remove(&peer);
        self.rotation.retain(|held| *held != peer);
    }

    /// Advance time: retransmissions, deadlines, and one ladder datagram per peer.
    pub fn tick(&mut self) -> EntryOutcome {
        self.tick_at(Instant::now())
    }

    /// [`WorldEntry::tick`] against a caller-supplied clock, which is what makes a retransmission
    /// testable without sleeping. One peer advances per call, so the caller loops until `Nothing`.
    pub fn tick_at(&mut self, now: Instant) -> EntryOutcome {
        let mut turns = self.rotation.len();
        // `serve` can close the last peer, so the rotation may empty mid-loop.
        while turns > 0 && !self.rotation.is_empty() {
            turns -= 1;
            let peer = self.rotation[self.cursor % self.rotation.len()];
            self.cursor = self.cursor.wrapping_add(1);
            match self.serve(peer, now) {
                EntryOutcome::Nothing => {}
                outcome => return outcome,
            }
        }
        EntryOutcome::Nothing
    }

    /// Reload the ticket file, logging what arrived. Consumed ids stay consumed, and the tick calls
    /// this every tick: the store stats the file and reads it only when it changed.
    pub fn refresh_tickets(&mut self, path: &Path) {
        match self.tickets.refresh(path) {
            Ok(0) => {}
            Ok(added) => eprintln!("[worldd] {added} ticket(s) now known"),
            Err(err) => eprintln!("[worldd] ticket reload failed: {err}"),
        }
    }

    /// What the entry knows about a peer's session, for logs and tests.
    #[must_use]
    pub fn session_state(&self, peer: SocketAddr) -> Option<SessionState> {
        self.peers.get(&peer).map(|state| state.session.state())
    }

    /// The V3 request inside a datagram, if it carries one.
    fn registration(&mut self, peer: SocketAddr, bytes: &[u8]) -> Option<RegistrationRequest> {
        // WHY THIS TRACES: a registration that fails to parse produces no reply and no error, which is
        // indistinguishable from "the client sent nothing". Every early return names the failed step.
        let Ok((_, body)) = envelope::parse(bytes) else {
            crate::diagnostics::note(peer, "not a Carrier envelope");
            return None;
        };
        let Ok(parsed) = record::parse(body) else {
            crate::diagnostics::note(peer, "Carrier body did not parse as records");
            return None;
        };
        if parsed.records.is_empty() {
            crate::diagnostics::note(peer, "a Carrier envelope with no records");
            return None;
        }
        let state = self.peers.get_mut(&peer)?;
        for message in &parsed.records {
            if message.channel != 0 {
                continue;
            }
            if let Some(body) = state.inbound.push(message)
                && let Some(request) = registration_body(&body)
            {
                return Some(request);
            }
        }
        None
    }

    /// Bind the ticket the request names, validate it, and start the ladder.
    fn register(
        &mut self,
        peer: SocketAddr,
        request: &RegistrationRequest,
        now: Instant,
    ) -> EntryOutcome {
        let Some(ticket_id) = request.ticket_uuid().map(str::to_owned) else {
            return self.reject(peer, "the registration names no ticket");
        };
        let Some(ticket) = self.tickets.consume(&ticket_id) else {
            return self.reject(peer, "unknown or already consumed ticket");
        };
        let validated = self.peers.get_mut(&peer).is_some_and(|state| {
            state.session.bind_ticket(ticket).is_ok()
                && state.session.register(request, now).is_ok()
        });
        if !validated {
            return self.reject(peer, "the ticket does not validate against this registration");
        }
        let mut ladder =
            Ladder::for_peer(peer, self.level_info_body.clone(), self.spawn_payload.clone());
        let encoded = (ladder.registration(session_token(&ticket_id)), ladder.next());
        let (Ok(response), Ok(Some(first))) = encoded else {
            return self.reject(peer, "the world could not encode the ladder");
        };
        let Some(state) = self.peers.get_mut(&peer) else { return EntryOutcome::Nothing };
        let mut datagrams = Vec::with_capacity(2);
        for out in [response, first] {
            let (sequence, datagram) = (out.reliable_sequence, out.datagram);
            if state.session.send_reliable(sequence, datagram.clone(), now).is_ok() {
                state.outbox.insert(sequence, datagram.clone());
            }
            datagrams.push(datagram);
        }
        state.ladder = Some(ladder);
        EntryOutcome::Send { peer, datagrams }
    }

    /// Close a peer's session and forget it.
    fn reject(&mut self, peer: SocketAddr, reason: &'static str) -> EntryOutcome {
        if let Some(state) = self.peers.get_mut(&peer) {
            let _ = state.session.close(CloseReason::ProtocolError);
        }
        self.dropped(peer);
        EntryOutcome::Reject { peer, reason }
    }

    /// Record one inbound datagram: the ACK range's counters, plus the session's own acknowledgement
    /// once the peer is past `Transport` — before that the session refuses the sequence.
    fn observe(&mut self, peer: SocketAddr, sequence: u16, now: Instant) {
        if let Some(state) = self.peers.get_mut(&peer) {
            state.inbound_datagrams = state.inbound_datagrams.saturating_add(1);
            state.last_inbound_seq = sequence;
            // A refused sequence belongs to a session that just closed, which the drop covers.
            let _ = state.session.on_datagram(sequence, now);
        }
    }

    /// Answer the client's `SM_CONNECT_REQUEST` with the Carrier acceptance flight.
    ///
    /// The envelope sequence ECHOES the inbound one and is not a server counter: without the echo the
    /// client retransmits as if our reply never arrived (first-light "Mixed Nuts", 2026-05-04). The ACK
    /// range is a *different* number — every datagram received, slid to `ACK_WINDOW_DEFAULT` — because
    /// a range of one is not an acknowledgement the client accepts (module docs, 2026-09-18).
    fn answer_request(&mut self, peer: SocketAddr, sequence: u16, payload: &[u8]) -> EntryOutcome {
        let Some(state) = self.peers.get(&peer) else { return EntryOutcome::Nothing };
        let (last, seen) = (state.last_inbound_seq, state.inbound_datagrams);
        let window = azoth_session::ACK_WINDOW_DEFAULT;
        let flight = AcceptanceFlight::answering(server_clock_ms(), payload, last, seen, window);
        crate::diagnostics::note_connect_request(peer, payload, &flight, seen, sequence);
        let Ok(datagram) = flight.datagram(sequence) else {
            // Unreachable: three fixed channel-3 records, far below the u16 size field.
            return EntryOutcome::Nothing;
        };
        EntryOutcome::Send { peer, datagrams: vec![datagram] }
    }

    /// Advance one peer's session and hand out its retransmissions plus one rung.
    fn serve(&mut self, peer: SocketAddr, now: Instant) -> EntryOutcome {
        let mut datagrams = Vec::new();
        let mut closed = false;
        if let Some(state) = self.peers.get_mut(&peer) {
            for event in state.session.advance(now) {
                match event {
                    SessionEvent::Retransmit(sequences) => {
                        let due = sequences.iter().filter_map(|seq| state.outbox.get(seq));
                        datagrams.extend(due.cloned());
                    }
                    SessionEvent::Close(_) => closed = true,
                    _ => {}
                }
            }
        }
        if closed {
            self.dropped(peer);
            return EntryOutcome::Nothing;
        }
        if let Some(state) = self.peers.get_mut(&peer) {
            datagrams.extend(next_rung(state, now));
        }
        if datagrams.is_empty() {
            return EntryOutcome::Nothing;
        }
        EntryOutcome::Send { peer, datagrams }
    }
}

/// Queue and return one ladder datagram for a peer, if it has one left.
fn next_rung(state: &mut Peer, now: Instant) -> Option<Vec<u8>> {
    let out = state.ladder.as_mut()?.next().ok()??;
    let (sequence, datagram) = (out.reliable_sequence, out.datagram);
    if state.session.send_reliable(sequence, datagram.clone(), now).is_ok() {
        state.outbox.insert(sequence, datagram.clone());
    }
    Some(datagram)
}

/// The server clock in milliseconds, truncated to the 32 bits `CLOCK_SYNC` carries.
fn server_clock_ms() -> u32 {
    SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_millis() as u32)
}

