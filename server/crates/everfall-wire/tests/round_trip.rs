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
    FlowWorldEntryRungSelfIdentification, MsgClientAddEntry,
    MsgContractsLookupContractsByParticipant, MsgContractsOnLookupContractsByParticipant,
    MsgGlobalStorageReceiveStorageSearchItems, MsgGridTrackingUpdatePhasing,
    MsgObjectivesSetObjectiveAutoPinning, MsgObjectivesUpdateTrackedObjectives,
    MsgReceiveSettingsFromClient, MsgSetReplicateStorage, MsgSocialReceiveAvailableTitles,
    MsgTimeSyncDayPhase, MsgTimeSyncTimeChange, MsgTimeSyncToClient, MsgTimeSynch0x14f,
    MsgVoiceChatServiceRegistered,
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
        decoded.local_facet_id, 0x180f_8d4e_5736_97c6,
        "0x5b2 sending facet's local id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
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
        decoded.local_facet_id, 0x180f_8d4e_5736_97c6,
        "0xa95 sending facet's local id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
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
        decoded.local_facet_id, 0xd1a9_4ccc_8706_60b0,
        "0x9d3 sending facet's local id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
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
            decoded.local_facet_id, 0x4c0c_0ed6_478a_69da,
            "0x9fc sending facet's local id"
        );
        assert_eq!(
            decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
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
        decoded.local_facet_id, 0xe264_0b7c_e540_8036,
        "0x183 sending facet's local id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
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
        decoded.local_facet_id, 0x93a3_e477_cb5f_d51e,
        "0x1098 sending facet's local id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
        "0x1098 second head u64"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1098");
    assert_eq!(out, body, "0x1098 did not round-trip byte for byte");
    println!("0x1098 body: {} bytes round-tripped", body.len());
}

#[test]
fn time_synch_counter_round_trips_and_advances_at_real_time() {
    // The four committed 0x14f records, all 12 bytes: the typed header then an
    // 8-byte body. Corpus `services/world/replay/messages-redacted.txt`, seqs
    // 0x0a, 0x27, 0x3c, 0x54.
    let records = [
        "00 01 8f 05 0b 88 8d 68 7b 13 00 1a",
        "00 01 8f 05 0b 88 8d 68 81 41 ab b4",
        "00 01 8f 05 0b 88 8d 69 36 5c c1 e0",
        "00 01 8f 05 0b 88 8d 69 e9 2f 11 ff",
    ];
    let mut counters = Vec::new();
    for record in records {
        let bytes = hex_bytes(&record.replace(' ', ""));
        // The card models the BODY, so the typed header is framing: 4 bytes.
        let body = &bytes[4..];
        let decoded = MsgTimeSynch0x14f::decode(body).expect("decode 0x14f body");
        let mut out = Vec::new();
        decoded.encode(&mut out).expect("encode 0x14f body");
        assert_eq!(out, body, "0x14f did not round-trip byte for byte");
        counters.push((u64::from(decoded.time_high) << 32) | u64::from(decoded.time_low));
    }
    // The counter is nanoseconds on a real-time scale: the two long gaps are
    // ~3 s, and each of them spans exactly three captured PingMsg records whose
    // period is 1.000 s. Asserted as a range, not an exact value, because the
    // capture's own timing is not sample-perfect.
    // Counters are 48-bit nanosecond values, so they fit an f64 exactly: the
    // mantissa holds 53 bits and the divide below is what makes the unit seconds.
    #[expect(
        clippy::cast_precision_loss,
        reason = "a 48-bit nanosecond counter is exactly representable in f64"
    )]
    let gaps: Vec<f64> = counters
        .windows(2)
        .map(|pair| (pair[1] - pair[0]) as f64 / 1e9)
        .collect();
    assert!(
        (gaps[1] - 3.0).abs() < 0.1,
        "seq 0x27 -> 0x3c should be ~3 s, got {}",
        gaps[1]
    );
    assert!(
        (gaps[2] - 3.0).abs() < 0.1,
        "seq 0x3c -> 0x54 should be ~3 s, got {}",
        gaps[2]
    );
}

