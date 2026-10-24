//! The output clock: one datagram per peer per tick, and the ACK that rides on every one.
//!
//! WHY THE WORLD SENDS ON A CLOCK INSTEAD OF IN REPLY
//! =================================================
//! MEASURED from the official server in the live capture
//! (`research/sessions/live_20261022_r1460_trading_timed/network/pktmon.pcapng`), DTLS payload only,
//! one REP flow:
//!
//! | direction | packets/s | inter-packet gap p50 | payload p50 |
//! | --- | --- | --- | --- |
//! | client -> server | 20.5 | 48.1 ms | 309 B |
//! | server -> client | 61.8 | 16.1 ms (p10 14.0, p90 18.2) | 180 B |
//!
//! 61.8 datagrams/s at a 16.1 ms median gap is an output clock, not a reply: a reply pattern would
//! track the client's 20.5/s instead of ignoring it. The ratio is 3:1, so a server that puts the ACK
//! on every datagram confirms each client input within at most one tick (20 ms at 50 Hz), and
//! **there is no separate ACK event** to schedule.
//!
//! WHY THE ACCEPTANCE FLIGHT IS RETIRED, WITH THE CENSUS THAT RETIRED IT
//! ====================================================================
//! A census of 465 MB of the Python prototype's own traffic (`services/world/rep_traffic.jsonl`,
//! 1,338,802 lines) counts every channel-3 system id it ever sent:
//!
//! | sys id | occurrences | message |
//! | --- | --- | --- |
//! | 1 | 65 | CONNECT_REQUEST (client) |
//! | 6 | 313,578 | CT_ACKS |
//! | 7 | 159 | CONN_CONTROL |
//! | 3 | 8 | DISCONNECT |
//! | 4 | 0 | CLOCK_SYNC |
//! | 2 | 0 | CONNECT_ACK |
//!
//! CLOCK_SYNC and CONNECT_ACK appear in no session at all, so the three-record acceptance flight
//! (`azoth_wire::carrier::AcceptanceFlight`) was a branch the prototype never exercised. The live
//! shape is CT_ACKS and nothing else, so the keepalive here is the ACK alone — not a DISCONNECT, not
//! a CLOCK_SYNC and not a CONNECT_ACK — and it is also the answer to a `SM_CONNECT_REQUEST`: on the
//! next tick, not in a reply.
//!
//! THE COST, STATED PLAINLY
//! =======================
//! 2,500 peers at 50 Hz is 125,000 datagrams/s. That is the contract's shape, not a surprise, so
//! [`Egress::for_peer`] allocates the datagram and its record payload and nothing else, and the ACK
//! range is O(1): [`ack_window_first`] is one subtraction in wrap space.
//!
//! WHAT THIS MODULE DOES NOT SEND
//! =============================
//! A retransmission. `azoth_session::resend` keeps the exact bytes of a reliable record so a resend is
//! byte-identical to the first transmission, which means a resend cannot carry a fresh ACK: the client
//! would see two different bodies under one reliable sequence. Replays therefore leave alongside the
//! clock's datagram ([`PeerView::advance`]), never through [`Egress::for_peer`].
//!
//! WHY THIS MODULE IS DECLARED FROM `entry` AND NOT FROM `main`
//! ===========================================================
//! `worldd` is a binary crate, so its integration tests compile these files by `#[path]`, and
//! `tests/entry.rs` compiles `entry.rs` **without** `egress.rs`. A module that `entry` depends on
//! must therefore be declared by `entry` itself; `main.rs` re-exports it as `crate::egress`, so the
//! public path is the obvious one and there is exactly one copy of every type.

use std::collections::{HashMap, VecDeque};
use std::net::SocketAddr;
use std::time::Instant;

use azoth_session::{ACK_WINDOW_DEFAULT, Session, SessionEvent};
use azoth_wire::carrier::{ack_window_first, acks_payload};
use azoth_wire::record::MessageRecord;
use azoth_wire::{CHANNEL_SYSTEM, WireError, envelope, ladder, marshal};

