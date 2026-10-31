//! Byte-exact round-trips for the world-entry bodies the server must SEND.
//!
//! The expected bytes are the committed corpus bodies in
//! `research/fixtures/wire/wire-bodies.json`. This is the falsification the
//! crate must pass: `decode` then `encode` returns the fixture body byte for
//! byte, and a few named values prove the decode is semantic, not a byte
//! shuttle. The library never touches these bytes; only this test does.

use std::fs;
use std::path::PathBuf;

use everfall_wire::generated::{
    FlowWorldEntryRungLevelInfo, FlowWorldEntryRungRegistration,
    FlowWorldEntryRungSelfIdentification, MsgObjectivesSetObjectiveAutoPinning,
    MsgObjectivesUpdateTrackedObjectives,
};

fn fixture_text() -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../research/fixtures/wire/wire-bodies.json");
    fs::read_to_string(&path).expect("read committed wire-body fixture")
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

fn body_for(fixture: &str, wire_id: u32) -> Vec<u8> {
    let needle = format!("\"wire_id\": {wire_id},");
    let start = fixture.find(&needle).expect("wire id present in fixture");
    let after_id = &fixture[start..];
    let body_key = "\"body\": \"";
    let body_start = after_id.find(body_key).expect("body key after wire id") + body_key.len();
    let after_body = &after_id[body_start..];
    let end = after_body.find('"').expect("closing quote after body");
    hex_bytes(&after_body[..end])
}

#[test]
fn registration_response_0x3_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x3);
    assert_eq!(body.len(), 85, "0x3 body length");
    assert_eq!(FlowWorldEntryRungRegistration::WIRE_ID, 0x3);

    let decoded = FlowWorldEntryRungRegistration::decode(&body).expect("decode 0x3");
    assert_eq!(
        decoded.server_version, "[RETAIL].Javelin.1.365.6031.6006993",
        "0x3 server_version is a named string"
    );
    assert_eq!(decoded.unresolved_block.len(), 32, "0x3 block width");

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x3");
    assert_eq!(out, body, "0x3 did not round-trip byte for byte");
    println!("0x3 body: {} bytes round-tripped", body.len());
}

#[test]
#[expect(
    clippy::float_cmp,
    reason = "the body is byte-exact, so the decoded floats are exact"
)]
fn level_info_0x663_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x663);
    assert_eq!(body.len(), 106, "0x663 body length");
    assert_eq!(FlowWorldEntryRungLevelInfo::WIRE_ID, 0x663);

    let decoded = FlowWorldEntryRungLevelInfo::decode(&body).expect("decode 0x663");
    assert_eq!(decoded.level_name, "NewWorld_VitaeEterna");
    assert_eq!(decoded.level_path, "coatlicue/NewWorld_VitaeEterna");
    assert_eq!(
        decoded.level_bounds,
        [2048.0_f32, 16.0, 12272.0, 10250.0],
        "0x663 level_bounds is four big-endian floats"
    );
    assert_eq!(decoded.unresolved_group.len(), 10);

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x663");
    assert_eq!(out, body, "0x663 did not round-trip byte for byte");
    println!("0x663 body: {} bytes round-tripped", body.len());
}

#[test]
fn self_identification_0x65c_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x65c);
    assert_eq!(body.len(), 12_702, "0x65c body length");
    assert_eq!(FlowWorldEntryRungSelfIdentification::WIRE_ID, 0x65c);

    let decoded = FlowWorldEntryRungSelfIdentification::decode(&body).expect("decode 0x65c");
    assert_eq!(decoded.prefix_lead, 5);
    assert_eq!(decoded.grid_side, 56, "0x65c grid side");
    assert_eq!(decoded.prefix_data.len(), 107);
    assert_eq!(
        decoded.grid_cells.len(),
        12_544,
        "0x65c grid is 56x56x4 bytes"
    );
    assert_eq!(decoded.tail_lead, 5);
    assert_eq!(decoded.identity_guid_tail.len(), 16);
    assert_eq!(
        decoded.grid_cells.id(),
        "flow.world-entry.rung.self-identification.grid_cells",
        "the run carries its Atlas id"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x65c");
    assert_eq!(out, body, "0x65c did not round-trip byte for byte");
    println!("0x65c body: {} bytes round-tripped", body.len());
}

#[test]
fn update_tracked_objectives_0x5b2_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x5b2);
    assert!(
        (17..=81).contains(&body.len()),
        "0x5b2 body is inside the stated 17..81 range"
    );
    assert_eq!(MsgObjectivesUpdateTrackedObjectives::WIRE_ID, 0x5b2);

    let decoded = MsgObjectivesUpdateTrackedObjectives::decode(&body).expect("decode 0x5b2");
    assert_eq!(
        decoded.field_a, 0x180f_8d4e_5736_97c6,
        "0x5b2 first head u64"
    );
    assert_eq!(
        decoded.field_b, 0xbf85_314b_bc4a_951a,
        "0x5b2 second head u64"
    );
    assert!(
        decoded.tracked_objective_ids.len() <= 8,
        "0x5b2 count is bounded by the stated max"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x5b2");
    assert_eq!(out, body, "0x5b2 did not round-trip byte for byte");
    println!("0x5b2 body: {} bytes round-tripped", body.len());
}

#[test]
fn set_objective_auto_pinning_0xa95_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0xa95);
    assert!(
        (17..=53).contains(&body.len()),
        "0xa95 body is inside the stated 17..53 range"
    );
    assert_eq!(MsgObjectivesSetObjectiveAutoPinning::WIRE_ID, 0xa95);

    let decoded = MsgObjectivesSetObjectiveAutoPinning::decode(&body).expect("decode 0xa95");
    assert_eq!(
        decoded.field_a, 0x180f_8d4e_5736_97c6,
        "0xa95 first head u64"
    );
    assert_eq!(
        decoded.field_b, 0xbf85_314b_bc4a_951a,
        "0xa95 second head u64"
    );
    assert!(
        decoded.auto_pinning_flags.len() <= 36,
        "0xa95 count is bounded by the stated max"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0xa95");
    assert_eq!(out, body, "0xa95 did not round-trip byte for byte");
    println!("0xa95 body: {} bytes round-tripped", body.len());
}

#[test]
fn objectives_count_caps_are_enforced() {
    // The card states a count cap; a body whose prefix-varint count is over the
    // cap must be rejected rather than read as an unbounded vector.
    let mut update = vec![0u8; 16];
    update.push(9); // 0x5b2 states at most 8 tracked-objective ids
    assert!(MsgObjectivesUpdateTrackedObjectives::decode(&update).is_err());

    let mut pinning = vec![0u8; 16];
    pinning.push(37); // 0xa95 states at most 36 flag bytes
    assert!(MsgObjectivesSetObjectiveAutoPinning::decode(&pinning).is_err());
}
