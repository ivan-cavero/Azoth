//! Parity between the composed ladder messages and the fixture they came from.
//!
//! WHAT THIS PROVES
//! ================
//! Two rungs are composed by this crate (greetings, self-identification) and one is captured
//! (`LevelInfoChanged`). This test pins all three against `tests/fixtures/ladder.json`, so:
//!
//! * a drift in a composed body fails here rather than as a client stuck one state earlier;
//! * the captured body is asserted to still be the 106 bytes and the shape the docs claim, so the
//!   constant that describes it cannot silently rot.
//!
//! WHY A CLIENT STUCK EARLIER IS THE FAILURE MODE
//! ==============================================
//! The client reads these as state triggers, not as data it validates. Nothing complains if a field
//! drifts — the ladder simply stops one rung short, with no error in any log. That is exactly the
//! class of failure a byte test exists for.

use azoth_wire::ladder::{
    self_identification_body, greetings_payload, typed_record_payload, DEFAULT_LEVEL,
    DEFAULT_LEVEL_PREFIX, LEVEL_INFO_CHANGED_TAIL, LEVEL_INFO_CHANGED_TYPE, SELF_IDENTIFICATION_TYPE,
};
use serde_json::Value;

const FIXTURE: &str = include_str!("fixtures/ladder.json");

fn fixture() -> Value {
    serde_json::from_str(FIXTURE).expect("the ladder fixture must be valid JSON")
}

fn unhex(text: &str) -> Vec<u8> {
    assert!(text.len() % 2 == 0, "odd-length hex string");
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).expect("valid hex"))
        .collect()
}

#[test]
fn the_fixture_is_the_installed_build() {
    // Every fact in this repository is build-scoped; a fixture from another build is not evidence.
    assert_eq!(
        fixture()["build_sha256"].as_str(),
        Some("30fe6461f929ba44178376a72f0765dc5da28ccba20e5006a60a229babd74033"),
        "the fixture must name the installed build"
    );
}

/// The greeting this crate composes is byte-identical to the fixture.
#[test]
fn the_greeting_matches() {
    let expected = unhex(fixture()["greetings"]["payload_hex"].as_str().expect("hex"));
    assert_eq!(greetings_payload(), expected);
    assert_eq!(expected.len(), 10);
}

/// Every field of the greeting, so a reviewer can see what is being asserted.
#[test]
fn the_greeting_names_us_host() {
    let payload = greetings_payload();
    assert_eq!(payload[0], 1, "Cmd_Greetings");
    assert_eq!(&payload[1..5], &[0x41, 0x5A, 0x4F, 0x54], "'AZOT' as the peer id");
    assert_eq!(payload[5], 1, "peerIsHost");
    assert_eq!(
        u32::from_be_bytes(payload[6..10].try_into().expect("4")),
        1 << 25,
        "RepIdSeed"
    );
}

/// The self-identification body this crate composes is byte-identical to the fixture.
#[test]
fn the_self_identification_matches() {
    let expected = unhex(
        fixture()["self_identification"]["body_hex"]
            .as_str()
            .expect("hex"),
    );
    assert_eq!(self_identification_body(), expected);
    assert_eq!(expected.len(), 21);
    assert!(expected.iter().all(|b| *b == 0), "every field is zero");
    assert_eq!(
        fixture()["self_identification"]["wire_type"].as_u64(),
        Some(u64::from(SELF_IDENTIFICATION_TYPE))
    );
}

/// `LevelInfoChanged` is captured, not composed, and this pins what the constant describes.
///
/// The prototype's composer for it is dead code with a wrong layout, so the honest representation is
/// the type number plus the decoded structure — and a check that the captured size still adds up.
#[test]
fn the_captured_level_info_changed_is_the_measured_shape() {
    let lic = &fixture()["level_info_changed"];
    let body = unhex(lic["body_hex"].as_str().expect("hex"));

    assert_eq!(lic["wire_type"].as_u64(), Some(u64::from(LEVEL_INFO_CHANGED_TYPE)));
    assert_eq!(LEVEL_INFO_CHANGED_TYPE, 0x663);
    assert_eq!(body.len(), 106);
    assert_eq!(lic["body_len"].as_u64(), Some(106));

    // Two length-prefixed strings: the level, then the prefixed path.
    assert_eq!(body[0] as usize, DEFAULT_LEVEL.len());
    assert_eq!(&body[1..1 + DEFAULT_LEVEL.len()], DEFAULT_LEVEL.as_bytes());
    let second = 1 + DEFAULT_LEVEL.len();
    assert_eq!(body[second] as usize, DEFAULT_LEVEL_PREFIX.len());
    assert_eq!(
        &body[second + 1..second + 1 + DEFAULT_LEVEL_PREFIX.len()],
        DEFAULT_LEVEL_PREFIX.as_bytes()
    );

    // The arithmetic the tail constant rests on.
    let two_strings = (1 + DEFAULT_LEVEL.len()) + (1 + DEFAULT_LEVEL_PREFIX.len());
    assert_eq!(two_strings + 16 + 8 + 4 + LEVEL_INFO_CHANGED_TAIL, body.len());
}

/// The four floats in the captured body are the constants the module documents.
#[test]
fn the_captured_bounds_are_the_documented_floats() {
    let body = unhex(
        fixture()["level_info_changed"]["body_hex"]
            .as_str()
            .expect("hex"),
    );
    let at = (1 + DEFAULT_LEVEL.len()) + (1 + DEFAULT_LEVEL_PREFIX.len());
    let mut found = Vec::new();
    for i in 0..4 {
        let start = at + i * 4;
        found.push(f32::from_be_bytes(
            body[start..start + 4].try_into().expect("4"),
        ));
    }
    assert_eq!(found, azoth_wire::ladder::LEVEL_BOUNDS);
    // They are identical in both captured copies, so they are constants of the level rather than
    // per-session values. That is a claim about constancy, which is why it is asserted here.
    assert_eq!(found, vec![2048.0, 16.0, 12272.0, 10250.0]);
}

/// A typed record built around the captured body carries the right type and length prefix.
#[test]
fn a_typed_record_wraps_the_captured_body_correctly() {
    let body = unhex(
        fixture()["level_info_changed"]["body_hex"]
            .as_str()
            .expect("hex"),
    );
    let payload = typed_record_payload(LEVEL_INFO_CHANGED_TYPE, &body).expect("encodes");
    // The prefix is the payload's own length minus the prefix.
    let (declared, after) = azoth_wire::varint::decode(&payload, 0).expect("length");
    assert_eq!(declared as usize, payload.len() - after);
    // And the type inside it is 0x663.
    assert_eq!(&payload[after..after + 2], &[0x00, 0x01]);
    let (wire, _) = azoth_wire::varint::decode(&payload, after + 2).expect("type");
    assert_eq!(wire, u64::from(LEVEL_INFO_CHANGED_TYPE));
}
