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
use std::sync::Mutex;

use azoth_wire::carrier::{SYS_CONNECT_ACK, SYS_CONNECT_REQUEST, SYS_CT_ACKS};
use azoth_wire::record::MessageRecord;
use azoth_wire::{envelope, record};

use crate::entry::{EntryOutcome, WorldEntry};
use crate::tickets::TicketStore;

/// The ids of the flight, in order: CLOCK_SYNC, CONNECT_ACK, CT_ACKS.
const FLIGHT_IDS: [u8; 3] = [4, 2, 6];

/// The diagnostics notes this test binary captured. A note sink is a `fn` pointer, so it cannot
/// capture: the sink writes into this buffer and a test filters it by peer address.
static NOTES: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// The sink `worldd` installs under `--diagnostics`: keep the line instead of printing it.
fn capture_note(peer: SocketAddr, line: &str) {
    if let Ok(mut notes) = NOTES.lock() {
        notes.push(format!("peer={peer} {line}"));
    }
}

/// The note lines captured for `peer`, draining them so a later test cannot read them again.
fn notes_for(peer: SocketAddr) -> Vec<String> {
    let prefix = format!("peer={peer} ");
    let Ok(mut notes) = NOTES.lock() else {
        return Vec::new();
    };
    let mine: Vec<String> = notes.iter().filter(|line| line.starts_with(&prefix)).cloned().collect();
    notes.retain(|line| !line.starts_with(&prefix));
    mine
}

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

/// Any other inbound datagram: the client's own CT_ACKS. `data` answers it with silence, but the ACK
/// range must still count it — that is the whole point of the window.
fn other_datagram(envelope_sequence: u16) -> Vec<u8> {
    system_datagram(envelope_sequence, &[0x40, 0x00, 0x05, 0x00, 0x05, SYS_CT_ACKS])
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

/// 7. The flight acknowledges every datagram the peer sent, not only the one carrying the request.
///    A degenerate range is the measured defect: the client re-sent its request five times and never
///    sent V3, because a range of one is not an acknowledgement it accepts (2026-09-18).
#[test]
fn the_flight_acknowledges_every_datagram_the_peer_sent() {
    let mut entry = entry();
    let peer = addr(5007);
    entry.established(peer);
    for sequence in 10..14 {
        assert_eq!(entry.data(peer, &other_datagram(sequence)), EntryOutcome::Nothing);
    }

    let (_, datagrams) = sent(entry.data(peer, &connect_request(14, &[0xAA, 0xBB, 0xCC, 0xDD])));
    let (first, last) = ack_range_of(&datagrams[0]);
    assert_eq!(last, 14, "the range ends at the sequence that carried the request");
    assert_eq!(first, last - 4, "five datagrams received, five acknowledged");
}

/// 8. A peer that has sent exactly one datagram gets a range of one — the window is the count while
///    the session is younger than it, so the first request is not answered with an empty range.
#[test]
fn a_single_datagram_produces_a_degenerate_range() {
    let mut entry = entry();
    let peer = addr(5008);
    entry.established(peer);

    let (_, datagrams) = sent(entry.data(peer, &connect_request(21, &[0xAA, 0xBB, 0xCC, 0xDD])));
    assert_eq!(ack_range_of(&datagrams[0]), (21, 21));
}

/// 9. The echo rule is unchanged by the window: the reply's envelope sequence is still the request's
///    own sequence, while the ACK range is the wider one.
#[test]
fn the_reply_still_echoes_the_requests_sequence_with_a_wider_range() {
    let mut entry = entry();
    let peer = addr(5009);
    entry.established(peer);
    for sequence in [0x1231, 0x1232, 0x1233] {
        assert_eq!(entry.data(peer, &other_datagram(sequence)), EntryOutcome::Nothing);
    }

    let (_, datagrams) =
        sent(entry.data(peer, &connect_request(0x1234, &[0xAA, 0xBB, 0xCC, 0xDD])));
    let (head, _) = envelope::parse(&datagrams[0]).expect("envelope");
    assert_eq!(head.sequence, 0x1234, "the reply echoes the inbound sequence");
    assert_eq!(
        ack_range_of(&datagrams[0]),
        (0x1231, 0x1234),
        "four datagrams received, four acknowledged"
    );
}

/// 10. The welcome is still the request payload minus its trailing sys-id byte, truncated to the
///     version field — the window changed what the flight acknowledges, not what it echoes.
#[test]
fn the_welcome_is_still_the_payload_without_its_sys_id() {
    let mut entry = entry();
    let peer = addr(5010);
    entry.established(peer);
    assert_eq!(entry.data(peer, &other_datagram(30)), EntryOutcome::Nothing);

    let request = connect_request(31, &[0xAA, 0xBB, 0xCC, 0xDD, 0xEE]);
    let (_, datagrams) = sent(entry.data(peer, &request));
    assert_eq!(
        welcome_of(&datagrams[0]),
        vec![0xAA, 0xBB, 0xCC, 0xDD],
        "the payload minus its sys id, truncated to four bytes"
    );
}

/// 11. With diagnostics on, one greppable line reports the whole `SM_CONNECT_REQUEST` payload, the
///     welcome derived from it, the ACK range claimed, the datagram count and the echoed sequence.
///     This is the measurement that decides the next step when a client will not leave CONNECTING.
#[test]
fn the_connect_request_payload_is_reported_with_the_range_and_the_echo() {
    diagnostics::install_note_sink(capture_note);
    let mut entry = entry();
    let peer = addr(5011);
    entry.established(peer);
    assert_eq!(entry.data(peer, &other_datagram(40)), EntryOutcome::Nothing);

    let _ = sent(entry.data(peer, &connect_request(41, &[0xAA, 0xBB, 0xCC, 0xDD])));
    let notes = notes_for(peer);
    assert_eq!(notes.len(), 1, "one line per request, not per record: {notes:?}");
    assert_eq!(
        notes[0],
        format!(
            "peer={peer} connect_request payload=aabbccdd01 welcome=aabbccdd ack_first=40 \
             ack_last=41 datagrams_seen=2 echo_seq=41"
        )
    );
}
