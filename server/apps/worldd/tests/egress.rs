//! The output clock: one datagram per peer per tick, and the ACK that rides on it.
//!
//! WHY THESE DRIVE `WorldEntry` AND ONE BARE `PeerView`
//! ===================================================
//! The seven rules the egress has to keep are about *what a peer is owed*, so they go through the
//! entry's clock (`egress_tick_at`) wherever the entry can reach the state — a peer is established and
//! fed datagrams, exactly as the transport would. The one exception is the ladder rung: installing a
//! ladder needs a validated ticket and a strict 832-byte registration body, which `tests/entry.rs`
//! already owns end to end, so that rule is asserted against [`Egress::for_peer`] with a `PeerView`
//! built directly. The composition (the clock calls `for_peer` once per peer) is what the keepalive
//! tests below prove.
//!
//! The modules are included by `#[path]` because `worldd` is a binary crate. `egress` is declared
//! *inside* `entry.rs`, so it arrives with it and there is one copy of every type.

#[path = "../src/config.rs"]
mod config;
#[path = "../src/diagnostics.rs"]
mod diagnostics;
#[path = "../src/entry.rs"]
mod entry;
#[path = "../src/ladder.rs"]
mod ladder;
#[path = "../src/peer.rs"]
mod peer;
#[path = "../src/presence.rs"]
mod presence;
#[path = "../src/tickets.rs"]
mod tickets;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::time::{Duration, Instant};

use azoth_session::{Session, SessionConfig};
use azoth_wire::carrier::{ACK_CONTINUOUS, SYS_CT_ACKS};
use azoth_wire::record::MessageRecord;
use azoth_wire::{CHANNEL_SYSTEM, envelope, record};

use crate::entry::egress::{Egress, PeerView};
use crate::entry::{EntryOutcome, WorldEntry};
use crate::ladder::Ladder;
use crate::tickets::TicketStore;

/// A world with no tickets: nothing here registers, so every tick owes the keepalive.
fn world() -> WorldEntry {
    WorldEntry::new(TicketStore::empty(), vec![0xAB; 106], vec![0xCD; 64])
}

fn addr(port: u16) -> SocketAddr {
    format!("127.0.0.1:{port}").parse().expect("addr")
}

/// The records of one datagram, which must consume it exactly.
fn records_of(datagram: &[u8]) -> Vec<MessageRecord> {
    let (_, body) = envelope::parse(datagram).expect("a Carrier envelope");
    let parsed = record::parse(body).expect("records");
    assert_eq!(parsed.trailing_bytes, 0, "the datagram is exactly records");
    parsed.records
}

/// The `(ack_first, ack_last)` range a datagram's `CT_ACKS` record carries: `0x40`, last, first, id.
fn ack_range_of(datagram: &[u8]) -> (u16, u16) {
    let records = records_of(datagram);
    let payload = &records
        .iter()
        .find(|message| message.system_msg_id() == Some(SYS_CT_ACKS))
        .expect("a CT_ACKS record")
        .payload;
    assert_eq!(payload.len(), 6, "flags, last, first, id");
    assert_eq!(payload[0], ACK_CONTINUOUS);
    let last = u16::from_be_bytes([payload[1], payload[2]]);
    let first = u16::from_be_bytes([payload[3], payload[4]]);
    (first, last)
}

/// A client datagram whose one channel-3 record carries `payload`.
fn system_datagram(envelope_sequence: u16, payload: &[u8]) -> Vec<u8> {
    let message = MessageRecord {
        flags: 0,
        channel: CHANNEL_SYSTEM,
        sequence: 0,
        reliable_sequence: 0,
        reliable: true,
        connecting: false,
        num_chunks: 1,
        payload: payload.to_vec(),
    };
    azoth_wire::ladder::datagram(envelope_sequence, &[message]).expect("a Carrier datagram")
}

/// The client's own CT_ACKS, which `data` answers with silence but the range must still count.
fn inbound(envelope_sequence: u16) -> Vec<u8> {
    system_datagram(envelope_sequence, &[0x40, 0x00, 0x05, 0x00, 0x05, SYS_CT_ACKS])
}

/// 1. A peer with nothing to send produces exactly one keepalive datagram per tick.
#[test]
fn a_peer_with_nothing_to_send_produces_one_keepalive_per_tick() {
    let mut world = world();
    let peer = addr(5101);
    world.established(peer);

    for tick in 0..3 {
        let outbound = world.egress_tick();
        assert_eq!(outbound.len(), 1, "tick {tick}: one peer, one datagram");
        assert_eq!(outbound[0].peer, peer);
        assert_eq!(
            records_of(&outbound[0].datagram).len(),
            1,
            "tick {tick}: the keepalive is one record"
        );
    }
}

/// 2. The keepalive contains a channel-3 record whose system id is 6 and whose payload is `0x40`,
///    `ack_last`, `ack_first`, 6.
#[test]
fn the_keepalive_is_a_channel_three_acks_record() {
    let mut world = world();
    let peer = addr(5102);
    world.established(peer);
    assert_eq!(world.data(peer, &inbound(0x1234)), EntryOutcome::Nothing);

    let outbound = world.egress_tick();
    let records = records_of(&outbound[0].datagram);
    assert_eq!(records.len(), 1, "one record");
    assert_eq!(records[0].channel, 3, "channel 3 is the system channel");
    assert_eq!(records[0].system_msg_id(), Some(6), "SM_CT_ACKS");
    // One datagram seen, so the range is degenerate and names the datagram it acknowledges.
    assert_eq!(
        records[0].payload,
        vec![0x40, 0x12, 0x34, 0x12, 0x34, 6],
        "0x40, ack_last, ack_first, sys id"
    );
}