use crate::ladder::{Ladder, Outgoing};
use crate::entry::WorldEntry;

/// The reliable sequence an unreliable record carries before any reliable record has been received.
///
/// `0xFFFF` is the value the client's own writer puts there (`rep.py::ct_acks_datagram`), and it is
/// the one an unreliable record must carry: delivering one requires its relSeq to equal the last
/// reliable sequence received, which starts at `0xFFFF`.
const NO_RELIABLE_YET: u16 = 0xFFFF;

/// One outbound datagram, addressed and ready to write.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outbound {
    /// Who to write it to.
    pub peer: SocketAddr,
    /// The plaintext to hand the transport.
    pub datagram: Vec<u8>,
}

/// A borrowed view of one peer's state, as the egress needs it.
///
/// WHY A VIEW AND NOT THE PEER: the session, the ladder, the resend outbox and the inbound counters
/// live together in one peer table entry. Borrowing them as separate fields is what lets one call
/// advance the session, read the outbox and write the ACK without cloning any of them — at 125,000
/// calls/s a clone per call would be the whole cost of the tick.
pub struct PeerView<'a> {
    /// Who the datagram is addressed to.
    pub peer: SocketAddr,
    /// The session: its deadlines, and which reliable sequences are due.
    pub session: &'a mut Session,
    /// The ladder, `None` until the peer registers.
    pub ladder: Option<&'a mut Ladder>,
    /// The bytes queued under each reliable sequence, which is what a retransmission resends.
    pub outbox: &'a mut HashMap<u16, Vec<u8>>,
    /// Inbound datagrams counted, which is the ACK range's width.
    pub datagrams_seen: u32,
    /// The last inbound envelope sequence seen, which is the ACK range's end.
    pub ack_last: u16,
    /// This peer's outbound envelope counter: the only one on its socket.
    pub outbound_sequence: &'a mut u16,
    /// Presence AOI datagrams waiting after the entry ladder (one per tick).
    pub presence_out: &'a mut VecDeque<Outgoing>,
}

/// The ACK range a peer's inbound counters have earned: `(ack_first, ack_last)`.
///
/// The width is `min(datagrams_seen, ACK_WINDOW_DEFAULT)` and never zero, and the window is
/// `azoth_session::ACK_WINDOW_DEFAULT` (16,384) rather than the whole 16-bit space: a pinned range
/// crossed half the sequence space at ~26 minutes and the client answered by retransmitting
/// everything (2026-10-14, 140,174 records carrying 660 distinct sequences).
#[must_use]
pub fn ack_range(ack_last: u16, datagrams_seen: u32) -> (u16, u16) {
    (
        ack_window_first(ack_last, datagrams_seen, ACK_WINDOW_DEFAULT),
        ack_last,
    )
}

