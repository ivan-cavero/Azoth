//! Parity with the Python reference on real captured datagrams.
//!
//! `fixtures/carrier_datagrams.rs` holds datagrams lifted verbatim from
//! `.azoth/logs/world.log`, together with the fields the Python reference
//! (`services/world/src/azoth_world/javelin/frame.py`) decoded from each one.
//! The tests below assert that the Rust envelope/record codec agrees field for
//! field and that re-encoding reproduces the captured bytes exactly.
//!
//! The three kinds are `app-data` (a client->server handshake datagram),
//! `record-bearing` (a client->server datagram whose records carry a real
//! data-channel body, not just a system stub), and `reply` (a server->client
//! datagram). A compressed datagram is carried too, for the envelope header
//! only: the envelope layer must leave an LZ4 body alone.

include!("fixtures/carrier_datagrams.rs");

use everfall_wire::{CarrierError, Datagram, Envelope};

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

fn first_divergence(left: &[u8], right: &[u8]) -> Option<usize> {
    let shorter = left.len().min(right.len());
    if let Some(index) = (0..shorter).find(|index| left[*index] != right[*index]) {
        return Some(index);
    }
    (left.len() != right.len()).then_some(shorter)
}

fn byte_at(bytes: &[u8], index: usize) -> String {
    bytes
        .get(index)
        .map_or_else(|| "past end".to_owned(), |byte| format!("{byte:#04x}"))
}

fn assert_same_bytes(produced: &[u8], expected: &[u8]) {
    let divergence = first_divergence(produced, expected);
    let detail = divergence.map(|index| {
        format!(
            "at {index}: produced {}, expected {}",
            byte_at(produced, index),
            byte_at(expected, index)
        )
    });
    assert!(
        divergence.is_none(),
        "first divergence {detail:?} (produced {} bytes, expected {} bytes)",
        produced.len(),
        expected.len()
    );
}

#[test]
fn the_fixture_covers_the_three_kinds() {
    let kinds: Vec<&str> = SAMPLES.iter().map(|sample| sample.kind).collect();
    for kind in ["app-data", "reply", "record-bearing"] {
        assert!(kinds.contains(&kind), "the fixture must cover {kind}");
    }
    assert_eq!(SAMPLES.len(), 7, "seven uncompressed datagrams");
    assert_eq!(
        kinds.iter().filter(|kind| **kind == "app-data").count(),
        3,
        "three handshake app-data datagrams"
    );
    assert_eq!(
        kinds.iter().filter(|kind| **kind == "reply").count(),
        3,
        "three server replies"
    );
    assert_eq!(
        kinds
            .iter()
            .filter(|kind| **kind == "record-bearing")
            .count(),
        1,
        "one record-bearing datagram"
    );
    assert_eq!(COMPRESSED_SAMPLES.len(), 1, "one compressed header sample");
}

#[test]
fn every_captured_datagram_decodes_as_the_python_reference_did() {
    for sample in SAMPLES {
        let raw = hex_bytes(sample.raw);
        assert_eq!(raw.len(), sample.envelope.size, "{}: size", sample.name);

        let (envelope, body) = Envelope::decode(&raw).expect("envelope decodes");
        assert_eq!(
            envelope.type_byte(),
            sample.envelope.type_byte,
            "{}: type byte",
            sample.name
        );
        assert_eq!(
            envelope.proto(),
            sample.envelope.proto,
            "{}: proto",
            sample.name
        );
        assert_eq!(
            envelope.sequence(),
            sample.envelope.sequence,
            "{}: sequence",
            sample.name
        );
        assert_eq!(
            envelope.is_compressed(),
            sample.envelope.compressed,
            "{}: compressed",
            sample.name
        );
        assert_eq!(
            body.len(),
            sample.envelope.size - 4,
            "{}: body length",
            sample.name
        );

        let records = everfall_wire::decode_records(body).expect("records decode");
        assert_eq!(
            records.len(),
            sample.records.len(),
            "{}: record count",
            sample.name
        );
        for (index, (found, expected)) in records.iter().zip(sample.records).enumerate() {
            let at = format!("{} record {index}", sample.name);
            assert_eq!(found.channel(), expected.channel, "{at}: channel");
            assert_eq!(found.flags(), expected.flags, "{at}: flags");
            assert_eq!(found.payload().len(), expected.size, "{at}: size");
            assert_eq!(found.sequence(), expected.sequence, "{at}: sequence");
            assert_eq!(
                found.reliable_sequence(),
                expected.reliable_sequence,
                "{at}: reliable sequence"
            );
            assert_eq!(found.is_reliable(), expected.reliable, "{at}: reliable");
            assert_eq!(
                found.is_connecting(),
                expected.connecting,
                "{at}: connecting"
            );
            assert_eq!(found.num_chunks(), expected.num_chunks, "{at}: chunks");
            assert_eq!(
                found.system_message_id(),
                expected.system,
                "{at}: system id"
            );
        }
    }
}

#[test]
fn every_captured_datagram_re_encodes_byte_for_byte() {
    for sample in SAMPLES {
        let raw = hex_bytes(sample.raw);
        let mut datagram = Datagram::decode(&raw).expect("datagram decodes");
        // Carry each record's captured flag byte so the writer reproduces the
        // exact bit layout: the reply's third record uses the `0x18` piggyback
        // form the canonical writer would not compute (reference
        // `MessageRecord.flags_override`).
        for record in datagram.records_mut() {
            *record = record.clone().with_flags_override(record.flags());
        }
        let produced = datagram.encode().expect("datagram encodes");
        assert_same_bytes(&produced, &raw);
    }
}

#[test]
fn the_canonical_writer_reproduces_the_client_datagrams_without_overrides() {
    for sample in SAMPLES {
        // A server reply can legitimately use the piggyback flag form, so the
        // canonical writer is only required to reproduce the client's datagrams.
        if sample.kind == "reply" {
            continue;
        }
        let raw = hex_bytes(sample.raw);
        let datagram = Datagram::decode(&raw).expect("datagram decodes");
        let produced = datagram.encode().expect("datagram encodes");
        assert_same_bytes(&produced, &raw);
    }
}

#[test]
fn a_compressed_datagram_is_read_as_a_header_and_left_alone() {
    for sample in COMPRESSED_SAMPLES {
        let raw = hex_bytes(sample.raw);
        assert_eq!(raw.len(), sample.envelope.size, "{}: size", sample.name);

        let (envelope, body) = Envelope::decode(&raw).expect("envelope decodes");
        assert_eq!(envelope.type_byte(), sample.envelope.type_byte);
        assert_eq!(envelope.proto(), sample.envelope.proto);
        assert_eq!(envelope.sequence(), sample.envelope.sequence);
        assert_eq!(envelope.is_compressed(), sample.envelope.compressed);
        assert!(envelope.is_compressed(), "the sample is compressed");

        // The body is the LZ4 block, carried untouched.
        assert_eq!(body, &raw[4..], "the body is the raw LZ4 block");
        let mut produced = Vec::new();
        envelope.encode(&mut produced);
        produced.extend_from_slice(body);
        assert_same_bytes(&produced, &raw);

        assert_eq!(
            Datagram::decode(&raw),
            Err(CarrierError::CompressedBody),
            "a compressed body is not a record stream"
        );
    }
}
