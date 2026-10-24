//! The acceptance flight as `worldd` produces it: the answer to the client's `SM_CONNECT_REQUEST`.
//!
//! WHY THIS DRIVES `WorldEntry` DIRECTLY
//! ====================================
//! The measured failure is not in the encoder — it is the *trigger*. A flight sent when the DTLS
//! handshake completes leaves with an empty welcome, because the client's version has not arrived
//! yet: the prototype only answers the request (`services/world/src/azoth_world/rep.py`,
//! `handle_app_data`: `if requests and not handshake_done`), and the version it echoes is that
//! request's payload minus its trailing sys-id byte. So the assertion that matters is about what a
//! `data` carrying a channel-3 `SM_CONNECT_REQUEST` produces, which is what [`WorldEntry::data`]
//! returns. A byte test on the encoder alone would have passed while the client still timed out.
//!
//! The modules are included by `#[path]` because `worldd` is a binary crate, exactly as
//! `tests/entry.rs` does it: the real entry machine, the real ladder and the real ticket store are
//! compiled in, so these assertions are about what the world actually serves.

#[path = "../src/config.rs"]
mod config;
#[path = "../src/diagnostics.rs"]
mod diagnostics;
#[path = "../src/entry.rs"]
mod entry;
#[path = "../src/ladder.rs"]
mod ladder;
#[path = "../src/tickets.rs"]
mod tickets;

use std::net::SocketAddr;

use azoth_wire::carrier::{SYS_CONNECT_ACK, SYS_CONNECT_REQUEST, SYS_CT_ACKS};
use azoth_wire::record::MessageRecord;
use azoth_wire::{envelope, record};

use crate::entry::{EntryOutcome, WorldEntry};
use crate::tickets::TicketStore;

/// The ids of the flight, in order: CLOCK_SYNC, CONNECT_ACK, CT_ACKS.
const FLIGHT_IDS: [u8; 3] = [4, 2, 6];

fn addr(port: u16) -> SocketAddr {
    format!("127.0.0.1:{port}").parse().expect("addr")
}

/// A world with no tickets: nothing here registers, so only the flight is exercised.
fn entry() -> WorldEntry {
    WorldEntry::new(TicketStore::empty(), vec![0xAB; 106], vec![0xCD; 64])
}

/// The records of one datagram, which must consume it exactly.
fn records_of(datagram: &[u8]) -> Vec<MessageRecord> {
    let (_, body) = envelope::parse(datagram).expect("a Carrier envelope");
    let parsed = record::parse(body).expect("records");
    assert_eq!(parsed.trailing_bytes, 0, "the datagram is exactly records");
    parsed.records
}

/// The records of the datagram an outcome sends, which must be a `Send`.
fn sent(outcome: EntryOutcome) -> (SocketAddr, Vec<Vec<u8>>) {
    match outcome {
        EntryOutcome::Send { peer, datagrams } => (peer, datagrams),
        other => panic!("expected a send, got {other:?}"),
    }
}

/// A client datagram whose one record rides channel 3 with `payload` — the shape the client sends
/// its `SM_CONNECT_REQUEST` in, sys id last.
fn system_datagram(envelope_sequence: u16, payload: &[u8]) -> Vec<u8> {
    let message = MessageRecord {
        flags: 0,
        channel: azoth_wire::CHANNEL_SYSTEM,
        sequence: 0,
        reliable_sequence: 0,
        reliable: true,
        connecting: false,
        num_chunks: 1,
        payload: payload.to_vec(),
    };
    azoth_wire::ladder::datagram(envelope_sequence, &[message]).expect("a Carrier datagram")
}

/// A `SM_CONNECT_REQUEST` carrying `version` as its data and the sys id after it.
fn connect_request(envelope_sequence: u16, version: &[u8]) -> Vec<u8> {
    let mut payload = version.to_vec();
    payload.push(SYS_CONNECT_REQUEST);
    system_datagram(envelope_sequence, &payload)
}

/// Assert that a datagram is the flight, and return its records.
fn assert_flight(datagram: &[u8]) -> Vec<MessageRecord> {
    let records = records_of(datagram);
    assert_eq!(records.len(), 3, "the flight is three records");
    let ids: Vec<Option<u8>> = records.iter().map(MessageRecord::system_msg_id).collect();
    assert_eq!(
        ids,
        FLIGHT_IDS.iter().copied().map(Some).collect::<Vec<_>>(),
        "CLOCK_SYNC, CONNECT_ACK, CT_ACKS"
    );
    for message in &records {
        assert_eq!(message.channel, 3, "every flight record rides channel 3");
    }
    records
}

/// The welcome bytes the flight's `CONNECT_ACK` echoes.
fn welcome_of(datagram: &[u8]) -> Vec<u8> {
    let records = assert_flight(datagram);
    let mut payload = records[1].payload.clone();
    assert_eq!(
        payload.pop(),
        Some(SYS_CONNECT_ACK),
        "the CONNECT_ACK payload ends with its sys id"
    );
    payload
}