impl PeerView<'_> {
    /// The ACK range this peer's inbound traffic has earned: `(ack_first, ack_last)`.
    #[must_use]
    pub fn ack_range(&self) -> (u16, u16) {
        ack_range(self.ack_last, self.datagrams_seen)
    }

    /// Advance the session and return the replays it owes, byte-identical to their first
    /// transmission.
    ///
    /// The sequences come back from the session already charged as sent, so every one returned here
    /// must be written: a replay that is dropped spends a try from the six-try budget without ever
    /// being offered again.
    #[must_use]
    pub fn advance(&mut self, now: Instant) -> Vec<Vec<u8>> {
        let mut replays = Vec::new();
        for event in self.session.advance(now) {
            if let SessionEvent::Retransmit(sequences) = event {
                let due = sequences.iter().filter_map(|seq| self.outbox.get(seq));
                replays.extend(due.cloned());
            }
        }
        replays
    }

    /// Whether the session closed while it was advanced, so the caller can forget the peer.
    #[must_use]
    pub fn is_closed(&self) -> bool {
        !self.session.state().is_open()
    }

    /// The next ladder datagram, or `None` once the ladder has nothing left.
    ///
    /// **One datagram per call**, which is the measured constraint twice over: batching two rungs
    /// crashed the client, and batching several chunks of one rung truncated its reassembly. A rung
    /// that needs many datagrams (the spawn is 43 chunks) is therefore drained across 43 ticks.
    pub fn rung(&mut self, now: Instant) -> Option<Vec<u8>> {
        let out = self.ladder.as_mut()?.next().ok()??;
        Some(self.send(out, now))
    }

    /// The next queued presence datagram (AOI AddActor), or `None` if idle.
    pub fn presence(&mut self, now: Instant) -> Option<Vec<u8>> {
        let out = self.presence_out.pop_front()?;
        Some(self.send(out, now))
    }

    /// Number, queue for retransmission, and return one ladder datagram.
    ///
    /// The datagram is queued in the session's resend table and in the outbox under the same reliable
    /// sequence, which is what makes its retransmission byte-identical to this transmission.
    pub fn send(&mut self, out: Outgoing, now: Instant) -> Vec<u8> {
        let (sequence, mut datagram) = (out.reliable_sequence, out.datagram);
        self.stamp(&mut datagram);
        if self.session.send_reliable(sequence, datagram.clone(), now).is_ok() {
            self.outbox.insert(sequence, datagram.clone());
        }
        datagram
    }

    /// The keepalive: one channel-3 record carrying the ACK and nothing else.
    ///
    /// This is the datagram that makes the clock a clock. Its shape is the prototype's
    /// `rep.py::ct_acks_datagram` byte for byte — an envelope, then a channel-3 unreliable record
    /// whose payload is `0x40 <ack_last> <ack_first> 6` — because CT_ACKS is the only channel-3
    /// message that appears in real traffic at all (313,578 occurrences, module docs).
    ///
    /// # Errors
    /// [`WireError::OutOfRange`] if the six-byte payload did not fit the `u16` size field, which
    /// cannot happen and is reported rather than unwrapped.
    pub fn keepalive(&mut self) -> Result<Vec<u8>, WireError> {
        let (first, last) = self.ack_range();
        let record = MessageRecord::data(
            CHANNEL_SYSTEM,
            0,
            NO_RELIABLE_YET,
            acks_payload(first, last),
        );
        let sequence = self.take_sequence();
        ladder::datagram(sequence, &[record])
    }

    /// Number this datagram with the peer's own outbound envelope sequence.
    ///
    /// WHY THE LADDER'S OWN NUMBER IS REPLACED: a peer has one socket, so it may have one envelope
    /// counter. The keepalive clock and the ladder both number datagrams on that socket, and two
    /// counters that each restart at 1 would re-use sequences the client has already seen — a re-used
    /// sequence is indistinguishable from a duplicate, and the client drops duplicates. So the peer's
    /// counter is the only one and the ladder's value is discarded; the ladder's internal counter
    /// still drives the state bundle's replication sequence, which is a different field.
    fn stamp(&mut self, datagram: &mut [u8]) {
        let sequence = self.take_sequence();
        if let Some(field) = datagram.get_mut(2..envelope::ENVELOPE_SIZE) {
            field.copy_from_slice(&sequence.to_be_bytes());
        }
    }

    /// The next outbound envelope sequence, wrapping like the `u16` field it is.
    fn take_sequence(&mut self) -> u16 {
        let value = *self.outbound_sequence;
        *self.outbound_sequence = value.wrapping_add(1);
        value
    }
}

/// The output clock: what the world owes a peer on this tick.
pub struct Egress;