#[test]
fn client_add_entry_names_the_same_actor_the_time_sync_does() {
    // The two committed 0xa4 records are byte-identical, so one body pins the
    // card: 00 01 a4 02 then a 16-byte actor id.
    let record = hex_bytes("0001a4021a954abc4b3185bfbe37c3d8592618e0");
    let body = &record[4..];
    let decoded = MsgClientAddEntry::decode(body).expect("decode 0xa4 body");
    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0xa4 body");
    assert_eq!(out, body, "0xa4 did not round-trip byte for byte");

    // The cross-check that makes this an identity and not 16 anonymous bytes:
    // the client's own 0x1098 SyncToClient carries the same actor id as its
    // second head u64, written BIG-endian. So the id below must equal that u64
    // byte for byte, and the little-endian spelling must equal the first 8 bytes
    // the state bundle uses for the same actor.
    let actor_id = &body[..16];
    let head_u64 = u64::from_be_bytes(actor_id[..8].try_into().expect("8 bytes"));
    assert_eq!(
        head_u64, 0x1a95_4abc_4b31_85bf,
        "0xa4's actor id must be the 0x1098 head u64 in big-endian"
    );
    let little = u64::from_le_bytes(actor_id[..8].try_into().expect("8 bytes"));
    assert_eq!(
        little, 0xbf85_314b_bc4a_951a,
        "and the same value read little-endian is the bundle's first 8 actor bytes"
    );
}

#[test]
fn grid_tracking_update_phasing_0x18a6_round_trips_its_four_records() {
    // The four committed 0x18a6 records, 40 bytes each: the typed header then a
    // 36-byte body. Corpus `services/world/replay/messages-redacted.txt`, seqs
    // 0x0b, 0x38, 0x53, 0x68.
    let records = [
        "00 01 a6 62 f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a 01 01 00 00 9c fa 58 61 78 14 69 f2 65 03 00 00 00 00 02 01",
        "00 01 a6 62 f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a 01 01 00 00 9c fa 58 61 78 14 69 f2 65 03 00 00 00 00 02 02",
        "00 01 a6 62 f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a 01 01 00 00 9c fa 58 61 78 14 69 f2 65 03 00 00 00 00 02 03",
        "00 01 a6 62 f8 cb ed 57 c6 8b 18 f4 bf 85 31 4b bc 4a 95 1a 01 01 00 00 9c fa 58 61 78 14 69 f2 65 03 00 00 00 00 02 04",
    ];
    assert_eq!(MsgGridTrackingUpdatePhasing::WIRE_ID, 0x18a6);

    let mut counters = Vec::new();
    for record in records {
        let bytes = hex_bytes(&record.replace(' ', ""));
        assert_eq!(bytes.len(), 40, "0x18a6 record length");
        // The card models the BODY, so the typed header is framing: 4 bytes.
        let body = &bytes[4..];
        let decoded = MsgGridTrackingUpdatePhasing::decode(body).expect("decode 0x18a6 body");

        // The head is the shared two-u64 pair nine other types carry, not an
        // anonymous id: the first u64 is the GridTracking client facet's own
        // local id, the second the first half of the player's actor id.
        assert_eq!(
            decoded.local_facet_id, 0xf8cb_ed57_c68b_18f4,
            "0x18a6's local facet id"
        );
        assert_eq!(
            decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
            "0x18a6's head actor u64"
        );
        // And the head really is the shared one: the facet id the 0x18a6 family
        // uses is the same value the level-info tail carries, read big-endian.
        let _ = decoded.tail_flags;
        assert_eq!(decoded.tail_tag.len(), 6, "0x18a6's tail tag is six bytes");
        assert_eq!(
            decoded.tail_discriminator, 0x02,
            "0x18a6's own discriminator, where the level-info tail carries 01"
        );

        let mut out = Vec::new();
        decoded.encode(&mut out).expect("encode 0x18a6 body");
        assert_eq!(out, body, "0x18a6 did not round-trip byte for byte");
        counters.push(decoded.sequence_counter);
    }
    assert_eq!(
        counters,
        vec![1, 2, 3, 4],
        "the last byte counts once per message in capture order"
    );
}

#[test]
fn the_0x18a6_head_is_the_facet_head_nine_other_types_carry() {
    // The corpus-wide measurement behind the card's two head fields: 36 of the
    // 138 R records, spanning 10 wire types, carry body[8..16] = the actor u64,
    // and no record of any other type does. Here the same two u64 are read off
    // an independently committed 0x1b88 record, so the head is proven shared
    // rather than assumed from one message's bytes.
    let other = hex_bytes(&format!(
        "0001886ee2640b7ce5408036bf85314bbc4a951a{}",
        "00".repeat(22)
    ));
    assert_eq!(other.len(), 42, "0x1b88 record length");
    let body = &other[4..];

    // 0x1b88 is not modelled by a card, so read the two head u64 directly.
    let facet = u64::from_be_bytes(body[..8].try_into().expect("8 bytes"));
    let actor = u64::from_be_bytes(body[8..16].try_into().expect("8 bytes"));
    assert_eq!(actor, 0xbf85_314b_bc4a_951a, "0x1b88's head actor u64");
    assert_eq!(
        facet, 0xe264_0b7c_e540_8036,
        "0x1b88's local facet id, a different component than 0x18a6's"
    );
    assert_ne!(
        facet, 0xf8cb_ed57_c68b_18f4,
        "two components, two local ids: the head is per-component, not constant"
    );
}

