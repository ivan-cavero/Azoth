//! The state machine that turns a registered peer into a spawning one.
//!
//! WHY THIS MODULE EXISTS
//! ======================
//! The tick tracked peers and answered nothing: a client could complete its DTLS handshake, send a
//! registration and sit in `WaitingForREPConnection` until it timed out, with no error anywhere.
//! This is the missing half — read the V3, validate the ticket, answer, walk the ladder — kept out
//! of [`crate::tick`] so the clock and the protocol decisions can be read and tested separately.
//!
//! THE THREE DECISIONS, IN ORDER
//! ============================
//! 1. [`WorldEntry::established`] opens a session in [`SessionState::Transport`] and sends nothing:
//!    the client speaks first, and its registration starts the exchange.
//! 2. [`WorldEntry::data`] looks for a V3 registration; if the datagram parses as one, the ticket it
//!    names is consumed, bound and validated, and the world either answers with
//!    `RegistrationResponseMsg` and starts the ladder or rejects the peer. A datagram that is **not**
//!    a registration gets `Nothing`: the prototype's size heuristic (`channel == 0 and size > 64`)
//!    answered game data as if it were one — measured 2026-10-09, 15 of 17 same-sized records were
//!    game data and `OnLocalNetworkConnectionWarning` climbed until the transport dropped.
//! 3. After that, each datagram and each tick advances the ladder by exactly one datagram.
//! The response and the first rung leave as **two datagrams in order**, never as one datagram
//! carrying two records: batching two rungs in one burst crashed the client (`azoth_wire::ladder`).
//! [`WorldEntry::tick`] serves one peer per call, because [`EntryOutcome`] names one destination.
//!
//! THE V3 BODY NEEDS NO FRAMING STRIPPED, AND THE OUTBOUND ONE DOES
//! ==============================================================
//! Measured on a live 1.460 session (`.azoth/logs/world.log.gz`, 2026-10-22): the registration
//! arrives as channel-0 records with `MF_CHUNKS` (`numChunks 3`, 1115-byte chunks), and the
//! reassembled payload starts with the retry form's 32-byte prelude — tagged record type `4` with
//! value `6033` sits at offset 32, exactly where `azoth_wire::v3::parse` reads it. So the request
//! body carries **no** VLQ prefix and **no** typed marker; the prefix belongs to the reply only
//! (`RegistrationResponse::encode_record`), without which the client dies with
//! `registration_unmarshal_error` (measured 2026-09-20). The client's self-validating container and
//! a VLQ-prefixed body are accepted too, because the strict first-attempt form is not in that log.
//! WHAT THIS PHASE DOES NOT DO: no inbound acknowledgement is parsed, so nothing is ever marked
//! delivered — the resend table retransmits each rung up to `max_resend_tries` and then drops it.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::Path;
use std::time::Instant;

use azoth_session::{CloseReason, Session, SessionConfig, SessionEvent, SessionState};
use azoth_wire::record::MessageRecord;
use azoth_wire::v3::{self, RegistrationRequest};
use azoth_wire::{container, envelope, record, varint};

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
    /// Reject the peer: close its session.
    ///
    /// The session is already closed and forgotten when this is returned. The reason is for the
    /// log; `&'static str` keeps attacker-controlled text out of an outcome.
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
            Self::Send { peer, datagrams } => (
                datagrams
                    .into_iter()
                    .map(|datagram| Outbound { peer, datagram })
                    .collect(),
                None,
            ),
            Self::Nothing => (Vec::new(), None),
            Self::Reject { peer, reason } => (Vec::new(), Some((peer, reason))),
        }
    }
}

/// Inbound chunk reassembly for one peer.
///
/// The client chunks its own registration (`numChunks 3` measured), so a body only exists once its
/// last chunk arrives; every chunk carries the **total**, which is what lets a complete message be
/// recognised without a timer. Out-of-order delivery loses the message rather than corrupting it.
#[derive(Debug, Default)]
struct Reassembly {
    expected: u16,
    next: u16,
    parts: Vec<Vec<u8>>,
}