impl Egress {
    /// Build the datagrams one peer is owed this tick.
    ///
    /// Order of precedence: real state first (the ladder), then the keepalive. Either way the
    /// returned datagram CARRIES THE ACK for everything received so far.
    ///
    /// `None` when the session is closed — the caller must forget the peer — or when a datagram
    /// could not be encoded, which for these fixed bodies means a bug rather than bad input.
    #[must_use]
    pub fn for_peer(peer: &mut PeerView<'_>, now: Instant) -> Option<Outbound> {
        if peer.is_closed() {
            return None;
        }
        let ack = peer.ack_range();
        let datagram = match peer.rung(now) {
            Some(rung) => piggyback(rung, ack).ok()?,
            None => match peer.presence(now) {
                Some(presence) => piggyback(presence, ack).ok()?,
                None => {
                    crate::diagnostics::note_keepalive(
                        peer.peer,
                        ack.0,
                        ack.1,
                        peer.datagrams_seen,
                    );
                    peer.keepalive().ok()?
                }
            },
        };
        Some(Outbound {
            peer: peer.peer,
            datagram,
        })
    }
}

/// The clock's two entry points, on the peer table they drive.
///
/// WHY THE CLOCK LIVES HERE AND NOT IN `entry`: it is the only code that has to walk *every* peer
/// every tick, while `entry` keeps the per-peer state pump. One implementation each, and the file that
/// owns the output clock is the file that can be read against the measurement in the module docs.
impl WorldEntry {
    /// One tick of the output clock: every established peer gets at least one datagram.
    pub fn egress_tick(&mut self) -> Vec<Outbound> {
        self.egress_tick_at(Instant::now())
    }

    /// [`WorldEntry::egress_tick`] against a caller-supplied clock, so a test can run two ticks and
    /// compare them without sleeping.
    ///
    /// The `Vec` is allocated once per tick, not once per peer: 2,500 peers at 50 Hz is 125,000
    /// datagrams/s, and this is the only allocation the loop adds on top of the datagrams themselves.
    pub fn egress_tick_at(&mut self, now: Instant) -> Vec<Outbound> {
        let mut out = Vec::with_capacity(self.peers.len());
        // A peer that closes during the tick is removed from the rotation, which is empty here, so
        // the removal is re-applied to the copy that is put back.
        let rotation = std::mem::take(&mut self.rotation);
        for peer in &rotation {
            self.egress_peer(*peer, now, &mut out);
        }
        self.rotation = rotation;
        self.rotation.retain(|peer| self.peers.contains_key(peer));
        out
    }

    /// Advance one peer and append everything it is owed to `out`.
    ///
    /// The replays come first because they are bytes the session already charged as sent: dropping
    /// one would spend a try from the six-try budget without offering the record again. Then the one
    /// datagram the clock produces — a rung, or the keepalive.
    fn egress_peer(&mut self, peer: SocketAddr, now: Instant, out: &mut Vec<Outbound>) {
        let Some(state) = self.peers.get_mut(&peer) else {
            return;
        };
        let mut view = state.view(peer);
        for replay in view.advance(now) {
            out.push(Outbound {
                peer,
                datagram: replay,
            });
        }
        let closed = view.is_closed();
        if !closed && let Some(clock) = Egress::for_peer(&mut view, now) {
            out.push(clock);
        }
        drop(view);
        if closed {
            self.dropped(peer);
        }
    }
}

/// Append the ACK to a datagram that already carries real state.
///
/// A Carrier datagram's body is a stream of self-delimiting records with no length field over the
/// whole body, so a piggyback is literally one more record. The record is marshalled on its own,
/// which sets `MF_DATA_CHANNEL` for it: the reader then reads its channel byte even though the record
/// before it was channel 0, so the ACK cannot inherit the wrong channel.
fn piggyback(mut datagram: Vec<u8>, ack: (u16, u16)) -> Result<Vec<u8>, WireError> {
    let record = MessageRecord::data(
        CHANNEL_SYSTEM,
        0,
        NO_RELIABLE_YET,
        acks_payload(ack.0, ack.1),
    );
    datagram.extend_from_slice(&marshal::marshal(&[record])?);
    Ok(datagram)
}
