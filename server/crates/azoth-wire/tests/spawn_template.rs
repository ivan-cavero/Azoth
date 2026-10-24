//! The spawn record template: its provenance, its shape, and the one mutation allowed on it.
//!
//! WHAT THIS PROVES
//! ================
//! The spawn record is the message that moves the client from `WaitingForPlayerSpawn` to `InGame`,
//! and it is *captured*, not composed. A captured payload is only evidence while three things stay
//! true, so each one is a test here rather than a sentence in a document:
//!
//! * it is still the measured shape — 46,393 bytes, `record_id` 1, **48** fragments (the client's own
//!   nested-call count, not a byte guess), and it re-emits byte for byte through
//!   [`azoth_wire::bundle`];
//! * its provenance is intact — the build SHA-256, the capture block, the fact that the block's first
//!   message carries a preamble this crate does not model, and the fact that the capture is
//!   **redacted**;
//! * the only mutation this crate performs on it is the actor id, and that mutation is exact.
//!
//! WHY THE FAILURE MODE IS SILENT
//! ==============================
//! The client reads this record as a state trigger. A drifted byte does not raise an error anywhere;
//! the client simply stays one state earlier. That is why the shape is pinned to bytes instead of
//! described in prose.

use azoth_wire::bundle;
use azoth_wire::spawn::{SpawnRecord, SPAWN_FRAGMENT_COUNT, SPAWN_PAYLOAD_LEN, SPAWN_RECORD_ID};
use azoth_wire::WireError;
use serde_json::Value;

/// The exported record payload: `[record_id][fragment_count][fragments…]`.
const PAYLOAD: &[u8] = include_bytes!("fixtures/spawn-record-1.bin");

/// The provenance and the measurements taken while exporting [`PAYLOAD`].
const TEMPLATE: &str = include_str!("fixtures/spawn-template.json");

/// The local player's actor id as measured in the capture.
const ACTOR_ID: [u8; 16] = [
    0x1a, 0x95, 0x4a, 0xbc, 0x4b, 0x31, 0x85, 0xbf, 0xbe, 0x37, 0xc3, 0xd8, 0x59, 0x26, 0x18, 0xe0,
];

fn template() -> Value {
    serde_json::from_str(TEMPLATE).expect("the spawn template must be valid JSON")
}

fn f32_at(bytes: &[u8], offset: usize) -> f32 {
    f32::from_be_bytes(bytes[offset..offset + 4].try_into().expect("four bytes"))
}

/// 1. The template payload is the documented length and starts with the documented header.
#[test]
fn the_template_payload_is_the_measured_size_and_header() {
    assert_eq!(PAYLOAD.len(), SPAWN_PAYLOAD_LEN);
    assert_eq!(PAYLOAD.len(), 46_393, "the census payload length");
    assert_eq!(&PAYLOAD[..2], &[0x01, 0x30], "[record_id 1][48 fragments]");
    assert_eq!(PAYLOAD[0], SPAWN_RECORD_ID);
}

/// The fixture names the build it was captured from. Every fact here is build-scoped.
#[test]
fn the_fixture_is_the_installed_build() {
    assert_eq!(
        template()["build_sha256"].as_str(),
        Some("30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"),
    );
    assert_eq!(template()["payload_len"].as_u64(), Some(46_393));
    assert_eq!(template()["record_id"].as_u64(), Some(1));
    assert_eq!(template()["fragment_count"].as_u64(), Some(48));
    assert_eq!(template()["capture_size"].as_u64(), Some(46_423));
}

/// The block this payload came from does **not** start with the bundle, and the JSON says so.
///
/// This is the measurement that contradicts the obvious reading of the capture: the typed marker is
/// not intact at any offset of block `0x25`, because that block is the first message of its datagram
/// and carries a preamble this crate does not model. The sibling block `0x2a` carries the same
/// bundle with an intact marker, and its size is 46,407 = 14 header bytes + 46,393 payload bytes.
#[test]
fn the_fixture_records_that_the_capture_block_has_a_preamble() {
    assert_eq!(template()["marker_intact"].as_bool(), Some(false));
    assert_eq!(template()["bundle_offset"].as_u64(), Some(17));
    assert_eq!(template()["payload_offset"].as_u64(), Some(30));
    assert_eq!(template()["replication_seq"].as_u64(), Some(1));
    assert_eq!(
        template()["cross_check"]["capture_size"].as_u64(),
        Some(46_407),
        "the intact-marker copy is the payload plus a 14-byte bundle header"
    );
}

