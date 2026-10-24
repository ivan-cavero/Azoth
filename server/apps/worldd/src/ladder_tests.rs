use super::*;
use azoth_wire::record::MessageRecord;
use azoth_wire::{envelope, record, varint};

fn ladder() -> Ladder {
    // The spawn payload is large enough to need chunking, because that is the measured case.
    Ladder::for_peer(
        "127.0.0.1:27000".parse().expect("addr"),
        vec![0xAB; 106],
        vec![0xCD; 3000],
    )
}

/// The single record in `datagram`.
fn message(datagram: &[u8]) -> MessageRecord {
    let (_, body) = envelope::parse(datagram).expect("envelope");
    record::parse(body).expect("records").records.remove(0)
}

#[test]
fn the_ladder_has_four_rungs() {
    let ladder = ladder();
    assert_eq!(ladder.remaining(), 4);
    assert!(!ladder.is_complete());
}

#[test]
fn each_call_returns_exactly_one_datagram() {
    // Batching two rungs in one datagram crashed the client, so one-per-call is the contract.
    let mut ladder = ladder();
    let mut seen = 0;
    while let Some(out) = ladder.next().expect("encodes") {
        seen += 1;
        assert!(out.datagram.len() > 4, "a datagram, not a bare payload");
        assert_eq!(out.datagram[0] & 0x80, 0x80, "plaintext envelope");
        assert!(seen <= 64, "the ladder must end");
    }
    assert!(ladder.is_complete());
    assert_eq!(ladder.remaining(), 0);
}

#[test]
fn the_envelope_sequence_advances_per_datagram() {
    // The envelope counter is a different counter from the record sequences, and the ACK range
    // is expressed over it. Conflating them cost the prototype a session at ~26 minutes.
    let mut ladder = ladder();
    let mut expected = 1u16;
    while let Some(out) = ladder.next().expect("encodes") {
        assert_eq!(u16::from_be_bytes([out.datagram[2], out.datagram[3]]), expected);
        expected += 1;
    }
    assert!(expected > 4, "the spawn alone is many datagrams");
}

#[test]
fn the_first_rung_is_the_greeting() {
    let mut ladder = ladder();
    let first = ladder.next().expect("encodes").expect("rung");
    // The greeting payload is 10 bytes and starts with Cmd_Greetings = 1. The record prefix is
    // flags(1) + size(2) + seq(2) + rel(2): the CHANNEL byte is omitted for channel 0, because
    // the writer's previous-channel starts at 0.
    assert_eq!(first.datagram[4 + 1 + 2 + 2 + 2], 1, "Cmd_Greetings");
}

#[test]
fn the_spawn_rung_is_a_chunked_state_bundle() {
    let mut ladder = ladder();
    for _ in 0..3 {
        ladder.next().expect("encodes");
    }
    let spawn = ladder.next().expect("encodes").expect("rung");
    let message = message(&spawn.datagram);
    assert!(message.num_chunks > 1, "the spawn must be chunked");
    // A chunk is a slice of the message, so the first one starts with the message's VLQ length
    // and then the type marker.
    let (_, after) = varint::decode(&message.payload, 0).expect("VLQ length");
    assert_eq!(&message.payload[after..after + 3], &[0x00, 0x01, 0x08]);
}

#[test]
fn the_registration_rung_carries_the_response() {
    let mut ladder = ladder();
    let response = ladder.registration([0x5A; 32]).expect("encodes");
    let message = message(&response.datagram);
    assert_eq!(message.payload[0] as usize, 88, "VLQ32 length of the body");
    assert_eq!(&message.payload[1..3], &[0x00, 0x01], "the typed marker");
    assert_eq!(message.payload[3], 0x03, "RegistrationResponseMsg");
    assert_eq!(response.ontology_uid, "flow.world-entry.rung.v3-response");
    let greeting = ladder.next().expect("encodes").expect("rung");
    assert_eq!(greeting.reliable_sequence, 2, "the greeting shares the counters");
    assert_eq!(greeting.ontology_uid, "flow.world-entry.rung.greetings");
}

#[test]
fn every_ladder_step_names_an_ontology_concept() {
    let steps = [
        Step::Greetings,
        Step::SelfIdentification,
        Step::LevelInfoChanged { body: vec![0] },
        Step::Spawn { payload: vec![0] },
    ];
    for step in steps {
        assert!(
            step.ontology_uid().starts_with("flow.world-entry."),
            "{}",
            step.ontology_uid()
        );
    }
}