impl Reassembly {
    /// Append one record's payload, returning the body once it is complete.
    fn push(&mut self, message: &MessageRecord) -> Option<Vec<u8>> {
        if message.num_chunks <= 1 {
            return Some(message.payload.clone());
        }
        // A chunk continues the message in progress only when it is the next one; anything else
        // starts over, which drops a duplicate instead of concatenating it twice.
        if self.expected != message.num_chunks || message.sequence != self.next {
            self.expected = message.num_chunks;
            self.parts.clear();
            self.next = message.sequence;
        }
        self.parts.push(message.payload.clone());
        self.next = self.next.wrapping_add(1);
        if self.parts.len() < usize::from(self.expected) {
            return None;
        }
        Some(self.parts.drain(..).flatten().collect())
    }
}

#[derive(Debug)]
struct Peer {
    session: Session,
    ladder: Option<Ladder>,
    /// The bytes queued under each reliable sequence, which is what a retransmission resends. The
    /// session says *which* sequences are due and deliberately keeps no bytes of its own.
    outbox: HashMap<u16, Vec<u8>>,
    inbound: Reassembly,
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
    /// Build the entry.
    ///
    /// The two bodies are the ladder's captured payloads, passed in so this module never depends on
    /// where a template lives and a test can drive the ladder with its own bytes.
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

    /// A peer's DTLS handshake completed.
    ///
    /// A fresh handshake from an address we already hold replaces what was there: the transport
    /// sends `Dropped` first, and the client reuses its source port across attempts.
    pub fn established(&mut self, peer: SocketAddr) -> EntryOutcome {
        let now = Instant::now();
        if !self.peers.contains_key(&peer) {
            self.rotation.push(peer);
        }
        self.peers.insert(
            peer,
            Peer {
                session: Session::new_at(peer, self.config.clone(), now),
                ladder: None,
                outbox: HashMap::new(),
                inbound: Reassembly::default(),
            },
        );
        EntryOutcome::Nothing
    }

    /// Decrypted application data arrived.
    pub fn data(&mut self, peer: SocketAddr, bytes: &[u8]) -> EntryOutcome {
        if !self.peers.contains_key(&peer) {
            // The transport announces a peer before it can deliver its data, so this is stale.
            return EntryOutcome::Nothing;
        }
        let now = Instant::now();
        if self.peers[&peer].ladder.is_some() {
            self.touch(peer, bytes, now);
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
    /// testable without sleeping. Each call advances one peer, so the caller loops until `Nothing`.
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

    /// Reload the ticket file, logging what arrived. Consumed ids stay consumed.
    ///
    /// The tick calls this every tick; the store stats the file and only reads it when it changed.
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
        let (_, body) = envelope::parse(bytes).ok()?;
        let parsed = record::parse(body).ok()?;
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
        let Some(state) = self.peers.get_mut(&peer) else {
            return EntryOutcome::Nothing;
        };
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

    /// Acknowledge an inbound datagram's envelope sequence, if it has one.
    fn touch(&mut self, peer: SocketAddr, bytes: &[u8], now: Instant) {
        let Ok((envelope, _)) = envelope::parse(bytes) else {
            return;
        };
        if let Some(state) = self.peers.get_mut(&peer) {
            // A refused sequence belongs to a session that just closed, which the drop covers.
            let _ = state.session.on_datagram(envelope.sequence, now);
        }
    }

    /// Advance one peer's session and hand out its retransmissions plus one rung.
    fn serve(&mut self, peer: SocketAddr, now: Instant) -> EntryOutcome {
        let mut datagrams = Vec::new();
        let mut closed = false;
        if let Some(state) = self.peers.get_mut(&peer) {
            for event in state.session.advance(now) {
                match event {
                    SessionEvent::Retransmit(sequences) => datagrams.extend(
                        sequences
                            .iter()
                            .filter_map(|sequence| state.outbox.get(sequence))
                            .cloned(),
                    ),
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

/// The V3 body inside a record payload, in any of the three framings that could carry it.
fn registration_body(payload: &[u8]) -> Option<RegistrationRequest> {
    // The measured form: the body verbatim (see the module docs).
    if let Ok(request) = v3::parse(payload) {
        return Some(request);
    }
    // The client's self-validating container, documented for non-chunked channel-0 records; its CRC
    // is what makes this a check rather than a guess.
    if let Ok(inner) = container::parse_client(payload)
        && let Ok(request) = v3::parse(inner.body)
    {
        return Some(request);
    }
    // The server's own framing: a VLQ32 length, then the body.
    let (declared, after) = varint::decode(payload, 0).ok()?;
    if usize::try_from(declared).ok()? != payload.len() - after {
        return None;
    }
    v3::parse(&payload[after..]).ok()
}

