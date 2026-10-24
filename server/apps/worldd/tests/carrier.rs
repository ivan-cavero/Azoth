//! The Carrier layer as `worldd` produces it: the retired acceptance flight as an *encoder*, and the
//! keepalive that replaced it as *behaviour*.
//!
//! WHY NINE TESTS CHANGED AND NONE OF THE BYTES DID
//! ===============================================
//! The census is in `worldd::entry::egress`: across 1,338,802 lines of the Python prototype's own
//! traffic (`services/world/rep_traffic.jsonl`) the channel-3 system ids are CT_ACKS 313,578,
//! CONN_CONTROL 159, CONNECT_REQUEST 65, DISCONNECT 8 — and **CLOCK_SYNC 0, CONNECT_ACK 0**. The
//! acceptance flight is those two zeros, so `worldd` no longer builds it: `established` sends nothing,
//! `data` answers a `SM_CONNECT_REQUEST` with `Nothing`, and the ACK rides on the next tick's
//! keepalive. The tests that asserted the flight came out of `established`/`data` were therefore
//! rewritten to assert that, and the byte-level assertions they carried are kept below pinned to
//! [`AcceptanceFlight`] itself — the encoder is still the only statement of what those captured bytes
//! were, and `acks_payload` (which it shares with the keepalive) still has to be right.
//!
//! The modules are included by `#[path]` because `worldd` is a binary crate, exactly as
//! `tests/entry.rs` does it. `egress` is declared *inside* `entry.rs`, so it arrives with it.

#[path = "../src/config.rs"]
mod config;
#[path = "../src/diagnostics.rs"]
mod diagnostics;
#[path = "../src/entry.rs"]
mod entry;
#[path = "../src/ladder.rs"]
mod ladder;
#[path = "../src/presence.rs"]
mod presence;
#[path = "../src/tickets.rs"]
mod tickets;

use std::net::SocketAddr;
use std::sync::Mutex;

use azoth_session::ACK_WINDOW_DEFAULT;
use azoth_wire::carrier::{ACK_CONTINUOUS, AcceptanceFlight, SYS_CONNECT_ACK, SYS_CONNECT_REQUEST, SYS_CT_ACKS};
use azoth_wire::record::MessageRecord;
use azoth_wire::{envelope, record};

use crate::entry::{EntryOutcome, WorldEntry};
use crate::tickets::TicketStore;

/// The ids of the retired flight, in order: CLOCK_SYNC, CONNECT_ACK, CT_ACKS.
const FLIGHT_IDS: [u8; 3] = [4, 2, 6];

/// The flag bytes the flight was sent with: `MF_DATA_CHANNEL`, `MF_RELIABLE | MF_DATA_CHANNEL`, and
/// `MF_SEQUENTIAL_ID | MF_SEQUENTIAL_REL_ID` (both sequences inherited).
const FLIGHT_FLAGS: [u8; 3] = [0x20, 0x21, 0x18];

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
    let mine: Vec<String> = notes
        .iter()
        .filter(|line| line.starts_with(&prefix))
        .cloned()
        .collect();
    notes.retain(|line| !line.starts_with(&prefix));
    mine
}

fn addr(port: u16) -> SocketAddr {
    format!("127.0.0.1:{port}").parse().expect("addr")
}

/// A world with no tickets: nothing here registers, so only the Carrier layer is exercised.
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