/// 3. The fragment count byte is 48, the client's own measured nested-call count for this record.
///
/// The count cannot be derived from the bytes — a fragment carries no length — so this asserts the
/// measured number and the crate constant together.
#[test]
fn the_fragment_count_is_the_measured_nested_call_count() {
    assert_eq!(usize::from(PAYLOAD[1]), SPAWN_FRAGMENT_COUNT);
    assert_eq!(SPAWN_FRAGMENT_COUNT, 48);
    // The census that would supply boundaries is a census of the OTHER variant, so there is none
    // for this record and the fixture must not pretend otherwise.
    assert!(template()["boundaries"].is_null(), "boundaries must not be invented");
}

/// 2 and 6. `from_template` accepts the template and `payload()` re-emits it unchanged.
#[test]
fn from_template_accepts_the_template_and_payload_is_unchanged() {
    let record = SpawnRecord::from_template(PAYLOAD).expect("the template parses");
    assert_eq!(record.record_id, SPAWN_RECORD_ID);
    assert_eq!(record.payload(), PAYLOAD, "re-emission must be byte for byte");
}

/// 6, through the crate's own bundle encoder: the payload slots back into the captured header.
#[test]
fn re_emitting_the_template_reproduces_the_captured_bundle() {
    let record = SpawnRecord::from_template(PAYLOAD).expect("the template parses");
    let body = bundle::encode(
        template()["replication_seq"].as_u64().expect("seq"),
        record.payload(),
    )
    .expect("encodes");

    // 00 01 08 | 01 | seq 01 | 01 01 01 01 00 00 | d9 a9 05
    let header = [
        0x00, 0x01, 0x08, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xd9, 0xa9, 0x05,
    ];
    assert_eq!(&body[..header.len()], &header, "the captured bundle prologue");
    assert_eq!(body.len(), 46_407, "the sibling block's measured size");
    assert_eq!(&body[header.len()..], PAYLOAD);

    let parsed = bundle::decode(&body, true).expect("the crate decodes what it just encoded");
    assert_eq!(parsed.replication_seq, 1);
    assert_eq!(parsed.payload, PAYLOAD);
}

/// 4. The actor id sits at the measured offset, and its documented anchor precedes it.
#[test]
fn the_actor_id_is_at_the_measured_offset() {
    let record = SpawnRecord::from_template(PAYLOAD).expect("the template parses");
    let offset = record.actor_id_offset().expect("the offset must be measured");
    assert_eq!(offset, 29_731);
    assert_eq!(template()["actor_id_offset"].as_u64(), Some(29_731));
    assert_eq!(&PAYLOAD[offset..offset + 16], &ACTOR_ID);
    assert_eq!(
        &PAYLOAD[offset - 4..offset],
        &[0x00, 0x00, 0x00, 0x02],
        "the census's <00 00 00 02> anchor"
    );
}

/// 4. Rewriting the actor id changes those sixteen bytes and nothing else.
#[test]
fn rewriting_the_actor_id_changes_only_those_sixteen_bytes() {
    let record = SpawnRecord::from_template(PAYLOAD).expect("the template parses");
    let offset = record.actor_id_offset().expect("measured");
    let replacement = [0xCA; 16];
    let edited = record.with_actor_id(replacement).expect("the offset is known");

    assert_eq!(&edited.payload()[offset..offset + 16], &replacement);
    assert_eq!(edited.payload().len(), PAYLOAD.len(), "same length");

    let differing: Vec<usize> = (0..PAYLOAD.len())
        .filter(|i| PAYLOAD[*i] != edited.payload()[*i])
        .collect();
    let expected: Vec<usize> = (offset..offset + 16).collect();
    assert_eq!(differing, expected, "only the actor id may move");
    // The original is untouched: the mutation returns a new record.
    assert_eq!(record.payload(), PAYLOAD);
}

