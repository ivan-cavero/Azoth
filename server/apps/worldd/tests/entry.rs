//! `WorldEntry` driven directly, with constructed bytes and no socket.
//!
//! WHY THE MODULES ARE INCLUDED BY `#[path]`
//! ========================================
//! `worldd` is a binary crate, so an integration test cannot `use worldd::…`. Including the same
//! source files by path compiles the **real** entry machine, the real ladder and the real ticket
//! store into the test binary, which is the only way these assertions prove anything about what the
//! world serves. It is the same arrangement `apps/regiond/tests/login.rs` uses.
//!
//! WHY THE BODIES ARE BUILT HERE
//! =============================
//! The layout is what matters, and a builder that drifts is caught by `azoth-wire`'s own byte tests.
//! Only the spawn payload is loaded from its fixture, because the chunk count asserted below is the
//! measured one.

#[path = "../src/entry.rs"]
mod entry;
#[path = "../src/ladder.rs"]
mod ladder;
#[path = "../src/tickets.rs"]
mod tickets;

use std::net::SocketAddr;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use azoth_session::LoginTicket;
use azoth_wire::record::MessageRecord;
use azoth_wire::v3::EXPECTED_BODY_LEN;
use azoth_wire::{bundle, envelope, record, varint, TYPE_MARKER};

use crate::entry::{EntryOutcome, WorldEntry};
use crate::ladder::CHUNK_PAYLOAD;
use crate::tickets::TicketStore;

/// The captured spawn payload, so the chunk count asserted below is the measured one.
const SPAWN: &[u8] =
    include_bytes!("../../../crates/azoth-wire/tests/fixtures/spawn-record-1.bin");

const TICKET_A: &str = "01234567-89ab-4cde-8f01-23456789abcd";
const TICKET_B: &str = "11234567-89ab-4cde-8f01-23456789abcd";

/// End of the opaque prelude, and the first field's offset.
const PRELUDE_END: usize = 0x21;
/// The measured field offsets of the strict form.
const SCHEDULE: [usize; 12] = [
    0x021, 0x02A, 0x038, 0x044, 0x050, 0x05A, 0x083, 0x0A8, 0x0CD, 0x110, 0x144, 0x157,
];
/// Where the 12-byte trailer begins.
const TRAILER_OFF: usize = 0x334;
/// The 12-byte trailer the request must end with.
const REQUEST_TRAILER: [u8; 12] = [0x00, 0x43, 0x02, 0x80, 0, 0, 0, 0, 0, 0, 0, 0];

/// A strict 832-byte registration body naming `ticket_id`.
fn registration_body(ticket_id: &str) -> Vec<u8> {
    let signature = format!("sig:{ticket_id}");
    let fields: [&[u8]; 12] = [
        b"6033",
        b"400",
        b"Javelin",
        b"6024067x",
        b"[RETAIL]",
        signature.as_bytes(),
        b"127.0.0.1:27000",
        ticket_id.as_bytes(),
        b"amzn1.developerPersonaId.fc906c07-42a2-2dd1-f59f-9c56cf4f212c",
        b"STEAM_APP_ID.1063730",
        b"76561197960287930",
        b"steam|14",
    ];
    let mut out = vec![0xAA; PRELUDE_END];
    for (index, offset) in SCHEDULE.iter().enumerate() {
        while out.len() < *offset {
            out.push(0xBB); // an opaque gap
        }
        out.push(fields[index].len() as u8);
        out.extend_from_slice(fields[index]);
    }
    while out.len() < TRAILER_OFF {
        out.push(0xCC); // the auth blob
    }
    out.extend_from_slice(&REQUEST_TRAILER);
    assert_eq!(out.len(), EXPECTED_BODY_LEN, "the strict body's measured size");
    out
}

/// One datagram carrying `payload` as a single reliable channel-0 record.
fn datagram(sequence: u16, payload: &[u8]) -> Vec<u8> {
    let record = MessageRecord {
        flags: 0,
        channel: 0,
        sequence,
        reliable_sequence: sequence,
        reliable: true,
        connecting: false,
        num_chunks: 1,
        payload: payload.to_vec(),
    };
    azoth_wire::ladder::datagram(sequence, &[record]).expect("datagram")
}

/// The registration datagram a client sends.
fn registration(ticket_id: &str) -> Vec<u8> {
    datagram(0, &registration_body(ticket_id))
}

/// A ticket the store will accept, expiring an hour from now.
fn ticket(id: &str) -> LoginTicket {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| i64::try_from(elapsed.as_secs()).unwrap_or(i64::MAX));
    LoginTicket {
        ticket_id: id.to_string(),
        signature: format!("sig:{id}"),
        world_id: "world-1".to_string(),
        character_id: "character-1".to_string(),
        persona_id: "persona-1".to_string(),
        rep_address: "127.0.0.1:9000".to_string(),
        expires_at_unix: now + 3600,
    }
}

fn store(ids: &[&str]) -> TicketStore {
    let mut store = TicketStore::empty();
    for id in ids {
        store.insert(ticket(id));
    }
    store
}