/// The `(ack_first, ack_last)` range a datagram's `CT_ACKS` record carries: `0x40`, last, first, id.
fn ack_range_of(datagram: &[u8]) -> (u16, u16) {
    let records = records_of(datagram);
    let payload = &records
        .iter()
        .find(|message| message.system_msg_id() == Some(6))
        .expect("a CT_ACKS record")
        .payload;
    assert_eq!(payload.len(), 6, "flags, last, first, id");
    assert_eq!(payload[0], ACK_CONTINUOUS);
    let last = u16::from_be_bytes([payload[1], payload[2]]);
    let first = u16::from_be_bytes([payload[3], payload[4]]);
    (first, last)
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

/// Any other inbound datagram: the client's own CT_ACKS. It is answered with silence, but the ACK
/// range must still count it — that is the whole point of the window.
fn other_datagram(envelope_sequence: u16) -> Vec<u8> {
    system_datagram(
        envelope_sequence,
        &[0x40, 0x00, 0x05, 0x00, 0x05, SYS_CT_ACKS],
    )
}

/// The flight an `SM_CONNECT_REQUEST` with `version` used to produce, built directly.
fn flight(version: &[u8]) -> AcceptanceFlight {
    let mut payload = version.to_vec();
    payload.push(SYS_CONNECT_REQUEST);
    AcceptanceFlight::answering(1_700_000_000, &payload, 14, 5, ACK_WINDOW_DEFAULT)
}

/// 1. The encoder still produces the captured shape: three records, channel 3, CLOCK_SYNC then
///    CONNECT_ACK then CT_ACKS, each with the flag byte the client was sent.
#[test]
fn the_retired_flight_still_encodes_three_channel_three_records() {
    let datagram = flight(&[0xAA, 0xBB, 0xCC, 0xDD]).datagram(3).expect("encodes");
    let records = records_of(&datagram);
    let ids: Vec<Option<u8>> = records.iter().map(MessageRecord::system_msg_id).collect();
    assert_eq!(
        ids,
        FLIGHT_IDS.iter().copied().map(Some).collect::<Vec<_>>(),
        "CLOCK_SYNC, CONNECT_ACK, CT_ACKS"
    );
    for message in &records {
        assert_eq!(message.channel, 3, "every flight record rides channel 3");
    }
    let flags: Vec<u8> = records.iter().map(|message| message.flags).collect();
    assert_eq!(flags, FLIGHT_FLAGS, "the measured flag bytes, unchanged");
}

/// 2. The encoder echoes the envelope sequence it is given — the client's own, never a server counter.
#[test]
fn the_retired_flight_echoes_the_envelope_sequence_it_is_given() {
    let datagram = flight(&[0xAA, 0xBB, 0xCC, 0xDD]).datagram(0x1234).expect("encodes");
    let (head, _) = envelope::parse(&datagram).expect("envelope");
    assert_eq!(head.sequence, 0x1234);
}

/// 3. `CONNECT_ACK` echoes the request's version: the payload minus its trailing sys id.
#[test]
fn the_retired_flight_echoes_the_requests_version() {
    let datagram = flight(&[0xAA, 0xBB, 0xCC, 0xDD, 0xEE]).datagram(1).expect("encodes");
    let mut welcome = records_of(&datagram)[1].payload.clone();
    assert_eq!(welcome.pop(), Some(SYS_CONNECT_ACK));
    assert_eq!(welcome, vec![0xAA, 0xBB, 0xCC, 0xDD], "truncated to four bytes");
}

/// 4. A request too short to carry a version gets the prototype's `00 00 00 05` fallback rather than
///    an invented one.
#[test]
fn a_short_request_gets_the_default_welcome() {
    let datagram = flight(&[0xAA]).datagram(1).expect("encodes");
    let mut welcome = records_of(&datagram)[1].payload.clone();
    welcome.pop();
    assert_eq!(welcome, vec![0x00, 0x00, 0x00, 0x05]);
}

/// 5. The encoder acknowledges the range it is given, and `answering` derives that range from the
///    peer's counters: five datagrams seen ending at 14 is `10..=14`.
#[test]
fn the_retired_flight_acknowledges_the_range_its_counters_earned() {
    let datagram = flight(&[0xAA, 0xBB, 0xCC, 0xDD]).datagram(14).expect("encodes");
    assert_eq!(ack_range_of(&datagram), (10, 14));
}

/// 6. `established` alone sends nothing at all: no flight, and no CLOCK_SYNC keepalive either.
#[test]
fn established_alone_sends_nothing() {
    let mut entry = entry();
    let peer = addr(5001);

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
        EntryOutcome::Nothing,
        "the state pump has nothing for it"
    );
}

/// 7. THE RETIRED FLIGHT: `data` with a `SM_CONNECT_REQUEST` produces `Nothing`. This is the assertion
///    that replaced nine that expected the flight — the ACK is not a reply any more.
#[test]
fn a_connect_request_is_answered_with_nothing() {
    let mut entry = entry();
    let peer = addr(5002);
    entry.established(peer);

    let request = connect_request(3, &[0xAA, 0xBB, 0xCC, 0xDD]);
    assert_eq!(entry.data(peer, &request), EntryOutcome::Nothing);
    // A repeated request is equally quiet: the client's Carrier resends until it sees an ACK, and the
    // ACK it needs comes from the clock, not from an answer to the retransmission.
    assert_eq!(entry.data(peer, &request), EntryOutcome::Nothing);
    assert_eq!(
        entry.session_state(peer),
        Some(azoth_session::SessionState::Transport),
        "the request changes no state: it is only counted"
    );
}

/// 8. What replaced it: the next tick's keepalive, carrying the ACK for the request that was just
///    received. One record, channel 3, sys id 6, and the range names the request's sequence.
#[test]
fn the_tick_after_a_connect_request_sends_the_keepalive() {
    let mut entry = entry();
    let peer = addr(5003);
    entry.established(peer);
    assert_eq!(
        entry.data(peer, &connect_request(7, &[0xAA, 0xBB, 0xCC, 0xDD])),
        EntryOutcome::Nothing
    );

    let outbound = entry.egress_tick();
    assert_eq!(outbound.len(), 1, "one datagram for one peer");
    assert_eq!(outbound[0].peer, peer);
    let records = records_of(&outbound[0].datagram);
    assert_eq!(records.len(), 1, "the keepalive is the ACK and nothing else");
    assert_eq!(records[0].channel, 3);
    assert_eq!(
        records[0].system_msg_id(),
        Some(SYS_CT_ACKS),
        "CT_ACKS, not CLOCK_SYNC (sys 4) and not CONNECT_ACK (sys 2)"
    );
    assert_eq!(ack_range_of(&outbound[0].datagram), (7, 7), "one datagram, one acknowledged");
}

/// 9. With diagnostics on, the request is still measured: its payload, the welcome it implies, the
///    ACK range the next datagram will claim, and the sequence it arrived on. The reply is gone; the
///    measurement is not.
#[test]
fn the_connect_request_is_still_reported() {
    diagnostics::install_note_sink(capture_note);
    let mut entry = entry();
    let peer = addr(5004);
    entry.established(peer);
    assert_eq!(entry.data(peer, &other_datagram(40)), EntryOutcome::Nothing);

    let _ = entry.data(peer, &connect_request(41, &[0xAA, 0xBB, 0xCC, 0xDD]));
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