/// 5. A payload whose actor id is not at the documented offset is an ERROR, not a no-op.
///
/// A silent no-op would be indistinguishable from a rewrite the client ignored, which is the failure
/// shape this project has paid the most for. The anchor is corrupted, not the offset moved: the
/// payload stays a valid 46,393-byte record, so only the field check can reject it.
#[test]
fn rewriting_the_actor_id_without_a_known_offset_is_an_error() {
    let mut without = PAYLOAD.to_vec();
    without[29_727..29_731].copy_from_slice(&[0x00, 0x00, 0x00, 0x03]);

    let record = SpawnRecord::from_template(&without).expect("still this record");
    assert_eq!(record.actor_id_offset(), None);
    let err = record.with_actor_id([0xCA; 16]).expect_err("must fail");
    assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");
}

/// 7. The spawn position is two big-endian `f32` at payload offsets 38332/38336.
///
/// These offsets are documented from the 1.400 build, so the check is that they still hold on
/// 1.460 — the value is asserted to the float, and the range only as a sanity bound.
#[test]
fn the_payload_carries_the_spawn_position() {
    let x = f32_at(PAYLOAD, 38_332);
    let y = f32_at(PAYLOAD, 38_336);
    assert!(
        (9_000.0..10_000.0).contains(&x) && (2_000.0..3_000.0).contains(&y),
        "expected a world-space pair, got ({x}, {y})"
    );
    assert_eq!(x, 9_343.641_601_562_5);
    assert_eq!(y, 2_786.732_666_015_625);
    assert_eq!(template()["position"]["x_offset"].as_u64(), Some(38_332));
    assert_eq!(template()["position"]["y_offset"].as_u64(), Some(38_336));
    assert!((template()["position"]["x"].as_f64().expect("x") - f64::from(x)).abs() < 1e-3);
    assert!((template()["position"]["y"].as_f64().expect("y") - f64::from(y)).abs() < 1e-3);
}

/// The template is a REDACTED capture, and the fixture has to keep saying so.
///
/// The prototype replays these same redacted bytes and reaches `InGame`, so they are the shape that
/// is proven — but they are placeholders, and a reader who assumed "verbatim capture" would draw
/// wrong conclusions about 1,802 bytes of this record.
#[test]
fn the_template_is_redacted_and_declares_it() {
    let redacted = &template()["redacted"];
    assert_eq!(redacted["bytes"].as_u64(), Some(1_802));
    assert_eq!(redacted["spans"].as_u64(), Some(161));
    // The first redacted span starts at payload offset 11,062, and it is zeros in the payload.
    let first = redacted["first_payload_offsets"][0][0].as_u64().expect("offset");
    assert_eq!(first, 11_062);
    assert!(
        PAYLOAD[11_062..11_078].iter().all(|b| *b == 0),
        "a redacted span is stored as zeros"
    );
    // And the fields this crate relies on are NOT inside a redacted span.
    assert_ne!(&PAYLOAD[29_731..29_747], &[0u8; 16]);
    assert_ne!(f32_at(PAYLOAD, 38_332), 0.0);
}

/// `from_template` rejects a payload that is not this record, instead of serving it anyway.
#[test]
fn from_template_rejects_a_payload_that_is_not_this_record() {
    let short = SpawnRecord::from_template(&PAYLOAD[..PAYLOAD.len() - 1]).expect_err("short");
    assert!(matches!(short, WireError::LengthMismatch { .. }), "{short}");

    let mut wrong_record = PAYLOAD.to_vec();
    wrong_record[0] = 2;
    let err = SpawnRecord::from_template(&wrong_record).expect_err("record id");
    assert!(matches!(err, WireError::OutOfRange { .. }), "{err}");

    let mut wrong_count = PAYLOAD.to_vec();
    wrong_count[1] = 9; // the ongoing variant's count
    let err = SpawnRecord::from_template(&wrong_count).expect_err("fragment count");
    assert!(
        matches!(err, WireError::LengthMismatch { declared: 48, actual: 9 }),
        "{err}"
    );

    let empty = SpawnRecord::from_template(&[]).expect_err("empty");
    assert!(matches!(empty, WireError::Truncated { .. }), "{empty}");
}
