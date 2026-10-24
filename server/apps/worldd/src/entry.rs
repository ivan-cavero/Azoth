//! The state machine that turns a registered peer into a spawning one.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! The tick tracked peers and answered nothing: a client could complete its DTLS handshake, send a
//! registration and sit in `WaitingForREPConnection` until it timed out, with no error anywhere. This
//! is the missing half — read the V3, validate the ticket, walk the ladder — kept out of
//! [`crate::tick`] so the clock and the protocol decisions are read and tested separately.
//!
//! THE THREE DECISIONS, IN ORDER
//! ============================
//! 1. [`WorldEntry::established`] opens a session in [`SessionState::Transport`] and sends nothing;
//!    the first tick after it produces the keepalive ([`self::egress`]).
//! 2. [`WorldEntry::data`] looks for a V3 registration, validates the ticket it names, and answers
//!    with `RegistrationResponseMsg` plus the ladder's first rung or rejects the peer. A channel-3
//!    `SM_CONNECT_REQUEST` is **observed and not answered**: its ACK rides on the next tick's
//!    keepalive, which is the shape the official server has (61.8 datagrams/s, an ACK on each,
//!    [`self::egress`]). Anything else gets `Nothing`: the prototype's `channel == 0 and size > 64`
//!    heuristic answered game data as a registration — measured 2026-10-09, 15 of 17 same-sized
//!    records were game data and `OnLocalNetworkConnectionWarning` climbed until the transport
//!    dropped.
//! 3. Each tick then advances the ladder by one datagram, and the response and the first rung leave
//!    as **two datagrams in order** — batching two rungs crashed the client (`azoth_wire::ladder`).
//!
//! TWO PUMPS, ONE PEER TABLE
//! =========================
//! [`WorldEntry::egress_tick`] is the clock the tick drives: every established peer gets at least one
//! datagram per tick — a rung if the ladder owes one, the keepalive otherwise — plus whatever
//! byte-identical replay the session has staged. [`WorldEntry::tick`] is the same state work without
//! the clock, one peer per call: it answers "what state does this peer owe" rather than "what does
//! this tick send", which is what `tests/entry.rs` drives.
//!
//! WHY THE PEER COUNTS ITS OWN INBOUND SEQUENCES
//! ============================================
//! The ACK range is not read from the session's own window, because `Session::on_datagram` refuses a
//! sequence until the peer is past [`SessionState::Transport`]: the session never sees the
//! `SM_CONNECT_REQUEST` that arrives first, and a range that omits it is the degenerate range the
//! client rejects. MEASURED 2026-09-18 (`Game.log` 20:15:08→18): after the first
//! `RegistrationResponse` the client retransmits its 1115-byte channel-0 record for ~10 s, then
//! reports `@mm_csdkerr_disconnect (4)`. So each peer counts its datagrams and remembers the last
//! sequence, and [`self::egress::ack_range`] slides a window over them.
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

#[path = "egress.rs"]
pub mod egress;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::Path;
use std::time::Instant;

use azoth_session::{CloseReason, Session, SessionConfig, SessionState};
use azoth_wire::carrier::{Reassembly, connect_request, connect_welcome, registration_body};
use azoth_wire::v3::RegistrationRequest;
use azoth_wire::{envelope, record};

use self::egress::{Outbound, PeerView};
use crate::ladder::Ladder;
use crate::tickets::{session_token, TicketStore};

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
    /// The peer's outbound envelope counter. Every datagram written to this socket is numbered from
    /// it — ladder rungs and keepalives alike — because two counters restarting at 1 would re-use
    /// sequences the client has already seen ([`self::egress`]).
    outbound_sequence: u16,
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
            outbound_sequence: 0,
        }
    }

    /// Borrow this peer as the egress's view of it.
    fn view(&mut self, peer: SocketAddr) -> PeerView<'_> {
        PeerView {
            peer,
            session: &mut self.session,
            ladder: self.ladder.as_mut(),
            outbox: &mut self.outbox,
            datagrams_seen: self.inbound_datagrams,
            ack_last: self.last_inbound_seq,
            outbound_sequence: &mut self.outbound_sequence,
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
    /// `Dropped` first, and the client reuses its source port across attempts. Nothing is sent here at
    /// all: the first tick after this produces the keepalive, which is also the ACK for whatever the
    /// client has already sent.
    pub fn established(&mut self, peer: SocketAddr) -> EntryOutcome {
        let now = Instant::now();
        if !self.peers.contains_key(&peer) {
            self.rotation.push(peer);
        }
        self.peers.insert(peer, Peer::new(Session::new_at(peer, self.config.clone(), now)));
        EntryOutcome::Nothing
    }

    /// Decrypted application data arrived: look for a V3 registration, and answer nothing else.
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
            self.note_request(peer, sequence, &payload);
            // NO REPLY. The ACK for this request rides on the next tick's datagram, which is what the
            // official server does (61.8 datagrams/s, an ACK on each) and what the sys-id census
            // says: CONNECT_ACK never appears in real traffic at all (`self::egress`).
            return EntryOutcome::Nothing;
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

    /// Advance time without the output clock: retransmissions, deadlines, and one ladder datagram.
    ///
    /// One peer advances per call, so the caller loops until `Nothing`. The production tick does not
    /// use this — it drives [`WorldEntry::egress_tick`], which guarantees a datagram per peer — but
    /// the state alone is what a test of the ladder wants to see.
    pub fn tick(&mut self) -> EntryOutcome {
        self.tick_at(Instant::now())
    }

    /// [`WorldEntry::tick`] against a caller-supplied clock, which is what makes a retransmission
    /// testable without sleeping.
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
        // Domain id from the ticket (authority), not from opaque V3 bytes.
        let character = ticket.character();
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
        eprintln!(
            "[worldd] entry peer={peer} character={character} first_rung={}",
            first.ontology_uid
        );
        let Some(state) = self.peers.get_mut(&peer) else {
            return EntryOutcome::Nothing;
        };
        state.ladder = Some(ladder);
        let mut view = state.view(peer);
        let datagrams = [response, first]
            .map(|out| view.send(out, now))
            .to_vec();
        drop(view);
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

    /// Report the `SM_CONNECT_REQUEST` measurement: its payload, the welcome it implies, the ACK
    /// range the next datagram will claim, and the sequence it arrived on.
    ///
    /// The line is kept although the request is no longer answered: it is the only record of what a
    /// client that never registers actually asked for.
    fn note_request(&mut self, peer: SocketAddr, sequence: u16, payload: &[u8]) {
        let Some(state) = self.peers.get(&peer) else {
            return;
        };
        let (first, last) = egress::ack_range(state.last_inbound_seq, state.inbound_datagrams);
        crate::diagnostics::note_connect_request(
            peer,
            payload,
            &connect_welcome(payload),
            first,
            last,
            state.inbound_datagrams,
            sequence,
        );
    }

    /// Advance one peer's session and hand out its replays plus one rung: the state pump.
    fn serve(&mut self, peer: SocketAddr, now: Instant) -> EntryOutcome {
        let Some(state) = self.peers.get_mut(&peer) else {
            return EntryOutcome::Nothing;
        };
        let mut view = state.view(peer);
        let mut datagrams = view.advance(now);
        let closed = view.is_closed();
        if !closed && let Some(rung) = view.rung(now) {
            datagrams.push(rung);
        }
        drop(view);
        if closed {
            self.dropped(peer);
            return EntryOutcome::Nothing;
        }
        if datagrams.is_empty() {
            return EntryOutcome::Nothing;
        }
        EntryOutcome::Send { peer, datagrams }
    }
}