fn entry_with(tickets: TicketStore, spawn: &[u8]) -> WorldEntry {
    WorldEntry::new(tickets, vec![0xAB; 106], spawn.to_vec())
}

fn entry(tickets: TicketStore) -> WorldEntry {
    entry_with(tickets, SPAWN)
}

fn addr(port: u16) -> SocketAddr {
    format!("127.0.0.1:{port}").parse().expect("addr")
}

/// The single record of a datagram.
fn record_of(datagram: &[u8]) -> MessageRecord {
    let (_, body) = envelope::parse(datagram).expect("envelope");
    let mut parsed = record::parse(body).expect("records");
    assert_eq!(parsed.records.len(), 1, "one record per datagram");
    parsed.records.remove(0)
}

/// The typed wire type of a datagram's payload, and `None` for the untyped greeting.
///
/// Only a single-datagram message carries its own VLQ length, so the length check is skipped for a
/// chunk: a chunk is a slice of the message and its first bytes are whatever the cut landed on.
fn wire_type(datagram: &[u8]) -> Option<u64> {
    let message = record_of(datagram);
    let (declared, after) = varint::decode(&message.payload, 0).ok()?;
    if message.num_chunks == 1 && usize::try_from(declared).ok()? != message.payload.len() - after {
        return None;
    }
    bundle::read_type_marker(&message.payload[after..])
        .ok()
        .map(|(type_id, _)| type_id)
}

/// The chunks of a chunked message, concatenated back into the message.
fn reassemble(datagrams: &[Vec<u8>]) -> Vec<u8> {
    datagrams
        .iter()
        .flat_map(|datagram| record_of(datagram).payload)
        .collect()
}

/// Everything a peer is owed by `tick`, until the entry has nothing left.
fn drain(entry: &mut WorldEntry) -> Vec<Vec<u8>> {
    let mut datagrams = Vec::new();
    loop {
        match entry.tick() {
            EntryOutcome::Send { datagrams: sent, .. } => datagrams.extend(sent),
            _ => return datagrams,
        }
    }
}

#[test]
fn an_unknown_ticket_id_is_rejected() {
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4001);
    entry.established(peer);
    match entry.data(peer, &registration("22234567-89ab-4cde-8f01-23456789abcd")) {
        EntryOutcome::Reject { peer: who, reason } => {
            assert_eq!(who, peer);
            assert!(reason.contains("ticket"), "{reason}");
        }
        other => panic!("expected a rejection, got {other:?}"),
    }
    assert_eq!(entry.session_state(peer), None, "the session is forgotten");
}

#[test]
fn a_valid_registration_answers_with_the_v3_response() {
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4002);
    entry.established(peer);
    let EntryOutcome::Send { datagrams, .. } = entry.data(peer, &registration(TICKET_A)) else {
        panic!("a valid registration must be answered");
    };
    assert!(datagrams.len() >= 2, "the response and the first rung");
    let response = record_of(&datagrams[0]).payload;
    assert_eq!(response[0] as usize, 88, "VLQ32 length of the response body");
    assert_eq!(&response[1..3], &TYPE_MARKER, "the typed marker");
    assert_eq!(response[3], 0x03, "RegistrationResponseMsg");
}

#[test]
fn a_second_registration_with_the_same_ticket_is_rejected() {
    let mut entry = entry(store(&[TICKET_A]));
    let (first, second) = (addr(4003), addr(4004));
    entry.established(first);
    entry.established(second);
    assert!(matches!(
        entry.data(first, &registration(TICKET_A)),
        EntryOutcome::Send { .. }
    ));
    match entry.data(second, &registration(TICKET_A)) {
        EntryOutcome::Reject { reason, .. } => assert!(reason.contains("consumed"), "{reason}"),
        other => panic!("a consumed ticket must be rejected, got {other:?}"),
    }
}

#[test]
fn the_ladder_rungs_arrive_in_order() {
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4005);
    entry.established(peer);
    let EntryOutcome::Send { datagrams, .. } = entry.data(peer, &registration(TICKET_A)) else {
        panic!("a valid registration must be answered");
    };
    assert_eq!(wire_type(&datagrams[0]), Some(0x03), "the V3 response first");
    // The first rung rides with the response, as its own datagram.
    assert_eq!(record_of(&datagrams[1]).payload[0], 1, "Cmd_Greetings");
    let rest = drain(&mut entry);
    assert_eq!(wire_type(&rest[0]), Some(0x5D1), "then self-identification");
    assert_eq!(wire_type(&rest[1]), Some(0x663), "then level-info changed");
    let spawn = &rest[2..];
    assert!(spawn.len() > 1, "the spawn is many datagrams");
    for datagram in spawn {
        assert!(
            record_of(datagram).num_chunks > 1,
            "every spawn datagram is a chunk"
        );
    }
}

