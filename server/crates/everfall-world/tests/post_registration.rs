//! The post-registration ladder, driven from the committed corpus.
//!
//! After the client accepts the `0x3` registration it needs, in order, the
//! self-identification record (`0x65c`), level info (`0x663`) and the
//! replicated-state bundle the emitter authors (`0x08`). This file proves the
//! server can SEND all three from the Atlas cards on REAL captured bodies:
//!
//! * the self-identification and level-info bodies are the committed corpus in
//!   `research/fixtures/wire/wire-bodies.json`, decoded into the generated card
//!   and re-encoded, so no body byte is a bare vector;
//! * the state rung is the emitter's own `Emission` over the captured `0x9e`
//!   bundle, so its `0x08` bytes come from typed components, not a replay;
//! * the rungs are ordered and paced with the reference's constants, and a rung
//!   over the measured 256-byte single-record limit is split into the
//!   `MF_CHUNKS` chunks the client reassembles.
//!
//! Nothing here opens a socket: it checks the session's datagrams at the DTLS
//! boundary.

use std::fs;
use std::path::PathBuf;

use everfall_wire::Datagram;
use everfall_wire::generated::{FlowWorldEntryRungLevelInfo, FlowWorldEntryRungSelfIdentification};
use everfall_world::Decision;
use everfall_world::ladder::{
    CHUNK_GAP_MS, MESSAGE_INTERVAL_MS, POST_V3_DELAY_MS, PostV3Ladder, Rung,
};
use everfall_world::rep::RepSession;

const SELF_IDENT_WIRE_ID: u32 = 0x65c;
const LEVEL_INFO_WIRE_ID: u32 = 0x663;

/// The real `SM_CONNECT_REQUEST` datagram, envelope sequence 2 (see `rep_carrier.rs`).
const CONNECT_REQUEST: &str =
    "80010002a00005030000ffff0000000501880006ffff000000050101880002ffff2006";

/// The real V3 registration request datagram, envelope sequence 5 (LZ4 `0x81`).
const V3_REGISTRATION: &str = "81010005f00205045b000300000000890bd9290000099d0c00090200f00e0113970c0a5d06000000040436303331000000030334303000000002010e00f00501074a6176656c696e00000005073630303431351800f23700085b52455441494c5d00287369673a31373134383230302d616238662d343032302d393934322d3666636338376362663966340e3132372e302e302e313a393030302430300200102d0700702d343030302d380500000f00030200333124310100102d08000b0500040200ff473d616d7a6e312e646576656c6f706572506572736f6e6149642e66633930366330372d343261322d326464312d663539662d39633536636634663231326300103b321137363536313139373936303238373933300024d300116000006ace96fe0400045701520a000001010d002f01015b0003af8620737465616d7c61350200ffffad506135613561";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn read(relative: &str) -> String {
    fs::read_to_string(repo_root().join(relative)).expect("read the committed fixture")
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "odd hex length: {}", hex.len());
    (0..hex.len() / 2)
        .map(|index| {
            u8::from_str_radix(&hex[index * 2..index * 2 + 2], 16).expect("hex digit pair")
        })
        .collect()
}

/// One committed body for a wire id from `wire-bodies.json`.
fn wire_body(wire_id: u32) -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-bodies.json");
    let needle = format!("\"wire_id\": {wire_id},");
    let at = text.find(&needle).expect("wire id present");
    let body_key = "\"body\": \"";
    let body_at = text[at..].find(body_key).expect("body after the id") + body_key.len() + at;
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

/// The captured `0x9e` state bundle body, marker included.
fn state_bundle_body() -> Vec<u8> {
    let text = read("research/fixtures/wire/wire-fixtures.json");
    let needle = "\"source\": \"0x9e_T0x8_R.bin\"";
    let at = text.find(needle).expect("bundle source present");
    let body_key = "\"body\": \"";
    let body_at = text[..at].rfind(body_key).expect("body before source") + body_key.len();
    let rest = &text[body_at..];
    let end = rest.find('"').expect("closing quote after body");
    hex_bytes(&rest[..end])
}