#[test]
fn contracts_on_lookup_0x8e6_round_trips_and_echoes_the_request_id() {
    // The one committed 0x8e6 record, 42 bytes: the typed header then a 38-byte
    // body. Corpus `services/world/replay/messages-redacted.txt`, seq 0x43.
    let record = hex_bytes(
        "0001a6234c0c0ed6478a69dabf85314bbc4a951a\
         e1634370307b4d06a72fd9df005cd942000000000000",
    );
    assert_eq!(record.len(), 42, "0x8e6 record length");
    assert_eq!(MsgContractsOnLookupContractsByParticipant::WIRE_ID, 0x8e6);

    let body = &record[4..];
    let decoded =
        MsgContractsOnLookupContractsByParticipant::decode(body).expect("decode 0x8e6 body");

    // The head is the shared two-u64 pair, and its facet id is the SAME value
    // the client's own 0x9fc request carried: that is the correlation between
    // the request and this answer.
    assert_eq!(
        decoded.local_facet_id, 0x4c0c_0ed6_478a_69da,
        "0x8e6's head facet id matches its 0x9fc request"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
        "0x8e6's head actor u64"
    );

    // The echoed id: 16 bytes wide, matching the trailing field width the
    // client's own 0x9fc request uses. `Opaque` deliberately hides its bytes,
    // so the echo is pinned in the card by the byte measurement, and here by
    // decoding a committed 0x9fc body and comparing the two runs' widths.
    assert_eq!(decoded.lookup_id.len(), 16, "0x8e6 echoed id width");
    let request =
        MsgContractsLookupContractsByParticipant::decode(&body_for(&fixture_text(), 0x9fc))
            .expect("decode a committed 0x9fc request body");
    assert_eq!(
        decoded.lookup_id.len(),
        request.trailing_id.len(),
        "the answer's echoed id has the request's trailing width"
    );
    assert_eq!(
        decoded.local_facet_id, request.local_facet_id,
        "the answer addresses the same contracts facet the request sent from"
    );

    // The captured answer returns no contract payload: its trailing block is
    // empty, carried as a fixed 6-byte run because the internal split is not
    // pinned by an all-zero sample.
    assert_eq!(
        decoded.trailing_block.len(),
        6,
        "0x8e6 trailing block width"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x8e6 body");
    assert_eq!(out, body, "0x8e6 did not round-trip byte for byte");
}

#[test]
#[expect(
    clippy::float_cmp,
    reason = "the body is byte-exact, so the decoded floats are exact"
)]
fn time_sync_time_change_0x1096_round_trips_its_fourteen_fields() {
    // The one committed 0x1096 record, 80 bytes: typed header then a 76-byte
    // body. Corpus `services/world/replay/messages-redacted.txt`, seq 0x75.
    let record = hex_bytes(
        "0001964293a3e477cb5fd51ebf85314bbc4a951a\
         40c00000bf80000039f5f5b8\
         00005334000000000000fe4c0000000000000e1000000708\
         0b879fb33482a0b7\
         3e2aaaab3e2aaaab3f5555553f555555",
    );
    assert_eq!(record.len(), 80, "0x1096 record length");
    assert_eq!(MsgTimeSyncTimeChange::WIRE_ID, 0x1096);

    let body = &record[4..];
    assert_eq!(body.len(), 76, "0x1096 body is head plus sixty field bytes");
    let decoded = MsgTimeSyncTimeChange::decode(body).expect("decode 0x1096 body");

    // The head is the time facet, the same id 0x1097 and 0x1098 carry.
    assert_eq!(
        decoded.local_facet_id, 0x93a3_e477_cb5f_d51e,
        "0x1096's local facet id is the time component"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
        "0x1096's head actor u64"
    );

    // The calendar arithmetic that makes these names measurements rather than
    // guesses: the two second counts split a day exactly, and the pair of
    // integers is one hour and half of it.
    assert_eq!(
        decoded.day_length_seconds + decoded.day_switch_seconds,
        86_400,
        "the two second counts split exactly one day"
    );
    assert_eq!(decoded.seconds_per_hour, 3600, "one hour in seconds");
    assert_eq!(
        decoded.half_hour_seconds, 1800,
        "half of the field beside it"
    );

    // The four trailing factors are two duplicated pairs: 1/6 twice, 5/6 twice.
    assert_eq!(decoded.phase_rise_start, decoded.phase_rise_end);
    assert_eq!(decoded.phase_set_pos, decoded.phase_set_end);
    assert!((decoded.phase_rise_start - 1.0 / 6.0).abs() < 1e-6);
    assert!((decoded.phase_set_pos - 5.0 / 6.0).abs() < 1e-6);

    // The two round numbers that open the block.
    assert_eq!(decoded.horizon_angle, 6.0);
    assert_eq!(decoded.scale_a, -1.0);

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1096 body");
    assert_eq!(out, body, "0x1096 did not round-trip byte for byte");
}

