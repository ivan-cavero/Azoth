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
    FlowWorldEntryRungSelfIdentification, MsgContractsLookupContractsByParticipant,
    MsgObjectivesSetObjectiveAutoPinning, MsgObjectivesUpdateTrackedObjectives,
    MsgReceiveSettingsFromClient, MsgSetReplicateStorage, MsgTimeSyncToClient,
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
    bodies_for(fixture, wire_id)
        .into_iter()
        .next()
        .expect("wire id present in fixture")
}

/// Every committed body for one wire id, in fixture order.
///
/// A variable-width message (0x9fc carries both 72- and 74-byte bodies)
/// round-trips each width, so a single sample cannot hide a layout that only
/// happens to fit one width.
fn bodies_for(fixture: &str, wire_id: u32) -> Vec<Vec<u8>> {
    let needle = format!("\"wire_id\": {wire_id},");
    let body_key = "\"body\": \"";
    let mut out = Vec::new();
    let mut rest = fixture;
    while let Some(start) = rest.find(&needle) {
        let after_id = &rest[start..];
        let body_start = after_id.find(body_key).expect("body key after wire id") + body_key.len();
        let after_body = &after_id[body_start..];
        let end = after_body.find('"').expect("closing quote after body");
        out.push(hex_bytes(&after_body[..end]));
        rest = &after_body[end..];
    }
    out
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
fn receive_settings_from_client_0x9d3_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x9d3);
    assert_eq!(body.len(), 20, "0x9d3 body length");
    assert_eq!(MsgReceiveSettingsFromClient::WIRE_ID, 0x9d3);

    let decoded = MsgReceiveSettingsFromClient::decode(&body).expect("decode 0x9d3");
    assert_eq!(
        decoded.field_a, 0xd1a9_4ccc_8706_60b0,
        "0x9d3 first head u64"
    );
    assert_eq!(
        decoded.field_b, 0xbf85_314b_bc4a_951a,
        "0x9d3 second head u64"
    );
    assert_eq!(decoded.field_c, 0x0000_97c9, "0x9d3 trailing u32");

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x9d3");
    assert_eq!(out, body, "0x9d3 did not round-trip byte for byte");
    println!("0x9d3 body: {} bytes round-tripped", body.len());
}

#[test]
fn contracts_lookup_by_participant_0x9fc_round_trips_both_widths() {
    let fixture = fixture_text();
    let bodies = bodies_for(&fixture, 0x9fc);
    assert!(
        bodies.len() >= 2,
        "0x9fc has both the 72- and 74-byte widths"
    );
    assert_eq!(MsgContractsLookupContractsByParticipant::WIRE_ID, 0x9fc);

    let mut seen_widths = std::collections::BTreeSet::new();
    for body in &bodies {
        assert!(
            body.len() == 72 || body.len() == 74,
            "0x9fc body width {}",
            body.len()
        );
        seen_widths.insert(body.len());

        let decoded = MsgContractsLookupContractsByParticipant::decode(body).expect("decode 0x9fc");
        assert_eq!(
            decoded.field_a, 0x4c0c_0ed6_478a_69da,
            "0x9fc first head u64"
        );
        assert_eq!(
            decoded.field_b, 0xbf85_314b_bc4a_951a,
            "0x9fc second head u64"
        );
        assert_eq!(
            decoded.participant_id.len(),
            16,
            "0x9fc participant id width"
        );
        assert!(
            decoded.blob_64.is_empty() && decoded.blob_256.is_empty(),
            "0x9fc length-prefixed blobs are empty in every sample"
        );
        assert!(
            decoded.index_ids.len() <= 3,
            "0x9fc index vector is capped at 3"
        );
        assert!(
            decoded.type_ids.len() <= 25,
            "0x9fc type vector is capped at 25"
        );
        assert_eq!(decoded.trailing_id.len(), 16, "0x9fc trailing id width");

        let mut out = Vec::new();
        decoded.encode(&mut out).expect("encode 0x9fc");
        assert_eq!(&out, body, "0x9fc did not round-trip byte for byte");
    }
    assert_eq!(
        seen_widths.into_iter().collect::<Vec<_>>(),
        vec![72, 74],
        "both committed 0x9fc widths were exercised"
    );
}

#[test]
fn contracts_lookup_blob_caps_are_enforced() {
    // A 65-byte blob exceeds the stated cap of 64; the reader must reject it
    // rather than accept a longer prefix-counted run.
    let mut body = vec![0u8; 16 + 16 + 12]; // head + participant id + three u32
    body.push(65); // blob_64 length prefix above the cap
    body.extend(std::iter::repeat_n(0u8, 65));
    assert!(
        MsgContractsLookupContractsByParticipant::decode(&body).is_err(),
        "0x9fc rejects a blob_64 over its 64-byte cap"
    );
}

#[test]
fn set_replicate_storage_0x183_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x183);
    assert_eq!(body.len(), 32, "0x183 body length");
    assert_eq!(MsgSetReplicateStorage::WIRE_ID, 0x183);

    let decoded = MsgSetReplicateStorage::decode(&body).expect("decode 0x183");
    assert_eq!(
        decoded.field_a, 0xe264_0b7c_e540_8036,
        "0x183 first head u64"
    );
    assert_eq!(
        decoded.field_b, 0xbf85_314b_bc4a_951a,
        "0x183 second head u64"
    );
    assert_eq!(decoded.field_c.len(), 16, "0x183 trailing run is 16 bytes");
    assert_eq!(
        decoded.field_c.id(),
        "msg.set-replicate-storage.field_c",
        "the trailing run carries its Atlas id"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x183");
    assert_eq!(out, body, "0x183 did not round-trip byte for byte");
    println!("0x183 body: {} bytes round-tripped", body.len());
}

#[test]
fn time_sync_to_client_0x1098_round_trips() {
    let fixture = fixture_text();
    let body = body_for(&fixture, 0x1098);
    assert_eq!(body.len(), 16, "0x1098 is head-only");
    assert_eq!(MsgTimeSyncToClient::WIRE_ID, 0x1098);

    let decoded = MsgTimeSyncToClient::decode(&body).expect("decode 0x1098");
    assert_eq!(
        decoded.field_a, 0x93a3_e477_cb5f_d51e,
        "0x1098 first head u64"
    );
    assert_eq!(
        decoded.field_b, 0xbf85_314b_bc4a_951a,
        "0x1098 second head u64"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1098");
    assert_eq!(out, body, "0x1098 did not round-trip byte for byte");
    println!("0x1098 body: {} bytes round-tripped", body.len());
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