/// The nine measured `(key, type_index, payload_len)` extents of the bundle.
fn state_extents() -> Vec<(u64, u64, usize)> {
    let text = read("research/derived/state-bundle-fragments.json");
    let mut out = Vec::new();
    let mut current: Option<(u64, u64, usize)> = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("\"key\": ") {
            if let Some(done) = current.take() {
                out.push(done);
            }
            current = Some((number(rest), 0, 0));
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"type_index\": "), current.as_mut())
        {
            slot.1 = number(rest);
        } else if let (Some(rest), Some(slot)) =
            (line.strip_prefix("\"payload_length\": "), current.as_mut())
        {
            slot.2 = number(rest) as usize;
        }
    }
    if let Some(done) = current {
        out.push(done);
    }
    assert_eq!(out.len(), 9, "the captured record carries nine fragments");
    out
}

fn number(field: &str) -> u64 {
    field
        .trim_end_matches(',')
        .parse()
        .expect("a number in the measured layout")
}

fn ladder() -> PostV3Ladder {
    PostV3Ladder::from_captured(
        &wire_body(SELF_IDENT_WIRE_ID),
        &wire_body(LEVEL_INFO_WIRE_ID),
        &state_bundle_body(),
        &state_extents(),
        &Decision::Accepted,
    )
    .expect("the captured corpus builds the ladder")
}

/// Decode one Carrier record payload into `(wire id, body)`.
fn split_payload(payload: &[u8]) -> (u32, Vec<u8>) {
    // [VLQ32 size][00 01][prefix-varint type][body]. The VLQ32's leading one-bits
    // give its own width; the type is read with the verified prefix-varint reader.
    let vlq_len = 1 + payload[0].leading_ones() as usize;
    assert_eq!(&payload[vlq_len..vlq_len + 2], &[0x00, 0x01], "type marker");
    let mut reader = everfall_wire::Reader::new(&payload[vlq_len + 2..]);
    let wire_id = reader.prefix_varint("type").expect("type varint") as u32;
    let header = vlq_len + 2 + reader.position();
    (wire_id, payload[header..].to_vec())
}

/// Decode a datagram's single record payload into `(wire id, body)`.
fn record_payload(datagram: &[u8]) -> (u32, Vec<u8>) {
    let decoded = Datagram::decode(datagram).expect("the reply is a plaintext datagram");
    assert_eq!(decoded.records().len(), 1, "one record per ladder datagram");
    split_payload(decoded.records()[0].payload())
}

/// Build one planned datagram with a deterministic envelope sequence.
fn build(plan: &PostV3Ladder, index: usize) -> Vec<u8> {
    plan.datagram(index, index as u16 + 1, 1, 1)
        .expect("the planned datagram builds")
}

/// The records of one rung, decoded from their own datagrams and rejoined.
fn rung_records(plan: &PostV3Ladder, rung: Rung) -> Vec<u8> {
    let mut joined = Vec::new();
    for (index, record) in plan.records().iter().enumerate() {
        if record.rung() != rung {
            continue;
        }
        let datagram = build(plan, index);
        let decoded = Datagram::decode(&datagram).expect("plaintext datagram");
        joined.extend_from_slice(decoded.records()[0].payload());
    }
    joined
}

#[test]
fn the_ladder_plans_the_three_rungs_in_order_at_the_reference_pacing() {
    let plan = ladder();
    let records = plan.records();
    assert!(!records.is_empty(), "the ladder plans datagrams");
    assert_eq!(
        records[0].rung(),
        Rung::SelfIdentification,
        "self-identification goes first"
    );
    assert_eq!(records[0].offset_ms(), POST_V3_DELAY_MS);
    assert!(
        records[0].chunk().is_some(),
        "the 12.7 KB self-identification record is chunked"
    );
    assert_eq!(
        records
            .iter()
            .filter(|record| record.rung() == Rung::LevelInfo)
            .count(),
        1,
        "level info is a single record"
    );
    assert!(records.iter().any(|record| record.rung() == Rung::State));

    let offsets: Vec<u32> = records
        .iter()
        .map(everfall_world::PlannedRecord::offset_ms)
        .collect();
    assert!(
        offsets.windows(2).all(|pair| pair[1] >= pair[0]),
        "the plan is monotonic"
    );
    assert!(
        offsets
            .windows(2)
            .any(|pair| pair[1] - pair[0] == CHUNK_GAP_MS),
        "chunks are paced {CHUNK_GAP_MS} ms apart"
    );
    assert!(
        offsets
            .windows(2)
            .any(|pair| pair[1] - pair[0] == MESSAGE_INTERVAL_MS),
        "rungs are separated by the message interval"
    );
}