/// 3. The ACK range covers every datagram received: after 5 inbound datagrams the range width is 5.
#[test]
fn the_range_covers_every_datagram_received() {
    let mut world = world();
    let peer = addr(5103);
    world.established(peer);
    for sequence in 10..15 {
        assert_eq!(world.data(peer, &inbound(sequence)), EntryOutcome::Nothing);
    }

    let outbound = world.egress_tick();
    let (first, last) = ack_range_of(&outbound[0].datagram);
    assert_eq!(last, 14, "the range ends at the last datagram received");
    assert_eq!(last - first + 1, 5, "five datagrams received, five acknowledged");
}

/// 4. A peer with a pending ladder rung produces that rung, and it also carries the ACK.
///
/// The view is built directly because installing a ladder needs a validated ticket; see the module
/// docs. What is under test is the precedence rule: real state first, the keepalive only when the
/// ladder owes nothing.
#[test]
fn a_pending_rung_is_sent_with_the_ack_appended() {
    let peer = addr(5104);
    let now = Instant::now();
    let mut session = Session::new_at(peer, SessionConfig::default(), now);
    let mut ladder = Ladder::for_peer(peer, vec![0xAB; 106], vec![0xCD; 64]);
    let mut outbox = HashMap::new();
    let mut outbound_sequence = 0u16;
    let mut presence_out = std::collections::VecDeque::new();
    let mut view = PeerView {
        peer,
        session: &mut session,
        ladder: Some(&mut ladder),
        outbox: &mut outbox,
        datagrams_seen: 3,
        ack_last: 0x0100,
        outbound_sequence: &mut outbound_sequence,
        presence_out: &mut presence_out,
    };

    let outbound = Egress::for_peer(&mut view, now).expect("the rung is owed");
    assert_eq!(outbound.peer, peer);
    let records = records_of(&outbound.datagram);
    assert_eq!(records.len(), 2, "the rung, then the ACK");
    assert_eq!(records[0].channel, 0, "the rung rides channel 0");
    assert_eq!(records[0].payload[0], 1, "Cmd_Greetings, the ladder's first rung");
    assert_eq!(records[1].channel, 3, "the ACK rides channel 3");
    assert_eq!(records[1].system_msg_id(), Some(SYS_CT_ACKS));
    assert_eq!(
        ack_range_of(&outbound.datagram),
        (0x00FE, 0x0100),
        "three datagrams received, three acknowledged"
    );

    // The datagram is numbered from the peer's own counter, which starts at 0: the ladder's own
    // envelope number is discarded, so a keepalive that follows cannot re-use a sequence the rung
    // already took (`PeerView::stamp`).
    assert_eq!(
        u16::from_be_bytes([outbound.datagram[2], outbound.datagram[3]]),
        0,
        "the first datagram on this socket is sequence 0"
    );
}

/// 5. Two ticks produce two datagrams for one peer: the clock runs whether or not traffic arrived.
#[test]
fn two_ticks_produce_two_datagrams() {
    let mut world = world();
    let peer = addr(5105);
    world.established(peer);
    let now = Instant::now();

    let first = world.egress_tick_at(now);
    let second = world.egress_tick_at(now + Duration::from_millis(20));
    assert_eq!(first.len(), 1);
    assert_eq!(second.len(), 1);
    assert_ne!(
        first[0].datagram, second[0].datagram,
        "the envelope sequence advances, so the second is not a duplicate"
    );
}

/// 6. `data` with a `CONNECT_REQUEST` produces `Nothing`: the flight is retired and the ACK comes from
///    the clock instead.
#[test]
fn a_connect_request_produces_nothing() {
    let mut world = world();
    let peer = addr(5106);
    world.established(peer);

    let mut payload = vec![0xAA, 0xBB, 0xCC, 0xDD];
    payload.push(azoth_wire::carrier::SYS_CONNECT_REQUEST);
    let request = system_datagram(3, &payload);
    assert_eq!(world.data(peer, &request), EntryOutcome::Nothing);

    // And the tick right after it owes the keepalive, which is where the ACK now travels.
    let outbound = world.egress_tick();
    assert_eq!(outbound.len(), 1);
    assert_eq!(ack_range_of(&outbound[0].datagram), (3, 3));
}

/// 7. With zero peers, a tick produces no datagrams at all: the egress costs nothing when idle.
#[test]
fn an_idle_world_produces_no_datagrams() {
    let mut world = world();
    assert!(world.egress_tick().is_empty(), "no peers, no datagrams");

    // And a peer that went away leaves nothing behind either.
    let peer = addr(5107);
    world.established(peer);
    assert_eq!(world.egress_tick().len(), 1);
    world.dropped(peer);
    assert!(world.egress_tick().is_empty(), "the peer is forgotten");
}