/// The `(ack_first, ack_last)` range the flight's `CT_ACKS` carries: `0x40`, last, first, id.
fn ack_range_of(datagram: &[u8]) -> (u16, u16) {
    let records = assert_flight(datagram);
    let payload = &records[2].payload;
    assert_eq!(payload.len(), 6, "flags, last, first, id");
    let last = u16::from_be_bytes([payload[1], payload[2]]);
    let first = u16::from_be_bytes([payload[3], payload[4]]);
    (first, last)
}

/// 1. A channel-3 `SM_CONNECT_REQUEST` produces the flight, and the CONNECT_ACK echoes the client's
///    own version — the four bytes before the trailing sys id.
#[test]
fn a_connect_request_is_answered_with_the_flight_echoing_its_version() {
    let mut entry = entry();
    let peer = addr(5001);
    entry.established(peer);

    let (who, datagrams) = sent(entry.data(peer, &connect_request(3, &[0xAA, 0xBB, 0xCC, 0xDD])));
    assert_eq!(who, peer);
    assert_eq!(datagrams.len(), 1, "the flight is one datagram");
    assert_eq!(
        welcome_of(&datagrams[0]),
        vec![0xAA, 0xBB, 0xCC, 0xDD],
        "the CONNECT_ACK echoes the version the request carried"
    );
}

/// 2. A request too short to carry a version gets the prototype's `00 00 00 05` fallback instead of
///    an invented one.
#[test]
fn a_short_connect_request_gets_the_default_welcome() {
    let mut entry = entry();
    let peer = addr(5002);
    entry.established(peer);

    let (_, datagrams) = sent(entry.data(peer, &connect_request(3, &[0xAA, 0xBB])));
    assert_eq!(
        welcome_of(&datagrams[0]),
        vec![0x00, 0x00, 0x00, 0x05],
        "a payload under 5 bytes falls back to 00 00 00 05"
    );
}

/// 3. The reply's envelope sequence — and therefore the ACK range — is the inbound one, echoed. A
///    server counter here is the measured trap: the client keeps retransmitting as if the reply never
///    arrived.
#[test]
fn the_flight_echoes_the_envelope_sequence_of_the_request() {
    let mut entry = entry();
    let peer = addr(5003);
    entry.established(peer);

    let (_, datagrams) =
        sent(entry.data(peer, &connect_request(0x1234, &[0xAA, 0xBB, 0xCC, 0xDD])));
    let (head, _) = envelope::parse(&datagrams[0]).expect("envelope");
    assert_eq!(head.sequence, 0x1234, "the reply echoes the inbound sequence");
    assert_eq!(
        ack_range_of(&datagrams[0]),
        (0x1234, 0x1234),
        "and acknowledges exactly the datagram that carried the request"
    );
}

/// 4. `established` alone produces nothing: the version is not known yet, so a flight sent here could
///    only carry an empty welcome — the defect this trigger replaces.
#[test]
fn established_alone_sends_no_flight() {
    let mut entry = entry();
    let peer = addr(5004);

    assert_eq!(
        entry.established(peer),
        EntryOutcome::Nothing,
        "the handshake alone decides nothing to send"
    );
    assert_eq!(
        entry.session_state(peer),
        Some(azoth_session::SessionState::Transport),
        "the session is still opened"
    );
    assert_eq!(
        entry.tick_at(std::time::Instant::now()),
        EntryOutcome::Nothing
    );
}

/// 5. A repeated request is answered again. The client's Carrier resends the CONNECT_REQUEST until
///    one of our datagrams is acknowledged, so the retransmission that follows a lost flight has to
///    get an answer of its own.
#[test]
fn a_repeated_connect_request_is_answered_again() {
    let mut entry = entry();
    let peer = addr(5005);
    entry.established(peer);
    let request = connect_request(4, &[0xAA, 0xBB, 0xCC, 0xDD]);

    let (_, first) = sent(entry.data(peer, &request));
    assert_eq!(welcome_of(&first[0]), vec![0xAA, 0xBB, 0xCC, 0xDD]);

    let (_, second) = sent(entry.data(peer, &request));
    assert_eq!(second.len(), 1, "the retransmission gets its own flight");
    assert_eq!(welcome_of(&second[0]), vec![0xAA, 0xBB, 0xCC, 0xDD]);
}

/// 6. Only `SM_CONNECT_REQUEST` triggers the flight: another channel-3 system message (here the
///    client's own CT_ACKS) is not a request and must be answered with silence.
#[test]
fn another_channel_three_system_message_is_not_a_request() {
    let mut entry = entry();
    let peer = addr(5006);
    entry.established(peer);

    let ct_acks = system_datagram(5, &[0x40, 0x00, 0x05, 0x00, 0x05, SYS_CT_ACKS]);
    assert_eq!(entry.data(peer, &ct_acks), EntryOutcome::Nothing);
}