#[test]
fn the_self_identification_datagram_re_encodes_the_captured_card() {
    let captured = wire_body(SELF_IDENT_WIRE_ID);
    let plan = ladder();
    let joined = rung_records(&plan, Rung::SelfIdentification);
    let (wire_id, body) = split_payload(&joined);
    assert_eq!(wire_id, SELF_IDENT_WIRE_ID);
    assert_eq!(body, captured, "the card re-encoded the body byte for byte");

    let decoded = FlowWorldEntryRungSelfIdentification::decode(&body).expect("the card decodes");
    assert_eq!(decoded.grid_side, 56);
    assert_eq!(decoded.grid_cells.len(), 12_544);
}

#[test]
fn the_level_info_datagram_re_encodes_the_captured_card() {
    let captured = wire_body(LEVEL_INFO_WIRE_ID);
    let plan = ladder();
    let joined = rung_records(&plan, Rung::LevelInfo);
    let (wire_id, body) = split_payload(&joined);
    assert_eq!(wire_id, LEVEL_INFO_WIRE_ID);
    assert_eq!(body, captured, "the card re-encoded the body byte for byte");

    let decoded = FlowWorldEntryRungLevelInfo::decode(&captured).expect("the card decodes");
    assert_eq!(decoded.level_name, "NewWorld_VitaeEterna");
    assert_eq!(decoded.level_path, "coatlicue/NewWorld_VitaeEterna");
}

#[test]
fn the_state_rung_carries_the_emitter_payload_chunked() {
    let plan = ladder();
    let framed = plan.rung_payload(Rung::State);
    // The Carrier payload is `VLQ32(len) + the emitter's 0x08 bundle`.
    let vlq_len = 1 + framed[0].leading_ones() as usize;
    assert_eq!(
        &framed[vlq_len..vlq_len + 3],
        &[0x00, 0x01, 0x08],
        "the state payload is the emitter's 0x08 bundle"
    );

    let chunks = plan
        .records()
        .iter()
        .filter(|record| record.rung() == Rung::State)
        .count();
    assert!(chunks > 1, "a 7 KB bundle cannot ride one record");
    for record in plan.records() {
        if record.rung() == Rung::State {
            assert!(record.payload().len() <= 1_100, "under the measured cut");
        }
    }
    let joined = rung_records(&plan, Rung::State);
    assert_eq!(
        joined, framed,
        "the state rung is the emitter's bytes, chunked"
    );
}

#[test]
fn a_session_sends_the_ladder_only_after_the_post_v3_delay() {
    let mut session = RepSession::new();
    session.set_ladder(ladder());

    let clock = 0x9947_9CB9;
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), clock)
        .expect("flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), clock)
        .expect("registration builds");
    assert!(session.v3_responded());
    assert!(session.post_v3_armed());

    assert!(
        session.tick(clock + 100).expect("tick").is_empty(),
        "nothing is sent before the 300 ms post-V3 delay"
    );
    let first = session.tick(clock + POST_V3_DELAY_MS).expect("tick");
    assert_eq!(first.len(), 1, "the first self-identification chunk is due");
    let (wire_id, _) = record_payload(&first[0]);
    assert_eq!(wire_id, SELF_IDENT_WIRE_ID);
}

#[test]
fn the_session_drains_the_whole_ladder_on_its_own_clock() {
    let mut session = RepSession::new();
    let plan = ladder();
    let plan_len = plan.records().len();
    let expected_last = plan.records().last().expect("at least one record").rung();
    session.set_ladder(plan);
    let clock = 0x9947_9CB9;
    session
        .on_app_data(&hex_bytes(CONNECT_REQUEST), clock)
        .expect("flight builds");
    session
        .on_app_data(&hex_bytes(V3_REGISTRATION), clock)
        .expect("registration builds");

    let replies = session.tick(clock + 10_000).expect("tick");
    assert_eq!(replies.len(), plan_len, "every planned datagram is emitted");
    assert!(
        replies.iter().all(|reply| reply.starts_with(&[0x80, 0x01])),
        "every ladder datagram is a plaintext Carrier envelope"
    );
    let last = replies.last().expect("at least one reply");
    assert!(
        !Datagram::decode(last)
            .expect("plaintext datagram")
            .records()
            .is_empty()
    );
    assert_eq!(expected_last, Rung::State);
}