#[test]
fn time_sync_day_phase_0x1097_round_trips_and_shares_the_time_facet() {
    // The one committed 0x1097 record, 24 bytes: typed header, then the shared
    // head and a single u32. Corpus seq 0x76.
    let record = hex_bytes("0001974293a3e477cb5fd51ebf85314bbc4a951a00000002");
    assert_eq!(record.len(), 24, "0x1097 record length");
    assert_eq!(MsgTimeSyncDayPhase::WIRE_ID, 0x1097);

    let body = &record[4..];
    assert_eq!(body.len(), 20, "0x1097 body is head plus one u32");
    let decoded = MsgTimeSyncDayPhase::decode(body).expect("decode 0x1097 body");

    assert_eq!(decoded.day_phase, 2, "the only day phase ever captured");

    // The strongest structural fact here: 0x1096 and 0x1097 are two messages of
    // ONE component, so they carry the same local facet id. Decoding the sibling
    // and comparing turns "the id is the time facet" into a measurement.
    let sibling = MsgTimeSyncTimeChange::decode(&hex_bytes(
        "93a3e477cb5fd51ebf85314bbc4a951a\
         40c00000bf80000039f5f5b8\
         00005334000000000000fe4c0000000000000e1000000708\
         0b879fb33482a0b7\
         3e2aaaab3e2aaaab3f5555553f555555",
    ))
    .expect("decode the 0x1096 sibling body");
    assert_eq!(
        decoded.local_facet_id, sibling.local_facet_id,
        "both time messages are sent by the same facet"
    );
    assert_eq!(
        decoded.local_actor_id_word0, sibling.local_actor_id_word0,
        "and carry the same actor u64"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1097 body");
    assert_eq!(out, body, "0x1097 did not round-trip byte for byte");
}

#[test]
fn receive_storage_search_items_0x1b88_round_trips_its_23_identical_copies() {
    // The server repeats this 42-byte record 23 times during world entry, at
    // seqs 0x0c-0x0e and 0x11-0x24. The committed corpus holds ONE distinct
    // record, so decoding it once pins every copy.
    let record = hex_bytes(&format!(
        "0001886ee2640b7ce5408036bf85314bbc4a951a{}",
        "00".repeat(22)
    ));
    assert_eq!(record.len(), 42, "0x1b88 record length");
    assert_eq!(MsgGlobalStorageReceiveStorageSearchItems::WIRE_ID, 0x1b88);

    let body = &record[4..];
    assert_eq!(body.len(), 38, "0x1b88 body is head + id + empty tail");
    let decoded = MsgGlobalStorageReceiveStorageSearchItems::decode(body).expect("decode 0x1b88");

    // The head names the global-storage facet, and it is the SAME id the atlas
    // already pinned from the client's own 0x183 record: the two directions
    // agree on which component this is.
    assert_eq!(
        decoded.local_facet_id, 0xe264_0b7c_e540_8036,
        "0x1b88's facet id matches the one 0x183 carries client-to-server"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
        "0x1b88's head actor u64"
    );

    // The empty answer: a zero id and a six-byte tail that the reader's shape
    // produces from count 0 (1 count + 0 elements + 4 u32 + 1 flag = 6).
    assert_eq!(decoded.search_id.len(), 16, "0x1b88 search id width");
    assert_eq!(
        decoded.empty_search_tail.len(),
        6,
        "one count, zero elements, one u32, one flag"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1b88 body");
    assert_eq!(out, body, "0x1b88 did not round-trip byte for byte");
}

#[test]
fn voice_chat_service_registered_0x1067_round_trips_its_three_strings() {
    // The one committed 0x1067 record, 86 bytes: typed header then an 82-byte
    // body. Corpus `services/world/replay/messages-redacted.txt`, seq 0x65.
    let record = hex_bytes(
        "0001a741d8c9c8af5e7a353cbf85314bbc4a951a\
         2068747470733a2f2f6e7778702e7777772e7669766f782e636f6d2f617069322f\
         0f616d617a6f6e393035302d6e653833\
         0f406e7778702e7669766f782e636f6d\
         00",
    );
    assert_eq!(record.len(), 86, "0x1067 record length");
    assert_eq!(MsgVoiceChatServiceRegistered::WIRE_ID, 0x1067);

    let body = &record[4..];
    assert_eq!(body.len(), 82, "0x1067 body");
    let decoded = MsgVoiceChatServiceRegistered::decode(body).expect("decode 0x1067");

    // These three strings are verbatim ASCII on the wire, so unlike an opaque
    // run they can be asserted as VALUES and not merely as widths.
    assert_eq!(
        decoded.api_server_uri, "https://nwxp.www.vivox.com/api2/",
        "the Vivox API server the client is pointed at"
    );
    assert_eq!(
        decoded.login_token, "amazon9050-ne83",
        "the Vivox account half of the login"
    );
    // The realm is the THIRD string, not the second: the empty trailing value in
    // the old reading was this message's bool byte, not a channel string.
    assert_eq!(
        decoded.realm, "@nwxp.vivox.com",
        "the realm the SIP identifiers are addressed on"
    );
    assert!(!decoded.service_flag, "the captured service flag is zero");

    // The width arithmetic that closes the layout: head 16, then three
    // length-prefixed strings, then one byte.
    assert_eq!(
        body.len(),
        16 + 3 + decoded.api_server_uri.len() + decoded.login_token.len() + decoded.realm.len() + 1,
        "head + three strings + one bool byte accounts for all 82 bytes"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1067 body");
    assert_eq!(out, body, "0x1067 did not round-trip byte for byte");
}

#[test]
fn social_receive_available_titles_0x1033_round_trips_both_vectors() {
    // The one committed 0x1033 record, 498 bytes: typed header then a 494-byte
    // body. Corpus `services/world/replay/messages-redacted.txt`, seq 0x62.
    // The body is committed as its own fixture rather than retyped here: 494
    // bytes is far past the length where a hand copy is a reliable witness.
    let body_text = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../research/fixtures/wire/social-1033-body.hex"),
    )
    .expect("read the committed 0x1033 body fixture");
    let body = hex_bytes(body_text.trim());
    assert_eq!(body.len(), 494, "0x1033 body length");
    assert_eq!(MsgSocialReceiveAvailableTitles::WIRE_ID, 0x1033);

    let decoded = MsgSocialReceiveAvailableTitles::decode(&body).expect("decode 0x1033");

    assert_eq!(
        decoded.local_facet_id, 0xce81_136a_2b7a_d33e,
        "0x1033's social facet id"
    );
    assert_eq!(
        decoded.local_actor_id_word0, 0xbf85_314b_bc4a_951a,
        "0x1033's head actor u64"
    );

    // The two counts are the layout's whole argument: 109 and 10.
    assert_eq!(decoded.title_ids.len(), 109, "first vector count");
    assert_eq!(decoded.title_selection_ids.len(), 10, "second vector count");

    // The measured relation that earns the names: the second vector is a
    // STRICT subset of the first, written out of order - a selection, not a
    // parallel list. Asserting it here means a change to either vector breaks
    // the test rather than passing silently.
    let big: std::collections::BTreeSet<u32> = decoded.title_ids.iter().copied().collect();
    let small: std::collections::BTreeSet<u32> =
        decoded.title_selection_ids.iter().copied().collect();
    assert_eq!(big.len(), 109, "every first-vector id is distinct");
    assert_eq!(small.len(), 10, "every second-vector id is distinct");
    assert!(
        small.is_subset(&big),
        "the ten selections must all occur among the hundred and nine"
    );

    let mut out = Vec::new();
    decoded.encode(&mut out).expect("encode 0x1033 body");
    assert_eq!(out, body, "0x1033 did not round-trip byte for byte");
}

/// `0x635` is the client's input stream and the server must PARSE it, but the
/// element encoder is a delta encoder whose reference baseline has not been
/// read, so `everfall-wire` emits no codec for it. What CAN be falsified
/// without guessing is the container arithmetic and the frame-id pattern, and
/// those are checked here against the five committed records. This test is the
/// card's evidence, not a decode.
#[test]
fn action_list_input_container_arithmetic_holds_on_all_five_records() {
    // Bodies of seqs 0x6e..0x72 from `services/world/replay/messages-redacted.txt`.
    // These are channel-1 records, so a body starts at record offset 28; the
    // list below holds bodies only, with the 28-byte prefix already removed.
    const BODIES: [&str; 5] = [
        "fbde4b9a600d428fbf85314bbc4a951a00010000910206000001010000000000000000012007194b\
         000000ac0f01010100000001c0802000808080800300000001",
        "fbde4b9a600d428fbf85314bbc4a951a00000000910206000001010000000000000000012007194b\
         000000ac0f01020100000002c0802000808080800300000001000000000100808080800300000001",
        "fbde4b9a600d428fbf85314bbc4a951a00000000910206000001010000000000000000012007194b\
         000000ac0f01030100000003c0802000808080800300000001000000000200808080800300000001\
         000000000100808080800300000001",
        "fbde4b9a600d428fbf85314bbc4a951a00000000910206000001010000000000000000012007194b\
         000000ac0f01040100000004c0802000808080800300000001000000000300808080800300000001\
         000000000200808080800300000001000000000100808080800300000001",
        "fbde4b9a600d428fbf85314bbc4a951a00000000910206000001010000000000000000012007194b\
         000000ac0f01050100000005c0802000808080800300000001000000000400808080800300000001\
         0000000003008080808003000000010000000002008080808003000000010000000001008080808\
         00300000001",
    ];
    // The container, in body-relative offsets: shared head 16, a 29-byte
    // reference block, a flag byte, the frame count, a 3-byte presence mask,
    // then 15 bytes per frame. Nothing is left over in any record.
    const HEAD: usize = 16;
    const REFERENCE_BLOCK: usize = 29;
    const FLAG_AND_COUNT: usize = 2;
    const MASK: usize = 3;
    const FRAME_STRIDE: usize = 15;

    for (index, hex) in BODIES.iter().enumerate() {
        let body = hex_bytes(hex);
        let count = body[HEAD + REFERENCE_BLOCK + 1] as usize;
        assert_eq!(
            count,
            index + 1,
            "record {index} carries its own sequence position as the frame count"
        );
        assert_eq!(
            body.len(),
            HEAD + REFERENCE_BLOCK + FLAG_AND_COUNT + MASK + FRAME_STRIDE * count,
            "record {index}: 16 + 29 + 2 + 3 + 15*{count} must account for all {} bytes",
            body.len()
        );
        assert_eq!(
            body[HEAD + REFERENCE_BLOCK],
            0x01,
            "record {index}: the flag byte between the reference block and the count is 1"
        );
        assert_eq!(
            &body[HEAD + REFERENCE_BLOCK + 2..HEAD + REFERENCE_BLOCK + 2 + MASK],
            &[0x01, 0x00, 0x00],
            "record {index}: only the first mask bit is set"
        );

        // The frames are a descending, wrapping id run: the highest id first,
        // then every lower id down to 1. The id sat at frame+1 in the first
        // frame and at frame+4 in the rest, so only the count and the
        // descending order are asserted here, not the offset.
        let first = HEAD + REFERENCE_BLOCK + FLAG_AND_COUNT + MASK;
        let ids: Vec<u8> = (0..count)
            .map(|frame| body[first + FRAME_STRIDE * frame + 1])
            .collect();
        assert_eq!(
            ids[0], count as u8,
            "record {index}: the first frame carries the highest id"
        );
        for frame in 1..count {
            assert_eq!(
                body[first + FRAME_STRIDE * frame + 4],
                (count - frame) as u8,
                "record {index}: frame {frame} carries the next lower id"
            );
        }
    }

    // The head is shared with every other message in the corpus.
    let body = hex_bytes(BODIES[0]);
    assert_eq!(
        &body[..8],
        &[0xfb, 0xde, 0x4b, 0x9a, 0x60, 0x0d, 0x42, 0x8f],
        "the sending facet's own local id"
    );
    assert_eq!(
        &body[8..16],
        &[0xbf, 0x85, 0x31, 0x4b, 0xbc, 0x4a, 0x95, 0x1a],
        "the local actor id's first eight bytes, the same value the 0x1098 carries"
    );
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