#[test]
fn the_spawn_rung_is_chunked() {
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4006);
    entry.established(peer);
    entry.data(peer, &registration(TICKET_A));
    // The spawn is the rung after the three typed ones.
    let rest = drain(&mut entry);
    let spawn = &rest[2..];
    let total = u16::try_from(spawn.len()).expect("chunks");
    assert_eq!(total, 43, "46,393 bytes at 1100 per chunk");
    for (index, datagram) in spawn.iter().enumerate() {
        assert!(
            datagram.len() <= 1200,
            "datagram {index} is {} bytes",
            datagram.len()
        );
        let message = record_of(datagram);
        assert_eq!(message.num_chunks, total, "every chunk carries the total");
        if index + 1 < spawn.len() {
            assert_eq!(message.payload.len(), CHUNK_PAYLOAD, "chunk {index}");
        } else {
            assert!(message.payload.len() <= CHUNK_PAYLOAD, "the last chunk");
        }
        assert!(!message.payload.is_empty());
    }
    // Reassembling gives one VLQ-prefixed state bundle whose payload is the captured record.
    let inner = reassemble(spawn);
    let (declared, after) = varint::decode(&inner, 0).expect("VLQ length");
    assert_eq!(usize::try_from(declared).expect("len"), inner.len() - after);
    let body = bundle::decode(&inner[after..], true).expect("a state bundle");
    assert_eq!(body.payload.len(), SPAWN.len(), "the captured record");
}

#[test]
fn a_dropped_peer_starts_fresh() {
    let mut entry = entry(store(&[TICKET_A, TICKET_B]));
    let peer = addr(4007);
    entry.established(peer);
    assert!(matches!(
        entry.data(peer, &registration(TICKET_A)),
        EntryOutcome::Send { .. }
    ));
    entry.dropped(peer);
    assert_eq!(entry.session_state(peer), None, "the session is forgotten");
    assert!(
        matches!(entry.data(peer, &registration(TICKET_B)), EntryOutcome::Nothing),
        "no session means no peer to answer"
    );
    // A fresh handshake and a fresh ticket work, which is what "starts fresh" has to mean.
    entry.established(peer);
    match entry.data(peer, &registration(TICKET_B)) {
        EntryOutcome::Send { datagrams, .. } => assert!(datagrams.len() >= 2),
        other => panic!("a fresh session must register, got {other:?}"),
    }
}

#[test]
fn a_non_registration_does_not_disturb_a_registered_session() {
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4008);
    entry.established(peer);
    entry.data(peer, &registration(TICKET_A));
    drain(&mut entry);
    let junk = datagram(9, b"not a registration");
    assert_eq!(entry.data(peer, &junk), EntryOutcome::Nothing);
    assert_eq!(
        entry.session_state(peer),
        Some(azoth_session::SessionState::Active),
        "the session is still open"
    );
    // And an unregistered peer's junk is equally quiet.
    let stranger = addr(4009);
    entry.established(stranger);
    assert_eq!(entry.data(stranger, &junk), EntryOutcome::Nothing);
}

#[test]
fn a_payload_between_the_single_limit_and_the_chunk_size_is_split_in_two() {
    // 500 bytes is under the chunk size but over the single-datagram limit. One chunk carrying
    // `numChunks 1` would be the oversized single datagram that is never delivered.
    let mut entry = WorldEntry::new(store(&[TICKET_A]), vec![0xAB; 500], SPAWN.to_vec());
    let peer = addr(4010);
    entry.established(peer);
    entry.data(peer, &registration(TICKET_A));
    let rest = drain(&mut entry);
    // rest[0] is self-identification; level-info is the two chunks that follow it.
    let chunks: Vec<MessageRecord> = rest[1..3]
        .iter()
        .map(|datagram| record_of(datagram))
        .collect();
    assert_eq!(chunks[0].num_chunks, 2, "the level-info message is chunked");
    assert_eq!(chunks[1].num_chunks, 2);
    for chunk in &chunks {
        assert!(!chunk.payload.is_empty());
        assert!(chunk.payload.len() < CHUNK_PAYLOAD);
    }
    let inner = reassemble(&rest[1..3]);
    let (declared, after) = varint::decode(&inner, 0).expect("VLQ length");
    assert_eq!(usize::try_from(declared).expect("len"), inner.len() - after);
    assert_eq!(wire_type(&rest[1]), Some(0x663), "and it is still level-info");
}

#[test]
fn a_tick_retransmits_an_unacknowledged_rung() {
    // Nothing in this phase acknowledges, so the session's resend table is the only thing that ever
    // resends a rung — and it must actually reach the socket.
    let mut entry = entry(store(&[TICKET_A]));
    let peer = addr(4011);
    entry.established(peer);
    let EntryOutcome::Send { datagrams, .. } = entry.data(peer, &registration(TICKET_A)) else {
        panic!("a valid registration must be answered");
    };
    let later = Instant::now() + Duration::from_secs(1);
    let EntryOutcome::Send {
        datagrams: resent, ..
    } = entry.tick_at(later)
    else {
        panic!("a second past the 300 ms interval, both rungs are due");
    };
    assert!(resent.contains(&datagrams[0]), "the response is resent");
    assert!(resent.contains(&datagrams[1]), "and the first rung");
}
